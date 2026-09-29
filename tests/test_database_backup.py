import json
from datetime import date, timedelta

import pytest

from fieldforge.core.backup import export_backup, restore_backup
from fieldforge.core.models import HouseholdMember, InventoryCategory, InventoryItem
from fieldforge.db.database import FieldForgeDatabase
from fieldforge.navigation.geo import Waypoint


def test_database_roundtrip_alerts_waypoints_incidents_and_quantity_update(tmp_path):
    db = FieldForgeDatabase(tmp_path / "fieldforge.db")
    member = db.add_member(HouseholdMember("Chris"))
    assert member.id is not None

    item = db.add_inventory_item(
        InventoryItem(
            "Water",
            InventoryCategory.WATER,
            2,
            "jug",
            liters_per_unit=3.78541,
            minimum_quantity=3,
            expires_on=date.today() + timedelta(days=10),
        )
    )
    assert item.id is not None
    waypoint = db.add_waypoint(Waypoint("Primary meetup", 39.5, -75.5, kind="rendezvous"))
    assert waypoint.id is not None
    assert db.list_waypoints("rendezvous")[0].name == "Primary meetup"

    incident_id = db.add_incident_entry("warning", "Generator fuel below planning target")
    assert incident_id > 0
    incidents = db.list_incident_entries()
    assert incidents[0]["severity"] == "warning"
    assert "Generator" in incidents[0]["message"]

    assert len(db.list_members()) == 1
    assert len(db.list_inventory(InventoryCategory.WATER)) == 1
    assert db.low_stock_items()[0].name == "Water"
    assert db.expiring_items(date.today() + timedelta(days=30))[0].name == "Water"

    db.update_inventory_quantity(item.id, 5)
    assert db.list_inventory()[0].quantity == 5
    assert db.low_stock_items() == []


def test_json_backup_restore_roundtrip_includes_waypoints(tmp_path):
    source = FieldForgeDatabase(tmp_path / "source.db")
    source.add_member(HouseholdMember("A", daily_calories=1800))
    source.add_inventory_item(
        InventoryItem("Rice", InventoryCategory.FOOD, 4, "bag", calories_per_unit=6000)
    )
    source.add_waypoint(Waypoint("Shelter", 40.0, -75.0, kind="destination"))

    backup_path = export_backup(source, tmp_path / "backup.json")
    target = FieldForgeDatabase(tmp_path / "target.db")
    counts = restore_backup(target, backup_path)

    assert counts == {"members": 1, "inventory": 1, "waypoints": 1}
    assert target.list_members()[0].name == "A"
    assert target.list_inventory()[0].name == "Rice"
    assert target.list_waypoints()[0].name == "Shelter"


def test_backup_integrity_failure_is_detected_before_restore(tmp_path):
    source = FieldForgeDatabase(tmp_path / "source.db")
    source.add_member(HouseholdMember("A"))
    backup_path = export_backup(source, tmp_path / "backup.json")

    payload = json.loads(backup_path.read_text(encoding="utf-8"))
    payload["data"]["members"][0]["name"] = "tampered"
    backup_path.write_text(json.dumps(payload), encoding="utf-8")

    target = FieldForgeDatabase(tmp_path / "target.db")
    with pytest.raises(ValueError, match="integrity"):
        restore_backup(target, backup_path)
    assert target.list_members() == []
