"""Bounded GPX 1.1 waypoint-only interchange with preview-bound atomic imports.

WGS 84 decimal degrees. Routes/tracks are refused, not silently shortened into
waypoints. Ancillary GPX fields are disclosed as omitted. No external XML access,
location lookup, network, automatic imports or destination overwrites.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.parsers import expat

from fieldforge.navigation.geo import Waypoint
from fieldforge.navigation.places import (
    MAX_PLACES,
    PlaceConflict,
    PlaceSnapshot,
    PlaceStore,
    make_place,
    validate,
)

NS = "http://www.topografix.com/GPX/1/1"
MAX_INPUT = 1024 * 1024
MAX_IMPORT = 200
MAX_OUTPUT = 16 * 1024 * 1024
IMPORT_NOTICE = (
    "Import only trusted GPX 1.1 waypoint files. Names, coordinates, type and descriptions become "
    "local place records; descriptions become private place notes. Other fields are not retained. "
    "Coordinates are not verified. Same-name conflicts block the entire import; no existing record is replaced."
)
EXPORT_NOTICE = (
    "GPX discloses place names, types and precise coordinates even when notes are excluded. "
    "The file is unencrypted. Only share locations you intend to disclose. No routes or maps are included."
)


@dataclass(frozen=True)
class GPXCapture:
    filename: str
    sha256: str
    points: tuple[Waypoint, ...]
    omitted: tuple[str, ...] = ()
    generated_names: int = 0


@dataclass(frozen=True)
class ImportPlan:
    captured: GPXCapture
    states: tuple[str, ...]
    database_token: str

    @property
    def added(self) -> int:
        return self.states.count("new")

    @property
    def duplicates(self) -> int:
        return self.states.count("duplicate")

    @property
    def conflicts(self) -> int:
        return self.states.count("conflict")


@dataclass(frozen=True)
class GPXExport:
    points: tuple[Waypoint, ...]
    include_notes: bool = False


@dataclass(frozen=True)
class SavedGPX:
    path: Path
    sha256: str
    byte_count: int


def read_gpx(source: str | Path) -> GPXCapture:
    path = Path(source).expanduser()
    if path.suffix.lower() != ".gpx":
        raise ValueError("Choose a local .gpx waypoint file.")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_INPUT:
            raise ValueError("Choose a regular GPX file no larger than 1 MiB.")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_INPUT + 1)
        after = os.fstat(descriptor)
        if (len(raw), after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
            info.st_size, info.st_size, info.st_mtime_ns, info.st_ctime_ns
        ):
            raise ValueError("GPX changed during capture; choose it again when the writer has finished.")
    finally:
        os.close(descriptor)
    return parse_gpx(raw, filename=path.name)


def parse_gpx(raw: bytes, *, filename: str = "waypoints.gpx") -> GPXCapture:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_INPUT:
        raise ValueError("GPX input must be 1 byte to 1 MiB.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("This importer supports UTF-8 GPX files only.") from exc
    if not isinstance(filename, str) or len(filename) > 255:
        raise ValueError("Invalid GPX filename.")
    parser = expat.ParserCreate(namespace_separator="}")
    stack, points, ignored = [], [], Counter()
    fields, coords = {}, {}
    nodes, generated = 0, 0
    supported = {"name", "type", "desc"}
    other = {"ele", "time", "magvar", "geoidheight", "cmt", "src", "link", "sym", "fix", "sat",
             "hdop", "vdop", "pdop", "ageofdgpsdata", "dgpsid", "extensions"}

    def local(tag):
        return tag[len(NS)+1:] if tag.startswith(NS + "}") else "unknown-namespace"

    def forbidden(*_):
        raise ValueError("DTD, entities and processing instructions are not supported in GPX imports.")

    def declaration(_version, encoding, _standalone):
        if _version != "1.0":
            raise ValueError("Only XML 1.0 GPX documents are supported.")
        if encoding and encoding.lower().replace("-", "") != "utf8":
            raise ValueError("GPX XML declaration must specify UTF-8 or omit the encoding.")

    def start(tag, attrs):
        nonlocal fields, coords, nodes
        nodes += 1
        stack.append(local(tag))
        if nodes > 6000 or len(stack) > 12:
            raise ValueError("GPX XML structure exceeds the supported bounds.")
        if len(stack) == 1:
            if stack[0] != "gpx" or attrs.get("version") != "1.1" or not attrs.get("creator", "").strip():
                raise ValueError("Expected GPX 1.1 with its standard namespace and creator attribute.")
            if set(attrs) - {"version", "creator"}:
                ignored["root attributes (including schema hints)"] += 1
        elif len(stack) == 2:
            name = stack[-1]
            if name in {"rte", "trk"}:
                raise ValueError("This file contains routes/tracks. Export waypoints only; nothing will be imported.")
            if name == "wpt":
                if len(points) >= MAX_IMPORT:
                    raise ValueError("More than 200 GPX waypoints; split the file explicitly before importing.")
                if not {"lat", "lon"} <= set(attrs):
                    raise ValueError("Every waypoint needs latitude and longitude.")
                coords, fields = attrs, {}
                if set(attrs) - {"lat", "lon"}:
                    ignored["waypoint extra attributes"] += 1
            elif name in {"metadata", "extensions"}:
                ignored[name] += 1
            else:
                raise ValueError("Unsupported GPX root element; no partial import created.")
        elif stack[1] == "wpt":
            if len(stack) == 3:
                name = stack[-1]
                if name in supported:
                    if name in fields or attrs:
                        raise ValueError("Duplicate or attributed waypoint text fields are unsupported.")
                    fields[name] = ""
                elif name in other:
                    ignored["waypoint " + name] += 1
                else:
                    raise ValueError("Unsupported waypoint element; no partial import created.")
            elif stack[2] in supported:
                raise ValueError("Waypoint names/types/descriptions must be plain XML text, not nested elements.")

    def data(value):
        if len(stack) == 3 and stack[1] == "wpt" and stack[2] in supported:
            name = stack[2]
            fields[name] += value
            if len(fields[name]) > 4000:
                raise ValueError("Waypoint text is too long; nothing truncated or imported.")

    def end(_tag):
        nonlocal generated
        if stack == ["gpx", "wpt"]:
            name = fields.get("name", "").strip()
            if not name:
                generated += 1
                name = f"Imported waypoint {len(points)+1}"
            point = make_place(name, coords["lat"], coords["lon"], fields.get("type", "").strip() or "waypoint",
                               fields.get("desc", ""))
            if point.longitude >= 180:
                raise ValueError("GPX 1.1 longitude must be less than +180; use the equivalent -180 meridian.")
            points.append(point)
        stack.pop()

    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.CharacterDataHandler = data
    parser.XmlDeclHandler = declaration
    parser.StartDoctypeDeclHandler = forbidden
    parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    parser.ProcessingInstructionHandler = forbidden
    try:
        parser.Parse(text.encode("utf-8"), True)
    except expat.ExpatError as exc:
        raise ValueError(f"Malformed GPX XML near line {exc.lineno}; nothing imported.") from exc
    if not points:
        raise ValueError("No waypoints found in this GPX file.")
    return GPXCapture(filename, hashlib.sha256(raw).hexdigest(), tuple(points),
                      tuple(f"{key}: {value}" for key, value in sorted(ignored.items())), generated)


def _identity(point):
    return (point.name.strip().casefold(), point.latitude, -180.0 if point.longitude == 180 else point.longitude,
            point.kind, point.notes)


def _plan(snapshot: PlaceSnapshot, captured: GPXCapture) -> ImportPlan:
    if not isinstance(captured, GPXCapture) or not isinstance(captured.points, tuple) or not 1 <= len(captured.points) <= MAX_IMPORT:
        raise ValueError("Capture 1–200 GPX waypoints first.")
    seen = {}
    for record in snapshot.records:
        seen.setdefault(record.point.name.strip().casefold(), set()).add(_identity(record.point))
    states = []
    for point in captured.points:
        validate(point)
        if point.id is not None:
            raise ValueError("GPX imports must not supply database IDs.")
        name, identity = point.name.strip().casefold(), _identity(point)
        matches = seen.get(name, set())
        states.append("new" if not matches else "duplicate" if matches == {identity} else "conflict")
        seen.setdefault(name, set()).add(identity)
    return ImportPlan(captured, tuple(states), snapshot.token)


def preview_import(store: PlaceStore, captured: GPXCapture) -> ImportPlan:
    return _plan(store.snapshot(), captured)


def commit_import(store: PlaceStore, plan: ImportPlan, *, acknowledged: bool = False) -> tuple[int, int]:
    if acknowledged is not True or not isinstance(plan, ImportPlan):
        raise ValueError("Preview and confirm GPX storage/privacy before importing.")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        snapshot = store._snapshot(db)
        checked = _plan(snapshot, plan.captured)
        if checked != plan:
            raise PlaceConflict("Waypoints changed since preview. Rebuild the preview; no places were imported.")
        if checked.conflicts:
            raise PlaceConflict("Same-name conflicts must be resolved before import; nothing was replaced or imported.")
        if len(snapshot.records) + checked.added > MAX_PLACES:
            raise ValueError("Import would exceed the 2,000-waypoint limit; nothing imported.")
        for point, state in zip(checked.captured.points, checked.states):
            if state == "new":
                store._insert(db, point)
    return checked.added, checked.duplicates


def capture_export(store: PlaceStore, ids: tuple[int, ...], *, include_notes: bool = False) -> GPXExport:
    if type(include_notes) is not bool:
        raise ValueError("Choose whether to include private notes explicitly.")
    records = store.snapshot(ids).records
    return GPXExport(tuple(record.point if include_notes else replace(record.point, notes="") for record in records), include_notes)


def _decimal(value):
    return format(Decimal(str(value)), "f")


def render_gpx(snapshot: GPXExport) -> bytes:
    if not isinstance(snapshot, GPXExport) or not isinstance(snapshot.points, tuple) or not 1 <= len(snapshot.points) <= MAX_PLACES:
        raise ValueError("Capture selected places before exporting.")
    if type(snapshot.include_notes) is not bool or (not snapshot.include_notes and any(p.notes for p in snapshot.points)):
        raise ValueError("Private notes cannot be included without explicit opt-in.")
    root = ET.Element("gpx", {"xmlns": NS, "version": "1.1", "creator": "FieldForge"})
    for point in snapshot.points:
        validate(point)
        lon = -180.0 if point.longitude == 180 else point.longitude
        node = ET.SubElement(root, "wpt", {"lat": _decimal(point.latitude), "lon": _decimal(lon)})
        ET.SubElement(node, "name").text = point.name
        if snapshot.include_notes:
            ET.SubElement(node, "desc").text = point.notes
        ET.SubElement(node, "type").text = point.kind
    # Numeric CR references preserve CR/CRLF note text under XML newline normalization.
    raw = ET.tostring(root, encoding="utf-8", xml_declaration=True).replace(b"\r", b"&#13;")
    if len(raw) > MAX_OUTPUT:
        raise ValueError("GPX output exceeds 16 MiB; export fewer selected places.")
    return raw


def save_gpx(snapshot: GPXExport, destination: str | Path, *, acknowledged: bool = False) -> SavedGPX:
    if acknowledged is not True:
        raise ValueError("Confirm that the unencrypted GPX will disclose names and precise coordinates.")
    path = Path(destination).expanduser().absolute()
    if path.suffix.lower() != ".gpx":
        raise ValueError("Choose a NEW .gpx filename.")
    raw = render_gpx(snapshot)
    identity = None
    try:
        with path.open("xb") as stream:
            identity = os.fstat(stream.fileno())
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if identity is not None:
            try:
                current = path.lstat()
                if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                    path.unlink()
            except OSError:
                pass
        raise
    return SavedGPX(path.resolve(), hashlib.sha256(raw).hexdigest(), len(raw))
