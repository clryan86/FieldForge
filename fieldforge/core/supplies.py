"""Inventory editing with optimistic conflict checks and atomic private change records.

Works against the existing application tables. No new schema or network access.
The stricter validation applies to this workflow, not every legacy database API.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fieldforge.core.models import InventoryCategory, InventoryItem

NUMERIC_FIELDS = (
    "quantity", "minimum_quantity", "liters_per_unit", "calories_per_unit", "watt_hours_per_unit"
)
MAX_AMOUNT = 1_000_000_000_000
NOTICE = (
    "Enter usable stock and the amount in ONE unit. Units are not inferred from names. "
    "Estimates are planning arithmetic, not nutrition advice, water-safety approval, or proof of readiness."
)


def amount(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int, str)):
        raise ValueError(f"{label} must be a finite non-negative number")
    try:
        parsed = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite non-negative number") from exc
    if not math.isfinite(parsed) or not 0 <= parsed <= MAX_AMOUNT:
        raise ValueError(f"{label} must be between 0 and {MAX_AMOUNT:,}, not NaN or infinity")
    return parsed


def validate_item(item: InventoryItem) -> InventoryItem:
    if not isinstance(item, InventoryItem) or not isinstance(item.category, InventoryCategory):
        raise ValueError("expected an inventory item with a valid category")
    for name, maximum in (("name", 200), ("unit", 80), ("location", 300), ("notes", 10000)):
        text = getattr(item, name)
        if not isinstance(text, str) or len(text) > maximum or "\x00" in text:
            raise ValueError(f"{name} must be text of at most {maximum} characters without NUL")
    if not item.name.strip() or not item.unit.strip():
        raise ValueError("name and unit are required")
    if item.expires_on is not None and type(item.expires_on) is not date:
        raise ValueError("expiry must be a date, or empty")
    if item.id is not None and (type(item.id) is not int or item.id <= 0):
        raise ValueError("invalid inventory ID")
    numbers = {name: amount(getattr(item, name), name) for name in NUMERIC_FIELDS}
    return replace(item, **numbers)


def item_from_fields(fields: dict[str, str], *, item_id: int | None = None) -> InventoryItem:
    """Parse editor fields without guessing container sizes, calories or dates."""
    raw_date = fields.get("expires_on", "").strip()
    expiry = date.fromisoformat(raw_date) if raw_date else None
    if expiry is not None and expiry.isoformat() != raw_date:
        raise ValueError("expiry must be YYYY-MM-DD")
    numbers = {name: amount(fields.get(name, "0"), name) for name in NUMERIC_FIELDS}
    return validate_item(InventoryItem(
        fields.get("name", "").strip(), InventoryCategory(fields.get("category", "")),
        numbers.pop("quantity"), fields.get("unit", "").strip(), **numbers,
        expires_on=expiry, location=fields.get("location", "").strip(),
        notes=fields.get("notes", ""), id=item_id,
    ))


def flags(item: InventoryItem, today: date | None = None) -> tuple[str, ...]:
    today = today or date.today()
    result = []
    if item.quantity > 0:
        if item.category == InventoryCategory.WATER and not item.liters_per_unit:
            result.append("Needs liters/unit")
        if item.category == InventoryCategory.FOOD and not item.calories_per_unit:
            result.append("Needs kcal/unit")
        if item.expires_on and item.expires_on < today:
            result.append("Date passed: review stock")
    if item.minimum_quantity > 0 and item.quantity <= item.minimum_quantity:
        result.append("Low stock")
    return tuple(result)


def describe_item(item: InventoryItem) -> str:
    checked = validate_item(item)
    lines = [f"{checked.quantity:g} {checked.unit} · {checked.location or 'Location not set'}"]
    for field, unit in (("liters_per_unit", "liters"), ("calories_per_unit", "kcal"),
                        ("watt_hours_per_unit", "Wh")):
        factor = getattr(checked, field)
        if factor:
            lines.append(f"{checked.quantity:g} × {factor:g} {unit}/{checked.unit} = {checked.quantity * factor:g} {unit}")
    lines.extend(flags(checked))
    return "\n".join(lines)


def _item(row: sqlite3.Row) -> InventoryItem:
    values = dict(row)
    values["category"] = InventoryCategory(values["category"])
    values["expires_on"] = date.fromisoformat(values["expires_on"]) if values["expires_on"] else None
    return InventoryItem(**values)


def _token(row: sqlite3.Row) -> str:
    return hashlib.sha256(json.dumps(dict(row), sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class SupplyRecord:
    item: InventoryItem
    token: str


class SupplyConflict(ValueError):
    """The edited record changed since it was displayed; do not silently overwrite it."""


class SuppliesService:
    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path).expanduser().resolve()

    @contextmanager
    def connect(self):
        # Fail quickly rather than freeze a GUI behind another writer for seconds.
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=0.25)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _check(db, item_id, token):
        if type(item_id) is not int or item_id <= 0:
            raise ValueError("select a valid inventory record")
        row = db.execute("SELECT * FROM inventory_items WHERE id=?", (item_id,)).fetchone()
        if row is None or _token(row) != token:
            raise SupplyConflict("This supply changed or was removed in another window. Nothing was overwritten. "
                                 "Keep your edits, cancel, refresh the list and reopen the latest record.")
        return row

    def get(self, item_id: int) -> SupplyRecord:
        with self.connect() as db:
            row = db.execute("SELECT * FROM inventory_items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise SupplyConflict("Supply no longer exists. Refresh the list.")
        return SupplyRecord(_item(row), _token(row))

    def browse(self, query: str = "", category: str = "", *, offset: int = 0,
               limit: int = 50) -> tuple[SupplyRecord, ...]:
        if not isinstance(query, str) or len(query) > 200:
            raise ValueError("search must be at most 200 characters")
        if category:
            InventoryCategory(category)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid inventory page")
        with self.connect() as db:
            db.create_function("casefold", 1, lambda value: str(value).casefold())
            rows = db.execute(
                "SELECT * FROM inventory_items WHERE (?='' OR category=?) "
                "AND instr(casefold(name||' '||location||' '||unit),?)>0 "
                "ORDER BY name COLLATE NOCASE,id LIMIT ? OFFSET ?",
                (category, category, query.casefold().strip(), limit, offset),
            ).fetchall()
        return tuple(SupplyRecord(_item(row), _token(row)) for row in rows)

    @staticmethod
    def _event(db, operation: str, before, after, reason: str = ""):
        payload = {"operation": operation, "before": before, "after": after, "reason": reason}
        db.execute("INSERT INTO app_events(event_type,payload_json) VALUES('inventory_change',?)",
                   (json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False),))

    def save(self, item: InventoryItem, *, expected: str | None = None) -> SupplyRecord:
        item = validate_item(item)
        values = item.as_dict()
        values.pop("id")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            before = None
            if item.id is None:
                if expected is not None:
                    raise ValueError("new item cannot have an existing-record token")
                cursor = db.execute(
                    f"INSERT INTO inventory_items({','.join(values)}) VALUES({','.join('?' for _ in values)})",
                    tuple(values.values()),
                )
                item_id = cursor.lastrowid
            else:
                before = dict(self._check(db, item.id, expected))
                item_id = item.id
                if all(before[name] == value for name, value in values.items()):
                    row = db.execute("SELECT * FROM inventory_items WHERE id=?", (item_id,)).fetchone()
                    return SupplyRecord(_item(row), _token(row))
                db.execute(f"UPDATE inventory_items SET {','.join(name+'=?' for name in values)} WHERE id=?",
                           (*values.values(), item_id))
            row = db.execute("SELECT * FROM inventory_items WHERE id=?", (item_id,)).fetchone()
            self._event(db, "add" if before is None else "edit", before, dict(row))
            return SupplyRecord(_item(row), _token(row))

    def adjust(self, record: SupplyRecord, change: str, quantity: object, reason: str) -> SupplyRecord:
        if change not in {"receive", "use"}:
            raise ValueError("choose receive or use")
        value = amount(quantity, "adjustment")
        if value <= 0 or not isinstance(reason, str) or not reason.strip() or len(reason) > 500 or "\x00" in reason:
            raise ValueError("enter a positive amount and a reason of 1–500 characters")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self._check(db, record.item.id, record.token)
            current = validate_item(_item(old))
            total = Decimal(str(current.quantity)) + (1 if change == "receive" else -1) * Decimal(str(value))
            if total < 0:
                raise ValueError("cannot use more stock than is recorded")
            updated = validate_item(replace(current, quantity=float(total)))
            db.execute("UPDATE inventory_items SET quantity=? WHERE id=?", (updated.quantity, updated.id))
            row = db.execute("SELECT * FROM inventory_items WHERE id=?", (updated.id,)).fetchone()
            self._event(db, change, dict(old), dict(row), reason.strip())
            return SupplyRecord(_item(row), _token(row))

    def remove(self, record: SupplyRecord) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self._check(db, record.item.id, record.token)
            db.execute("DELETE FROM inventory_items WHERE id=?", (record.item.id,))
            self._event(db, "remove", dict(old), None)

    def dashboard(self, *, today: date | None = None) -> dict[str, object]:
        """One read snapshot. Suppress headline estimates for missing amounts or passed dates.

        Date flags call for review; they are not automatic food-safety verdicts.
        No valid date proves stock is safe. Legacy CLI calculator behavior is unchanged.
        """
        today = today or date.today()
        with self.connect() as db:
            db.execute("BEGIN")
            items = [validate_item(_item(row)) for row in db.execute("SELECT * FROM inventory_items")]
            members = db.execute("SELECT daily_water_liters,daily_calories FROM household_members").fetchall()
        result = {"household_members": len(members), "inventory_items": len(items)}
        for category, factor, daily, unit in ((InventoryCategory.WATER, "liters_per_unit", "daily_water_liters", "liters"),
                                              (InventoryCategory.FOOD, "calories_per_unit", "daily_calories", "kcal")):
            stock = [item for item in items if item.category == category and item.quantity > 0]
            warnings = []
            for item in stock:
                if not getattr(item, factor):
                    warnings.append(f"{item.name}: enter {unit} per {item.unit}.")
                if item.expires_on and item.expires_on < today:
                    warnings.append(f"{item.name}: recorded date {item.expires_on} has passed; review this stock.")
            demand = math.fsum(amount(member[daily], daily) for member in members)
            available = math.fsum(item.quantity * getattr(item, factor) for item in stock) * 0.9
            if daily == "daily_water_liters" and any(member[daily] <= 0 for member in members):
                warnings.append("A household water allowance is zero; review the saved assumptions.")
            if not members or not demand:
                label, days = "Set household", None
            elif warnings:
                label, days = "Review inputs", None
            else:
                days = available / demand
                if not math.isfinite(days):
                    raise ValueError("resource estimate exceeds the numeric range; review inputs")
                label = f"{days:.1f} days"
            result[category.value] = {"label": label, "days_remaining": days, "available": available,
                                     "daily_need": demand, "unit": unit, "warnings": warnings}
        result["low_stock"] = [item for item in items if item.minimum_quantity > 0 and item.quantity <= item.minimum_quantity]
        result["dated"] = [item for item in items if item.quantity > 0 and item.expires_on and
                           item.expires_on <= today + timedelta(days=30)]
        return result
