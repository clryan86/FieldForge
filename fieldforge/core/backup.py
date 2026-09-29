"""Portable, integrity-checked JSON backup and restore helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date
from pathlib import Path

from fieldforge.core.models import HouseholdMember, InventoryCategory, InventoryItem
from fieldforge.db.database import FieldForgeDatabase
from fieldforge.navigation.geo import Waypoint

_BACKUP_VERSION = 2


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _checksum(data: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_json(data).encode("utf-8")).hexdigest()


def export_backup(database: FieldForgeDatabase, destination: str | Path) -> Path:
    """Write an atomic JSON backup with a SHA-256 integrity checksum."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {
        "members": [member.as_dict() for member in database.list_members()],
        "inventory": [item.as_dict() for item in database.list_inventory()],
        "waypoints": [waypoint.as_dict() for waypoint in database.list_waypoints()],
    }
    payload = {
        "backup_version": _BACKUP_VERSION,
        "checksum_algorithm": "sha256",
        "checksum": _checksum(data),
        "data": data,
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
    return path


def restore_backup(database: FieldForgeDatabase, source: str | Path) -> dict[str, int]:
    """Validate an entire backup before adding its records to the database."""
    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    if payload.get("backup_version") != _BACKUP_VERSION:
        raise ValueError("unsupported FieldForge backup version")
    if payload.get("checksum_algorithm") != "sha256":
        raise ValueError("unsupported backup checksum algorithm")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("backup data must be an object")
    expected_checksum = payload.get("checksum")
    if not isinstance(expected_checksum, str) or not expected_checksum:
        raise ValueError("backup checksum is missing")
    if not hmac.compare_digest(_checksum(data), expected_checksum):
        raise ValueError("backup integrity check failed")

    members = data.get("members")
    inventory = data.get("inventory")
    waypoints = data.get("waypoints", [])
    if not isinstance(members, list) or not isinstance(inventory, list) or not isinstance(waypoints, list):
        raise ValueError("backup members, inventory, and waypoints must be arrays")

    parsed_members = [
        HouseholdMember(
            name=str(raw["name"]),
            daily_water_liters=float(raw.get("daily_water_liters", 3.78541)),
            daily_calories=int(raw.get("daily_calories", 2000)),
            notes=str(raw.get("notes", "")),
            is_child=bool(raw.get("is_child", False)),
            is_pet=bool(raw.get("is_pet", False)),
        )
        for raw in members
    ]
    parsed_inventory: list[InventoryItem] = []
    for raw in inventory:
        expires = raw.get("expires_on")
        parsed_inventory.append(
            InventoryItem(
                name=str(raw["name"]),
                category=InventoryCategory(str(raw["category"])),
                quantity=float(raw["quantity"]),
                unit=str(raw["unit"]),
                calories_per_unit=float(raw.get("calories_per_unit", 0.0)),
                liters_per_unit=float(raw.get("liters_per_unit", 0.0)),
                watt_hours_per_unit=float(raw.get("watt_hours_per_unit", 0.0)),
                expires_on=date.fromisoformat(expires) if expires else None,
                minimum_quantity=float(raw.get("minimum_quantity", 0.0)),
                location=str(raw.get("location", "")),
                notes=str(raw.get("notes", "")),
            )
        )
    parsed_waypoints = [
        Waypoint(
            name=str(raw["name"]),
            latitude=float(raw["latitude"]),
            longitude=float(raw["longitude"]),
            kind=str(raw.get("kind", "waypoint")),
            notes=str(raw.get("notes", "")),
        )
        for raw in waypoints
    ]

    for member in parsed_members:
        database.add_member(member)
    for item in parsed_inventory:
        database.add_inventory_item(item)
    for waypoint in parsed_waypoints:
        database.add_waypoint(waypoint)

    return {
        "members": len(parsed_members),
        "inventory": len(parsed_inventory),
        "waypoints": len(parsed_waypoints),
    }
