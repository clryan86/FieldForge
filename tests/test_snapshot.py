import json
import zipfile

import pytest

from fieldforge.core.models import HouseholdMember, InventoryCategory, InventoryItem
from fieldforge.core.snapshot import export_snapshot, restore_snapshot
from fieldforge.db.database import FieldForgeDatabase
from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.navigation.geo import Waypoint


def _seed(path):
    db = FieldForgeDatabase(path)
    db.add_member(HouseholdMember("Test Person"))
    db.add_inventory_item(InventoryItem("Rice", InventoryCategory.FOOD, 2, "bag"))
    db.add_waypoint(Waypoint("Meetup", 39.5, -75.5))
    db.add_incident_entry("warning", "Test incident")
    db.log_event("test", {"value": 1})
    library = KnowledgeLibrary(path)
    library.upsert(KnowledgeArticle(
        "water-reference", "Water Reference", "Example offline article body.", "water"
    ))
    library.annotate("water-reference", bookmarked=True, note="Private test note")


def test_complete_snapshot_roundtrip(tmp_path):
    source = tmp_path / "source.db"
    _seed(source)
    backup = export_snapshot(source, tmp_path / "complete.ffbackup")
    target = tmp_path / "restored.db"

    result = restore_snapshot(backup, target)
    assert result["status"] == "restored"

    db = FieldForgeDatabase(target)
    library = KnowledgeLibrary(target)
    assert db.list_members()[0].name == "Test Person"
    assert db.list_inventory()[0].name == "Rice"
    assert db.list_waypoints()[0].name == "Meetup"
    assert db.list_incident_entries()[0]["message"] == "Test incident"
    assert db.list_events()[0]["payload"] == {"value": 1}
    assert library.get("water-reference").title == "Water Reference"
    assert library.annotation("water-reference") == {
        "bookmarked": True, "note": "Private test note"
    }


def test_restore_protects_existing_database(tmp_path):
    source = tmp_path / "source.db"
    _seed(source)
    backup = export_snapshot(source, tmp_path / "complete.ffbackup")
    target = tmp_path / "existing.db"
    FieldForgeDatabase(target).add_member(HouseholdMember("Keep Me"))

    with pytest.raises(FileExistsError):
        restore_snapshot(backup, target)

    assert FieldForgeDatabase(target).list_members()[0].name == "Keep Me"


def test_tampered_snapshot_is_rejected_without_touching_target(tmp_path):
    source = tmp_path / "source.db"
    _seed(source)
    backup = export_snapshot(source, tmp_path / "complete.ffbackup")
    tampered = tmp_path / "tampered.ffbackup"

    with zipfile.ZipFile(backup) as original, zipfile.ZipFile(tampered, "w") as changed:
        manifest = json.loads(original.read("manifest.json"))
        manifest["database_sha256"] = "0" * 64
        changed.writestr("manifest.json", json.dumps(manifest))
        changed.writestr("fieldforge.sqlite3", original.read("fieldforge.sqlite3"))

    target = tmp_path / "restored.db"
    with pytest.raises(ValueError, match="integrity"):
        restore_snapshot(tampered, target)
    assert not target.exists()
