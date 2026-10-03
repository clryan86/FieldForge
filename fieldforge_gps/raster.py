"""Bounded local raster decoding; no georeferencing inferred from an image."""

from __future__ import annotations

import hashlib
import io
import math
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

TILE_FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}
REFERENCE_FORMATS = (
    "PNG",
    "JPEG",
    "WEBP",
    "TIFF",
    "BMP",
    "GIF",
    "ICO",
    "PPM",
    "TGA",
    "JPEG2000",
    "AVIF",
)
MAX_IMAGE_BYTES = 64 * 1024**2
MAX_IMAGE_PIXELS = 32_000_000
MAX_IMAGE_SIDE = 32_768
MAX_VIEW_PIXELS = 4_000_000


def pillow():
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError(
            'Image support requires Pillow; install FieldForge with the "maps" extra.'
        ) from exc
    return Image


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ValueError("Image operation cancelled.")


def _png(image):
    # Do not propagate source EXIF/GPS/ICC metadata into display buffers.
    image.info.clear()
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def tile_png(data: bytes, declared_format: str) -> bytes:
    """Decode a JPEG/WebP tile in its worker and return metadata-free PNG bytes."""
    expected = TILE_FORMATS.get(declared_format.lower())
    if expected is None or type(data) is not bytes or not 1 <= len(data) <= 2 * 1024**2:
        raise ValueError("Unsupported or oversized raster tile.")
    Image = pillow()
    try:
        with Image.open(io.BytesIO(data), formats=[expected]) as source:
            if source.width != source.height or source.width not in (256, 512):
                raise ValueError("Unsupported tile dimensions; use square 256/512-pixel tiles.")
            if getattr(source, "n_frames", 1) != 1:
                raise ValueError("Animated map tiles are not supported.")
            source.load()
            with source.convert("RGBA") as decoded:
                return _png(decoded)
    except (
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("Unreadable raster tile or unavailable image codec.") from exc


@dataclass(frozen=True)
class ReferenceImage:
    name: str
    format: str
    width: int
    height: int
    sha256: str
    pixels: object = field(repr=False, compare=False)


def read_reference(source, *, consent=False, cancel=None) -> ReferenceImage:
    if consent is not True:
        raise ValueError("Confirm image trust and permission before reading a file.")
    text = str(source)
    if "://" in text or text.lower().startswith("file:") or text.startswith(("//", "\\\\")):
        raise ValueError("Choose a local image file, not a URL or network-share path.")
    path = Path(source).expanduser()
    _cancel(cancel)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= MAX_IMAGE_BYTES:
        raise ValueError("Choose a regular image file of at most 64 MiB; links are not accepted.")
    identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if identity != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        ):
            raise ValueError("Image changed before reading; choose the intended file again.")
        chunks = []
        size = 0
        while True:
            _cancel(cancel)
            chunk = stream.read(min(1024**2, MAX_IMAGE_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_IMAGE_BYTES:
                raise ValueError("Image exceeds 64 MiB.")
        finished = os.fstat(stream.fileno())
    final = path.lstat()
    if any(
        identity != (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        for s in (finished, final)
    ):
        raise ValueError("Image changed during reading; no image accepted.")
    data = b"".join(chunks)
    Image = pillow()
    try:
        with Image.open(io.BytesIO(data), formats=list(REFERENCE_FORMATS)) as decoded:
            width, height = decoded.size
            if not (
                0 < width <= MAX_IMAGE_SIDE
                and 0 < height <= MAX_IMAGE_SIDE
                and width * height <= MAX_IMAGE_PIXELS
            ):
                raise ValueError("Image exceeds 32 million pixels or a 32,768-pixel side.")
            # Deliberately show the first page/frame in stored pixel order. No
            # EXIF orientation, world file, GeoTIFF CRS or GPS tag is interpreted.
            decoded.load()
            _cancel(cancel)
            pixels = decoded.convert("RGBA")
            pixels.info.clear()
            return ReferenceImage(
                path.name, decoded.format, width, height, hashlib.sha256(data).hexdigest(), pixels
            )
    except (
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError(
            "Image cannot be decoded. Check the file, supported format and installed codec."
        ) from exc


def render_reference(document, center, scale, size, *, cancel=None) -> bytes:
    _cancel(cancel)
    if (
        not isinstance(document, ReferenceImage)
        or len(center) != 2
        or len(size) != 2
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in (*center, scale))
        or not 0.001 <= scale <= 8
        or any(type(v) is not int or v < 1 for v in size)
        or size[0] * size[1] > MAX_VIEW_PIXELS
    ):
        raise ValueError("Unsupported image viewport; reduce the window size or zoom.")
    Image = pillow()
    left, top = center[0] - size[0] / (2 * scale), center[1] - size[1] / (2 * scale)
    with document.pixels.transform(
        size,
        Image.Transform.AFFINE,
        (1 / scale, 0, left, 0, 1 / scale, top),
        resample=Image.Resampling.BILINEAR,
        fillcolor=(235, 237, 233, 255),
    ) as view:
        _cancel(cancel)
        return _png(view)
