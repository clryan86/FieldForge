import math
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from fieldforge.app import FieldForgeApp
from fieldforge.navigation.geo import Waypoint
from fieldforge.navigation.places import (
    PlaceConflict,
    PlaceStore,
    coordinate,
    coordinate_text,
    describe_leg,
    estimate_leg,
    make_place,
)


@pytest.fixture
def store(tmp_path):
    app = FieldForgeApp(tmp_path / "places #test.db")
    return PlaceStore(app.db.path)


def point(**changes):
    return make_place(**{"name": "Fictional start", "latitude": "0", "longitude": "0", **changes})


@pytest.mark.parametrize("value,latitude,expected", [(" -40.5 ", True, -40.5), ("0", True, 0),
    ("+90", True, 90), ("-90", True, -90), ("180", False, 180), ("-180", False, -180),
    (".125", True, 0.125), ("-0.00000001", False, -1e-8)])
def test_coordinate_format_and_boundaries(value, latitude, expected):
    assert coordinate(value, latitude=latitude) == expected
    assert coordinate(coordinate_text(expected), latitude=latitude) == expected


@pytest.mark.parametrize("value", ["", " ", "90.001", "-90.001", "40,123", "12N", "12°30", "1/2",
    "1+2", "1e2", "NaN", "Infinity", float("inf"), float("nan"), True, None, [], "x"*41])
def test_invalid_latitudes_are_not_guessed(value):
    with pytest.raises(ValueError):
        coordinate(value, latitude=True)


def test_init_does_not_mutate_schema_or_seed_places(store):
    before = store.path.read_bytes()
    assert not store.snapshot().records
    PlaceStore(store.path)
    assert store.path.read_bytes() == before


def test_add_edit_unicode_notes_reopen_and_existing_cli_compatibility(store):
    first = store.save(point(name="  Café 森  ", notes="  Private note\r\n\n"))
    assert first.point.name == "Café 森"
    assert first.point.id > 0 and first.point.notes == "  Private note\r\n\n"
    updated = store.save(replace(first.point, longitude=1.25, kind="meeting point"), expected=first)
    assert updated.token != first.token
    assert PlaceStore(store.path).snapshot().records == (updated,)
    assert FieldForgeApp(store.path).waypoints() == [updated.point]
    original = FieldForgeApp(store.path).add_waypoint(Waypoint("Old CLI point", 2, 3, notes="Keep old"))
    assert store.snapshot((original.id,)).records[0].point == original


def test_identical_save_is_byte_preserving_noop(store):
    record = store.save(point())
    before = store.path.read_bytes()
    assert store.save(record.point, expected=record) == record
    assert store.path.read_bytes() == before


def test_stale_edit_delete_and_raw_legacy_change_are_guarded(store):
    old = store.save(point())
    new = store.save(replace(old.point, name="Updated"), expected=old)
    with pytest.raises(PlaceConflict):
        store.save(replace(old.point, longitude=5), expected=old)
    with pytest.raises(PlaceConflict):
        store.remove(old)
    with store.connect() as db:
        db.execute("UPDATE waypoints SET notes='Legacy raw update' WHERE id=?", (new.point.id,))
    with pytest.raises(PlaceConflict):
        store.remove(new)
    assert store.snapshot().records[0].point.notes == "Legacy raw update"


def test_concurrent_edits_have_one_winner(store):
    original = store.save(point())
    def change(value):
        try:
            store.save(replace(original.point, longitude=value), expected=original)
            return "saved"
        except PlaceConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change, [1, 2])) == ["conflict", "saved"]


def test_remove_preserves_other_tables_and_does_not_reuse_id(store):
    app = FieldForgeApp(store.path)
    app.add_incident("info", "Keep separate record")
    old = store.save(point())
    store.remove(old)
    new = store.save(point())
    assert new.point.id > old.point.id
    with pytest.raises(PlaceConflict):
        store.remove(old)
    assert app.incidents()[0]["message"] == "Keep separate record"


def test_failed_writes_are_rolled_back(store):
    original = store.save(point())
    with store.connect() as db:
        db.execute("CREATE TRIGGER deny_place BEFORE UPDATE ON waypoints BEGIN SELECT RAISE(ABORT,'simulated'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.save(replace(original.point, latitude=2), expected=original)
    assert store.snapshot().records == (original,)


@pytest.mark.parametrize("changes", [{"name": " "}, {"name": "x"*201}, {"kind": ""}, {"kind": "x"*81},
    {"name": "a\nb"}, {"notes": "x"*4001}, {"notes": "bad\x00"}, {"longitude": "180.1"}, {"latitude": True}])
def test_invalid_fields_do_not_create_rows(store, changes):
    with pytest.raises(ValueError):
        store.save(point(**changes))
    assert not store.snapshot().records


def test_selection_and_storage_limits(store, monkeypatch):
    from fieldforge.navigation import places
    monkeypatch.setattr(places, "MAX_PLACES", 1)
    row = store.save(point())
    with pytest.raises(ValueError, match="limit"):
        store.save(point(name="Second"))
    for ids in ((), [row.point.id], (True,), (None,), ([1],), (row.point.id, row.point.id)):
        with pytest.raises(ValueError):
            store.snapshot(ids)
    with pytest.raises(PlaceConflict):
        store.snapshot((999,))


def test_missing_or_unknown_schema_does_not_create_or_reset_data(tmp_path, store):
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        PlaceStore(missing)
    assert not missing.exists()
    with store.connect() as db:
        db.execute("ALTER TABLE waypoints ADD COLUMN future TEXT")
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="schema"):
        PlaceStore(store.path)
    assert store.path.read_bytes() == before


def test_invalid_existing_row_is_preserved_not_silently_hidden(store):
    row = store.save(point())
    with store.connect() as db:
        db.execute("UPDATE waypoints SET latitude=999 WHERE id=?", (row.point.id,))
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="preserved"):
        store.snapshot()
    assert before == store.path.read_bytes()


@pytest.mark.parametrize("destination,bearing", [((0, 1), 90), ((1, 0), 0), ((0, -1), 270), ((-1, 0), 180)])
def test_independent_cardinal_distances_and_true_bearings(destination, bearing):
    leg = estimate_leg(point(), point(name="End", latitude=destination[0], longitude=destination[1]))
    assert leg.meters == pytest.approx(math.pi * 6_371_008.8 / 180, abs=1e-7)
    assert leg.true_bearing == pytest.approx(bearing)
    assert "not magnetic" in describe_leg(leg) and "NOT a safe route" in describe_leg(leg)


def test_dateline_shortest_arc_and_same_meridian_convention():
    leg = estimate_leg(point(longitude=179), point(longitude=-179))
    assert leg.true_bearing == pytest.approx(90)
    assert leg.meters == pytest.approx(2*math.pi * 6_371_008.8 / 180)
    equal = estimate_leg(point(longitude=-180), point(longitude=180))
    assert equal.meters < 1e-6 and equal.true_bearing is None


@pytest.mark.parametrize("a,b,reason", [((0, 0), (0, 0), "Coincident"), ((0, 0), (0, 180), "Antipodal"),
    ((90, 0), (80, 10), "pole"), ((-90, 100), (-80, 50), "pole")])
def test_undefined_bearings_are_not_reported_as_north(a, b, reason):
    leg = estimate_leg(point(latitude=a[0], longitude=a[1]), point(latitude=b[0], longitude=b[1]))
    assert leg.true_bearing is None and reason in leg.bearing_note
    assert math.isfinite(leg.meters)
    assert "Unavailable" in describe_leg(leg)


def test_leg_uses_current_saved_coordinates_and_excludes_notes(store, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("No network expected")
    for name in ("socket", "getaddrinfo", "create_connection"):
        monkeypatch.setattr(socket, name, blocked)
    a = store.save(point(notes="PRIVATE_A"))
    b = store.save(point(name="End", longitude=1, notes="PRIVATE_B"))
    store.save(replace(b.point, longitude=2), expected=b)
    leg = store.estimate(a.point.id, b.point.id)
    assert leg.end.longitude == 2
    assert not leg.start.notes and not leg.end.notes
    assert "PRIVATE_" not in describe_leg(leg)
    assert store.estimate(a.point.id, a.point.id).true_bearing is None


def test_both_endpoints_come_from_one_sqlite_snapshot(store, monkeypatch):
    a = store.save(point())
    b = store.save(point(name="End", longitude=1))
    with store.connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
    original = PlaceStore._record
    changed = []
    def decode(row):
        result = original(row)
        if result.point.id == a.point.id and not changed:
            changed.append(True)
            with store.connect() as writer:
                writer.execute("UPDATE waypoints SET longitude=2 WHERE id=?", (b.point.id,))
        return result
    monkeypatch.setattr(PlaceStore, "_record", staticmethod(decode))
    first = store.estimate(a.point.id, b.point.id)
    assert first.end.longitude == 1
    assert store.estimate(a.point.id, b.point.id).end.longitude == 2
