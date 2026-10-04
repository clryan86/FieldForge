"""Offline waypoint editing and approximate point-to-point calculations.

Uses the original waypoints table without migration. No GPS, maps, route finding,
magnetic correction, geocoding, personal-profile lookup or network operations.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from fieldforge.navigation.geo import Waypoint

MAX_PLACES = 2000
NOTICE = (
    "WGS 84 decimal degrees; latitude first. North/east positive, south/west negative. "
    "User-entered places are not verified safe destinations. No live GPS, maps or route guidance. "
    "Distances are spherical estimates; bearings are initial TRUE bearings, not magnetic compass bearings."
)
_FIELDS = {"id", "name", "latitude", "longitude", "kind", "notes"}
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z")


def coordinate(value: str | float, *, latitude: bool) -> float:
    if isinstance(value, str):
        if len(value) > 40 or not _DECIMAL.fullmatch(value.strip()):
            raise ValueError("Enter signed decimal degrees only; no commas, direction letters or expressions.")
        value = value.strip()
    elif type(value) not in (int, float):
        raise ValueError("Coordinates must be finite numbers, not blank or boolean values.")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError("Coordinate is not a supported finite number.") from exc
    bound = 90 if latitude else 180
    if not math.isfinite(number) or not -bound <= number <= bound:
        raise ValueError(f"{'Latitude' if latitude else 'Longitude'} must be between {-bound} and {bound} degrees.")
    return number


def coordinate_text(value: float) -> str:
    """Round-trip decimal spelling without exponent notation or display rounding."""
    return format(Decimal(str(value)), "f")


def _text(value: str, name: str, maximum: int, *, multiline: bool = False) -> None:
    if not isinstance(value, str) or len(value) > maximum or (not multiline and not value.strip()):
        raise ValueError(f"{name} must be {'at most' if multiline else '1 to'} {maximum} characters.")
    for char in value:
        n = ord(char)
        xml_character = n in (9, 10, 13) or 0x20 <= n <= 0xD7FF or 0xE000 <= n <= 0xFFFD or 0x10000 <= n <= 0x10FFFF
        if not xml_character or (not multiline and (n < 32 or n == 127)):
            raise ValueError(f"{name} contains unsupported control characters.")


def validate(point: Waypoint) -> Waypoint:
    if not isinstance(point, Waypoint):
        raise ValueError("Choose a waypoint record.")
    _text(point.name, "Place name", 200)
    _text(point.kind, "Place type", 80)
    _text(point.notes, "Private place notes", 4000, multiline=True)
    coordinate(point.latitude, latitude=True)
    coordinate(point.longitude, latitude=False)
    if point.id is not None and (type(point.id) is not int or point.id <= 0):
        raise ValueError("Invalid waypoint ID.")
    return point


def make_place(name: str, latitude: str | float, longitude: str | float,
               kind: str = "waypoint", notes: str = "", *, place_id: int | None = None) -> Waypoint:
    if not isinstance(name, str) or not isinstance(kind, str):
        raise ValueError("Place name and type must be text.")
    return validate(Waypoint(name.strip(), coordinate(latitude, latitude=True),
                             coordinate(longitude, latitude=False), kind.strip(), notes, place_id))


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PlaceRecord:
    point: Waypoint
    token: str


@dataclass(frozen=True)
class PlaceSnapshot:
    records: tuple[PlaceRecord, ...]
    token: str


@dataclass(frozen=True)
class LegEstimate:
    start: Waypoint
    end: Waypoint
    meters: float
    true_bearing: float | None
    bearing_note: str
    captured_at: str


class PlaceConflict(ValueError):
    """A stored row or import preview changed; do not silently overwrite it."""


class PlaceStore:
    def __init__(self, database: str | Path) -> None:
        self.path = Path(database).expanduser().resolve()
        with self.connect() as db:
            table = db.execute("SELECT type,sql FROM sqlite_master WHERE name='waypoints'").fetchone()
            if table is None or table[0] != "table" or "VIRTUAL" in (table[1] or "").upper().split():
                raise ValueError("Open an initialized FieldForge database with a waypoint table.")
            if {r[1] for r in db.execute("PRAGMA table_info(waypoints)")} != _FIELDS:
                raise ValueError("Unsupported waypoint schema; existing data was not reset.")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=0.25)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _record(row) -> PlaceRecord:
        if row is None:
            raise PlaceConflict("Place no longer exists. Refresh before continuing.")
        try:
            point = validate(Waypoint(**dict(row)))
            return PlaceRecord(point, _hash(dict(row)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("A saved waypoint has invalid fields; data was preserved, not reset. " + str(exc)) from exc

    @classmethod
    def _snapshot(cls, db) -> PlaceSnapshot:
        rows = db.execute("SELECT * FROM waypoints ORDER BY id LIMIT ?", (MAX_PLACES + 1,)).fetchall()
        if len(rows) > MAX_PLACES:
            raise ValueError("More than 2,000 waypoints; this workspace cannot load a partial collection.")
        records = tuple(cls._record(row) for row in rows)
        return PlaceSnapshot(records, _hash(tuple(r.token for r in records)))

    def snapshot(self, ids: tuple[int, ...] | None = None) -> PlaceSnapshot:
        with self.connect() as db:
            db.execute("BEGIN")
            if ids is None:
                return self._snapshot(db)
            if not isinstance(ids, tuple) or not 1 <= len(ids) <= MAX_PLACES:
                raise ValueError("Select distinct waypoint IDs.")
            for number in ids:
                self._id(number)
            if len(set(ids)) != len(ids):
                raise ValueError("Select distinct waypoint IDs.")
            records = tuple(self._record(db.execute("SELECT * FROM waypoints WHERE id=?", (i,)).fetchone()) for i in ids)
            return PlaceSnapshot(records, _hash(tuple(r.token for r in records)))

    @staticmethod
    def _id(value):
        if type(value) is not int or value <= 0:
            raise ValueError("Select a valid waypoint ID.")

    def _check(self, db, expected: PlaceRecord) -> PlaceRecord:
        if not isinstance(expected, PlaceRecord):
            raise ValueError("Load the saved place before editing or removing it.")
        self._id(expected.point.id)
        actual = self._record(db.execute("SELECT * FROM waypoints WHERE id=?", (expected.point.id,)).fetchone())
        if actual.token != expected.token:
            raise PlaceConflict("This place changed in another window. Keep your edits, cancel, refresh and reopen it.")
        return actual

    @staticmethod
    def _insert(db, point: Waypoint) -> int:
        cursor = db.execute("INSERT INTO waypoints(name,latitude,longitude,kind,notes) VALUES(?,?,?,?,?)",
                            (point.name, point.latitude, point.longitude, point.kind, point.notes))
        return int(cursor.lastrowid)

    def save(self, point: Waypoint, *, expected: PlaceRecord | None = None) -> PlaceRecord:
        validate(point)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if expected is None:
                if point.id is not None:
                    raise ValueError("New places must not specify an existing ID.")
                if db.execute("SELECT COUNT(*) FROM waypoints").fetchone()[0] >= MAX_PLACES:
                    raise ValueError("Waypoint limit reached (2,000); no record added.")
                number = self._insert(db, point)
            else:
                actual = self._check(db, expected)
                if point.id != actual.point.id:
                    raise ValueError("Edited waypoint ID does not match the loaded record.")
                if point == actual.point:
                    return actual
                number = actual.point.id
                db.execute("UPDATE waypoints SET name=?,latitude=?,longitude=?,kind=?,notes=? WHERE id=?",
                           (point.name, point.latitude, point.longitude, point.kind, point.notes, number))
            return self._record(db.execute("SELECT * FROM waypoints WHERE id=?", (number,)).fetchone())

    def remove(self, expected: PlaceRecord) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self._check(db, expected)
            db.execute("DELETE FROM waypoints WHERE id=?", (record.point.id,))

    def estimate(self, start_id: int, end_id: int) -> LegEstimate:
        if start_id == end_id:
            points = self.snapshot((start_id,)).records * 2
        else:
            points = self.snapshot((start_id, end_id)).records
        return estimate_leg(points[0].point, points[1].point)


def estimate_leg(start: Waypoint, end: Waypoint) -> LegEstimate:
    validate(start)
    validate(end)
    lat1, lat2 = math.radians(start.latitude), math.radians(end.latitude)
    lon1, lon2 = math.radians(start.longitude), math.radians(end.longitude)
    a = (math.cos(lat1)*math.cos(lon1), math.cos(lat1)*math.sin(lon1), math.sin(lat1))
    b = (math.cos(lat2)*math.cos(lon2), math.cos(lat2)*math.sin(lon2), math.sin(lat2))
    cross = (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    angle = math.atan2(math.sqrt(sum(x*x for x in cross)), sum(x*y for x, y in zip(a, b)))
    bearing, reason = None, ""
    if angle < 1e-10:
        reason = "Coincident or extremely close points: no meaningful direction."
    elif math.pi - angle < 1e-8:
        reason = "Antipodal or nearly antipodal points: no stable unique initial bearing."
    elif abs(math.cos(lat1)) < 1e-10:
        reason = "Start at or extremely near a geographic pole: true-north reference is undefined here."
    else:
        dlon = lon2-lon1
        x = math.sin(dlon)*math.cos(lat2)
        y = math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(dlon)
        bearing = math.degrees(math.atan2(x, y)) % 360
    return LegEstimate(replace(start, notes=""), replace(end, notes=""), angle*6_371_008.8, bearing, reason,
                       datetime.now(timezone.utc).isoformat(timespec="seconds"))


def describe_leg(leg: LegEstimate) -> str:
    bearing = (f"{leg.true_bearing:.1f}° TRUE (not magnetic)" if leg.true_bearing is not None
               else "Unavailable — " + leg.bearing_note)
    return (f"FROM: {leg.start.name}\nLatitude {coordinate_text(leg.start.latitude)}, longitude {coordinate_text(leg.start.longitude)}\n\n"
            f"TO: {leg.end.name}\nLatitude {coordinate_text(leg.end.latitude)}, longitude {coordinate_text(leg.end.longitude)}\n\n"
            f"Approximate great-circle distance: {leg.meters/1000:,.3f} km ({leg.meters:,.1f} m)\n"
            f"Initial bearing: {bearing}\n\n"
            "Spherical model, not surveyed accuracy or traveled distance. No roads, obstacles, terrain, "
            "access rights, current hazards or travel time are evaluated. A straight line is NOT a safe route. "
            "True and magnetic bearings differ; no magnetic declination is applied.\n\n"
            f"Calculated from saved coordinates at {leg.captured_at} (device UTC). Refresh/recalculate after changes. "
            "Private place notes are not included in this result.")
