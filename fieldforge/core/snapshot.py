"""Complete SQLite snapshots. Checksums detect corruption, not trusted authorship.

Archives are unencrypted and contain private records. Restore only trusted
snapshots. Close FieldForge before restoring; prefer recovery to a new path.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
import zipfile
from contextlib import closing
from pathlib import Path

_FORMAT = "fieldforge-snapshot"
_VERSION = 1
_DB_MEMBER = "fieldforge.sqlite3"
_MANIFEST_MEMBER = "manifest.json"
_MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024 * 1024
_MAX_MANIFEST_BYTES = 16 * 1024
_OPERATION_SECONDS = 60


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_file(first: Path, second: Path) -> bool:
    return first.resolve() == second.resolve() or (
        first.exists() and second.exists() and first.samefile(second)
    )


def _connect(path: Path, mode: str = "ro") -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + f"?mode={mode}", uri=True, timeout=5)


def _check(db: sqlite3.Connection) -> None:
    deadline = time.monotonic() + _OPERATION_SECONDS
    db.execute("PRAGMA trusted_schema=OFF")
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
    try:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("database failed SQLite integrity check")
    except sqlite3.Error as exc:
        raise ValueError(f"database integrity check could not complete: {exc}") from exc
    finally:
        db.set_progress_handler(None, 0)


def _copy_database(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    deadline = time.monotonic() + _OPERATION_SECONDS
    page_size = source.execute("PRAGMA page_size").fetchone()[0]

    def progress(_status: int, _remaining: int, total: int) -> None:
        if total * page_size > _MAX_SNAPSHOT_BYTES:
            raise ValueError("snapshot database exceeds the 8 GiB safety limit")
        if time.monotonic() > deadline:
            raise TimeoutError("snapshot operation timed out; close other database users and retry")

    source.backup(target, pages=256, progress=progress, sleep=0.05)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate snapshot manifest key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def export_snapshot(database_path: str | Path, destination: str | Path) -> Path:
    """Create an atomic archive of all SQLite state, including committed WAL data."""
    source = Path(database_path).expanduser()
    target = Path(destination).expanduser()
    if not source.is_file():
        raise FileNotFoundError(source)
    protected = [source, *(Path(str(source.resolve()) + suffix)
                           for suffix in ("-wal", "-shm", "-journal"))]
    if target.is_symlink() or any(_same_file(path, target) for path in protected):
        raise ValueError("snapshot destination cannot be the live database or a sidecar")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fieldforge-snapshot-") as directory:
        snapshot_db = Path(directory) / _DB_MEMBER
        # Connection context managers do NOT close handles; closing is essential on Windows.
        with closing(_connect(source)) as src, closing(sqlite3.connect(snapshot_db)) as dst:
            _copy_database(src, dst)
            _check(dst)
            dst.execute("PRAGMA journal_mode=DELETE")
        size = snapshot_db.stat().st_size
        if size > _MAX_SNAPSHOT_BYTES:
            raise ValueError("snapshot database exceeds the 8 GiB safety limit")
        manifest = {
            "format": _FORMAT, "version": _VERSION, "database_member": _DB_MEMBER,
            "database_bytes": size, "database_sha256": _sha256(snapshot_db),
        }
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".fieldforge-", suffix=".tmp",
                                             dir=target.parent, delete=False) as output:
                temporary = Path(output.name)
                with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                                     allowZip64=True) as archive:
                    archive.write(snapshot_db, _DB_MEMBER)
                    archive.writestr(_MANIFEST_MEMBER, json.dumps(manifest, sort_keys=True))
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return target


def _read_manifest(archive: zipfile.ZipFile) -> tuple[int, str]:
    if sorted(archive.namelist()) != sorted([_DB_MEMBER, _MANIFEST_MEMBER]):
        raise ValueError("invalid FieldForge snapshot contents")
    info = archive.getinfo(_MANIFEST_MEMBER)
    if info.file_size > _MAX_MANIFEST_BYTES:
        raise ValueError("snapshot manifest exceeds the 16 KiB safety limit")
    with archive.open(info) as stream:
        raw = stream.read(_MAX_MANIFEST_BYTES + 1)
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise ValueError("snapshot manifest exceeds the 16 KiB safety limit")
    try:
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid FieldForge snapshot manifest") from exc
    keys = {"format", "version", "database_member", "database_bytes", "database_sha256"}
    if not isinstance(manifest, dict) or set(manifest) != keys:
        raise ValueError("invalid FieldForge snapshot manifest")
    if (manifest["format"] != _FORMAT or type(manifest["version"]) is not int
            or manifest["version"] != _VERSION or manifest["database_member"] != _DB_MEMBER):
        raise ValueError("unsupported FieldForge snapshot")
    size, digest = manifest["database_bytes"], manifest["database_sha256"]
    if (type(size) is not int or not 0 < size <= _MAX_SNAPSHOT_BYTES
            or not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)):
        raise ValueError("invalid FieldForge snapshot metadata")
    if archive.getinfo(_DB_MEMBER).file_size != size:
        raise ValueError("snapshot database size mismatch")
    return size, digest


def restore_snapshot(source: str | Path, database_path: str | Path, *,
                     overwrite: bool = False) -> dict[str, object]:
    """Validate first, then install without clobbering a racing new target.

    Existing targets require explicit overwrite and are updated through SQLite's
    backup transaction, NEVER by replacing a live database file beside its WAL.
    New-target publication uses an atomic hard link; unsupported filesystems fail
    safely. Choose a local filesystem supporting hard links (e.g. NTFS/ext4).
    """
    archive_path = Path(source).expanduser()
    target = Path(database_path).expanduser()
    if type(overwrite) is not bool:
        raise ValueError("overwrite must be a boolean")
    if target.is_symlink() or _same_file(archive_path, target):
        raise ValueError("restore target cannot be a symlink or the snapshot archive")
    if target.exists() and not overwrite:
        raise FileExistsError(f"target database already exists: {target}; choose a new path")
    if archive_path.stat().st_size > _MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot archive exceeds the 8 GiB safety limit")
    temporary: Path | None = None
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            size, digest = _read_manifest(archive)
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".fieldforge-restore-", suffix=".db",
                                             dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
                hasher = hashlib.sha256()
                copied = 0
                with archive.open(_DB_MEMBER) as incoming:
                    for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                        copied += len(chunk)
                        if copied > size:
                            raise ValueError("snapshot database size mismatch")
                        hasher.update(chunk)
                        stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
        if copied != size or hasher.hexdigest() != digest:
            raise ValueError("snapshot integrity check failed")
        with closing(_connect(temporary)) as verified:
            _check(verified)
            if target.is_symlink():
                raise ValueError("restore target cannot be a symlink")
            if target.exists() and overwrite:
                with closing(_connect(target, "rw")) as existing:
                    _copy_database(verified, existing)
                return {"database": str(target), "database_bytes": size, "status": "restored"}
        # All temporary SQLite handles are closed before publication, including on Windows.
        # link() fails with FileExistsError if another process created the target meanwhile.
        os.link(temporary, target)
        return {"database": str(target), "database_bytes": size, "status": "restored"}
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError(f"invalid or unsupported snapshot archive: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
