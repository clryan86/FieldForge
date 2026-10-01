"""Synthetic schemas match the existing inventory/household/event tables."""

import json
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import date

import pytest

from fieldforge.core.models import InventoryCategory, InventoryItem
from fieldforge.core.supplies import SuppliesService, SupplyConflict, amount, flags, item_from_fields


def seed_database(path):
    with closing(sqlite3.connect(path)) as db:
        db.executescript('''
            CREATE TABLE inventory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT NOT NULL,
                quantity REAL NOT NULL CHECK(quantity>=0), unit TEXT NOT NULL,
                calories_per_unit REAL NOT NULL DEFAULT 0, liters_per_unit REAL NOT NULL DEFAULT 0,
                watt_hours_per_unit REAL NOT NULL DEFAULT 0, expires_on TEXT,
                minimum_quantity REAL NOT NULL DEFAULT 0, location TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE household_members (id INTEGER PRIMARY KEY, name TEXT, daily_water_liters REAL, daily_calories INTEGER);
            CREATE TABLE app_events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                                     event_type TEXT NOT NULL, payload_json TEXT NOT NULL);
        ''')
    return SuppliesService(path)


@pytest.fixture
def service(tmp_path):
    return seed_database(tmp_path / "inventory.db")


def water(**changes):
    return replace(InventoryItem("Water bottles", InventoryCategory.WATER, 6, "bottle",
                                 liters_per_unit=2, minimum_quantity=2, location="Storage shelf"), **changes)


def household(service, liters=3, kcal=2000):
    with service.connect() as db:
        db.execute("INSERT INTO household_members VALUES(1,'Fictional person',?,?)", (liters, kcal))


def events(service):
    with service.connect() as db:
        return [json.loads(row[0]) for row in db.execute("SELECT payload_json FROM app_events ORDER BY id")]


@pytest.mark.parametrize("value", ["nan", "inf", "-Infinity", "-1", "1e999", "", "not-a-number", True, None, [], 1e13])
def test_invalid_amounts_are_rejected(value):
    with pytest.raises(ValueError):
        amount(value, "quantity")


@pytest.mark.parametrize("field", ["quantity", "minimum_quantity", "liters_per_unit", "calories_per_unit", "watt_hours_per_unit"])
def test_nonfinite_values_never_reach_storage(service, field):
    with pytest.raises(ValueError):
        service.save(water(**{field: float("nan")}))
    assert service.browse() == () and events(service) == []


def test_form_parser_exact_units_dates_and_notes():
    item = item_from_fields({"name": " Rice bag ", "category": "food", "quantity": "2.5", "unit": "bag",
                            "calories_per_unit": "8000", "expires_on": "2026-10-05", "notes": " Preserve\n\n"})
    assert item.quantity == 2.5 and item.calories_per_unit == 8000
    assert item.notes == " Preserve\n\n" and item.expires_on == date(2026, 10, 5)
    assert item.name == "Rice bag" and item.liters_per_unit == 0


@pytest.mark.parametrize("date_string", ["20261005", "2026-02-30", "10/05/2026", "tomorrow"])
def test_dates_not_guessed(date_string):
    with pytest.raises(ValueError):
        item_from_fields({"name": "test", "category": "food", "quantity": "1", "unit": "bag", "expires_on": date_string})


def test_add_edit_remove_keep_atomic_private_history(service):
    first = service.save(water(notes="Private stock note"))
    assert first.item.id and service.get(first.item.id) == first
    updated = service.save(replace(first.item, liters_per_unit=3, name="Larger bottles"), expected=first.token)
    assert updated.token != first.token and updated.item.liters_per_unit == 3
    assert [event["operation"] for event in events(service)] == ["add", "edit"]
    service.remove(updated)
    assert not service.browse()
    assert events(service)[-1]["before"]["notes"] == "Private stock note"
    assert events(service)[-1]["after"] is None


def test_identical_save_writes_no_additional_history(service):
    record = service.save(water())
    same = service.save(record.item, expected=record.token)
    assert same == record and len(events(service)) == 1


@pytest.mark.parametrize("operation", ["save", "use", "remove"])
def test_stale_records_do_not_overwrite_new_data(service, operation):
    old = service.save(water())
    newer = service.adjust(old, "receive", 2, "New delivery")
    with pytest.raises(SupplyConflict):
        if operation == "save":
            service.save(replace(old.item, quantity=100), expected=old.token)
        elif operation == "use":
            service.adjust(old, "use", 1, "Stale use")
        else:
            service.remove(old)
    assert service.get(old.item.id) == newer and len(events(service)) == 2


def test_legacy_direct_updates_are_detected_by_content_token(service):
    old = service.save(water())
    with service.connect() as db:
        db.execute("UPDATE inventory_items SET location='Changed outside editor' WHERE id=?", (old.item.id,))
    with pytest.raises(SupplyConflict):
        service.save(old.item, expected=old.token)
    assert service.get(old.item.id).item.location == "Changed outside editor"


def test_use_receive_decimal_quantities_and_no_overdraw(service):
    record = service.save(water(quantity=0.3))
    remaining = service.adjust(record, "use", 0.1, "Practice adjustment")
    assert remaining.item.quantity == 0.2
    remaining = service.adjust(remaining, "use", 0.2, "Use remainder")
    assert remaining.item.quantity == 0
    with pytest.raises(ValueError, match="more stock"):
        service.adjust(remaining, "use", 1, "Too much")
    assert service.get(record.item.id) == remaining
    received = service.adjust(remaining, "receive", 2.5, "Delivery")
    assert received.item.quantity == 2.5 and events(service)[-1]["reason"] == "Delivery"


@pytest.mark.parametrize("change,quantity,reason", [("other", 1, "reason"), ("use", 0, "reason"),
                                                   ("use", 1, ""), ("use", 1, "x"*501), ("receive", float("inf"), "reason")])
def test_invalid_adjustment_never_records_change(service, change, quantity, reason):
    original = service.save(water())
    with pytest.raises(ValueError):
        service.adjust(original, change, quantity, reason)
    assert service.get(original.item.id) == original and len(events(service)) == 1


def test_simultaneous_consumption_has_one_success_and_one_conflict(service):
    original = service.save(water(quantity=1))

    def consume(_):
        try:
            service.adjust(original, "use", 1, "Concurrent test")
            return "saved"
        except SupplyConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume, range(2))) == ["conflict", "saved"]
    assert service.get(original.item.id).item.quantity == 0


@pytest.mark.parametrize("operation", ["add", "edit", "use", "remove"])
def test_event_failure_rolls_back_stock_mutation(service, operation):
    original = service.save(water())
    with service.connect() as db:
        db.execute("CREATE TRIGGER deny_event BEFORE INSERT ON app_events BEGIN SELECT RAISE(ABORT, 'simulated disk error'); END")
    with pytest.raises(sqlite3.IntegrityError, match="simulated"):
        if operation == "add":
            service.save(water(name="New stock"))
        elif operation == "edit":
            service.save(replace(original.item, name="Edited"), expected=original.token)
        elif operation == "use":
            service.adjust(original, "use", 1, "Test")
        else:
            service.remove(original)
    assert service.get(original.item.id) == original and len(service.browse()) == 1


def test_filtering_pagination_and_sql_words_are_literal(service):
    for i in range(4):
        service.save(water(name=f"Bottle {i}"))
    assert len(service.browse(limit=2)) == 2 and len(service.browse(offset=2, limit=2)) == 2
    assert service.browse("Bottle 3")[0].item.name == "Bottle 3"
    assert not service.browse("' OR 1=1 --") and not service.browse("%")
    assert not service.browse(category="food")
    assert len(service.browse("storage SHELF")) == 4


def test_dashboard_totals_and_missing_assumptions(service):
    service.save(water())
    assert service.dashboard()["water"]["label"] == "Set household"
    household(service)
    result = service.dashboard()
    assert result["water"]["available"] == pytest.approx(10.8)
    assert result["water"]["daily_need"] == 3
    assert result["water"]["days_remaining"] == pytest.approx(3.6)
    assert result["food"]["days_remaining"] == 0
    food = InventoryItem("Rice", InventoryCategory.FOOD, 4, "bag", calories_per_unit=6000)
    service.save(food)
    assert service.dashboard()["food"]["days_remaining"] == pytest.approx(10.8)


def test_missing_conversions_hide_headline_not_silently_zero(service):
    household(service)
    record = service.save(water(liters_per_unit=0))
    data = service.dashboard()["water"]
    assert data["label"] == "Review inputs" and data["days_remaining"] is None
    assert "liters per bottle" in data["warnings"][0]
    service.save(replace(record.item, liters_per_unit=2), expected=record.token)
    assert service.dashboard()["water"]["days_remaining"] is not None


def test_passed_dates_require_review_and_zero_stock_does_not_contaminate_estimate(service):
    household(service)
    record = service.save(water(expires_on=date(2025, 1, 1)))
    assert service.dashboard(today=date(2026, 1, 1))["water"]["days_remaining"] is None
    service.adjust(record, "use", 6, "Removed from usable stock after review")
    assert service.dashboard(today=date(2026, 1, 1))["water"]["days_remaining"] == 0


def test_low_stock_and_upcoming_date_flags(service):
    record = service.save(water(quantity=2, expires_on=date(2026, 1, 20)))
    data = service.dashboard(today=date(2026, 1, 1))
    assert data["low_stock"] == [record.item] and data["dated"] == [record.item]
    assert flags(record.item, date(2026, 1, 1)) == ("Low stock",)


def test_invalid_legacy_data_raises_instead_of_displaying_nan(service):
    service.save(water())
    with service.connect() as db:
        db.execute("UPDATE inventory_items SET quantity=?", (float("inf"),))
    with pytest.raises(ValueError, match="infinity"):
        service.dashboard()


def test_missing_database_is_not_implicitly_created(tmp_path):
    service = SuppliesService(tmp_path / "absent.db")
    with pytest.raises(sqlite3.OperationalError):
        service.browse()
    assert not service.path.exists()


def test_no_network_needed(service, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("network attempted")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, fail)
    record = service.save(water())
    service.adjust(record, "use", 1, "Offline test")
    assert service.dashboard()["inventory_items"] == 1
