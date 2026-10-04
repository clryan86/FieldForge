"""Owned, locked checkpoints for explicitly resumable map transfers.

Partial bytes are never listed as offline maps. Locks are released by the OS
on process exit; the empty lock files deliberately remain to avoid lock races.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path

from .models import (
    ValidationError,
    encode_json,
    object_fields,
    safe_filename,
    validate_asset,
    validate_portal_url,
)
from .storage import _signature, check_directory, read_local_json, write_new_bytes

CHECKPOINT_BYTES = 8 * 1024 * 1024


def _regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValidationError("Partial-download storage must use regular files without links; files were preserved.")
    return info


def _open(path, *, create=False):
    before = None
    try:
        before = _regular(path)
    except FileNotFoundError:
        if not create:
            raise
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    if before is None:
        flags |= os.O_CREAT | os.O_EXCL
    stream = os.fdopen(os.open(path, flags, 0o600), "r+b")
    try:
        opened = os.fstat(stream.fileno())
        current = _regular(path)
        if (_signature(opened)[:4] != _signature(current)[:4]
                or (before is not None and _signature(before) != _signature(current))):
            raise ValidationError("Partial-download storage changed while opening; files were preserved.")
        return stream
    except BaseException:
        stream.close()
        raise


class PartialDownload:
    def __init__(self, target, asset, portal):
        self.target = Path(target)
        self.asset = validate_asset(asset)
        self.binding = {"portal": validate_portal_url(portal), "asset": self.asset, "filename": self.target.name}
        key = hashlib.sha256(json.dumps(self.binding, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=True).encode()).hexdigest()
        stem = ".fieldforge-partial-" + key
        self.path = self.target.with_name(stem + "." + self.asset["format"])
        self.note = self.target.with_name(stem + ".json")
        self.lock_path = self.target.with_name(stem + ".lock")
        self.lock = self.stream = None
        self.note_value = None
        self.received = self.saved = 0
        self.digest = hashlib.sha256()

    def __enter__(self):
        check_directory(self.target.parent)
        self.lock = _open(self.lock_path, create=True)
        try:
            if os.fstat(self.lock.fileno()).st_size:
                raise ValidationError("The partial-download lock file is unexpected; files were preserved.")
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self
        except OSError as exc:
            self.lock.close()
            self.lock = None
            raise ValidationError("Another transfer is using this partial map. Wait for it to stop, then retry.") from exc
        except BaseException:
            self.lock.close()
            self.lock = None
            raise

    def __exit__(self, *_exc):
        self.close_data()
        if self.lock is not None:
            self.lock.close()  # Closing releases the OS lock, including after a crash.
            self.lock = None

    def close_data(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def prepare(self, guard):
        guard()
        data_exists = self.path.exists() or self.path.is_symlink()
        note_exists = self.note.exists() or self.note.is_symlink()
        if data_exists != note_exists:
            raise ValidationError("An incomplete checkpoint was found. Discard partial files for this map list before retrying.")
        if not data_exists:
            self.stream = _open(self.path, create=True)
            self.checkpoint()
            return
        _regular(self.note)
        value = object_fields(read_local_json(self.note),
                              {"schema_version", "kind", "binding", "bytes", "sha256"}, "Map checkpoint")
        if (type(value["schema_version"]) is not int or value["schema_version"] != 1
                or value["kind"] != "partial-map" or value["binding"] != self.binding
                or type(value["bytes"]) is not int or not 0 <= value["bytes"] <= self.asset["bytes"]):
            raise ValidationError("Partial map metadata differs from this selection; files were preserved.")
        self.note_value = value
        self.stream = _open(self.path)
        before = os.fstat(self.stream.fileno())
        if not value["bytes"] <= before.st_size <= self.asset["bytes"]:
            raise ValidationError("Partial map size differs from its checkpoint; files were preserved.")
        remaining = value["bytes"]
        while remaining:
            guard()
            chunk = self.stream.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValidationError("The partial map changed during verification.")
            self.digest.update(chunk)
            remaining -= len(chunk)
        guard()
        if self.digest.hexdigest() != value["sha256"] or _signature(before) != _signature(os.fstat(self.stream.fileno())):
            raise ValidationError("The partial map failed its checkpoint checksum; discard its partial files before retrying.")
        self._unchanged()
        self.received = self.saved = value["bytes"]
        # A crash can leave a tail after the last durable checkpoint. Only the
        # verified prefix is reused; uncommitted bytes from our file are dropped.
        self.stream.truncate(self.received)
        self.stream.seek(self.received)

    def _unchanged(self):
        check_directory(self.target.parent)
        if self.stream is not None:
            self.stream.flush()
            if _signature(_regular(self.path))[:4] != _signature(os.fstat(self.stream.fileno()))[:4]:
                raise ValidationError("The partial map was replaced; files were preserved.")
        if self.note_value is not None:
            _regular(self.note)
            if read_local_json(self.note) != self.note_value:
                raise ValidationError("The partial checkpoint was replaced; files were preserved.")
        elif self.note.exists() or self.note.is_symlink():
            raise ValidationError("A partial checkpoint already exists; files were preserved.")

    def checkpoint(self):
        self._unchanged()
        self.stream.flush()
        os.fsync(self.stream.fileno())
        value = {"schema_version": 1, "kind": "partial-map", "binding": self.binding,
                 "bytes": self.received, "sha256": self.digest.hexdigest()}
        data = encode_json(value)
        if self.note_value is None:
            write_new_bytes(self.note, data)
        else:
            fd, name = tempfile.mkstemp(prefix=".fieldforge-checkpoint-", suffix=".tmp", dir=self.target.parent)
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(data)
                    out.flush()
                    os.fsync(out.fileno())
                self._unchanged()
                os.replace(name, self.note)
            finally:
                Path(name).unlink(missing_ok=True)
        self.note_value, self.saved = value, self.received

    def append(self, chunk):
        self.stream.write(chunk)
        self.digest.update(chunk)
        self.received += len(chunk)
        if self.received - self.saved >= CHECKPOINT_BYTES:
            self.checkpoint()

    def restart(self):
        self._unchanged()
        self.stream.seek(0)
        self.stream.truncate()
        self.digest = hashlib.sha256()
        self.received = 0
        self.checkpoint()

    def discard(self):
        """Explicitly remove only this binding's regular, unlocked partial files."""
        self.close_data()
        check_directory(self.target.parent)
        existing = []
        for path in (self.path, self.note):
            try:
                existing.append((path, _regular(path)))
            except FileNotFoundError:
                pass
        size = next((info.st_size for path, info in existing if path == self.path), 0)
        for path, info in existing:
            if _signature(path.lstat()) != _signature(info):
                raise ValidationError("Partial files changed before removal; remaining files were preserved.")
            path.unlink()
        return size

    def published(self):
        """Remove our cache names after immutable publication (POSIX hard link)."""
        self._unchanged()
        if self.path.exists() or self.path.is_symlink():
            info, published = self.path.lstat(), self.target.lstat()
            if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (published.st_dev, published.st_ino):
                raise ValidationError("The partial filename changed after publication; remaining files were preserved.")
        self.note.unlink()
        self.path.unlink(missing_ok=True)


def discard_partials(document, directory):
    from .download_list import validate_download_list

    document = validate_download_list(document)
    directory = Path(directory)
    check_directory(directory)
    removed = 0
    for asset in document["maps"]:
        with PartialDownload(directory / safe_filename(asset["filename"]), asset, document["portal"]) as partial:
            removed += partial.discard()
    return removed
