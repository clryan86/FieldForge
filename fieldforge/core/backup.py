"""Portable JSON backup and restore helpers."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fieldforge.core.models import HouseholdMember, InventoryCategory, InventoryItem
from fieldforge.db.database import FieldForgeDatabase

_BACKUP_VERSION = 1


def export_backup(database: FieldForgeDatabase, destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "backup_version": _BACKUP_VERSION,
        "members": [member.as_dict() for member in database.list_members()],
        "inventory": [item.as_dict() for item in database.list_inventory()],
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
    return path


def restore_backup(database: FieldForgeDatabase, source: str | Path) -> dict[str, int]:
    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    if payload.get("backup_version") != _BACKUP_VERSION:
        raise ValueError("unsupported FieldForge backup version")
    members = payload.get("members")
    inventory = payload.get("inventory")
    if not isinstance(members, list) or not isinstance(inventory, list):
        raise ValueError("backup must contain members and inventory arrays")

    restored_members = 0
    restored_inventory = 0
    for raw in members:
        database.add_member(
            HouseholdMember(
                name=str(raw["name"]),
                daily_water_liters=float(raw.get("daily_water_liters", 3.78541)),
                daily_calories=int(raw.get("daily_calories", 2000)),
                notes=str(raw.get("notes", "")),
                is_child=bool(raw.get("is_child", False)),
                is_pet=bool(raw.get("is_pet", False)),
            )
        )
        restored_members += 1

    for raw in inventory:
        expires = raw.get("expires_on")
        database.add_inventory_item(
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
        restored_inventory += 1
    return {"members": restored_members, "inventory": restored_inventory}
