"""Bounded, local-only named-coordinate catalogues and Unicode search.

CSV and a documented Point-only GeoJSON subset; no downloads, persistence,
address geocoding, coordinate-system conversion, routes, or receiver access.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from ._file_identity import path_matches_descriptor

MAX_BYTES = 16 * 1024 * 1024
MAX_PLACES = 50_000
MAX_QUERY = 160
MAX_RESULTS = 100
MAX_DEPTH = 16
MAX_STRUCTURE = 1_000_000
DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z")
CSV_FIELDS = frozenset(
    {"name", "latitude", "longitude", "country", "region", "aliases", "source_id", "source"}
)
REQUIRED = frozenset({"name", "latitude", "longitude"})
CRS84 = "urn:ogc:def:crs:OGC:1.3:CRS84"


class PlaceReadCancelled(ValueError):
    """A discarded operation must not publish a partial catalogue or search."""


def check_cancel(cancel: Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise PlaceReadCancelled("Place operation cancelled; no partial result accepted.")


def clean_text(value, field: str, *, limit=160, required=False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{field} must be plain text of at most {limit} characters.")
    # Text stays inert. Strip control/bidi formatting, preserve Unicode letters.
    value = " ".join(
        "".join(c if unicodedata.category(c)[0] != "C" else " " for c in value).split()
    )
    if required and not value:
        raise ValueError(f"{field} is required.")
    return value


def folded(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        "".join(c if c.isalnum() else " " for c in value if not unicodedata.combining(c)).split()
    )


def coordinate(value, field: str) -> float:
    if field not in ("latitude", "longitude"):
        raise ValueError("Unknown coordinate field.")
    if isinstance(value, str):
        value = value.strip()
        if len(value) > 80 or not DECIMAL.fullmatch(value):
            raise ValueError(f"{field} requires decimal degrees, not DMS or scientific notation.")
        value = float(value)
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be a finite number, not a boolean or missing value.")
    bound = 90 if field == "latitude" else 180
    if not -bound <= value <= bound or not math.isfinite(value):
        raise ValueError(f"{field} must be between {-bound} and {bound}.")
    return float(value)


@dataclass(frozen=True)
class Place:
    ordinal: int
    name: str
    latitude: float
    longitude: float
    country: str = ""
    region: str = ""
    aliases: tuple[str, ...] = ()
    source_id: str = ""
    source: str = ""


@dataclass(frozen=True)
class PlaceCatalog:
    places: tuple[Place, ...]
    source_sha256: str
    source_bytes: int
    format: str
    declared_name: str
    index: tuple[tuple[str, tuple[str, ...], str], ...]
    ignored_elevations: int = 0


@dataclass(frozen=True)
class SearchResults:
    places: tuple[Place, ...]
    total: int
    query: str


def manual_place(latitude: str, longitude: str) -> Place:
    return Place(
        0, "Manual coordinate", coordinate(latitude, "latitude"), coordinate(longitude, "longitude")
    )


def _aliases(value) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        if len(value) > 2048:
            raise ValueError("Aliases exceed 2048 characters.")
        value = value.split("|")
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError("Use at most 16 aliases, separated by | or a JSON string array.")
    return tuple(dict.fromkeys(t for item in value if (t := clean_text(item, "Alias"))))


def _make_place(row: dict, ordinal: int, latitude, longitude) -> Place:
    identifier = row.get("source_id", "")
    if type(identifier) is int:
        identifier = str(identifier)
    return Place(
        ordinal,
        clean_text(row.get("name"), "Place name", required=True),
        coordinate(latitude, "latitude"),
        coordinate(longitude, "longitude"),
        clean_text(row.get("country"), "Country / area"),
        clean_text(row.get("region"), "Region"),
        _aliases(row.get("aliases")),
        clean_text(identifier, "Source identifier"),
        clean_text(row.get("source"), "Source", limit=512),
    )


def _csv_places(text: str, cancel) -> list[Place]:
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
        header = [h.strip().lower() for h in header]
        if (
            len(header) != len(set(header))
            or not REQUIRED <= set(header)
            or not set(header) <= CSV_FIELDS
        ):
            raise ValueError(
                "CSV requires unique name,latitude,longitude columns; see docs for optional columns."
            )
        places = []
        for row in reader:
            check_cancel(cancel)
            if not row:  # Ignore blank lines, not malformed or unnamed records.
                continue
            number = len(places) + 1
            if number > MAX_PLACES:
                raise ValueError("Place catalogue exceeds 50,000 records.")
            if len(row) != len(header):
                raise ValueError(
                    f"CSV record {number} has a different field count than its header."
                )
            values = dict(zip(header, row))
            try:
                places.append(_make_place(values, number, values["latitude"], values["longitude"]))
            except ValueError as exc:
                raise ValueError(f"CSV record {number}: {exc}") from exc
        return places
    except StopIteration as exc:
        raise ValueError("CSV has no header.") from exc
    except csv.Error as exc:
        raise ValueError("Malformed CSV or a field exceeds the CSV reader limit.") from exc


def _json_preflight(text: str, cancel) -> None:
    depth = structure = 0
    quoted = escaped = False
    for index, char in enumerate(text):
        if index % 65536 == 0:
            check_cancel(cancel)
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "{[":
            depth += 1
            structure += 1
            if depth > MAX_DEPTH:
                raise ValueError("GeoJSON exceeds the nesting limit.")
        elif char in "}]":
            depth -= 1
        elif char in ",:":
            structure += 1
        if structure > MAX_STRUCTURE:
            raise ValueError("GeoJSON exceeds the structural work limit.")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object keys are not supported.")
        result[key] = value
    return result


def _no_constant(_value):
    raise ValueError("Non-finite JSON constants are not supported.")


def _geojson_places(text: str, cancel) -> tuple[list[Place], str, int]:
    _json_preflight(text, cancel)
    try:
        root = json.loads(text, object_pairs_hook=_unique, parse_constant=_no_constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Malformed or excessively nested GeoJSON.") from exc
    check_cancel(cancel)
    if not isinstance(root, dict) or root.get("type") != "FeatureCollection":
        raise ValueError("GeoJSON must be a FeatureCollection of named Point features.")
    crs = root.get("crs")
    if "crs" in root and crs != {"type": "name", "properties": {"name": CRS84}}:
        raise ValueError(
            "Only longitude/latitude WGS84 is supported; legacy CRS must be explicit CRS84."
        )
    features = root.get("features")
    if not isinstance(features, list) or len(features) > MAX_PLACES:
        raise ValueError("GeoJSON requires a features array of at most 50,000 records.")
    name = clean_text(root.get("name"), "Collection name", limit=256)
    places, ignored = [], 0
    for ordinal, feature in enumerate(features, 1):
        check_cancel(cancel)
        try:
            if (
                not isinstance(feature, dict)
                or feature.get("type") != "Feature"
                or "crs" in feature
            ):
                raise ValueError("Each record must be a Feature without an overriding CRS.")
            props, geom = feature.get("properties"), feature.get("geometry")
            if (
                not isinstance(props, dict)
                or not isinstance(geom, dict)
                or geom.get("type") != "Point"
                or "crs" in geom
            ):
                raise ValueError(
                    "Only named Point features with plain properties are supported; nothing is silently skipped."
                )
            coords = geom.get("coordinates")
            if not isinstance(coords, list) or len(coords) not in (2, 3):
                raise ValueError(
                    "Point coordinates must be [longitude, latitude] with optional elevation."
                )
            if len(coords) == 3:
                if type(coords[2]) not in (int, float) or not math.isfinite(coords[2]):
                    raise ValueError("Optional elevation must be finite.")
                ignored += 1
            # GeoJSON coordinate positions must be numbers, never numeric strings.
            if any(type(c) not in (int, float) for c in coords[:2]):
                raise ValueError("GeoJSON coordinates must be numeric, not strings or booleans.")

            # Case variants used by Natural Earth GeoJSON exports are explicit.
            def get(*keys, default=None):
                for key in keys:
                    if key in props and props[key] is not None:
                        return props[key]
                return default

            aliases = list(_aliases(get("aliases", "namealt", "NAMEALT")))
            ascii_name = get("nameascii", "NAMEASCII")
            if ascii_name:
                aliases.append(clean_text(ascii_name, "ASCII alias"))
            row = {
                "name": get("name", "NAME"),
                "country": get("country", "adm0name", "ADM0NAME"),
                "region": get("region", "adm1name", "ADM1NAME"),
                "aliases": list(dict.fromkeys(aliases)),
                "source_id": get("source_id", "ne_id", "NE_ID", default=feature.get("id", "")),
                "source": get("source", default=name),
            }
            places.append(_make_place(row, ordinal, coords[1], coords[0]))
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"GeoJSON record {ordinal}: {exc}") from exc
    return places, name, ignored


def parse_catalog(data: bytes, format: str, *, cancel: Event | None = None) -> PlaceCatalog:
    """Pure parse: complete acceptance only, no files/network. Caller controls consent."""
    check_cancel(cancel)
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        raise ValueError("Use a nonempty UTF-8 place file no larger than 16 MiB.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Only UTF-8 CSV and GeoJSON are supported.") from exc
    if "\x00" in text:
        raise ValueError("Null bytes are not supported.")
    name, ignored = "", 0
    if format == "csv":
        places = _csv_places(text, cancel)
    elif format == "geojson":
        places, name, ignored = _geojson_places(text, cancel)
    else:
        raise ValueError("Supported place formats are CSV and Point GeoJSON.")
    if not places:
        raise ValueError("Catalogue has no named places.")
    index = []
    for place in places:
        check_cancel(cancel)
        normalized, aliases = folded(place.name), tuple(folded(a) for a in place.aliases)
        index.append(
            (
                normalized,
                aliases,
                " ".join((normalized, *aliases, folded(place.country), folded(place.region))),
            )
        )
    return PlaceCatalog(
        tuple(places),
        hashlib.sha256(data).hexdigest(),
        len(data),
        format,
        name,
        tuple(index),
        ignored,
    )


def _identity(info) -> tuple[int, ...]:
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES:
        raise ValueError("Choose a regular, nonempty place file of at most 16 MiB.")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_catalog(
    path, *, consent=False, wgs84_confirmed=False, cancel: Event | None = None
) -> PlaceCatalog:
    if consent is not True or wgs84_confirmed is not True:
        raise ValueError(
            "Confirm file permission/privacy and WGS84 coordinates before reading places."
        )
    check_cancel(cancel)
    value = str(path)
    if "://" in value or value.lower().startswith("file:") or value.startswith(("\\\\", "//")):
        raise ValueError("Select a local place file, not a URL or network-share path.")
    path = Path(path).expanduser().resolve(strict=True)
    if str(path).startswith(("\\\\", "//")) or path.suffix.lower() not in (
        ".csv",
        ".geojson",
        ".json",
    ):
        raise ValueError("Select a local .csv, .geojson, or .json place file.")
    before = path.stat()
    identity = _identity(before)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        opened_identity = _identity(opened)
        if not path_matches_descriptor(before, opened):
            raise ValueError("Place file changed before reading. Reopen the intended version.")
        blocks, size = [], 0
        while True:
            check_cancel(cancel)
            block = os.read(descriptor, 65536)
            if not block:
                break
            size += len(block)
            if size > MAX_BYTES:
                raise ValueError("Place file grew beyond the 16 MiB limit.")
            blocks.append(block)
        after = os.fstat(descriptor)
        final = path.stat()
        if (
            _identity(after) != opened_identity
            or _identity(final) != identity
            or not path_matches_descriptor(final, after)
        ):
            raise ValueError("Place file changed during reading. No catalogue accepted.")
    finally:
        os.close(descriptor)
    result = parse_catalog(
        b"".join(blocks), "csv" if path.suffix.lower() == ".csv" else "geojson", cancel=cancel
    )
    if _identity(path.stat()) != identity:
        raise ValueError("Place file changed during parsing. No catalogue accepted.")
    check_cancel(cancel)
    return result


def search_places(
    catalog: PlaceCatalog, query: str, *, limit=MAX_RESULTS, cancel: Event | None = None
) -> SearchResults:
    check_cancel(cancel)
    if not isinstance(query, str) or len(query) > MAX_QUERY:
        raise ValueError("Search text must be at most 160 characters.")
    if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
        raise ValueError("Search result limit must be between 1 and 100.")
    query = folded(query)
    if not query:
        return SearchResults((), 0, query)
    tokens = query.split()
    if len(tokens) > 12:
        raise ValueError("Use at most 12 search words.")
    matches = []
    for place, (name, aliases, context) in zip(catalog.places, catalog.index):
        check_cancel(cancel)
        if all(token in context for token in tokens):
            rank = (
                0
                if name == query
                else 1
                if query in aliases
                else 2
                if name.startswith(query)
                else 3
                if query in name
                else 4
            )
            matches.append(
                (rank, name, folded(place.country), folded(place.region), place.ordinal, place)
            )
    matches.sort(key=lambda row: row[:-1])
    check_cancel(cancel)
    return SearchResults(tuple(row[-1] for row in matches[:limit]), len(matches), query)
