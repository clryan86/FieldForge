import hashlib
import json
import os
import sqlite3
import stat
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from fieldforge.cli import main
from fieldforge.core.models import HouseholdMember
from fieldforge.core.snapshot import export_snapshot, inspect_snapshot, restore_snapshot
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


@pytest.fixture
def snapshot_source(tmp_path):
    source = tmp_path / "source # space.db"
    db = FieldForgeDatabase(source)
    db.add_member(HouseholdMember("Original"))
    KnowledgeLibrary(source)
    return source


def test_wal_snapshot_is_self_contained_and_inspect_does_not_initialize_a_database(snapshot_source, tmp_path, capsys):
    with closing(sqlite3.connect(snapshot_source)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE household_members SET name='Committed in WAL'")
        writer.commit()
        assert Path(str(snapshot_source) + "-wal").exists()
        archive = export_snapshot(snapshot_source, tmp_path / "backup.zip")
        untouched = tmp_path / "do-not-create.db"
        assert main(["--database", str(untouched), "backup-inspect", str(archive)]) == 0
        summary = json.loads(capsys.readouterr().out)
        assert summary["records"]["household_members"] == 1
        assert not untouched.exists()
        target = restore_snapshot(tmp_path / "recovered.db", archive)
        assert FieldForgeDatabase(target).list_members()[0].name == "Committed in WAL"
        with closing(sqlite3.connect(target)) as restored:
            assert restored.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_export_cannot_write_live_database_or_sidecars(snapshot_source, suffix):
    with pytest.raises(ValueError, match="live database"):
        export_snapshot(snapshot_source, Path(str(snapshot_source) + suffix))
    assert FieldForgeDatabase(snapshot_source).list_members()[0].name == "Original"


def test_export_rejects_hardlink_alias(snapshot_source, tmp_path):
    alias = tmp_path / "alias.zip"
    os.link(snapshot_source, alias)
    with pytest.raises(ValueError, match="live database"):
        export_snapshot(snapshot_source, alias)


@pytest.mark.parametrize("manifest", [None, [], 7, "bad", {"format": "fieldforge-full-backup", "version": True, "sha256": "0"*64}])
def test_invalid_manifests_fail_without_touching_target(snapshot_source, tmp_path, manifest):
    archive = export_snapshot(snapshot_source, tmp_path / "backup.zip")
    with zipfile.ZipFile(archive) as bundle:
        content = bundle.read("database.sqlite3")
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest))
        bundle.writestr("database.sqlite3", content)
    before = snapshot_source.read_bytes()
    with pytest.raises(ValueError, match="format"):
        restore_snapshot(snapshot_source, archive, replace=True)
    assert snapshot_source.read_bytes() == before
    assert not list(tmp_path.glob(".fieldforge-*"))


def test_invalid_zip_is_a_readable_cli_error(tmp_path, capsys):
    archive = tmp_path / "invalid.zip"
    archive.write_bytes(b"not a zip archive")
    with pytest.raises(SystemExit) as exc:
        main(["backup-inspect", str(archive)])
    assert exc.value.code == 2
    assert "invalid FieldForge backup" in capsys.readouterr().err


def test_duplicate_manifest_keys_are_rejected(snapshot_source, tmp_path):
    archive = export_snapshot(snapshot_source, tmp_path / "backup.zip")
    with zipfile.ZipFile(archive) as bundle:
        content = bundle.read("database.sqlite3")
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", '{"version":1,"version":1}')
        bundle.writestr("database.sqlite3", content)
    with pytest.raises(ValueError, match="duplicate"):
        inspect_snapshot(archive)


@pytest.mark.parametrize("fault", ["fsync", "replace"])
def test_export_failure_preserves_existing_backup_and_cleans_temp(snapshot_source, tmp_path, monkeypatch, fault):
    output = tmp_path / "backup.zip"
    output.write_bytes(b"keep previous backup")

    def fail(*args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("fieldforge.core.snapshot.os." + fault, fail)
    with pytest.raises(OSError, match="disk failure"):
        export_snapshot(snapshot_source, output)
    assert output.read_bytes() == b"keep previous backup"
    assert not list(tmp_path.glob(".fieldforge-*"))


def test_all_snapshot_connections_are_closed(snapshot_source, tmp_path, monkeypatch):
    real_connect = sqlite3.connect
    opened = []

    def connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr("fieldforge.core.snapshot.sqlite3.connect", connect)
    archive = export_snapshot(snapshot_source, tmp_path / "backup.zip")
    inspect_snapshot(archive)
    restore_snapshot(tmp_path / "copy.db", archive)
    assert opened
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_restore_never_overwrites_a_target_created_during_validation(snapshot_source, tmp_path, monkeypatch):
    archive = export_snapshot(snapshot_source, tmp_path / "backup.zip")
    target = tmp_path / "copy.db"
    real_link = os.link

    def create_concurrently(source, destination):
        target.write_bytes(b"concurrent data")
        real_link(source, destination)

    monkeypatch.setattr("fieldforge.core.snapshot.os.link", create_concurrently)
    with pytest.raises(FileExistsError):
        restore_snapshot(target, archive)
    assert target.read_bytes() == b"concurrent data"
    assert not list(tmp_path.glob(".fieldforge-*"))


def test_restore_rechecks_journals_before_replacing(snapshot_source, tmp_path, monkeypatch):
    from fieldforge.core import snapshot

    archive = export_snapshot(snapshot_source, tmp_path / "backup.zip")
    original = snapshot_source.read_bytes()
    real_check = snapshot._check

    def check(connection):
        counts = real_check(connection)
        Path(str(snapshot_source) + "-wal").write_bytes(b"new journal")
        return counts

    monkeypatch.setattr(snapshot, "_check", check)
    with pytest.raises(ValueError, match="journal"):
        restore_snapshot(snapshot_source, archive, replace=True)
    assert snapshot_source.read_bytes() == original


def test_restore_protects_archive_and_active_database(snapshot_source, tmp_path):
    archive = export_snapshot(snapshot_source, tmp_path / "backup.zip")
    with pytest.raises(ValueError, match="backup archive"):
        restore_snapshot(archive, archive, replace=True)
    with pytest.raises(ValueError, match="live database"):
        restore_snapshot(Path(str(snapshot_source) + "-wal"), archive,
                         protected_database=snapshot_source)


def test_export_rejects_unknown_schema_and_size_before_publish(snapshot_source, tmp_path, monkeypatch):
    output = tmp_path / "backup.zip"
    with closing(sqlite3.connect(snapshot_source)) as connection:
        connection.execute("UPDATE metadata SET value='999' WHERE key='schema_version'")
        connection.commit()
    with pytest.raises(ValueError, match="schema version"):
        export_snapshot(snapshot_source, output)
    assert not output.exists()
    monkeypatch.setattr("fieldforge.core.snapshot._MAX_BYTES", 10)
    with pytest.raises(ValueError, match="limit"):
        export_snapshot(snapshot_source, output)
    assert not output.exists()


def test_cli_backup_does_not_create_a_missing_source(tmp_path, capsys):
    missing, output = tmp_path / "typo.db", tmp_path / "backup.zip"
    with pytest.raises(SystemExit) as error:
        main(["--database", str(missing), "backup-full", str(output)])
    assert error.value.code == 2
    assert "source database does not exist" in capsys.readouterr().err
    assert not missing.exists()
    assert not output.exists()


@pytest.mark.parametrize("statement,error", [
    ("UPDATE metadata SET value='999' WHERE key='schema_version'", "schema version"),
    ("ALTER TABLE knowledge_state RENAME COLUMN value TO unexpected", "required columns"),
    ("INSERT INTO knowledge_annotations VALUES('missing',1,'orphan')", "record references"),
])
def test_restore_rejects_unusable_database_before_replacing(snapshot_source, tmp_path, statement, error):
    archive = export_snapshot(snapshot_source, tmp_path / "backup.zip")
    with zipfile.ZipFile(archive) as bundle:
        content = bundle.read("database.sqlite3")
        manifest = json.loads(bundle.read("manifest.json"))
    changed = tmp_path / "changed.db"
    changed.write_bytes(content)
    with closing(sqlite3.connect(changed)) as connection:
        connection.execute(statement)
        connection.commit()
    content = changed.read_bytes()
    manifest["sha256"] = hashlib.sha256(content).hexdigest()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("database.sqlite3", content)
        bundle.writestr("manifest.json", json.dumps(manifest))
    before = snapshot_source.read_bytes()
    with pytest.raises(ValueError, match=error):
        restore_snapshot(snapshot_source, archive, replace=True)
    assert snapshot_source.read_bytes() == before


@pytest.mark.skipif(os.name != "posix", reason="Unix file permission bits")
def test_backup_and_recovery_files_are_owner_only(snapshot_source, tmp_path):
    archive = export_snapshot(snapshot_source, tmp_path / "backup.zip")
    recovered = restore_snapshot(tmp_path / "recovered.db", archive)
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert stat.S_IMODE(recovered.stat().st_mode) == 0o600
