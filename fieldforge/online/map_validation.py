"""Shared map preflight for portal publishing and desktop downloads.

This reads file structures and dimensions without loading pixel buffers or
requiring Pillow. Actual rendering still uses the existing trusted-image reader.
Both ends enforce the same 64 MiB file, 32-million-pixel, 32,768-pixel-side limits.
The checks are a format preflight, not a full image decoder or malicious-file
sandbox. No source bytes are changed and no network operations are performed.
Prepared regional maps use the same bounded inspector as their offline reader.
"""

from __future__ import annotations

import stat
import struct
import zlib
from pathlib import Path

from fieldforge.online.models import MAX_IMAGE_BYTES, format_byte_limit
from fieldforge_gps.raster import MAX_IMAGE_PIXELS, MAX_IMAGE_SIDE

CHUNK_BYTES = 64 * 1024
OPTIONAL_FORMATS = {"ico": "ICO", "ppm": "PPM", "tga": "TGA",
                    "jpeg2000": "JPEG2000", "avif": "AVIF"}


class RasterValidationError(ValueError):
    """The supplied image is unsupported or exceeds the viewer's limits."""


class RasterCancelled(ValueError):
    """Image preflight was cancelled before publication or installation."""


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise RasterCancelled("Map image verification cancelled.")


def regional_file_preflight(path: Path, cancel=None) -> tuple:
    """Check a complete single-file regional database before opening SQLite."""
    from fieldforge.navigation.mbtiles import MapCancelled
    from fieldforge.navigation.pbf_stream import signature

    if cancel is not None and cancel.is_set():
        raise MapCancelled("Prepared regional map verification cancelled.")
    path = Path(path).absolute()
    before = signature(path)
    if not 0 < before[2] <= format_byte_limit("ffmap"):
        raise ValueError("Prepared regional maps must be regular files up to 4 GiB.")
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            raise ValueError("Prepared regional map has a SQLite sidecar; close/export its writer first.")
    with path.open("rb") as stream:
        header = stream.read(100)
    if not header.startswith(b"SQLite format 3\x00") or header[18:20] != b"\x01\x01":
        raise ValueError("Use a closed, rollback-mode prepared regional database.")
    if signature(path) != before:
        raise ValueError("Prepared regional map changed during verification.")
    return before


def validate_regional_map(path: Path, cancel=None) -> None:
    """Verify a nonempty prepared index without changing its embedded receipt."""
    from fieldforge.navigation.regional_index import inspect_index

    before = regional_file_preflight(path, cancel)
    index = inspect_index(path, cancel=cancel)
    if index.metadata["features"] == 0:
        raise ValueError("An empty prepared regional index is not a downloadable map.")
    if index.fingerprint != before or regional_file_preflight(path, cancel) != before:
        raise ValueError("Prepared regional map changed during verification.")


def _dimensions(width, height):
    if not (0 < width <= MAX_IMAGE_SIDE and 0 < height <= MAX_IMAGE_SIDE
            and width * height <= MAX_IMAGE_PIXELS):
        raise RasterValidationError(
            "Map image exceeds 32 million pixels or a 32,768-pixel side."
        )


def _png(stream, header, tail, size, cancel):
    if (len(header) < 33 or header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            or tail != b"\x00\x00\x00\x00IEND\xaeB`\x82"):
        return False
    _dimensions(*struct.unpack(">II", header[16:24]))
    if zlib.crc32(header[12:29]) & 0xFFFFFFFF != int.from_bytes(header[29:33], "big"):
        return False
    stream.seek(8)
    seen_data, chunks = False, 0
    while stream.tell() < size:
        _cancelled(cancel)
        chunk_header = stream.read(8)
        if len(chunk_header) != 8 or chunks >= 100_000:
            return False
        length, tag = struct.unpack(">I4s", chunk_header)
        if length > size - stream.tell() - 4:
            return False
        crc, remaining = zlib.crc32(tag), length
        while remaining:
            _cancelled(cancel)
            data = stream.read(min(CHUNK_BYTES, remaining))
            if not data:
                return False
            crc = zlib.crc32(data, crc)
            remaining -= len(data)
        expected = stream.read(4)
        if len(expected) != 4 or crc & 0xFFFFFFFF != int.from_bytes(expected, "big"):
            return False
        seen_data |= tag == b"IDAT" and length > 0
        chunks += 1
    return seen_data


def _jpeg(stream, header, tail, size, cancel):
    if len(header) < 4 or not header.startswith(b"\xff\xd8\xff") or not tail.endswith(b"\xff\xd9"):
        return False
    stream.seek(2)
    frame_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                     0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    for _ in range(8192):
        _cancelled(cancel)
        if stream.read(1) != b"\xff":
            return False
        marker = stream.read(1)
        for _padding in range(4096):
            if marker != b"\xff":
                break
            marker = stream.read(1)
        if len(marker) != 1 or marker[0] in {0, 0xFF, 0xD8, 0xD9, 0xDA}:
            return False
        if marker[0] in {0x01, *range(0xD0, 0xD8)}:
            continue
        encoded_length = stream.read(2)
        if len(encoded_length) != 2:
            return False
        length = int.from_bytes(encoded_length, "big")
        if length < 2 or stream.tell() + length - 2 > size:
            return False
        if marker[0] in frame_markers:
            if length < 8:
                return False
            frame = stream.read(6)
            if len(frame) != 6:
                return False
            height, width = struct.unpack(">HH", frame[1:5])
            _dimensions(width, height)
            return True
        stream.seek(length - 2, 1)
    return False


def _webp(header, size):
    if (len(header) < 25 or header[:4] != b"RIFF" or header[8:12] != b"WEBP"
            or int.from_bytes(header[4:8], "little") + 8 != size):
        return False
    chunk_size = int.from_bytes(header[16:20], "little")
    if 20 + chunk_size > size:
        return False
    kind = header[12:16]
    if kind == b"VP8 ":
        if len(header) < 30 or chunk_size < 10 or header[20] & 1 or header[23:26] != b"\x9d\x01\x2a":
            return False
        width, height = struct.unpack("<HH", header[26:30])
        _dimensions(width & 0x3FFF, height & 0x3FFF)
    elif kind == b"VP8L":
        if chunk_size < 5 or header[20] != 0x2F:
            return False
        dimensions = int.from_bytes(header[21:25], "little")
        if dimensions >> 29:
            return False
        _dimensions((dimensions & 0x3FFF) + 1, ((dimensions >> 14) & 0x3FFF) + 1)
    elif kind == b"VP8X":
        if len(header) < 30 or chunk_size != 10:
            return False
        _dimensions(int.from_bytes(header[24:27], "little") + 1,
                    int.from_bytes(header[27:30], "little") + 1)
    else:
        return False
    return True


def _tiff(stream, header, size, cancel):
    if len(header) < 8 or header[:4] not in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
        return False
    order = "little" if header[:2] == b"II" else "big"
    large = header[2:4] in (b"+\x00", b"\x00+")
    if large and (len(header) < 16 or int.from_bytes(header[4:6], order) != 8
                  or header[6:8] != b"\x00\x00"):
        return False
    count_bytes, entry_bytes, pointer_bytes = (8, 20, 8) if large else (2, 12, 4)
    offset = int.from_bytes(header[8:16] if large else header[4:8], order)
    if not (16 if large else 8) <= offset <= size - count_bytes:
        return False
    stream.seek(offset)
    entries = int.from_bytes(stream.read(count_bytes), order)
    if not 1 <= entries <= 4096 or offset + count_bytes + entries * entry_bytes + pointer_bytes > size:
        return False
    dimensions = {}
    for index in range(entries):
        _cancelled(cancel)
        stream.seek(offset + count_bytes + index * entry_bytes)
        entry = stream.read(entry_bytes)
        if len(entry) != entry_bytes:
            return False
        tag = int.from_bytes(entry[:2], order)
        if tag not in {256, 257}:
            continue
        kind = int.from_bytes(entry[2:4], order)
        value_count = int.from_bytes(entry[4:12] if large else entry[4:8], order)
        if tag in dimensions or value_count != 1 or kind not in ({3, 4, 16} if large else {3, 4}):
            return False
        value_size = {3: 2, 4: 4, 16: 8}[kind]
        value_offset = 12 if large else 8
        dimensions[tag] = int.from_bytes(entry[value_offset:value_offset + value_size], order)
    if set(dimensions) != {256, 257}:
        return False
    _dimensions(dimensions[256], dimensions[257])
    return True


def validate_raster_image(path: Path, kind: str, cancel=None) -> None:
    """Apply identical format/dimension checks before publishing or installing."""
    _cancelled(cancel)
    path = Path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_IMAGE_BYTES:
        raise RasterValidationError("Map image must be a regular file no larger than 64 MiB.")
    if kind in OPTIONAL_FORMATS:
        # Retain the published image families through the existing bounded
        # decoder, without making Pillow mandatory for the core map formats.
        from fieldforge_gps.raster import read_reference

        try:
            decoded = read_reference(path, consent=True, cancel=cancel)
            try:
                if decoded.format != OPTIONAL_FORMATS[kind]:
                    raise RasterValidationError("Image bytes do not match the declared map format.")
            finally:
                decoded.pixels.close()
        except ValueError as exc:
            _cancelled(cancel)
            raise RasterValidationError(str(exc)) from exc
        _cancelled(cancel)
        return
    size = info.st_size
    with path.open("rb") as stream:
        header = stream.read(64)
        stream.seek(max(0, size - 12))
        tail = stream.read(12)
        valid = False
        if kind == "png":
            valid = _png(stream, header, tail, size, cancel)
        elif kind == "jpeg":
            valid = _jpeg(stream, header, tail, size, cancel)
        elif kind == "webp":
            valid = _webp(header, size)
        elif kind == "tiff":
            valid = _tiff(stream, header, size, cancel)
        elif kind == "gif":
            valid = len(header) >= 13 and header[:6] in (b"GIF87a", b"GIF89a") and tail.endswith(b";")
            if valid:
                _dimensions(*struct.unpack("<HH", header[6:10]))
        elif kind == "bmp":
            valid = (len(header) >= 26 and header[:2] == b"BM"
                     and int.from_bytes(header[2:6], "little") == size)
            if valid:
                dib = int.from_bytes(header[14:18], "little")
                if dib == 12:
                    _dimensions(*struct.unpack("<HH", header[18:22]))
                elif dib >= 40 and len(header) >= 54:
                    width, height = struct.unpack("<ii", header[18:26])
                    _dimensions(width, abs(height))
                else:
                    valid = False
    if not valid:
        raise RasterValidationError("Map bytes do not match a supported raster image format.")
    _cancelled(cancel)
