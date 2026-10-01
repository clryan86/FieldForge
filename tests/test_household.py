"""New household workflow against fixtures matching the existing table definitions."""

import json
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace

import pytest

from fieldforge.core.household import (
    HouseholdConflict,
    HouseholdService,
    kind_label,
    member_from_fields,
    validate_member,
)
from fieldforge.core.models import HouseholdMember


def database(path):
    with closing(sqlite3.connect(path)) as db:
        db.executescript("""
            CREATE TABLE household_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                daily_water_liters REAL NOT NULL, daily_calories INTEGER NOT NULL,
                notes TEXT NOT NULL DEFAULT '', is_child INTEGER NOT NULL DEFAULT 0,
                is_pet INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE app_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT NOT NULL, payload_json TEXT NOT NULL
            );
        """)
    return HouseholdService(path)


@pytest.fixture
def service(tmp_path):
    return database(tmp_path / "household #1.db")


def profile(**changes):
    return replace(HouseholdMember("Example person", 3, 2000, " Private note\n\n"), **changes)


def fields(**changes):
    return {"name": " Example person ", "kind": "Adult", "water": "3", "calories": "2000", "notes": "Exact\n\n", **changes}


def event_records(service):
    with service.connect() as db:
        return [(r[0], json.loads(r[1])) for r in db.execute("SELECT event_type,payload_json FROM app_events ORDER BY id")]


@pytest.mark.parametrize("kind,child,pet", [("Adult", False, False), ("Child", True, False), ("Pet", False, True)])
def test_explicit_profile_kinds_and_exact_notes(kind, child, pet):
    member = member_from_fields(fields(kind=kind))
    assert member.name == "Example person" and member.notes == "Exact\n\n"
    assert member.is_child is child and member.is_pet is pet
    assert member.daily_water_liters == 3 and member.daily_calories == 2000
    assert kind_label(member) == kind


@pytest.mark.parametrize("key,value", [
    ("water", ""), ("calories", ""), ("water", "NaN"), ("water", "inf"), ("water", "1e999"),
    ("water", "0"), ("water", "-1"), ("calories", "-1"), ("calories", "2.5"),
    ("calories", "1e3"), ("calories", "2000.0"), ("calories", "1000000001"),
    ("name", " "), ("name", "x"*201), ("notes", "\x00"), ("notes", "x"*10001),
    ("kind", "Unknown"), ("kind", ""), ("water", None),
])
def test_invalid_editor_fields_not_inferred(key, value):
    with pytest.raises(ValueError):
        member_from_fields(fields(**{key: value}))


@pytest.mark.parametrize("changes", [
    {"daily_water_liters": float("inf")}, {"daily_water_liters": float("nan")},
    {"daily_water_liters": True}, {"daily_water_liters": 10**900},
    {"daily_calories": True}, {"daily_calories": 12.5}, {"daily_calories": float("nan")},
    {"is_pet": 1}, {"is_child": "yes"}, {"is_child": True, "is_pet": True}, {"id": True}, {"id": -1},
])
def test_service_validation_rejects_invalid_programmatic_values(service, changes):
    with pytest.raises(ValueError):
        service.save(profile(**changes))
    assert not service.browse() and not event_records(service)


def test_add_edit_and_remove_use_same_ids_and_minimal_events(service):
    first = service.save(profile())
    updated = service.save(replace(first.member, name="Edited alias", daily_water_liters=4, notes="Updated secret"), expected=first.token)
    assert first.member.id == updated.member.id and first.token != updated.token
    assert service.get(updated.member.id) == updated
    events = event_records(service)
    assert events[0][0] == "household_change"
    assert events[1][1]["changed_fields"] == ["name", "daily_water_liters", "notes"]
    encoded = json.dumps(events)
    assert "Updated secret" not in encoded and "Example person" not in encoded and "Edited alias" not in encoded
    service.remove(updated)
    assert not service.browse()
    assert event_records(service)[-1][1] == {"operation": "remove", "member_id": first.member.id, "changed_fields": []}


def test_identical_save_is_noop(service):
    first = service.save(profile())
    before = service.path.read_bytes()
    assert service.save(first.member, expected=first.token) == first
    assert before == service.path.read_bytes() and len(event_records(service)) == 1


@pytest.mark.parametrize("operation", ["edit", "remove"])
def test_stale_record_cannot_clobber_other_window(service, operation):
    old = service.save(profile())
    new = service.save(replace(old.member, daily_water_liters=5), expected=old.token)
    with pytest.raises(HouseholdConflict):
        if operation == "edit":
            service.save(replace(old.member, name="Stale changes"), expected=old.token)
        else:
            service.remove(old)
    assert service.get(old.member.id) == new and len(event_records(service)) == 2


def test_legacy_update_and_deleted_record_are_detected(service):
    first = service.save(profile())
    with service.connect() as db:
        db.execute("UPDATE household_members SET notes='Legacy API edit' WHERE id=?", (first.member.id,))
    with pytest.raises(HouseholdConflict):
        service.save(first.member, expected=first.token)
    latest = service.get(first.member.id)
    service.remove(latest)
    with pytest.raises(HouseholdConflict):
        service.save(latest.member, expected=latest.token)
    with pytest.raises(HouseholdConflict):
        service.get(latest.member.id)


def test_concurrent_edits_allow_one_winner(service):
    original = service.save(profile())

    def edit(number):
        try:
            service.save(replace(original.member, name=f"Window {number}"), expected=original.token)
            return "saved"
        except HouseholdConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, range(2))) == ["conflict", "saved"]
    assert len(event_records(service)) == 2


@pytest.mark.parametrize("operation", ["add", "edit", "remove"])
def test_event_failure_rolls_back_profile_write(service, operation):
    original = service.save(profile())
    with service.connect() as db:
        db.execute("CREATE TRIGGER fail_event BEFORE INSERT ON app_events BEGIN SELECT RAISE(ABORT,'Simulated failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="Simulated"):
        if operation == "add":
            service.save(profile(name="Second person"))
        elif operation == "edit":
            service.save(replace(original.member, daily_water_liters=6), expected=original.token)
        else:
            service.remove(original)
    assert service.get(original.member.id) == original and len(service.browse()) == 1


def test_counts_totals_and_filters_are_explicit(service):
    service.save(profile(name="Adult", daily_water_liters=3, daily_calories=2000))
    service.save(profile(name="Child", is_child=True, daily_water_liters=2, daily_calories=1500))
    service.save(profile(name="Animal", is_pet=True, daily_water_liters=1, daily_calories=0))
    summary = service.summary()
    assert (summary.people, summary.children, summary.pets) == (2, 1, 1)
    assert (summary.water_liters, summary.calories, summary.zero_calorie_profiles) == (6, 3500, 1)
    assert len(service.browse(kind="People")) == 2
    assert len(service.browse(kind="Children")) == 1 and len(service.browse(kind="Pets")) == 1
    assert not service.browse("Private note")  # Notes are not searched by the name filter.
    assert not service.browse("' OR 1=1 --") and not service.browse("%")


def test_search_unicode_paging_does_not_change_totals(service):
    for i in range(5):
        service.save(profile(name=f"Café {i}"))
    assert len(service.browse("CAFÉ", limit=2)) == 2
    assert len(service.browse(offset=4, limit=2)) == 1
    assert service.summary().people == 5


def test_empty_household_and_new_service_do_not_create_members(service):
    assert not service.browse() and service.summary().people == 0
    assert service.summary().water_liters == service.summary().calories == 0
    assert not event_records(service)


def test_unknown_existing_flags_not_silently_reclassified_on_save(service):
    original = service.save(profile())
    with service.connect() as db:
        db.execute("UPDATE household_members SET is_child=1,is_pet=1 WHERE id=?", (original.member.id,))
    invalid = service.get(original.member.id)
    assert kind_label(invalid.member) == "Child + pet: review"
    with pytest.raises(ValueError, match="not both"):
        service.save(invalid.member, expected=invalid.token)
    fixed = service.save(replace(invalid.member, is_child=False), expected=invalid.token)
    assert fixed.member.is_pet and not fixed.member.is_child


def test_legacy_infinite_water_can_be_corrected_without_displaying_valid_total(service):
    original = service.save(profile())
    with service.connect() as db:
        db.execute("UPDATE household_members SET daily_water_liters=?", (float("inf"),))
    with pytest.raises(ValueError, match="finite"):
        service.summary()
    invalid = service.get(original.member.id)
    service.save(replace(invalid.member, daily_water_liters=3), expected=invalid.token)
    assert service.summary().water_liters == 3


def test_path_reopen_and_schema_unchanged(service):
    with service.connect() as db:
        before = [tuple(row) for row in db.execute("SELECT name,sql FROM sqlite_master ORDER BY name")]
    saved = service.save(profile(notes="Café — 故事\n\n"))
    assert HouseholdService(service.path).get(saved.member.id) == saved
    with service.connect() as db:
        assert [tuple(row) for row in db.execute("SELECT name,sql FROM sqlite_master ORDER BY name")] == before


def test_new_id_token_and_invalid_id_rejected(service):
    with pytest.raises(ValueError):
        service.save(profile(), expected="stale")
    with pytest.raises(ValueError):
        service.get(True)
    with pytest.raises(ValueError):
        service.remove({})
    with pytest.raises(ValueError):
        validate_member({})


@pytest.mark.parametrize("arguments", [{"kind": "wrong"}, {"limit": True}, {"offset": -1},
                                       {"query": "x"*201}, {"query": None}, {"query": "\x00"}])
def test_invalid_queries_raise_without_writes(service, arguments):
    with pytest.raises(ValueError):
        service.browse(**arguments)
    assert not event_records(service)


def test_missing_database_not_created(tmp_path):
    service = HouseholdService(tmp_path / "absent.db")
    with pytest.raises(sqlite3.OperationalError):
        service.browse()
    assert not service.path.exists()


def test_no_network_required(service, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network attempted")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, forbidden)
    original = service.save(profile())
    assert service.summary().people == 1
    service.remove(original)
    assert not service.browse()
