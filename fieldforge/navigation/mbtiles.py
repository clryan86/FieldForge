"""Read a limited, flat/indexed raster and vector MBTiles subset, offline.

This is NOT a general MBTiles validator or a malicious-file sandbox. Only open
trusted, closed map-pack copies. The pack remains external to the app database.
"""

from __future__ import annotations

import math
import re
import sqlite3
import stat
import struct
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Iterator

from fieldforge.navigation.map_view import TILE_SIZE, TileSlot, Viewport, unproject

MAX_PACK_BYTES = 16 * 1024**3
MAX_TILE_BYTES = 2 * 1024**2
MAX_FRAME_BYTES = 32 * 1024**2
MAX_METADATA_ROWS = 128
MAX_METADATA_VALUE_BYTES = 16 * 1024
QUERY_SECONDS = 3.0
NOTICE = (
    "Offline map images are reference material, not verified routes or current conditions. "
    "No GPS, downloads, road routing or hazard checks. Missing tiles are not safe or empty terrain. "
    "Map packs remain separate files and are NOT included in FieldForge database backups."
)


class MapCancelled(ValueError):
    """The request is obsolete; never paint its late result."""


def _cancelled(cancel: Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise MapCancelled("Map request cancelled.")


def _signature(path: Path) -> tuple[int, int, int, int, int]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 16 <= info.st_size <= MAX_PACK_BYTES:
        raise ValueError("Choose a regular .mbtiles file of at most 16 GiB.")
    for suffix in ("-wal", "-journal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise ValueError("Map has an active WAL/journal/shared-memory sidecar. Use a closed, fully exported single-file map copy.")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def _read_database(path: Path, signature, cancel: Event | None = None) -> Iterator[sqlite3.Connection]:
    _cancelled(cancel)
    if _signature(path) != signature:
        raise ValueError("Map file changed since opening. Close and reopen the intended map pack.")
    # A WAL-mode header can cause SQLite to create auxiliary files even for a
    # read-only connection. Match the GPS viewer's closed rollback-mode subset
    # before opening SQLite, including when no sidecars currently exist.
    with path.open("rb") as stream:
        header = stream.read(100)
    if not header.startswith(b"SQLite format 3\x00"):
        raise sqlite3.DatabaseError("Not a SQLite MBTiles file.")
    if header[18:20] != b"\x01\x01":
        raise ValueError("Unsupported SQLite header or WAL-mode map; use a closed rollback-mode export.")
    deadline = time.monotonic() + QUERY_SECONDS
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.25)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA cache_size=-4096")
        db.execute("PRAGMA mmap_size=0")
        db.set_progress_handler(lambda: int(time.monotonic() > deadline or (cancel is not None and cancel.is_set())), 1000)
        db.execute("BEGIN")
        yield db
        _cancelled(cancel)
        if _signature(path) != signature:
            raise ValueError("Map file changed while being read; this frame was discarded.")
    except sqlite3.OperationalError as exc:
        _cancelled(cancel)
        if "interrupt" in str(exc).lower():
            raise TimeoutError("Map query exceeded its work deadline; use a smaller, indexed trusted map pack.") from exc
        raise
    finally:
        db.set_progress_handler(None, 0)
        db.close()


@dataclass(frozen=True)
class MapPack:
    path: Path
    signature: tuple[int, int, int, int, int]
    metadata: tuple[tuple[str, str], ...]
    zooms: tuple[int, ...]
    latitude: float
    longitude: float
    zoom: int
    index_name: str
    warnings: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return dict(self.metadata)["name"]


@dataclass(frozen=True)
class MapTile:
    slot: TileSlot
    data: bytes | None = field(default=None, repr=False)
    pixels: int = 0
    issue: str = ""


@dataclass(frozen=True)
class MapFrame:
    view: Viewport
    tiles: tuple[MapTile, ...]


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _png_size(data: bytes) -> int:
    """Preflight compressed size/dimensions; Tk does actual PNG decoding later."""
    if (type(data) is not bytes or not 33 <= len(data) <= MAX_TILE_BYTES
            or data[:8] != b"\x89PNG\r\n\x1a\n" or data[8:16] != b"\x00\x00\x00\rIHDR"):
        raise ValueError("Unreadable PNG tile")
    width, height = struct.unpack(">II", data[16:24])
    if width != height or width not in (256, 512):
        raise ValueError("Unsupported tile dimensions")
    return width


def inspect_pack(source: str | Path, *, cancel: Event | None = None) -> MapPack:
    path = Path(source).expanduser().resolve()
    if path.suffix.lower() != ".mbtiles":
        raise ValueError("Choose a local raster or vector .mbtiles pack, not a URL, image or GPX file.")
    signature = _signature(path)
    warnings = []
    with _read_database(path, signature, cancel) as db:
        objects = dict(db.execute("SELECT name,type FROM sqlite_master WHERE name IN ('metadata','tiles')"))
        if objects != {"metadata": "table", "tiles": "table"}:
            raise ValueError("This reader requires ordinary metadata/tiles tables; normalized/view-based MBTiles are not supported yet.")
        for table, expected in (
            ("metadata", (("name", "TEXT"), ("value", "TEXT"))),
            ("tiles", (("zoom_level", "INTEGER"), ("tile_column", "INTEGER"),
                       ("tile_row", "INTEGER"), ("tile_data", "BLOB"))),
        ):
            schema = db.execute("SELECT substr(sql,1,2048) FROM sqlite_master WHERE name=?", (table,)).fetchone()[0] or ""
            columns = tuple((row[1], row[2].upper()) for row in
                            db.execute(f"PRAGMA table_info({table})").fetchmany(len(expected) + 1))
            if not re.match(r"\s*CREATE\s+TABLE\b", schema, re.I) or columns != expected:
                raise ValueError("Unsupported map table structure, column layout or declared types; file was not modified.")
        indexes = db.execute("PRAGMA index_list(tiles)").fetchmany(65)
        if len(indexes) > 64:
            raise ValueError("Too many map indexes.")
        index_name = ""
        for row in indexes:
            if row[2] and not row[4]:
                columns = [item for item in db.execute(f"PRAGMA index_xinfo({_quoted(row[1])})").fetchmany(5) if item[5]]
                if ([item[2] for item in columns] == ["zoom_level", "tile_column", "tile_row"]
                        and all(item[4] == "BINARY" for item in columns)):
                    index_name = row[1]
                    break
        if not index_name:
            raise ValueError("Map needs a unique non-partial BINARY (zoom_level, tile_column, tile_row) index. This reader does not alter files or build indexes.")
        # Keep the metadata budget shared with the already-supported GPS
        # viewer, so a portal download can be opened in either offline viewer.
        sizes = db.execute("SELECT length(CAST(name AS BLOB)),length(CAST(value AS BLOB)) FROM metadata LIMIT ?",
                           (MAX_METADATA_ROWS + 1,)).fetchall()
        if len(sizes) > MAX_METADATA_ROWS or any(type(a) is not int or type(b) is not int
                                                or a > 128 or b > MAX_METADATA_VALUE_BYTES for a, b in sizes):
            raise ValueError("Map metadata exceeds the supported bounds.")
        metadata = {}
        for key, value in db.execute("SELECT name,value FROM metadata LIMIT ?", (MAX_METADATA_ROWS + 1,)):
            if not isinstance(key, str) or not isinstance(value, str) or key in metadata or "\x00" in key + value:
                raise ValueError("Invalid or duplicate map metadata.")
            metadata[key] = value
        if not metadata.get("name", "").strip():
            raise ValueError("Map metadata must supply a name.")
        if metadata.get("format", "").lower() not in {"png", "jpg", "jpeg", "webp", "pbf"}:
            raise ValueError("Use PNG, JPEG, WebP raster MBTiles or gzip-compressed Mapbox vector MBTiles.")
        if metadata.get("scheme", "tms").lower() != "tms":
            raise ValueError("Map row scheme must be MBTiles/TMS, not XYZ.")
        indexed = f"tiles INDEXED BY {_quoted(index_name)}"
        for order in ("ASC", "DESC"):
            value = db.execute(f"SELECT zoom_level FROM {indexed} ORDER BY zoom_level {order} LIMIT 1").fetchone()
            if value is None or type(value[0]) is not int or not 0 <= value[0] <= 22:
                raise ValueError("Map must contain integer zoom levels in the supported range 0–22.")
        zooms = tuple(z for z in range(23) if db.execute(f"SELECT 1 FROM {indexed} WHERE zoom_level=? LIMIT 1", (z,)).fetchone())
        # Start on an actually stored tile, not inferred global coverage.
        z = zooms[0]
        column, row = db.execute(f"SELECT tile_column,tile_row FROM {indexed} WHERE zoom_level=? LIMIT 1", (z,)).fetchone()
        if any(type(n) is not int or not 0 <= n < (1 << z) for n in (column, row)):
            raise ValueError("Map has invalid coordinates at its initial tile.")
        latitude, longitude = unproject((column + .5) * TILE_SIZE, ((1 << z) - 1 - row + .5) * TILE_SIZE, z)
        if "center" in metadata:
            try:
                lon, lat, level = map(float, metadata["center"].split(","))
                if not all(math.isfinite(n) for n in (lon, lat, level)) or not level.is_integer() or int(level) not in zooms:
                    raise ValueError()
                Viewport(lat, lon, int(level), 1, 1)
                latitude, longitude, z = lat, lon, int(level)
            except (ValueError, OverflowError):
                warnings.append("Invalid/unsupported declared center ignored; initial stored tile used instead.")
        for key, observed in (("minzoom", zooms[0]), ("maxzoom", zooms[-1])):
            if key in metadata and metadata[key].strip() != str(observed):
                warnings.append(f"Declared {key} differs from observed levels; observed levels are used.")
        if not metadata.get("attribution", "").strip():
            warnings.append("No attribution supplied; verify source and reuse rights separately.")
        if metadata.get("format", "").lower() == "pbf":
            sample = db.execute(f"SELECT typeof(tile_data),tile_data FROM {indexed} LIMIT 1").fetchone()
            if (sample is None or sample[0] != "blob" or not isinstance(sample[1], bytes)
                    or len(sample[1]) > MAX_TILE_BYTES or not sample[1].startswith(b"\x1f\x8b")):
                raise ValueError("Vector MBTiles has no bounded PBF tile sample.")
            from fieldforge.navigation.vector_tiles import render_vector_tile

            render_vector_tile(sample[1])
            warnings.append("Vector features use FieldForge's basic preview style with limited point-name labels; publisher styling and label rules are not applied.")
        warnings.append("Zoom availability is not a coverage, freshness, integrity or safety audit. Tiles are checked as viewed.")
    return MapPack(path, signature, tuple(sorted(metadata.items())), zooms, latitude, longitude, z, index_name, tuple(warnings))


def read_frame(pack: MapPack, view: Viewport, *, cancel: Event | None = None) -> MapFrame:
    if not isinstance(pack, MapPack) or not isinstance(view, Viewport) or view.zoom not in pack.zooms:
        raise ValueError("Open a compatible map and choose an available zoom level.")
    result, cache, total = [], {}, 0
    with _read_database(pack.path, pack.signature, cancel) as db:
        table = f"tiles INDEXED BY {_quoted(pack.index_name)}"
        for slot in view.slots():
            _cancelled(cancel)
            if not 0 <= slot.row < (1 << view.zoom):
                result.append(MapTile(slot, issue="Outside projection"))
                continue
            key = (view.zoom, slot.column, (1 << view.zoom) - 1 - slot.row)
            if key not in cache:
                info = db.execute(f"SELECT typeof(tile_data),length(tile_data) FROM {table} "
                                  "WHERE zoom_level=? AND tile_column=? AND tile_row=?", key).fetchone()
                data, pixels, issue = None, 0, ""
                if info is None:
                    issue = "Tile not installed"
                elif (info[0] != "blob" or type(info[1]) is not int
                      or not (1 if dict(pack.metadata)["format"].lower() == "pbf" else 33)
                      <= info[1] <= MAX_TILE_BYTES):
                    issue = "Invalid/oversized tile"
                else:
                    total += info[1]
                    if total > MAX_FRAME_BYTES:
                        raise ValueError("Visible map data exceeds the 32 MiB frame budget; use a smaller window.")
                    data = db.execute(f"SELECT tile_data FROM {table} WHERE zoom_level=? AND tile_column=? AND tile_row=?", key).fetchone()[0]
                    try:
                        tile_format = dict(pack.metadata)["format"].lower()
                        if tile_format == "pbf":
                            from fieldforge.navigation.vector_tiles import render_vector_tile

                            if not data.startswith(b"\x1f\x8b"):
                                raise ValueError("PBF MBTiles tiles must be gzip-compressed.")
                            converted = render_vector_tile(data)
                        elif tile_format != "png":
                            from fieldforge_gps.raster import tile_png

                            converted = tile_png(data, tile_format)
                        else:
                            converted = data
                        if tile_format != "png":
                            total += max(0, len(converted) - len(data))
                            if total > MAX_FRAME_BYTES:
                                raise ValueError("Decoded tile buffers exceed the 32 MiB frame budget.")
                        data = converted
                        pixels = _png_size(data)
                    except ValueError as exc:
                        data, issue = None, str(exc)
                cache[key] = data, pixels, issue
            result.append(MapTile(slot, *cache[key]))
    return MapFrame(view, tuple(result))


@dataclass(frozen=True)
class MapMarker:
    id: int
    name: str
    latitude: float
    longitude: float


def read_markers(database: str | Path) -> tuple[MapMarker, ...]:
    """Explicit opt-in only. Read identifiers/names/coordinates, NEVER private notes."""
    path = Path(database).expanduser().resolve()
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=.25)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        table = db.execute("SELECT type,sql FROM sqlite_master WHERE name='waypoints'").fetchone()
        if table is None or table[0] != "table" or "VIRTUAL" in (table[1] or "").upper().split():
            raise ValueError("Saved places are unavailable in this database.")
        rows = db.execute("SELECT id,name,latitude,longitude FROM waypoints ORDER BY id LIMIT 2001").fetchall()
        if len(rows) > 2000:
            raise ValueError("More than 2,000 saved places; no partial overlay shown.")
        result = []
        for number, name, latitude, longitude in rows:
            if (type(number) is not int or number <= 0 or not isinstance(name, str) or len(name) > 200 or "\x00" in name
                    or any(type(n) not in (int, float) or not math.isfinite(n) for n in (latitude, longitude))
                    or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
                raise ValueError("Invalid saved place; fix it in Places before using the overlay.")
            result.append(MapMarker(number, name, latitude, longitude))
        return tuple(result)
    finally:
        db.close()
