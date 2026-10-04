"""Consistent, whole-database backup for local FieldForge installations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import zipfile
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator

from fieldforge.db.database import _SCHEMA_VERSION

_MAX_BYTES = 1024 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
_SIDECARS = ("-wal", "-shm", "-journal")
_TABLES = {
    "metadata": {"key", "value"},
    "household_members": {"id", "name", "daily_water_liters", "daily_calories", "notes", "is_child", "is_pet"},
    "inventory_items": {"id", "name", "category", "quantity", "unit", "calories_per_unit", "liters_per_unit",
                        "watt_hours_per_unit", "expires_on", "minimum_quantity", "location", "notes"},
    "waypoints": {"id", "name", "latitude", "longitude", "kind", "notes"},
    "incident_entries": {"id", "created_at", "severity", "message"},
    "app_events": {"id", "created_at", "event_type", "payload_json"},
    "knowledge_articles": {"id", "slug", "title", "body", "category", "tags", "source_title", "source_url",
                           "source_publisher", "reviewed_on", "safety_level", "checksum", "license", "updated_at"},
    "knowledge_annotations": {"slug", "bookmarked", "note"},
    "knowledge_state": {"key", "value"},
}


def _check(connection: sqlite3.Connection) -> dict[str, int]:
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("database integrity check failed")
    names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not _TABLES.keys() <= names:
        raise ValueError("backup is missing FieldForge tables")
    for table, required in _TABLES.items():
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        if not required <= columns:
            raise ValueError(f"backup is missing required columns in {table}")
    version = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
    if version is None or version[0] != str(_SCHEMA_VERSION):
        raise ValueError("unsupported FieldForge database schema version")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("database contains broken record references")
    return {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in _TABLES if table not in {"metadata", "knowledge_state"}}


def _same_path(first: Path, second: Path) -> bool:
    return first.resolve() == second.resolve() or (
        first.exists() and second.exists() and os.path.samefile(first, second)
    )


def _protect_live_database(source: Path, output: Path) -> None:
    for path in [source, *(Path(str(source) + suffix) for suffix in _SIDECARS)]:
        if _same_path(path, output):
            raise ValueError("backup cannot overwrite the live database or its journal files")


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def export_snapshot(database_path: str | Path, destination: str | Path) -> Path:
    """Snapshot every SQLite table; close all handles before publishing the archive."""
    source = Path(database_path).expanduser().resolve()
    output = Path(destination).expanduser().resolve()
    if not source.is_file():
        raise ValueError("source database does not exist")
    _protect_live_database(source, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".fieldforge-") as temporary:
        snapshot = Path(temporary) / "database.sqlite3"
        archive = Path(temporary) / "backup.zip"

        def progress(_status: int, _remaining: int, total: int) -> None:
            if total * page_size > _MAX_BYTES:
                raise ValueError("backup exceeds 1 GiB limit")

        try:
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as current:
                page_size = current.execute("PRAGMA page_size").fetchone()[0]
                with closing(sqlite3.connect(snapshot)) as copy:
                    current.backup(copy, pages=256, progress=progress)
                    copy.execute("PRAGMA journal_mode=DELETE")
                    _check(copy)
        except sqlite3.Error as exc:
            raise ValueError(f"could not snapshot the FieldForge database: {exc}") from exc
        if snapshot.stat().st_size > _MAX_BYTES:
            raise ValueError("backup exceeds 1 GiB limit")
        digest = _digest(snapshot)
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
            bundle.writestr("manifest.json", json.dumps({"format": "fieldforge-full-backup",
                                                        "version": 1, "sha256": digest}))
            bundle.write(snapshot, "database.sqlite3")
        archive.chmod(0o600)
        # Windows _commit/FlushFileBuffers requires a writable handle.
        with archive.open("r+b") as stream:
            os.fsync(stream.fileno())
        _protect_live_database(source, output)
        os.replace(archive, output)
    return output


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate backup manifest key")
        result[key] = value
    return result


@contextmanager
def _verified_snapshot(source: Path, directory: Path | None = None) -> Iterator[tuple[Path, dict[str, object]]]:
    if source.stat().st_size > _MAX_BYTES + 65536:
        raise ValueError("backup archive exceeds size limit")
    with tempfile.TemporaryDirectory(dir=directory, prefix=".fieldforge-restore-") as temporary:
        staged = Path(temporary) / "database.sqlite3"
        try:
            with zipfile.ZipFile(source) as bundle:
                if sorted(bundle.namelist()) != ["database.sqlite3", "manifest.json"]:
                    raise ValueError("unexpected backup entries")
                if any(info.flag_bits & 1 or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                       for info in bundle.infolist()):
                    raise ValueError("unsupported backup compression or encryption")
                if bundle.getinfo("manifest.json").file_size > 4096:
                    raise ValueError("backup manifest exceeds size limit")
                manifest = json.loads(bundle.read("manifest.json"), object_pairs_hook=_unique_object)
                if (not isinstance(manifest, dict) or set(manifest) != {"format", "version", "sha256"}
                        or manifest["format"] != "fieldforge-full-backup"
                        or type(manifest["version"]) is not int or manifest["version"] != 1
                        or not isinstance(manifest["sha256"], str)
                        or re.fullmatch(r"[0-9a-f]{64}", manifest["sha256"]) is None):
                    raise ValueError("unsupported backup format")
                info = bundle.getinfo("database.sqlite3")
                if not 0 < info.file_size <= _MAX_BYTES:
                    raise ValueError("backup database exceeds size limit or is empty")
                digest, size = hashlib.sha256(), 0
                with bundle.open(info) as content, staged.open("wb") as output:
                    while chunk := content.read(_CHUNK_BYTES):
                        size += len(chunk)
                        if size > _MAX_BYTES or size > info.file_size:
                            raise ValueError("backup database exceeds size limit")
                        digest.update(chunk)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if size != info.file_size or digest.hexdigest() != manifest["sha256"]:
                    raise ValueError("backup integrity check failed")
            # This is our private, complete staged copy; immutable avoids sidecars
            # when checking old snapshots whose header still names WAL mode.
            with closing(sqlite3.connect(staged.as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
                counts = _check(connection)
        except (zipfile.BadZipFile, UnicodeError, sqlite3.Error, RuntimeError, NotImplementedError) as exc:
            raise ValueError(f"invalid FieldForge backup: {exc}") from exc
        yield staged, {"format": manifest["format"], "version": manifest["version"],
                       "database_bytes": size, "sha256": digest.hexdigest(), "records": counts}


def inspect_snapshot(source: str | Path) -> dict[str, object]:
    """Validate an archive and return record counts without changing any database."""
    with _verified_snapshot(Path(source).expanduser().resolve()) as (_staged, summary):
        return summary


def _restore_target(target: Path, archive: Path, replace: bool) -> None:
    if _same_path(target, archive):
        raise ValueError("restore cannot overwrite its backup archive")
    if target.exists() and not replace:
        raise ValueError("target database exists; pass --replace to restore")
    if any(Path(str(target) + suffix).exists() for suffix in _SIDECARS):
        raise ValueError("database has active journal files; close FieldForge before restore")


def restore_snapshot(database_path: str | Path, source: str | Path, *, replace: bool = False,
                     protected_database: str | Path | None = None) -> Path:
    """Verify a full backup and restore it; in-place replacement requires a closed app."""
    target = Path(database_path).expanduser().resolve()
    archive = Path(source).expanduser().resolve()
    if protected_database is not None:
        _protect_live_database(Path(protected_database).expanduser().resolve(), target)
    _restore_target(target, archive, replace)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _verified_snapshot(archive, target.parent) as (staged, _summary):
        if protected_database is not None:
            _protect_live_database(Path(protected_database).expanduser().resolve(), target)
        _restore_target(target, archive, replace)
        staged.chmod(0o600)
        if replace:
            os.replace(staged, target)
        else:
            # Link atomically fails if another process created the target after
            # validation. TemporaryDirectory removes the staging name afterward.
            os.link(staged, target)
    return target
