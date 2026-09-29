"""SQLite persistence layer for FieldForge."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

from fieldforge.core.models import HouseholdMember, InventoryCategory, InventoryItem
from fieldforge.navigation.geo import Waypoint

_SCHEMA_VERSION = 2


class FieldForgeDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS household_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    daily_water_liters REAL NOT NULL,
                    daily_calories INTEGER NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    is_child INTEGER NOT NULL DEFAULT 0,
                    is_pet INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS inventory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    quantity REAL NOT NULL CHECK(quantity >= 0),
                    unit TEXT NOT NULL,
                    calories_per_unit REAL NOT NULL DEFAULT 0,
                    liters_per_unit REAL NOT NULL DEFAULT 0,
                    watt_hours_per_unit REAL NOT NULL DEFAULT 0,
                    expires_on TEXT,
                    minimum_quantity REAL NOT NULL DEFAULT 0,
                    location TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_inventory_category
                    ON inventory_items(category);
                CREATE INDEX IF NOT EXISTS idx_inventory_expiry
                    ON inventory_items(expires_on);
                CREATE TABLE IF NOT EXISTS waypoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'waypoint',
                    notes TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_waypoints_kind ON waypoints(kind);
                CREATE TABLE IF NOT EXISTS incident_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_incident_created_at
                    ON incident_entries(created_at);
                CREATE TABLE IF NOT EXISTS app_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )

    def add_member(self, member: HouseholdMember) -> HouseholdMember:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO household_members
                (name, daily_water_liters, daily_calories, notes, is_child, is_pet)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    member.name,
                    member.daily_water_liters,
                    member.daily_calories,
                    member.notes,
                    int(member.is_child),
                    int(member.is_pet),
                ),
            )
            return HouseholdMember(**{**member.as_dict(), "id": int(cursor.lastrowid)})

    def list_members(self) -> list[HouseholdMember]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM household_members ORDER BY id").fetchall()
        return [
            HouseholdMember(
                id=row["id"],
                name=row["name"],
                daily_water_liters=row["daily_water_liters"],
                daily_calories=row["daily_calories"],
                notes=row["notes"],
                is_child=bool(row["is_child"]),
                is_pet=bool(row["is_pet"]),
            )
            for row in rows
        ]

    def add_inventory_item(self, item: InventoryItem) -> InventoryItem:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO inventory_items
                (name, category, quantity, unit, calories_per_unit, liters_per_unit,
                 watt_hours_per_unit, expires_on, minimum_quantity, location, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.name,
                    item.category.value,
                    item.quantity,
                    item.unit,
                    item.calories_per_unit,
                    item.liters_per_unit,
                    item.watt_hours_per_unit,
                    item.expires_on.isoformat() if item.expires_on else None,
                    item.minimum_quantity,
                    item.location,
                    item.notes,
                ),
            )
            return InventoryItem(**{**item.__dict__, "id": int(cursor.lastrowid)})

    def list_inventory(self, category: InventoryCategory | None = None) -> list[InventoryItem]:
        query = "SELECT * FROM inventory_items"
        parameters: tuple[str, ...] = ()
        if category is not None:
            query += " WHERE category = ?"
            parameters = (category.value,)
        query += " ORDER BY category, name, id"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_inventory_item(row) for row in rows]

    def update_inventory_quantity(self, item_id: int, quantity: float) -> None:
        if quantity < 0:
            raise ValueError("quantity cannot be negative")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE inventory_items SET quantity = ? WHERE id = ?", (quantity, item_id)
            )
            if cursor.rowcount != 1:
                raise KeyError(f"inventory item {item_id} not found")

    def delete_inventory_item(self, item_id: int) -> None:
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
            if cursor.rowcount != 1:
                raise KeyError(f"inventory item {item_id} not found")

    def low_stock_items(self) -> list[InventoryItem]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM inventory_items
                WHERE minimum_quantity > 0 AND quantity <= minimum_quantity
                ORDER BY (minimum_quantity - quantity) DESC, name"""
            ).fetchall()
        return [self._row_to_inventory_item(row) for row in rows]

    def expiring_items(self, on_or_before: date) -> list[InventoryItem]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM inventory_items
                WHERE expires_on IS NOT NULL AND expires_on <= ?
                ORDER BY expires_on, name""",
                (on_or_before.isoformat(),),
            ).fetchall()
        return [self._row_to_inventory_item(row) for row in rows]

    def add_waypoint(self, waypoint: Waypoint) -> Waypoint:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO waypoints(name, latitude, longitude, kind, notes)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    waypoint.name,
                    waypoint.latitude,
                    waypoint.longitude,
                    waypoint.kind,
                    waypoint.notes,
                ),
            )
            return Waypoint(**{**waypoint.as_dict(), "id": int(cursor.lastrowid)})

    def list_waypoints(self, kind: str | None = None) -> list[Waypoint]:
        query = "SELECT * FROM waypoints"
        parameters: tuple[str, ...] = ()
        if kind is not None:
            query += " WHERE kind = ?"
            parameters = (kind,)
        query += " ORDER BY name, id"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            Waypoint(
                id=row["id"],
                name=row["name"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                kind=row["kind"],
                notes=row["notes"],
            )
            for row in rows
        ]

    def add_incident_entry(self, severity: str, message: str) -> int:
        severity = severity.strip().lower()
        if severity not in {"info", "warning", "critical"}:
            raise ValueError("severity must be info, warning, or critical")
        if not message.strip():
            raise ValueError("incident message cannot be empty")
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO incident_entries(severity, message) VALUES (?, ?)",
                (severity, message.strip()),
            )
            return int(cursor.lastrowid)

    def list_incident_entries(self, limit: int = 100) -> list[dict[str, object]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, created_at, severity, message
                FROM incident_entries ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def log_event(self, event_type: str, payload: dict[str, object]) -> None:
        if not event_type.strip():
            raise ValueError("event_type cannot be empty")
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO app_events(event_type, payload_json) VALUES (?, ?)",
                (event_type, json.dumps(payload, sort_keys=True)),
            )

    def list_events(self, limit: int = 100) -> list[dict[str, object]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, created_at, event_type, payload_json
                FROM app_events ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    @staticmethod
    def _row_to_inventory_item(row: sqlite3.Row) -> InventoryItem:
        return InventoryItem(
            id=row["id"],
            name=row["name"],
            category=InventoryCategory(row["category"]),
            quantity=row["quantity"],
            unit=row["unit"],
            calories_per_unit=row["calories_per_unit"],
            liters_per_unit=row["liters_per_unit"],
            watt_hours_per_unit=row["watt_hours_per_unit"],
            expires_on=date.fromisoformat(row["expires_on"]) if row["expires_on"] else None,
            minimum_quantity=row["minimum_quantity"],
            location=row["location"],
            notes=row["notes"],
        )
