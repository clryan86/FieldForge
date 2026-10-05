"""Publish supplied, licensed MBTiles, prepared regional maps and map images.

Example (the operator must have permission to redistribute the source file)::

    python -m fieldforge.online.catalog add --root ./portal-maps \
      --file ./county.mbtiles --id county-2026 --title "County map" \
      --attribution "Map data: ..." --license "Redistribution license: ..." \
      --coverage "County, state; zooms 0-14" --version 2026-10
    python -m fieldforge.online.catalog list --root ./portal-maps

The publisher copies the file, calculates its actual size and SHA-256, and
installs a content-addressed object. Published IDs cannot be reassigned to new
content. Use a new ID for an updated version. The index never contains source
paths, and the HTTP service exposes only the public metadata, never storage paths.

Image signatures and bounded raster/vector-MBTiles preflights catch mislabeled files;
they are not a full cartographic, license, or hostile-file audit. Only publish
trusted, complete map exports. This module never downloads or scrapes map tiles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from fieldforge.online.map_validation import (
    RasterValidationError,
    regional_file_preflight,
    validate_raster_image,
    validate_regional_map,
)
from fieldforge.online.models import (
    FORMATS as MODEL_FORMATS,
)
from fieldforge.online.models import (
    format_byte_limit,
    format_family,
    text,
    validate_asset,
)
from fieldforge.online.storage import _publish_new_path

MAX_MAP_BYTES = 64 * 1024**3
MAX_CATALOG_BYTES = 8 * 1024**2
MAX_CATALOG_MAPS = 5000
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z", re.ASCII)
HASH_PATTERN = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)
FORMATS = {suffix: kind for kind, suffixes in MODEL_FORMATS.items() for suffix in suffixes}
MIME_TYPES = {
    "mbtiles": "application/vnd.sqlite3", "ffmap": "application/vnd.sqlite3",
    "png": "image/png", "jpeg": "image/jpeg",
    "webp": "image/webp", "tiff": "image/tiff", "gif": "image/gif", "bmp": "image/bmp",
    "ico": "image/vnd.microsoft.icon", "ppm": "image/x-portable-anymap", "tga": "image/x-tga",
    "jpeg2000": "image/jp2", "avif": "image/avif",
}


class CatalogError(ValueError):
    """The catalog or supplied map is not a valid published asset."""


def _text(value, name, maximum, *, multiline=False):
    try:
        return text(value, name, maximum, multiline=multiline)
    except ValueError as exc:
        raise CatalogError(str(exc)) from None


def _coverage(value):
    if isinstance(value, str):
        return _text(value, "coverage", 2000)
    if not isinstance(value, list) or len(value) != 4:
        raise CatalogError("coverage must be text or [west,south,east,north].")
    try:
        finite = all(type(n) in (int, float) and math.isfinite(n) for n in value)
    except OverflowError:
        finite = False
    if not finite:
        raise CatalogError("coverage bounds must be finite numbers.")
    west, south, east, north = value
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= north <= 90):
        raise CatalogError("coverage bounds are outside WGS 84 latitude/longitude ranges.")
    return value


def _asset(value, *, legacy=False):
    if not isinstance(value, dict):
        raise CatalogError("Map catalog entries must be objects.")
    map_id = value.get("id")
    if not isinstance(map_id, str) or not ID_PATTERN.fullmatch(map_id):
        raise CatalogError("Map ID must contain 1-80 ASCII letters, digits, underscores or hyphens.")
    filename = _text(value.get("filename"), "filename", 180)
    if (filename in {".", ".."} or "/" in filename or "\\" in filename
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", filename, re.ASCII)):
        raise CatalogError("Map filename must be a safe ASCII basename.")
    kind = value.get("format")
    if not isinstance(kind, str) or kind not in MIME_TYPES or FORMATS.get(Path(filename).suffix.lower()) != kind:
        raise CatalogError("Map filename/format must identify MBTiles, a prepared regional map or a raster image.")
    size, digest = value.get("bytes"), value.get("sha256")
    maximum = format_byte_limit(kind)
    if type(size) is not int or not 0 < size <= maximum:
        raise CatalogError("Published maps are limited to 16 GiB for MBTiles, 4 GiB for prepared regional maps or 64 MiB for images.")
    if not isinstance(digest, str) or not HASH_PATTERN.fullmatch(digest):
        raise CatalogError("Published map SHA-256 must be 64 lowercase hexadecimal characters.")
    download_path = f"/api/v1/maps/{map_id}/download"
    if value.get("download_path") != download_path:
        raise CatalogError("Catalog download path must match its map ID.")
    public = {
        "id": map_id,
        "title": _text(value.get("title"), "title", 500 if legacy else 240),
        "filename": filename, "format": kind, "download_path": download_path,
        "bytes": size, "sha256": digest,
        "attribution": _text(value.get("attribution"), "attribution", 4000, multiline=True),
        "license": _text(value.get("license"), "license", 2000, multiline=True),
        "coverage": _coverage(value.get("coverage")),
        "version": _text(value.get("version"), "version", 500 if legacy else 100),
    }
    if "source" in value:
        public["source"] = _text(value["source"], "source", 500)
    try:
        return validate_asset(public)
    except ValueError as exc:
        raise CatalogError(str(exc)) from None


def _image_format(header):
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    if header.startswith((b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")):
        return "tiff"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if header.startswith(b"BM"):
        return "bmp"
    return None


def inspect_raster(path: Path, kind: str) -> None:
    """Check the declared map format through its supported offline readers."""
    if kind == "ffmap":
        try:
            validate_regional_map(path)
        except (ValueError, TimeoutError, sqlite3.Error) as exc:
            raise CatalogError("Prepared regional map is not supported: " + str(exc)) from None
        return
    with path.open("rb") as stream:
        header = stream.read(100)
    if kind != "mbtiles":
        try:
            validate_raster_image(path, kind)
        except RasterValidationError as exc:
            raise CatalogError(str(exc)) from None
        return
    if not header.startswith(b"SQLite format 3\x00") or header[18:20] != b"\x01\x01":
        raise CatalogError("Use a closed, rollback-mode MBTiles database.")
    from fieldforge.navigation.mbtiles import inspect_pack
    from fieldforge_gps.mbtiles import inspect_pack as inspect_gps_pack

    try:
        inspect_pack(path)
        inspect_gps_pack(path, consent=True)
    except (ValueError, TimeoutError, sqlite3.Error) as exc:
        raise CatalogError("Map does not meet the shared offline MBTiles reader requirements: " + str(exc)) from None
    deadline = time.monotonic() + 3
    db = None
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True, timeout=.2)
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA cache_size=-2048")
        db.execute("PRAGMA mmap_size=0")
        objects = dict(db.execute(
            "SELECT name,type FROM sqlite_master WHERE name IN ('metadata','tiles')"
        ))
        if objects != {"metadata": "table", "tiles": "table"}:
            raise CatalogError("Publish indexed MBTiles with ordinary metadata and tiles tables.")
        for table, fields in (("metadata", {"name", "value"}),
                              ("tiles", {"zoom_level", "tile_column", "tile_row", "tile_data"})):
            schema = db.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
            if (not re.match(r"\s*CREATE\s+TABLE\b", schema or "", re.I)
                    or not fields <= {row[1] for row in db.execute(f"PRAGMA table_info({table})")}):
                raise CatalogError("Unsupported MBTiles table structure.")
        metadata_rows = db.execute(
            "SELECT substr(name,1,129),substr(value,1,16385) FROM metadata LIMIT 129"
        ).fetchall()
        if len(metadata_rows) > 128 or any(
            not isinstance(k, str) or not isinstance(v, str) or len(k) > 128 or len(v) > 16384
            for k, v in metadata_rows
        ):
            raise CatalogError("MBTiles metadata exceeds the supported bounds.")
        metadata = dict(metadata_rows)
        if len(metadata) != len(metadata_rows):
            raise CatalogError("MBTiles metadata contains duplicate names.")
        tile_format = metadata.get("format", "").lower()
        tile_format = "jpeg" if tile_format == "jpg" else tile_format
        if tile_format not in {"png", "jpeg", "webp", "pbf"}:
            raise CatalogError("Use PNG, JPEG, WebP raster MBTiles or Mapbox Vector Tile PBF MBTiles.")
        if metadata.get("scheme", "tms").lower() != "tms":
            raise CatalogError("MBTiles must use the TMS row scheme.")
        unique_index = False
        for row in db.execute("PRAGMA index_list(tiles)").fetchmany(129):
            if row[2] and not row[4]:
                quoted = '"' + row[1].replace('"', '""') + '"'
                columns = [r[2] for r in db.execute(f"PRAGMA index_info({quoted})")]
                if columns == ["zoom_level", "tile_column", "tile_row"]:
                    unique_index = True
                    break
        if not unique_index:
            raise CatalogError("MBTiles needs a unique zoom/column/row index.")
        samples = db.execute(
            "SELECT zoom_level,tile_column,tile_row,typeof(tile_data),length(tile_data),"
            "substr(tile_data,1,100) FROM tiles LIMIT 64"
        ).fetchall()
        if not samples:
            raise CatalogError("An empty MBTiles database is not a downloadable map.")
        for z, x, y, storage_type, length, tile_header in samples:
            if (type(z) is not int or not 0 <= z <= 22 or type(x) is not int
                    or type(y) is not int or not 0 <= x < 2**z or not 0 <= y < 2**z
                    or storage_type != "blob" or not 1 <= length <= 2 * 1024**2
                    or (tile_format == "pbf" and tile_header[:2] != b"\x1f\x8b")
                    or (tile_format != "pbf" and _image_format(tile_header) != tile_format)):
                raise CatalogError("An MBTiles sample has invalid coordinates or does not match its declared tile format.")
        if tile_format == "pbf":
            sample = db.execute("SELECT tile_data FROM tiles LIMIT 1").fetchone()[0]
            try:
                from fieldforge.navigation.vector_tiles import render_vector_tile

                render_vector_tile(sample)
            except (ImportError, ValueError) as exc:
                raise CatalogError("The vector MBTiles sample is not a readable Mapbox Vector Tile.") from exc
    except sqlite3.Error as exc:
        raise CatalogError("Unreadable MBTiles or database inspection work limit reached.") from exc
    finally:
        if db is not None:
            db.close()


def _signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class Catalog:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def _entries(self):
        index = self.root / "catalog.json"
        if not index.exists():
            return []
        if index.is_symlink() or not index.is_file() or index.stat().st_size > MAX_CATALOG_BYTES:
            raise CatalogError("Catalog index is not a regular bounded file.")
        try:
            with index.open("rb") as stream:
                raw = stream.read(MAX_CATALOG_BYTES + 1)
            if len(raw) > MAX_CATALOG_BYTES:
                raise CatalogError("Catalog exceeds 8 MiB.")
            document = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CatalogError("Catalog index cannot be read.") from exc
        if (not isinstance(document, dict) or type(document.get("schema_version")) is not int
                or document.get("schema_version") != 1
                or not isinstance(document.get("maps"), list)
                or len(document["maps"]) > MAX_CATALOG_MAPS):
            raise CatalogError("Unsupported catalog schema or too many maps.")
        entries, ids = [], set()
        for value in document["maps"]:
            public = _asset(value)
            if public["id"] in ids:
                raise CatalogError("Duplicate published map ID.")
            ids.add(public["id"])
            expected = f"objects/{public['sha256']}{Path(public['filename']).suffix.lower()}"
            if value.get("storage_path") != expected:
                raise CatalogError("Catalog storage path does not match immutable object identity.")
            entries.append({**public, "storage_path": expected})
        return entries

    def assets(self) -> list[dict]:
        return [{k: v for k, v in entry.items() if k != "storage_path"}
                for entry in self._entries()]

    def open_asset(self, map_id: str) -> tuple[dict, BinaryIO]:
        if not isinstance(map_id, str) or not ID_PATTERN.fullmatch(map_id):
            raise KeyError("Map not found.")
        entry = next((item for item in self._entries() if item["id"] == map_id), None)
        if entry is None:
            raise KeyError("Map not found.")
        path = self.root / entry["storage_path"]
        # Reject symlinks at either level, even when they happen to point inside storage.
        if path.parent.is_symlink() or path.is_symlink() or path.resolve().parent != self.root / "objects":
            raise CatalogError("Map storage must contain local immutable regular files.")
        descriptor = None
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                                 | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size != entry["bytes"]:
                raise CatalogError("Published map is missing or changed; republish a verified new version.")
            stream = os.fdopen(descriptor, "rb")
            descriptor = None
            return {k: v for k, v in entry.items() if k != "storage_path"}, stream
        except OSError as exc:
            raise CatalogError("Published map file is unavailable.") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)


class LegacyCatalog:
    """Read-only bridge for version-1 inline manifests; never copies source files.

    Each operator-declared regular file is checked at startup using the same
    format preflight as publication, its exact declared size/hash, and a captured
    file identity. Serving refuses changed files. New deployments should prefer
    the content-addressed catalog publisher.
    """

    def __init__(self, entries, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        if not isinstance(entries, list) or len(entries) > 500:
            raise CatalogError("Legacy inline catalogs are limited to 500 map files.")
        self._maps = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise CatalogError("Legacy map entries must be objects.")
            filename = _text(entry.get("filename"), "filename", 180)
            kind = FORMATS.get(Path(filename).suffix.lower())
            if kind is None or entry.get("kind") != format_family(kind):
                raise CatalogError("Legacy map kind and file format disagree.")
            map_id = entry.get("id")
            asset = _asset({
                "id": map_id, "title": entry.get("title"), "filename": filename, "format": kind,
                "bytes": entry.get("size"), "sha256": entry.get("sha256"),
                "download_path": f"/api/v1/maps/{map_id}/download", "coverage": entry.get("coverage"),
                "version": entry.get("updated"), "source": entry.get("source"),
                "attribution": entry.get("attribution"), "license": entry.get("license"),
            }, legacy=True)
            if map_id in self._maps:
                raise CatalogError("Legacy map IDs must be distinct.")
            path = self.root / filename
            stream = self._open(path)
            with stream:
                before = _signature(os.fstat(stream.fileno()))
                if before[2] != asset["bytes"]:
                    raise CatalogError("Legacy map size changed; update its manifest before serving.")
                digest = hashlib.sha256()
                total = 0
                while chunk := stream.read(min(1024**2, asset["bytes"] + 1 - total)):
                    total += len(chunk)
                    if total > asset["bytes"]:
                        raise CatalogError("Legacy map grew while being verified.")
                    digest.update(chunk)
                if (total != asset["bytes"] or _signature(os.fstat(stream.fileno())) != before
                        or digest.hexdigest() != asset["sha256"]):
                    raise CatalogError("Legacy map checksum changed; update its manifest before serving.")
            inspect_raster(path, kind)
            # Compare descriptors with descriptors: Windows may report a different
            # ctime through path.stat() than through fstat().
            with self._open(path) as verified:
                after = _signature(os.fstat(verified.fileno()))
            if after != before:
                raise CatalogError("Legacy map changed while being verified.")
            self._maps[map_id] = (asset, path, before)

    def _open(self, path):
        if path.is_symlink() or path.resolve().parent != self.root:
            raise CatalogError("Legacy catalog maps must be regular files directly in the asset folder.")
        descriptor = None
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                                 | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise CatalogError("Legacy catalog maps must be regular files.")
            result = os.fdopen(descriptor, "rb")
            descriptor = None
            return result
        except OSError as exc:
            raise CatalogError("Legacy map file is unavailable.") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def assets(self):
        return [dict(item[0]) for item in self._maps.values()]

    def open_asset(self, map_id):
        if map_id not in self._maps:
            raise KeyError("Map not found.")
        asset, path, identity = self._maps[map_id]
        stream = self._open(path)
        if _signature(os.fstat(stream.fileno())) != identity:
            stream.close()
            raise CatalogError("Legacy map changed after verification; restart with an updated manifest.")
        return dict(asset), stream


@contextmanager
def _publishing_lock(root):
    lock = root / ".publish.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise CatalogError("Another publisher is active; retry after it finishes.") from exc
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def publish_map(root: str | Path, source: str | Path, *, map_id: str, title: str,
                attribution: str, license: str, coverage, version: str, source_name: str | None = None) -> dict:
    """Publish a completed operator-supplied map; an existing ID is immutable."""
    root = Path(root).expanduser().resolve()
    source = Path(source).expanduser().resolve(strict=True)
    extension = source.suffix.lower()
    kind = FORMATS.get(extension)
    if kind is None:
        raise CatalogError("Choose MBTiles, a prepared .ffmap regional map or a raster image; archives and raw source packs are unsupported.")
    # Validate before doing a potentially large file copy.
    metadata = {
        "id": map_id, "title": title, "filename": f"{map_id}{extension}", "format": kind,
        "download_path": f"/api/v1/maps/{map_id}/download", "bytes": 1, "sha256": "0" * 64,
        "attribution": attribution, "license": license, "coverage": coverage, "version": version,
    }
    if source_name is not None:
        metadata["source"] = source_name
    prospective = _asset(metadata)
    regional_source = None
    if kind == "ffmap":
        try:
            regional_source = regional_file_preflight(source)
        except ValueError as exc:
            raise CatalogError(str(exc)) from None
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(source) + suffix)
        if kind == "mbtiles" and sidecar.exists() and sidecar.stat().st_size:
            raise CatalogError("Close/export the MBTiles database before publishing; active sidecar found.")
    root.mkdir(parents=True, exist_ok=True)
    objects = root / "objects"
    if objects.is_symlink():
        raise CatalogError("Catalog object storage must not be a symlink.")
    objects.mkdir(exist_ok=True)
    with _publishing_lock(root):
        catalog = Catalog(root)
        entries = catalog._entries()
        existing = next((e for e in entries if e["id"] == map_id), None)
        if existing is not None:
            raise CatalogError("This map ID is already published; use a new ID for a new version.")
        if len(entries) >= MAX_CATALOG_MAPS:
            raise CatalogError("Catalog already contains the maximum 5000 maps.")
        temporary = None
        try:
            descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
                                 | getattr(os, "O_BINARY", 0))
            with os.fdopen(descriptor, "rb") as input_stream:
                before = os.fstat(input_stream.fileno())
                maximum = format_byte_limit(kind)
                if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
                    raise CatalogError("Use a regular MBTiles file up to 16 GiB, prepared regional map up to 4 GiB or image up to 64 MiB.")
                digest, size = hashlib.sha256(), 0
                with tempfile.NamedTemporaryFile(dir=objects, suffix=extension, delete=False) as output:
                    temporary = Path(output.name)
                    while chunk := input_stream.read(1024**2):
                        size += len(chunk)
                        if size > maximum:
                            raise CatalogError("Map grew beyond its format's publishing limit.")
                        digest.update(chunk)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if _signature(before) != _signature(os.fstat(input_stream.fileno())) or size != before.st_size:
                    raise CatalogError("Map changed during publishing; retry with a completed export.")
            inspect_raster(temporary, kind)
            if regional_source is not None:
                try:
                    if regional_file_preflight(source) != regional_source:
                        raise CatalogError("Prepared regional source changed during publication.")
                except ValueError as exc:
                    raise CatalogError(str(exc)) from None
            digest = digest.hexdigest()
            prospective.update(bytes=size, sha256=digest)
            storage_path = f"objects/{digest}{extension}"
            destination = root / storage_path
            if destination.exists():
                # Same bytes can be published under distinct licensed regional/version entries.
                if destination.is_symlink() or not destination.is_file() or destination.stat().st_size != size:
                    raise CatalogError("Existing content-addressed object is invalid.")
                existing_digest = hashlib.sha256()
                with destination.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024**2), b""):
                        existing_digest.update(chunk)
                if existing_digest.hexdigest() != digest:
                    raise CatalogError("Existing content-addressed object has changed.")
            else:
                # Use the same atomic no-overwrite install as local downloads.
                # Remove the writable temporary name before making the installed
                # object read-only: Windows shares that attribute across hard
                # links and refuses to unlink a read-only temporary name.
                _publish_new_path(temporary, destination)
                temporary.unlink(missing_ok=True)
                temporary = None
                destination.chmod(0o444)
            entries.append({**prospective, "storage_path": storage_path})
            raw = json.dumps({"schema_version": 1, "maps": entries}, indent=2, ensure_ascii=False,
                             allow_nan=False).encode("utf-8")
            if len(raw) > MAX_CATALOG_BYTES:
                raise CatalogError("Catalog metadata exceeds 8 MiB.")
            with tempfile.NamedTemporaryFile(dir=root, suffix=".json", delete=False) as output:
                index_temp = Path(output.name)
                try:
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                    output.close()
                    os.replace(index_temp, root / "catalog.json")
                finally:
                    index_temp.unlink(missing_ok=True)
            return prospective
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)
    add = subparsers.add_parser("add", help="Publish a licensed local MBTiles pack, prepared regional map or map image.")
    for flag in ("root", "file", "id", "title", "attribution", "license", "coverage", "version"):
        add.add_argument("--" + flag, required=True)
    add.add_argument("--source", dest="source_name", help="Actual source or provider reference for this map.")
    listing = subparsers.add_parser("list", help="Print the current public map catalog.")
    listing.add_argument("--root", required=True)
    build = subparsers.add_parser("build", help="Prepare all maps in an explicit inventory as one new catalog.")
    build.add_argument("--root", required=True, help="New catalog directory; must not already exist.")
    build.add_argument("--inventory", required=True, help="JSON inventory with approved maps and their provenance.")
    collection = subparsers.add_parser("prepare-collection", help="Verify selected collection ZIPs as a new map inventory.")
    collection.add_argument("--collection", required=True, help="Local fieldforge-map-collection-v1 JSON record.")
    collection.add_argument("--archives", required=True, help="Existing folder containing the selected ZIPs.")
    collection.add_argument("--output", required=True, help="New inventory directory; must not already exist.")
    collection.add_argument("--select", action="append", required=True, dest="filenames",
                            help="Exact collection ZIP basename; repeat for each explicit selection.")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            result = {"maps": Catalog(args.root).assets()}
        elif args.command == "build":
            from fieldforge.online.inventory import publish_inventory
            result = {"maps": publish_inventory(args.root, args.inventory)}
        elif args.command == "prepare-collection":
            from fieldforge.online.collection import prepare_collection
            result = prepare_collection(args.collection, args.archives, args.output, filenames=args.filenames)
        else:
            result = publish_map(args.root, args.file, map_id=args.id, title=args.title,
                                 attribution=args.attribution, license=args.license,
                                 coverage=args.coverage, version=args.version, source_name=args.source_name)
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, OSError) as exc:
        # Under python -m, imported APIs use the canonical catalog error class,
        # distinct from __main__.CatalogError; all validation errors are ValueErrors.
        parser.exit(2, f"Map publishing failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
