"""Portable map selections and explicit, verified sequential downloads."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from .client import PortalCancelled, PortalOffline
from .models import (
    ValidationError,
    encode_json,
    object_fields,
    safe_filename,
    validate_asset,
    validate_portal_url,
    validate_timestamp,
)
from .storage import (
    MAP_MANIFEST_SUFFIX,
    _signature,
    check_directory,
    ensure_directory,
    read_local_json,
    write_new_bytes,
)

MAX_LIST_MAPS = 100


def make_download_list(portal, maps):
    """Copy and validate a bounded selection; never connect or modify input."""
    portal = validate_portal_url(portal)
    if not isinstance(maps, (tuple, list)) or len(maps) > MAX_LIST_MAPS:
        raise ValidationError("A download list can contain at most 100 maps.")
    assets = [validate_asset(item) for item in maps]
    if len({item["id"] for item in assets}) != len(assets):
        raise ValidationError("Each map may appear only once in a download list.")
    names = [safe_filename(item["filename"]).casefold() for item in assets]
    if len(set(names)) != len(names):
        raise ValidationError("These maps would use the same local filename. Choose separate lists.")
    result = {"schema_version": 1, "kind": "map-download-list", "portal": portal,
              "maps": assets, "total_bytes": sum(item["bytes"] for item in assets)}
    encode_json(result)
    return result


def validate_download_list(value):
    value = object_fields(value, {"schema_version", "kind", "portal", "maps", "total_bytes"}, "Map download list")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "map-download-list":
        raise ValidationError("Choose a version 1 FieldForge map download list.")
    result = make_download_list(value["portal"], value["maps"])
    if type(value["total_bytes"]) is not int or value["total_bytes"] != result["total_bytes"]:
        raise ValidationError("The download list's total does not match its map sizes.")
    return result


def load_download_list(path):
    return validate_download_list(read_local_json(Path(path).expanduser().absolute()))


def save_download_list(value, path):
    data = encode_json(validate_download_list(value))
    return write_new_bytes(Path(path).expanduser().absolute(), data)


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise PortalCancelled("Download list stopped. Completed files remain available offline.")


def verified_local_map(directory, asset, portal, cancel=None):
    """Reuse only an exact local copy with matching provenance and stable bytes.

    Any collision fails without replacing files. Verifying a large map is local
    I/O, and cancellation is checked between chunks. No requests are made here.
    """
    _check_cancel(cancel)
    check_directory(directory)
    target = directory / safe_filename(asset["filename"])
    manifest = target.with_name(target.name + MAP_MANIFEST_SUFFIX)
    if not any(path.exists() or path.is_symlink() for path in (target, manifest)):
        return None
    error = "An existing map or source note differs from this list; existing files were preserved: " + target.name
    if target.is_symlink() or manifest.is_symlink() or not target.is_file() or not manifest.is_file():
        raise ValidationError(error)
    note = object_fields(read_local_json(manifest),
                         {"schema_version", "kind", "saved_at", "portal", "local_filename", "asset"}, "Saved map metadata")
    validate_timestamp(note["saved_at"], "Map saved timestamp")
    if (type(note.get("schema_version")) is not int or note["schema_version"] != 1
            or note.get("kind") != "downloaded-map" or note.get("portal") != portal
            or note.get("local_filename") != target.name or note.get("asset") != asset):
        raise ValidationError(error)
    before = target.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size != asset["bytes"]:
        raise ValidationError(error)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    digest = hashlib.sha256()
    with os.fdopen(os.open(target, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        # Windows may expose different ctime precision through a path and a
        # handle. Compare identity/size/mtime across APIs, then compare the
        # complete signatures within each API before and after the read.
        if not stat.S_ISREG(opened.st_mode) or _signature(before)[:4] != _signature(opened)[:4]:
            raise ValidationError(error)
        remaining = asset["bytes"]
        while chunk := stream.read(min(1024 * 1024, remaining + 1)):
            _check_cancel(cancel)
            remaining -= len(chunk)
            if remaining < 0:
                raise ValidationError(error)
            digest.update(chunk)
        if _signature(os.fstat(stream.fileno())) != _signature(opened):
            raise ValidationError(error)
    _check_cancel(cancel)
    if (digest.hexdigest() != asset["sha256"] or _signature(target.lstat()) != _signature(before)
            or read_local_json(manifest) != note):
        raise ValidationError(error)
    check_directory(directory)
    return target


def download_maps(client, document, directory, *, cancel=None, progress=None, resume=False):
    """Refresh catalog once, then download the exact selected maps sequentially.

    A retry verifies/reuses completed local files without downloading them again.
    Partial transfers are retained only when explicitly enabled. A failure
    stops the list rather than silently continuing to other transfers.
    """
    document = validate_download_list(document)
    if type(resume) is not bool:
        raise ValidationError("Choose whether to keep partial downloads using a boolean.")
    if validate_portal_url(client.base_url) != document["portal"]:
        raise ValidationError("Connect to the portal named in this download list; it will not be changed automatically.")
    if not client.connected:
        raise PortalOffline("Connect explicitly before downloading this list.")
    _check_cancel(cancel)
    if not document["maps"]:
        return ()
    current = {item["id"]: validate_asset(item) for item in client.catalog(cancel=cancel)}
    _check_cancel(cancel)
    if any(current.get(item["id"]) != item for item in document["maps"]):
        raise ValidationError("A selected map was removed or changed. Refresh the catalog and build a new list before downloading.")
    directory = ensure_directory(directory)
    total, done, ready = document["total_bytes"], 0, []
    for number, asset in enumerate(document["maps"], start=1):
        _check_cancel(cancel)
        label = f"{number}/{len(document['maps'])} · {asset['title']}"
        if progress:
            progress(done, total, "Checking local copy · " + label)
        path = verified_local_map(directory, asset, document["portal"], cancel)
        _check_cancel(cancel)
        if path is None:
            def transferred(amount, _size):
                if progress:
                    progress(done + amount, total, "Downloading · " + label)
            options = {"resume": True} if resume else {}
            path = client.download(asset, directory, cancel=cancel, progress=transferred, **options)
        ready.append(path)
        done += asset["bytes"]
        if progress:
            progress(done, total, "Verified and ready · " + label)
    _check_cancel(cancel)
    return tuple(ready)
