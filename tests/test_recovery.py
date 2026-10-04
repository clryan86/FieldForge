"""Backend recovery tests use synthetic SQLite schemas, not personal user records."""

import json
import os
import socket
import sqlite3
import sys
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from fieldforge.core import recovery
from fieldforge.core.recovery import (
    create_verified_backup,
    inspect_backup,
    launch_recovered_copy,
    render_preview,
    restore_verified_copy,
)
from fieldforge.core.snapshot import export_snapshot


def seed(path, marker="PRIVATE_SENTINEL", *, minimal=False):
    with closing(sqlite3.connect(path)) as db:
        db.executescript("""
            CREATE TABLE knowledge_articles(id INTEGER PRIMARY KEY, slug TEXT, title TEXT, body TEXT, checksum TEXT);
            CREATE TABLE knowledge_annotations(slug TEXT, bookmarked INTEGER, note TEXT);
            CREATE TABLE knowledge_state(key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO knowledge_state VALUES('pathways_schema','1');
            CREATE TABLE pathway_progress(slug TEXT PRIMARY KEY, status TEXT, note TEXT, revision INTEGER);
        """)
        db.execute("INSERT INTO knowledge_articles VALUES(1,'example','Synthetic fixture',?,'synthetic')", (marker,))
        db.execute("INSERT INTO knowledge_annotations VALUES('example',1,?)", (marker,))
        db.execute("INSERT INTO pathway_progress VALUES('water','exploring',?,1)", (marker,))
        if not minimal:
            db.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
                INSERT INTO metadata VALUES('schema_version','2');
                CREATE TABLE household_members(id INTEGER, name TEXT, daily_water_liters REAL);
                CREATE TABLE inventory_items(id INTEGER, name TEXT, category TEXT, quantity REAL);
                CREATE TABLE waypoints(id INTEGER, name TEXT, latitude REAL, longitude REAL);
                CREATE TABLE incident_entries(id INTEGER, created_at TEXT, severity TEXT, message TEXT);
                CREATE TABLE app_events(id INTEGER, created_at TEXT, event_type TEXT, payload_json TEXT);
                INSERT INTO household_members VALUES(1,'Fictional person',1);
                INSERT INTO inventory_items VALUES(1,'Fictional supply','other',3);
                INSERT INTO waypoints VALUES(1,'Fictional waypoint',0,0);
                INSERT INTO incident_entries VALUES(1,'2026-01-01','info','Fixture');
                INSERT INTO app_events VALUES(1,'2026-01-01','test','{}');
            """)
        db.commit()
    return path


@pytest.fixture
def sample(tmp_path):
    path = seed(tmp_path / "source.db")
    archive = tmp_path / "sample.ffbackup"
    preview = create_verified_backup(path, archive)
    return path, archive, preview


def test_backup_readback_counts_no_private_text_and_source_unchanged(tmp_path):
    source = seed(tmp_path / "source.db")
    before = source.read_bytes()
    preview = create_verified_backup(source, tmp_path / "copy.ffbackup")
    assert preview.source.exists()
    assert len(preview.database_sha256) == 64
    assert all(count == 1 for _, count in preview.counts)
    assert "PRIVATE_SENTINEL" not in render_preview(preview)
    assert "not stored" in render_preview(preview)
    assert "individual article hashes" in render_preview(preview)
    assert source.read_bytes() == before
    assert not list(tmp_path.glob(".fieldforge-backup-*"))


def test_inspection_does_not_create_or_open_current_database(sample, tmp_path):
    source, archive, preview = sample
    before = source.read_bytes()
    checked = inspect_backup(archive)
    assert checked.database_sha256 == preview.database_sha256
    assert checked.counts == preview.counts
    assert source.read_bytes() == before
    assert not (tmp_path / "not-created.db").exists()


def test_restore_copy_keeps_original_and_archive_bytes(sample, tmp_path):
    source, archive, preview = sample
    original, packed = source.read_bytes(), archive.read_bytes()
    target = restore_verified_copy(preview, tmp_path / "recovered.db", active_database=source)
    assert recovery._hash(target) == preview.database_sha256
    assert source.read_bytes() == original and archive.read_bytes() == packed
    with closing(sqlite3.connect(target)) as db:
        assert db.execute("SELECT note FROM pathway_progress").fetchone()[0] == "PRIVATE_SENTINEL"
    assert not list(tmp_path.glob(".fieldforge-recovery-*"))


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_backup_cannot_target_live_database_or_sidecars(sample, suffix):
    source, _, _ = sample
    before = source.read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        create_verified_backup(source, str(source) + suffix)
    assert source.read_bytes() == before


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_recovery_cannot_target_live_database_or_sidecars(sample, suffix):
    source, _, preview = sample
    before = source.read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        restore_verified_copy(preview, str(source) + suffix, active_database=source)
    assert source.read_bytes() == before


def test_existing_archive_or_database_never_overwritten(sample, tmp_path):
    source, archive, preview = sample
    before = archive.read_bytes()
    with pytest.raises(FileExistsError):
        create_verified_backup(source, archive)
    target = tmp_path / "existing.db"
    target.write_bytes(b"Do not clobber")
    with pytest.raises(FileExistsError):
        restore_verified_copy(preview, target, active_database=source)
    with pytest.raises(FileExistsError):
        restore_verified_copy(preview, archive, active_database=source)
    assert archive.read_bytes() == before
    assert target.read_bytes() == b"Do not clobber"


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_new_target_with_unrelated_sidecar_refused(sample, tmp_path, suffix):
    source, _, preview = sample
    target = tmp_path / "new.db"
    Path(str(target) + suffix).write_bytes(b"Existing sidecar")
    with pytest.raises(FileExistsError, match="sidecars"):
        restore_verified_copy(preview, target, active_database=source)
    assert not target.exists()


def test_preview_content_cannot_be_silently_substituted(sample, tmp_path):
    source, archive, preview = sample
    other = seed(tmp_path / "other.db", "DIFFERENT_BACKUP")
    export_snapshot(other, archive)
    with pytest.raises(ValueError, match="changed since preview"):
        restore_verified_copy(preview, tmp_path / "recovered.db", active_database=source)
    assert not (tmp_path / "recovered.db").exists()
    assert not list(tmp_path.glob(".fieldforge-recovery-*"))


def test_recovery_still_rejects_tampering_after_successful_preview(sample, tmp_path):
    source, archive, preview = sample
    with zipfile.ZipFile(archive) as original:
        content = original.read("fieldforge.sqlite3")
        manifest = json.loads(original.read("manifest.json"))
    manifest["database_sha256"] = "0" * 64
    with zipfile.ZipFile(archive, "w") as changed:
        changed.writestr("fieldforge.sqlite3", content)
        changed.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(ValueError, match="integrity"):
        restore_verified_copy(preview, tmp_path / "recovered.db", active_database=source)
    assert not (tmp_path / "recovered.db").exists()


@pytest.mark.parametrize("data", [b"not a zip", b"", b'{}'])
def test_invalid_archive_never_claims_success(tmp_path, data):
    archive = tmp_path / "bad.ffbackup"
    archive.write_bytes(data)
    with pytest.raises(ValueError):
        inspect_backup(archive)


def test_unrelated_sqlite_archive_is_not_reported_as_fieldforge(tmp_path):
    path = tmp_path / "other.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE unrelated(x)")
    archive = export_snapshot(path, tmp_path / "other.ffbackup")
    with pytest.raises(ValueError, match="no recognized"):
        inspect_backup(archive)


@pytest.mark.parametrize("table,key,version", [("metadata", "schema_version", "99"),
                                               ("knowledge_state", "pathways_schema", "2")])
def test_future_schema_is_rejected_without_migration(tmp_path, table, key, version):
    path = seed(tmp_path / "newer.db")
    with closing(sqlite3.connect(path)) as db:
        db.execute(f"UPDATE {table} SET value=? WHERE key=?", (version, key))
        db.commit()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="unsupported"):
        create_verified_backup(path, tmp_path / "should-not-publish.ffbackup")
    assert path.read_bytes() == before
    assert not (tmp_path / "should-not-publish.ffbackup").exists()


@pytest.mark.parametrize("kind", ["view", "wrong-columns"])
def test_known_record_names_do_not_make_malformed_schema_valid(tmp_path, kind):
    path = seed(tmp_path / "bad-schema.db", minimal=True)
    with closing(sqlite3.connect(path)) as db:
        if kind == "view":
            db.execute("CREATE VIEW household_members AS SELECT 1 AS id, 'x' AS name, 1 AS daily_water_liters")
        else:
            db.execute("CREATE TABLE household_members(unexpected_column TEXT)")
    archive = export_snapshot(path, tmp_path / "bad-schema.ffbackup")
    with pytest.raises(ValueError, match="ordinary|columns"):
        inspect_backup(archive)


def test_absent_tables_are_not_misrepresented_as_zero_records(tmp_path):
    path = seed(tmp_path / "library.db", minimal=True)
    preview = create_verified_backup(path, tmp_path / "library.ffbackup")
    counts = dict(preview.counts)
    assert counts["Household members"] is None and counts["Knowledge articles"] == 1
    assert "not present" in render_preview(preview)
    assert any("older or library-only" in warning for warning in preview.warnings)


def test_committed_wal_data_is_present_in_checked_copy(tmp_path):
    source = seed(tmp_path / "source.db")
    with closing(sqlite3.connect(source)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("INSERT INTO household_members VALUES(2,'Another fictional person',1)")
        db.commit()
        preview = create_verified_backup(source, tmp_path / "wal.ffbackup")
        assert dict(preview.counts)["Household members"] == 2


@pytest.mark.parametrize("operation", ["backup", "restore"])
def test_publish_race_preserves_the_other_process_file(sample, tmp_path, monkeypatch, operation):
    source, _, preview = sample
    target = tmp_path / "race-output"
    original = os.link

    def race(src, dst, *args, **kwargs):
        if Path(dst) == target:
            target.write_bytes(b"Won by another process")
        return original(src, dst, *args, **kwargs)

    monkeypatch.setattr(recovery.os, "link", race)
    with pytest.raises(FileExistsError):
        if operation == "backup":
            create_verified_backup(source, target)
        else:
            restore_verified_copy(preview, target, active_database=source)
    assert target.read_bytes() == b"Won by another process"
    assert not list(tmp_path.glob(".fieldforge-backup-*"))
    assert not list(tmp_path.glob(".fieldforge-recovery-*"))


def test_failed_readback_does_not_publish_backup(sample, tmp_path, monkeypatch):
    source, _, _ = sample
    target = tmp_path / "failed.ffbackup"

    def fail(*args):
        raise OSError("Simulated read-back error")

    monkeypatch.setattr(recovery, "inspect_backup", fail)
    with pytest.raises(OSError, match="read-back"):
        create_verified_backup(source, target)
    assert not target.exists()
    assert not list(tmp_path.glob(".fieldforge-backup-*"))


def test_restore_failure_cleans_private_staging_files(sample, tmp_path, monkeypatch):
    source, _, preview = sample

    def fail(src, dst):
        dst.write_bytes(b"Partial private data")
        raise OSError("Simulated restore failure")

    monkeypatch.setattr(recovery, "restore_snapshot", fail)
    with pytest.raises(OSError, match="restore failure"):
        restore_verified_copy(preview, tmp_path / "failed.db", active_database=source)
    assert not (tmp_path / "failed.db").exists()
    assert not list(tmp_path.glob(".fieldforge-recovery-*"))


def test_explicit_launch_uses_no_shell_and_keeps_parent_environment(sample, monkeypatch):
    source, _, _ = sample
    monkeypatch.setenv("FIELDFORGE_DB", "unchanged-default.db")
    launches = []
    sentinel = object()

    def spawn(*args, **kwargs):
        launches.append((args, kwargs))
        return sentinel

    monkeypatch.setattr(recovery.subprocess, "Popen", spawn)
    assert launch_recovered_copy(source) is sentinel
    args, kwargs = launches[0]
    assert args[0] == [sys.executable, "-m", "fieldforge.ui.desktop"]
    assert kwargs["shell"] is False
    assert kwargs["env"]["FIELDFORGE_DB"] == str(source.resolve())
    assert os.environ["FIELDFORGE_DB"] == "unchanged-default.db"


def test_missing_database_or_archive_not_created(tmp_path):
    missing = tmp_path / "absent.db"
    for operation in (lambda: create_verified_backup(missing, tmp_path / "backup"),
                      lambda: inspect_backup(missing), lambda: launch_recovered_copy(missing)):
        with pytest.raises(FileNotFoundError):
            operation()
    assert not missing.exists()


def test_backup_and_recovery_need_no_network_calls(sample, tmp_path, monkeypatch):
    source, archive, _ = sample

    def blocked(*args, **kwargs):
        raise AssertionError("Unexpected network request")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, blocked)
    preview = inspect_backup(archive)
    target = restore_verified_copy(preview, tmp_path / "offline.db", active_database=source)
    assert target.exists()
    assert create_verified_backup(target, tmp_path / "offline.ffbackup").source.exists()
