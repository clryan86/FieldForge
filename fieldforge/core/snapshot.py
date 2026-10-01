"""Complete, integrity-checked FieldForge snapshot backup and restore."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

_FORMAT = "fieldforge-snapshot"
_VERSION = 1
_DB_MEMBER = "fieldforge.sqlite3"
_MANIFEST_MEMBER = "manifest.json"
_MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_snapshot(database_path: str | Path, destination: str | Path) -> Path:
    """Create one atomic archive containing the complete SQLite application state."""
    source = Path(database_path).expanduser()
    target = Path(destination).expanduser()
    if not source.exists():
        raise FileNotFoundError(source)
    if source.resolve() == target.resolve():
        raise ValueError("snapshot destination cannot be the live database")
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="fieldforge-snapshot-") as directory:
        snapshot_db = Path(directory) / _DB_MEMBER
        with sqlite3.connect(source) as src, sqlite3.connect(snapshot_db) as dst:
            src.backup(dst)
            result = dst.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise ValueError("source database failed SQLite integrity check")
        size = snapshot_db.stat().st_size
        if size > _MAX_SNAPSHOT_BYTES:
            raise ValueError("snapshot database exceeds the 8 GiB safety limit")
        manifest = {
            "format": _FORMAT,
            "version": _VERSION,
            "database_member": _DB_MEMBER,
            "database_bytes": size,
            "database_sha256": _sha256(snapshot_db),
        }
        fd, temp_name = tempfile.mkstemp(
            prefix=".fieldforge-", suffix=".tmp", dir=target.parent
        )
        os.close(fd)
        temporary = Path(temp_name)
        try:
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
            ) as archive:
                archive.write(snapshot_db, _DB_MEMBER)
                archive.writestr(
                    _MANIFEST_MEMBER,
                    json.dumps(manifest, sort_keys=True, separators=(",", ":")),
                )
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return target


def restore_snapshot(
    source: str | Path,
    database_path: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, object]:
    """Validate a complete snapshot, then atomically install its database.

    Existing databases are protected unless overwrite=True. The archive is never
    extracted by filename, preventing archive path traversal.
    """
    archive_path = Path(source).expanduser()
    target = Path(database_path).expanduser()
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"target database already exists: {target}; restore to a new path or allow overwrite"
        )
    if archive_path.stat().st_size > _MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot archive exceeds the 8 GiB safety limit")

    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        if sorted(names) != sorted([_DB_MEMBER, _MANIFEST_MEMBER]):
            raise ValueError("invalid FieldForge snapshot contents")
        try:
            manifest = json.loads(archive.read(_MANIFEST_MEMBER).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid FieldForge snapshot manifest") from exc
        expected_keys = {
            "format", "version", "database_member", "database_bytes", "database_sha256"
        }
        if not isinstance(manifest, dict) or set(manifest) != expected_keys:
            raise ValueError("invalid FieldForge snapshot manifest")
        if (
            manifest["format"] != _FORMAT
            or manifest["version"] != _VERSION
            or manifest["database_member"] != _DB_MEMBER
        ):
            raise ValueError("unsupported FieldForge snapshot")
        size = manifest["database_bytes"]
        digest = manifest["database_sha256"]
        if (
            type(size) is not int
            or not 0 <= size <= _MAX_SNAPSHOT_BYTES
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("invalid FieldForge snapshot metadata")
        info = archive.getinfo(_DB_MEMBER)
        if info.file_size != size or info.file_size > _MAX_SNAPSHOT_BYTES:
            raise ValueError("snapshot database size mismatch")

        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=".fieldforge-restore-", suffix=".db", dir=target.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            hasher = hashlib.sha256()
            with archive.open(_DB_MEMBER, "r") as db_stream:
                copied = 0
                while True:
                    chunk = db_stream.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > _MAX_SNAPSHOT_BYTES:
                        raise ValueError("snapshot database exceeds the 8 GiB safety limit")
                    hasher.update(chunk)
                    stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            if copied != size or hasher.hexdigest() != digest:
                raise ValueError("snapshot integrity check failed")
            with sqlite3.connect(temporary) as db:
                result = db.execute("PRAGMA integrity_check").fetchone()
                if result is None or result[0] != "ok":
                    raise ValueError("restored database failed SQLite integrity check")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    return {"database": str(target), "database_bytes": size, "status": "restored"}
