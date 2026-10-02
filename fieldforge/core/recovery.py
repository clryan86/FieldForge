"""Verified backup copies and preview-bound recovery, without in-place replacement.

The GUI deliberately exposes no overwrite mode. Archive validation is not a
security sandbox, content review, or proof of authorship: use trusted backups.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from fieldforge.core.snapshot import export_snapshot, restore_snapshot
from fieldforge.runtime import desktop_command, desktop_environment

NOTICE = (
    "Backups are unencrypted and include private household records, articles, notes, and learning "
    "progress and original PDFs explicitly stored in this database. External files not stored here, "
    "Python, models and map packs are not included. An integrity check is not content review or proof of authorship."
)
# Fixed identifiers only: an archive can never supply a SQL identifier to query.
_TABLES = (
    ("household_members", "Household members", {"id", "name", "daily_water_liters"}),
    ("inventory_items", "Inventory items", {"id", "name", "category", "quantity"}),
    ("waypoints", "Waypoints", {"id", "name", "latitude", "longitude"}),
    ("incident_entries", "Incident entries", {"id", "created_at", "severity", "message"}),
    ("app_events", "Application events", {"id", "created_at", "event_type", "payload_json"}),
    ("knowledge_articles", "Knowledge articles", {"id", "slug", "title", "body", "checksum"}),
    ("knowledge_annotations", "Article annotation records", {"slug", "bookmarked", "note"}),
    ("pathway_progress", "Learning-progress records", {"slug", "status", "note", "revision"}),
)
_QUERY_SECONDS = 5


@dataclass(frozen=True)
class BackupPreview:
    source: Path
    database_sha256: str
    database_bytes: int
    counts: tuple[tuple[str, int | None], ...]
    checked_at: str
    warnings: tuple[str, ...] = ()


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _new_path(path: str | Path, *, protected: tuple[Path, ...] = ()) -> Path:
    target = Path(path).expanduser().absolute()
    if target.is_symlink() or target.exists():
        raise FileExistsError("Choose a NEW filename. Existing files and symlinks are never replaced here.")
    if any(target.resolve() == item.resolve() for item in protected):
        raise ValueError("destination cannot be the active database, a sidecar, or the backup archive")
    return target


def _database_paths(database: Path) -> tuple[Path, ...]:
    database = database.expanduser().resolve()
    return (database, *(Path(str(database) + suffix) for suffix in ("-wal", "-shm", "-journal")))


def _summarize(database: Path) -> tuple[tuple[tuple[str, int | None], ...], tuple[str, ...]]:
    """Read counts, not personal record values. Do not migrate an inspected file."""
    deadline = time.monotonic() + _QUERY_SECONDS
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        try:
            rows = db.execute("SELECT name,type,sql FROM sqlite_master LIMIT 1001").fetchall()
            if len(rows) > 1000:
                raise ValueError("database schema is too large for this recovery preview")
            objects = {row[0]: (row[1], row[2] or "") for row in rows}

            def columns(table):
                kind, sql = objects[table]
                if kind != "table" or "VIRTUAL" in sql.upper().split():
                    raise ValueError(f"expected an ordinary FieldForge table: {table}")
                return {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}

            counts = []
            for table, label, required in _TABLES:
                if table not in objects:
                    counts.append((label, None))
                    continue
                if not required <= columns(table):
                    raise ValueError(f"unrecognized columns in {table}; use a compatible FieldForge build")
                counts.append((label, db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]))
            originals = {
                "knowledge_original_blobs": ("Stored original PDF files", {"sha256", "byte_count", "payload"}),
                "knowledge_original_refs": ("Original PDF references", {"id", "file_sha256", "article_slug"}),
            }
            if set(originals).intersection(objects):
                for table, (label, required) in originals.items():
                    if table not in objects or not required <= columns(table):
                        raise ValueError("incomplete original PDF storage schema in backup")
                    counts.append((label, db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]))
                if "knowledge_state" not in objects or not {"key", "value"} <= columns("knowledge_state"):
                    raise ValueError("missing original PDF version marker in backup")
                version = db.execute("SELECT value FROM knowledge_state WHERE key='original_files_schema'").fetchone()
                if version is None or version[0] != "1":
                    raise ValueError("unsupported original PDF storage version in backup")
            if not {"household_members", "knowledge_articles"}.intersection(objects):
                raise ValueError("archive contains SQLite data, but no recognized FieldForge records")
            warnings = []
            for table, key, expected in (("metadata", "schema_version", "2"),
                                          ("knowledge_state", "pathways_schema", "1")):
                if table in objects:
                    if not {"key", "value"} <= columns(table):
                        raise ValueError(f"unrecognized version table: {table}")
                    versions = db.execute(f'SELECT value FROM "{table}" WHERE key=? LIMIT 2', (key,)).fetchall()
                    if len(versions) > 1 or (versions and versions[0][0] != expected):
                        raise ValueError("unsupported database schema version; use a compatible FieldForge build")
            if any(count is None for _, count in counts):
                warnings.append("Some record tables are absent. This may be an older or library-only database, not a full app backup.")
            warnings.append("Checks cover archive bytes and SQLite structure, not every record's meaning, individual article hashes or original-PDF hashes. Verify original PDF bytes after recovery.")
            return tuple(counts), tuple(warnings)
        finally:
            db.set_progress_handler(None, 0)


def _preview(archive: Path, database: Path) -> BackupPreview:
    counts, warnings = _summarize(database)
    return BackupPreview(archive.resolve(), _hash(database), database.stat().st_size, counts,
                         datetime.now(timezone.utc).isoformat(timespec="seconds"), warnings)


def inspect_backup(source: str | Path) -> BackupPreview:
    """Fully decode/check into a temporary database, summarize, then remove it.

    No current application database is opened. checked_at is the time of this
    verification, not the backup creation date (v1 archives do not record one).
    """
    archive = Path(source).expanduser().resolve()
    if not archive.is_file():
        raise FileNotFoundError("choose an existing FieldForge .ffbackup archive")
    with tempfile.TemporaryDirectory(prefix="fieldforge-inspect-") as directory:
        database = Path(directory) / "checked.db"
        restore_snapshot(archive, database)
        return _preview(archive, database)


def create_verified_backup(database: str | Path, destination: str | Path) -> BackupPreview:
    """Save a new archive only after a read-back recovery and structure check.

    Publication uses a non-clobbering hard link in the destination filesystem;
    unsupported filesystems fail safely rather than overwriting an older copy.
    """
    source = Path(database).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError("active database not found; open FieldForge before backing up")
    target = _new_path(destination, protected=_database_paths(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fieldforge-backup-", dir=target.parent) as directory:
        staged = Path(directory) / "snapshot.ffbackup"
        export_snapshot(source, staged)
        preview = inspect_backup(staged)
        os.link(staged, target)  # Fails if another process created the path after the dialog.
    return replace(preview, source=target.resolve())


def restore_verified_copy(preview: BackupPreview, destination: str | Path, *,
                          active_database: str | Path) -> Path:
    """Revalidate and restore the previewed bytes to a NEW database, never the active one."""
    if not isinstance(preview, BackupPreview):
        raise ValueError("inspect the backup before restoring")
    target = _new_path(destination, protected=(preview.source, *_database_paths(Path(active_database))))
    # Do not create a new main file beside unrelated, pre-existing SQLite sidecars.
    if any(path.exists() or path.is_symlink() for path in _database_paths(target)[1:]):
        raise FileExistsError("destination has SQLite sidecars; choose a different NEW database filename")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fieldforge-recovery-", dir=target.parent) as directory:
        staged = Path(directory) / "recovered.db"
        restore_snapshot(preview.source, staged)
        current = _preview(preview.source, staged)
        if (current.database_sha256, current.database_bytes) != (preview.database_sha256, preview.database_bytes):
            raise ValueError("backup changed since preview; inspect the backup again before restoring")
        if any(path.exists() or path.is_symlink() for path in _database_paths(target)[1:]):
            raise FileExistsError("destination has SQLite sidecars; choose a different filename")
        os.link(staged, target)
    return target.resolve()


def launch_recovered_copy(database: str | Path) -> subprocess.Popen:
    """Explicit user action: launch a separate desktop process, without a shell.

    Does not alter this process's environment or the user's default database.
    A successful Popen is a launch request, not proof the child displayed its UI.
    """
    path = Path(database).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError("recovered database no longer exists")
    environment = desktop_environment(path)
    return subprocess.Popen(desktop_command(), env=environment,
                            cwd=Path(__file__).resolve().parents[2], shell=False)


def render_preview(preview: BackupPreview) -> str:
    rows = ["ARCHIVE CHECK PASSED", f"Archive: {preview.source}",
            f"Checked at (UTC): {preview.checked_at}",
            "Backup creation time: not stored in this archive format",
            f"Database size: {preview.database_bytes:,} bytes",
            f"Database SHA-256: {preview.database_sha256}", "", "RECORD COUNTS"]
    rows.extend(f"{label}: {count:,}" if count is not None else f"{label}: not present"
                for label, count in preview.counts)
    rows.extend(("", *preview.warnings, "", NOTICE))
    return "\n".join(rows)
