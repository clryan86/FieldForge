import zipfile

import pytest

from fieldforge.cli import main
from fieldforge.core.models import HouseholdMember
from fieldforge.core.snapshot import export_snapshot, restore_snapshot
from fieldforge.db.database import FieldForgeDatabase
from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary


def test_full_backup_restores_private_data_and_events(tmp_path):
    original = tmp_path / "original.db"
    db = FieldForgeDatabase(original)
    db.add_member(HouseholdMember("A"))
    db.add_incident_entry("warning", "Test incident")
    library = KnowledgeLibrary(original)
    library.upsert(KnowledgeArticle("guide", "Guide", "Offline content", "reference"))
    library.annotate("guide", bookmarked=True, note="Private note")
    backup = export_snapshot(original, tmp_path / "full.zip")
    target = tmp_path / "restored.db"
    restore_snapshot(target, backup)
    assert FieldForgeDatabase(target).list_members()[0].name == "A"
    assert FieldForgeDatabase(target).list_incident_entries()[0]["message"] == "Test incident"
    assert KnowledgeLibrary(target).get("guide").body == "Offline content"
    assert KnowledgeLibrary(target).annotation("guide")["note"] == "Private note"


def test_rejects_tampering_and_preserves_existing_target(tmp_path):
    original = tmp_path / "original.db"
    FieldForgeDatabase(original)
    KnowledgeLibrary(original)
    backup = export_snapshot(original, tmp_path / "full.zip")
    with zipfile.ZipFile(backup) as bundle:
        manifest = bundle.read("manifest.json")
        content = bundle.read("database.sqlite3")
    with zipfile.ZipFile(backup, "w") as bundle:
        bundle.writestr("manifest.json", manifest)
        bundle.writestr("database.sqlite3", content + b"changed")
    target = tmp_path / "target.db"
    FieldForgeDatabase(target).add_member(HouseholdMember("Keep"))
    with pytest.raises(ValueError, match="integrity"):
        restore_snapshot(target, backup, replace=True)
    assert FieldForgeDatabase(target).list_members()[0].name == "Keep"


def test_cli_requires_explicit_replace(tmp_path, capsys):
    source = tmp_path / "source.db"
    assert main(["--database", str(source), "init"]) == 0
    backup = tmp_path / "backup.zip"
    assert main(["--database", str(source), "backup-full", str(backup)]) == 0
    target = tmp_path / "target.db"
    assert main(["--database", str(target), "restore-full", str(backup)]) == 0
    with pytest.raises(SystemExit):
        main(["--database", str(target), "restore-full", str(backup)])
    assert main(["--database", str(target), "restore-full", str(backup), "--replace"]) == 0
