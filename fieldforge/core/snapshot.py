"""Consistent, whole-database backup for local FieldForge installations."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

_MAX_BYTES = 1024 * 1024 * 1024
_TABLES = {"metadata", "household_members", "inventory_items", "waypoints",
           "incident_entries", "app_events", "knowledge_articles", "knowledge_annotations"}


def _check(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("database integrity check failed")
    names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not _TABLES <= names:
        raise ValueError("backup is missing FieldForge tables")


def export_snapshot(database_path: str | Path, destination: str | Path) -> Path:
    """Snapshot all SQLite tables, including knowledge and personal annotations."""
    source, output = Path(database_path), Path(destination)
    if not source.is_file():
        raise ValueError("source database does not exist")
    if output.exists() and os.path.samefile(source, output):
        raise ValueError("backup cannot overwrite the live database")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".fieldforge-") as temporary:
        snapshot = Path(temporary) / "database.sqlite3"
        archive = Path(temporary) / "backup.zip"
        with sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True) as current:
            with sqlite3.connect(snapshot) as copy:
                current.backup(copy)
        with sqlite3.connect(snapshot) as copy:
            _check(copy)
        if snapshot.stat().st_size > _MAX_BYTES:
            raise ValueError("backup exceeds 1 GiB limit")
        digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
            bundle.writestr("manifest.json", json.dumps({"format": "fieldforge-full-backup",
                                                        "version": 1, "sha256": digest}))
            bundle.write(snapshot, "database.sqlite3")
        with archive.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(archive, output)
    return output


def restore_snapshot(database_path: str | Path, source: str | Path, *, replace: bool = False) -> Path:
    """Verify a full backup and replace a closed application's database atomically."""
    target, archive = Path(database_path), Path(source)
    if target.exists() and not replace:
        raise ValueError("target database exists; pass --replace to restore")
    if any(Path(str(target) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("database has active journal files; close FieldForge before restore")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".fieldforge-restore-") as temporary:
        staged = Path(temporary) / "database.sqlite3"
        with zipfile.ZipFile(archive) as bundle:
            if sorted(bundle.namelist()) != ["database.sqlite3", "manifest.json"]:
                raise ValueError("unexpected backup entries")
            if bundle.getinfo("manifest.json").file_size > 4096:
                raise ValueError("backup manifest exceeds size limit")
            manifest = json.loads(bundle.read("manifest.json"))
            if (set(manifest) != {"format", "version", "sha256"}
                    or manifest["format"] != "fieldforge-full-backup"
                    or type(manifest["version"]) is not int or manifest["version"] != 1):
                raise ValueError("unsupported backup format")
            info = bundle.getinfo("database.sqlite3")
            if info.file_size > _MAX_BYTES:
                raise ValueError("backup exceeds 1 GiB limit")
            digest = hashlib.sha256()
            with bundle.open(info) as content, staged.open("wb") as output:
                while chunk := content.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if digest.hexdigest() != manifest["sha256"]:
                raise ValueError("backup integrity check failed")
        with sqlite3.connect(f"file:{staged}?mode=ro", uri=True) as connection:
            _check(connection)
        if target.exists() and not replace:
            raise ValueError("target database exists; pass --replace to restore")
        os.replace(staged, target)
    return target
