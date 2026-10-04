"""Build a new immutable map catalog using the shared map publisher."""

from __future__ import annotations

import json
import re
import stat
import tempfile
from pathlib import Path

from fieldforge.online.catalog import (
    MAX_CATALOG_BYTES,
    MAX_CATALOG_MAPS,
    Catalog,
    CatalogError,
    _publishing_lock,
    _signature,
    publish_map,
)
from fieldforge.online.storage import _publish_new_path


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError("Inventory contains duplicate JSON fields.")
        result[key] = value
    return result


def publish_inventory(root, inventory, *, progress=None):
    """Publish all listed maps together into a NEW directory, or no catalog.

    No source scan, server restart, provider calls or existing-catalog replacement.
    Every map is validated/copied by publish_map in a private staging directory.
    """
    root, inventory = Path(root).expanduser().absolute(), Path(inventory).expanduser().absolute()
    if root.exists() or root.is_symlink():
        raise CatalogError("Choose a new catalog directory; existing catalogs are never replaced.")
    with inventory.open("rb") as stream:
        raw = stream.read(MAX_CATALOG_BYTES + 1)
    if len(raw) > MAX_CATALOG_BYTES:
        raise CatalogError("Inventory exceeds eight MiB.")
    try:
        data = json.loads(raw, object_pairs_hook=_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError("Inventory must be valid UTF-8 JSON.") from exc
    if (not isinstance(data, dict) or set(data) != {"schema_version", "asset_folder", "maps"}
            or type(data.get("schema_version")) is not int or data["schema_version"] != 1):
        raise CatalogError("Use a schema_version 1 inventory with asset_folder and maps.")
    if not isinstance(data["asset_folder"], str) or not data["asset_folder"].strip():
        raise CatalogError("Inventory needs a local asset_folder.")
    folder = (inventory.parent / data["asset_folder"]).resolve(strict=True)
    if not folder.is_dir():
        raise CatalogError("Inventory asset_folder must be a directory.")
    entries = data["maps"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_CATALOG_MAPS:
        raise CatalogError("Inventory must list 1–5000 maps.")
    sources, ids = [], set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"id", "title", "filename", "coverage", "version", "source", "attribution", "license"}:
            raise CatalogError("Each inventory map needs id, title, filename, coverage, version, source, attribution and license.")
        filename = entry["filename"]
        if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,179}", filename):
            raise CatalogError("Inventory filename must be a portable basename, without path components.")
        if not isinstance(entry["id"], str) or entry["id"] in ids:
            raise CatalogError("Inventory map IDs must be distinct strings.")
        ids.add(entry["id"])
        source = folder / filename
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise CatalogError("Inventory maps must be regular files, not links or special files.")
        sources.append((source, _signature(info)))
    with tempfile.TemporaryDirectory(prefix=".fieldforge-catalog-", dir=root.parent) as temporary:
        stage = Path(temporary)
        for index, (entry, (source, _identity)) in enumerate(zip(entries, sources)):
            publish_map(stage, source, map_id=entry["id"], title=entry["title"], coverage=entry["coverage"],
                        version=entry["version"], source_name=entry["source"], attribution=entry["attribution"], license=entry["license"])
            if progress:
                progress(index + 1, len(entries), source.name)
        assets = Catalog(stage).assets()
        for source, identity in sources:
            if _signature(source.lstat()) != identity or source.is_symlink():
                raise CatalogError("An inventory map changed during preparation; no catalog was published.")
        root.mkdir(mode=0o700)  # Atomic claim; never overwrite even an empty directory.
        objects, created = root / "objects", []
        try:
            with _publishing_lock(root):
                objects.mkdir()
                for source in sorted((stage / "objects").iterdir()):
                    destination = objects / source.name
                    # Stage objects belong only to this operation. Make them
                    # writable before unlinking their private Windows name.
                    source.chmod(0o600)
                    _publish_new_path(source, destination)
                    created.append(destination)
                    source.unlink(missing_ok=True)
                    destination.chmod(0o444)
                _publish_new_path(stage / "catalog.json", root / "catalog.json")
        except BaseException:
            if not (root / "catalog.json").exists():
                for path in reversed(created):
                    path.chmod(0o600)
                    path.unlink()
                if objects.exists():
                    objects.rmdir()
                root.rmdir()
            raise
        return assets
