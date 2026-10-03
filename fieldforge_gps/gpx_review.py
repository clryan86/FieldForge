"""Read-only, bounded GPX 1.1 track inspection. Never touches a receiver Session.

This intentionally supports a documented GPX subset, not general XML/XSD
validation. Whole-file rejection avoids silently joining around bad coordinates.
Links, extensions, schemas and executable content are never followed or run.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import stat
import threading
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.parsers import expat

NS = "http://www.topografix.com/GPX/1/1"
Q = "{" + NS + "}"
MAX_BYTES = 16 * 1024 * 1024
MAX_POINTS = 50_000
MAX_TRACKS = 200
MAX_SEGMENTS = 10_000
MAX_ELEMENTS = 250_000
MAX_DEPTH = 32
MAX_TEXT = 16_384
DECIMAL = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$")
TIME = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})?$"
)


class ImportCancelled(ValueError):
    """A requested read was cancelled; its partial results must not be published."""


def _cancelled(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise ImportCancelled("GPX read cancelled. Previous review was not replaced.")


@dataclass(frozen=True)
class ReviewPoint:
    latitude: float
    longitude: float
    elevation_m: float | None = None
    time_text: str | None = None  # Retained verbatim after validation; no fabricated time.


@dataclass(frozen=True)
class ReviewTrack:
    name: str
    segments: tuple[tuple[ReviewPoint, ...], ...]

    @property
    def point_count(self) -> int:
        return sum(len(segment) for segment in self.segments)


@dataclass(frozen=True)
class ReviewDocument:
    tracks: tuple[ReviewTrack, ...]
    source_sha256: str
    source_bytes: int
    ignored_waypoints: int
    ignored_routes: int
    empty_tracks: int
    empty_segments: int

    @property
    def point_count(self) -> int:
        return sum(track.point_count for track in self.tracks)

    @property
    def segment_count(self) -> int:
        return sum(len(track.segments) for track in self.tracks)


class _BoundedBuilder(ET.TreeBuilder):
    def __init__(self, cancel):
        super().__init__()
        self.sizes: list[int] = []
        self.tags: list[str] = []
        self.count = 0
        self.cancel = cancel

    def start(self, tag, attrs):
        _cancelled(self.cancel)
        self.count += 1
        if self.count > MAX_ELEMENTS or len(self.sizes) >= MAX_DEPTH:
            raise ValueError("GPX XML exceeds the element or nesting limit.")
        if (
            len(tag) > 1024
            or len(attrs) > 64
            or any(len(k) > 1024 or len(v) > MAX_TEXT for k, v in attrs.items())
        ):
            raise ValueError("GPX XML attributes exceed the supported limits.")
        expected = {
            Q + "gpx": None,
            Q + "trk": Q + "gpx",
            Q + "trkseg": Q + "trk",
            Q + "trkpt": Q + "trkseg",
        }
        if tag in expected and (self.tags[-1] if self.tags else None) != expected[tag]:
            raise ValueError(
                "Misplaced GPX track structure; refusing to silently omit track points."
            )
        self.sizes.append(0)
        self.tags.append(tag)
        return super().start(tag, attrs)

    def end(self, tag):
        value = super().end(tag)
        self.sizes.pop()
        self.tags.pop()
        return value

    def data(self, data):
        if self.sizes:
            self.sizes[-1] += len(data)
            if self.sizes[-1] > MAX_TEXT:
                raise ValueError("A GPX text field exceeds the supported limit.")
        return super().data(data)

    def doctype(self, *args):
        raise ValueError("DTD and entity declarations are not accepted.")

    def pi(self, *args):
        raise ValueError("XML processing instructions are not accepted.")


def _decimal(text: str | None, field: str) -> float:
    if text is None or len(text.strip()) > 80 or not DECIMAL.fullmatch(text.strip()):
        raise ValueError(f"Invalid GPX {field}; expected a finite decimal.")
    value = float(text.strip())
    if not math.isfinite(value):
        raise ValueError(f"Invalid GPX {field}; expected a finite decimal.")
    return value


def _field(element, name: str) -> str | None:
    children = element.findall(Q + name)
    if len(children) > 1:
        raise ValueError(f"A GPX point or track has duplicate {name} fields.")
    if not children:
        return None
    if len(children[0]):
        raise ValueError(f"The GPX {name} field must be plain text.")
    return (children[0].text or "").strip()


def _time(text: str | None) -> str | None:
    if text is None:
        return None
    if len(text) > 80 or not TIME.fullmatch(text):
        raise ValueError("Unsupported GPX time; use an ISO date/time, optionally with a time zone.")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("The GPX time is not a valid calendar date/time.") from exc
    # XSD timezone offsets must be no more than 14:00, not Python's wider range.
    match = re.search(r"[+-]([0-9]{2}):([0-9]{2})$", text)
    if match and (
        int(match[1]) > 14 or int(match[2]) > 59 or (int(match[1]) == 14 and int(match[2]) != 0)
    ):
        raise ValueError("GPX time zone offset is outside the supported range.")
    return text


def _name(element, index: int) -> str:
    name = _field(element, "name")
    if not name:
        return f"Unnamed track {index}"
    if len(name) > 160:
        raise ValueError("GPX track names may contain at most 160 characters.")
    # Names are labels, never markup. Remove control/bidi formatting to prevent
    # display spoofing, without changing the actual source file.
    return (
        " ".join("".join(ch if unicodedata.category(ch)[0] != "C" else " " for ch in name).split())
        or f"Unnamed track {index}"
    )


def parse_gpx(data: bytes, *, cancel: threading.Event | None = None) -> ReviewDocument:
    """Parse GPX track content; no filesystem/network access and no partial result.

    UTF-8 GPX 1.1 only. Missing time/elevation stays missing. Supplied times are
    validated and kept as written; an absent timezone is NOT interpreted as UTC.
    """
    _cancelled(cancel)
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        raise ValueError("Select a nonempty GPX file no larger than 16 MiB.")
    if expat.version_info < (2, 6, 0):
        raise ValueError(
            "This GPX reader requires Python built with Expat 2.6.0 or newer. Update Python."
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "Only UTF-8 GPX files are supported; convert a copy of this file first."
        ) from exc
    if "\x00" in text or re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.I):
        raise ValueError("DTD/entity declarations and null characters are not accepted.")
    declaration = re.match(r"<\?xml\s[^?]*\?>", text)
    encoding = (
        re.search(r"encoding\s*=\s*['\"]([^'\"]+)['\"]", declaration[0], re.I)
        if declaration
        else None
    )
    if encoding and encoding[1].lower() not in ("utf-8", "utf8", "us-ascii", "ascii"):
        raise ValueError("Only UTF-8 GPX files are supported.")
    parser = ET.XMLParser(target=_BoundedBuilder(cancel))
    try:
        for offset in range(0, len(data), 65536):
            _cancelled(cancel)
            parser.feed(data[offset : offset + 65536])
        root = parser.close()
    except ET.ParseError as exc:
        raise ValueError(
            f"Malformed GPX XML at line {exc.position[0]}. Previous review was not replaced."
        ) from exc
    if root.tag != Q + "gpx" or root.get("version") != "1.1" or root.get("creator") is None:
        raise ValueError(
            "Expected a namespaced GPX 1.1 document with version and creator attributes."
        )
    elements = root.findall(Q + "trk")
    if not elements or len(elements) > MAX_TRACKS:
        raise ValueError(
            "Select a GPX file containing 1 to 200 tracks. Routes/waypoints are not tracks."
        )
    tracks = []
    points_count = segments_count = empty_tracks = empty_segments = 0
    for index, element in enumerate(elements, 1):
        _cancelled(cancel)
        segments = []
        for segment in element.findall(Q + "trkseg"):
            segments_count += 1
            if segments_count > MAX_SEGMENTS:
                raise ValueError("GPX exceeds the 10,000-segment limit; nothing was imported.")
            points = []
            for point in segment.findall(Q + "trkpt"):
                _cancelled(cancel)
                points_count += 1
                if points_count > MAX_POINTS:
                    raise ValueError("GPX exceeds the 50,000-point limit; nothing was imported.")
                lat = _decimal(point.get("lat"), "latitude")
                lon = _decimal(point.get("lon"), "longitude")
                if not -90 <= lat <= 90 or not -180 <= lon < 180:
                    raise ValueError(
                        "GPX coordinates are outside latitude [-90,90] / longitude [-180,180)."
                    )
                elevation = _field(point, "ele")
                points.append(
                    ReviewPoint(
                        lat,
                        lon,
                        _decimal(elevation, "elevation") if elevation is not None else None,
                        _time(_field(point, "time")),
                    )
                )
            if points:
                segments.append(tuple(points))
            else:
                empty_segments += 1
        name = _name(element, index)
        if segments:
            tracks.append(ReviewTrack(name, tuple(segments)))
        else:
            empty_tracks += 1
    if not points_count:
        raise ValueError(
            "The GPX file has no track points. Routes and waypoints were not converted."
        )
    _cancelled(cancel)
    return ReviewDocument(
        tuple(tracks),
        hashlib.sha256(data).hexdigest(),
        len(data),
        len(root.findall(Q + "wpt")),
        len(root.findall(Q + "rte")),
        empty_tracks,
        empty_segments,
    )


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_gpx(
    path: str | Path, *, consent: bool, wgs84_confirmed: bool, cancel: threading.Event | None = None
) -> ReviewDocument:
    """Read only a selected regular local file, with ordinary change detection.

    This is not a tamper-proof filesystem snapshot or a provenance signature.
    Symlink leaf paths and devices/pipes are refused. Never creates output files.
    """
    if consent is not True or wgs84_confirmed is not True:
        raise ValueError(
            "Confirm WGS84 coordinates and permission to inspect private history first."
        )
    _cancelled(cancel)
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_BYTES:
        raise ValueError(
            "Select a nonempty regular GPX file, not a link/device, of at most 16 MiB."
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or _signature(before) != _signature(opened):
            raise ValueError("GPX file changed before reading. Review was not replaced.")
        chunks = []
        total = 0
        while True:
            _cancelled(cancel)
            block = stream.read(min(65536, MAX_BYTES + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total > MAX_BYTES:
                raise ValueError("GPX grew beyond the 16 MiB limit. Review was not replaced.")
        after = os.fstat(stream.fileno())
    if (
        _signature(opened) != _signature(after)
        or _signature(after) != _signature(path.lstat())
        or total != opened.st_size
    ):
        raise ValueError("GPX file changed during reading. Review was not replaced.")
    return parse_gpx(b"".join(chunks), cancel=cancel)
