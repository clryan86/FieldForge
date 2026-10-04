"""Bounded, read-only local raster/vector MBTiles reader. No network or household database.

Supports a deliberately narrow, indexed ordinary-table subset of MBTiles 1.3.
Use trusted, fully exported files on maintained Python/SQLite/Tk installations.
Stat checks detect ordinary changes, not hostile timestamp/path races.
"""

from __future__ import annotations

import math
import re
import sqlite3
import stat
import struct
import time
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event

MAX_PACK_BYTES = 16 * 1024**3
MAX_TILE_BYTES = 2 * 1024**2
MAX_FRAME_BYTES = 32 * 1024**2
MAX_CELLS = 96
MAX_METADATA = 128
MAX_TEXT = 16_384
SQL_SECONDS = 4.0
MAX_LAT = math.degrees(math.atan(math.sinh(math.pi)))


class MapReadCancelled(ValueError):
    """An obsolete read must not replace a newer view."""


@dataclass(frozen=True)
class MapPack:
    path: Path
    identity: tuple[int, ...]
    metadata: tuple[tuple[str, str], ...]
    levels: tuple[int, ...]
    start: tuple[float, float, int]  # longitude, latitude, zoom
    start_notice: str

    @property
    def name(self) -> str:
        return dict(self.metadata)["name"]


@dataclass(frozen=True)
class Tile:
    key: tuple[int, int, int]  # XYZ, not database TMS
    state: str
    data: bytes = b""
    reason: str = ""


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise MapReadCancelled("Map read cancelled.")


def _identity(path: Path) -> tuple[int, ...]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 100 <= info.st_size <= MAX_PACK_BYTES:
        raise ValueError("Choose a regular MBTiles file between 100 bytes and 16 GiB.")
    for suffix in ("-wal", "-journal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise ValueError(
                "Active database sidecar found. Use a closed, fully exported map copy."
            )
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _local_path(value) -> Path:
    text = str(value)
    if "://" in text or text.lower().startswith("file:") or text.startswith(("\\\\", "//")):
        raise ValueError("Choose a local file, not a URL or network-share path.")
    path = Path(value).expanduser().resolve(strict=True)
    if str(path).startswith(("\\\\", "//")) or path.suffix.lower() != ".mbtiles":
        raise ValueError("Choose a local .mbtiles file.")
    return path


@contextmanager
def _database(path: Path, identity, cancel):
    _cancelled(cancel)
    if _identity(path) != identity:
        raise ValueError("Map file changed. Close and reopen the intended version.")
    with path.open("rb") as stream:
        header = stream.read(100)
    if not header.startswith(b"SQLite format 3\x00") or header[18:20] != b"\x01\x01":
        raise ValueError(
            "Unsupported SQLite header or WAL-mode pack; export a closed rollback-mode copy."
        )
    connection = None
    deadline = time.monotonic() + SQL_SECONDS
    budget = 20_000  # 20 million VM instructions at the 1,000-instruction cadence.

    def progress():
        nonlocal budget
        budget -= 1
        return int(
            budget <= 0 or time.monotonic() >= deadline or (cancel is not None and cancel.is_set())
        )

    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.25)
        connection.set_progress_handler(progress, 1000)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA cache_size=-2048")
        connection.execute("BEGIN")
        yield connection
        _cancelled(cancel)
        if _identity(path) != identity:
            raise ValueError("Map file changed during reading. Close and reopen it.")
    except sqlite3.Error as exc:
        _cancelled(cancel)
        raise ValueError(
            "Unreadable map database, unsupported schema, or SQLite work limit reached."
        ) from exc
    finally:
        if connection is not None:
            connection.close()


def _schema(db):
    for table, expected in (
        ("metadata", (("name", "TEXT"), ("value", "TEXT"))),
        (
            "tiles",
            (
                ("zoom_level", "INTEGER"),
                ("tile_column", "INTEGER"),
                ("tile_row", "INTEGER"),
                ("tile_data", "BLOB"),
            ),
        ),
    ):
        row = db.execute(
            "SELECT type, substr(sql,1,2048) FROM sqlite_master WHERE name=?", (table,)
        ).fetchone()
        if not row or row[0] != "table" or not re.match(r"\s*CREATE\s+TABLE\b", row[1] or "", re.I):
            raise ValueError(
                "Only ordinary metadata/tiles tables are supported, not views or virtual tables."
            )
        columns = tuple((r[1], r[2].upper()) for r in db.execute(f'PRAGMA table_info("{table}")'))
        if columns != expected:
            raise ValueError("Unsupported metadata/tiles column layout or declared types.")
    found = False
    for row in db.execute('PRAGMA index_list("tiles")').fetchmany(129):
        if row[2] and not row[4]:
            name = row[1].replace('"', '""')
            columns = [r for r in db.execute(f'PRAGMA index_xinfo("{name}")') if r[5]]
            if tuple(r[2] for r in columns) == ("zoom_level", "tile_column", "tile_row") and all(
                r[4] == "BINARY" for r in columns
            ):
                found = True
                break
    if not found:
        raise ValueError(
            "A unique non-partial index on zoom_level, tile_column, tile_row is required; no index is created."
        )


def _text(value: str) -> str:
    # Keep HTML/URLs inert, and remove control/bidi formatting characters.
    return "".join(
        c
        for c in value
        if c in "\n\t"
        or (c.isprintable() and not 0x202A <= ord(c) <= 0x202E and not 0x2066 <= ord(c) <= 0x2069)
    )


def inspect_pack(path, *, consent: bool = False, cancel: Event | None = None) -> MapPack:
    if consent is not True:
        raise ValueError("Confirm trust and permission before opening a local map.")
    _cancelled(cancel)
    path = _local_path(path)
    identity = _identity(path)
    with _database(path, identity, cancel) as db:
        _schema(db)
        rows = db.execute(
            "SELECT substr(name,1,129), substr(value,1,16385), "
            "length(CAST(name AS BLOB)), length(CAST(value AS BLOB)), "
            "typeof(name), typeof(value) FROM metadata LIMIT 129"
        ).fetchall()
        if len(rows) > MAX_METADATA:
            raise ValueError("Map metadata exceeds 128 entries.")
        metadata = {}
        for key, value, nk, nv, tk, tv in rows:
            if (
                tk != "text"
                or tv != "text"
                or nk > 128
                or nv > MAX_TEXT
                or not key
                or key in metadata
                or _text(key) != key
            ):
                raise ValueError("Map metadata contains invalid, oversized, or duplicate entries.")
            metadata[key] = _text(value)
        if not metadata.get("name", "").strip() or metadata.get("format", "").lower() not in {
            "png",
            "jpg",
            "jpeg",
            "webp",
            "pbf",
        }:
            raise ValueError(
                "A map name and PNG, JPEG, WebP raster or Mapbox PBF vector format are required."
            )
        if metadata.get("scheme", "tms").lower() != "tms":
            raise ValueError("This reader requires MBTiles TMS rows, not an XYZ-row extension.")
        extremes = [
            db.execute(
                f"SELECT zoom_level FROM tiles ORDER BY zoom_level {order} LIMIT 1"
            ).fetchone()
            for order in ("ASC", "DESC")
        ]
        if not all(r and type(r[0]) is int and 0 <= r[0] <= 22 for r in extremes):
            raise ValueError("Map must contain tiles only at integer zoom levels 0 through 22.")
        levels, initial = [], None
        for z in range(23):
            _cancelled(cancel)
            row = db.execute(
                "SELECT tile_column,tile_row FROM tiles WHERE zoom_level=? "
                "ORDER BY tile_column,tile_row LIMIT 1",
                (z,),
            ).fetchone()
            if row:
                if not all(type(v) is int and 0 <= v < 2**z for v in row):
                    raise ValueError("An initial map tile has invalid coordinates.")
                levels.append(z)
                if initial is None:
                    x, tms_y = row
                    xyz_y = 2**z - 1 - tms_y
                    initial = (
                        (x + 0.5) / 2**z * 360 - 180,
                        math.degrees(
                            math.atan(math.sinh(math.pi * (1 - 2 * (xyz_y + 0.5) / 2**z)))
                        ),
                        z,
                    )
        start, notice = initial, "Start is the center of an observed tile, not a current location."
        if "center" in metadata:
            try:
                parts = metadata["center"].split(",")
                if len(parts) != 3:
                    raise ValueError
                lon, lat, z = map(float, parts)
                if (
                    not all(math.isfinite(v) for v in (lon, lat, z))
                    or not -180 <= lon <= 180
                    or not -MAX_LAT <= lat <= MAX_LAT
                    or z not in levels
                ):
                    raise ValueError
                start = ((lon + 180) % 360 - 180, lat, int(z))
                notice = "Start is pack-declared, not verified coverage or a current location."
            except (ValueError, OverflowError):
                notice = "Invalid declared center ignored; using an observed tile center, not current location."
        if metadata.get("format", "").lower() == "pbf":
            row = db.execute("SELECT typeof(tile_data),tile_data FROM tiles LIMIT 1").fetchone()
            if (row is None or row[0] != "blob" or not isinstance(row[1], bytes)
                    or len(row[1]) > MAX_TILE_BYTES or not row[1].startswith(b"\x1f\x8b")):
                raise ValueError("Vector MBTiles has no bounded PBF tile sample.")
            from fieldforge.navigation.vector_tiles import render_vector_tile

            render_vector_tile(row[1])
            notice += " Vector tiles use a basic preview style with limited point-name labels; publisher styling and label rules are not applied."
        return MapPack(path, identity, tuple(metadata.items()), tuple(levels), start, notice)


def png_preflight(data: bytes) -> int:
    """Check size/header/dimensions before Tk decoding. This is not full PNG validation."""
    if type(data) is not bytes or not 45 <= len(data) <= MAX_TILE_BYTES:
        raise ValueError("PNG is missing or exceeds the 2 MiB tile limit.")
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[8:16] != b"\x00\x00\x00\rIHDR":
        raise ValueError("Unsupported PNG header.")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", data[16:29]
    )
    if width != height or width not in (256, 512):
        raise ValueError("Only square 256- or 512-pixel PNG tiles are supported.")
    legal = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
    if (
        depth not in legal.get(color, ())
        or compression != 0
        or filtering != 0
        or interlace not in (0, 1)
    ):
        raise ValueError("Unsupported PNG encoding.")
    if zlib.crc32(data[12:29]) != struct.unpack(">I", data[29:33])[0]:
        raise ValueError("PNG header checksum failed.")
    return width


def read_tiles(pack: MapPack, keys, *, cancel: Event | None = None) -> tuple[Tile, ...]:
    keys = tuple(keys)
    if len(keys) > MAX_CELLS:
        raise ValueError("Viewport exceeds the 96-cell limit.")
    for key in keys:
        if (
            not isinstance(key, tuple)
            or len(key) != 3
            or any(type(v) is not int for v in key)
            or not 0 <= key[0] <= 22
            or not all(0 <= v < 2 ** key[0] for v in key[1:])
        ):
            raise ValueError("Invalid XYZ tile coordinates.")
    results, total = {}, 0
    with _database(pack.path, pack.identity, cancel) as db:
        for z, x, y in dict.fromkeys(keys):
            _cancelled(cancel)
            key = (z, x, y)
            row = db.execute(
                "SELECT typeof(tile_data), length(tile_data), substr(tile_data,1,?) "
                "FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (MAX_TILE_BYTES + 1, z, x, 2**z - 1 - y),
            ).fetchone()
            if row is None:
                results[key] = Tile(key, "missing", reason="Tile not installed at this zoom")
                continue
            kind, size, data = row
            tile_format = dict(pack.metadata)["format"].lower()
            if kind != "blob" or size > MAX_TILE_BYTES or size < (1 if tile_format == "pbf" else 33):
                results[key] = Tile(key, "bad", reason="Tile is unreadable or exceeds the 2 MiB limit")
                continue
            try:
                if tile_format == "pbf":
                    from fieldforge.navigation.vector_tiles import render_vector_tile

                    if not data.startswith(b"\x1f\x8b"):
                        raise ValueError("PBF MBTiles tiles must be gzip-compressed.")
                    data = render_vector_tile(data)
                elif tile_format != "png":
                    from .raster import tile_png

                    data = tile_png(data, tile_format)
                png_preflight(data)
            except ValueError as exc:
                results[key] = Tile(key, "bad", reason=str(exc))
                continue
            total += max(size, len(data))
            if total > MAX_FRAME_BYTES:
                raise ValueError("Viewport exceeds the 32 MiB compressed-tile limit.")
            results[key] = Tile(key, "ready", data)
    return tuple(results[key] for key in keys)
