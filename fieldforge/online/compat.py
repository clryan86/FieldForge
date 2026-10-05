"""Compatibility API for published FieldForge online tools.

PortalSession retains the original dataclasses, CSV/GPX helpers and exact-file
map downloads. All network response bounds, protocol selection and cancellation
are owned by the shared PortalClient; no network runs at import or construction.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fieldforge.navigation.places import coordinate, coordinate_text
from fieldforge_gps.places import clean_text

from . import models
from .client import PortalCancelled, PortalClient, PortalError, _NoRedirect
from .storage import check_directory, write_new_bytes

USER_AGENT = "FieldForge/0.1 (+https://github.com/clryan86/FieldForge)"
MAX_JSON = models.MAX_JSON_BYTES
MAX_MAP = models.MAX_MBTILES_BYTES
IMAGE_SUFFIXES = {suffix for kind, suffixes in models.FORMATS.items()
                  if models.format_family(kind) == "image" for suffix in suffixes}
OnlineError = PortalError
Cancelled = PortalCancelled


def checked(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled("Online operation cancelled. No new result accepted.")


def base_url(value: str) -> str:
    if (not isinstance(value, str) or len(value) > 2048
            or any(ord(c) < 33 for c in value) or any(c in value for c in "? #\\")):
        raise OnlineError("Enter a portal URL without credentials, query or control characters.")
    try:
        parts = urllib.parse.urlsplit(value)
        models.validate_portal_url(urllib.parse.urlunsplit((parts.scheme, parts.netloc, "", "", "")))
    except ValueError as exc:
        raise OnlineError(str(exc)) from exc
    return value.rstrip("/")


def open_request(url, *, payload=None, timeout=8):
    """Public injectable opening hook; PortalClient owns bounded response reading."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "identity"}
    raw = None
    if payload is not None:
        raw = models.encode_json(payload)
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=raw, headers=headers)
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout)


class _CompatOpener:
    def open(self, request, timeout):
        payload = models.decode_json(request.data) if request.data is not None else None
        return open_request(request.full_url, payload=payload, timeout=timeout)


def request_json(url, *, payload=None, cancel=None):
    """Retain the old helper while sharing the core's strict, bounded transport."""
    checked(cancel)
    parts = urllib.parse.urlsplit(url)
    if "#" in url or "\\" in url:
        raise OnlineError("Request URLs must not contain fragments or backslashes.")
    origin = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    client = PortalClient(origin, timeout=8, opener=_CompatOpener())
    path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
    return client._json(path, payload, client._generation, cancel)


def text(value, label, limit=500):
    return clean_text(value, label, limit=limit, required=True)


@dataclass(frozen=True)
class Address:
    label: str
    latitude: float
    longitude: float
    source: str
    attribution: str
    license: str = ""
    retrieved_at: str = field(default="", compare=False)

    @classmethod
    def parse(cls, item):
        if not isinstance(item, dict):
            raise OnlineError("Invalid address result.")
        license_text = item.get("license", "")
        retrieved_at = item.get("retrieved_at", "")
        if not isinstance(license_text, str) or not isinstance(retrieved_at, str):
            raise OnlineError("Optional address license and retrieval timestamp must be text.")
        if license_text:
            license_text = models.text(license_text, "License", 2000, multiline=True)
        if retrieved_at:
            retrieved_at = models.validate_timestamp(retrieved_at)
        return cls(text(item.get("label"), "Address", 1000), coordinate(item.get("latitude"), latitude=True),
                   coordinate(item.get("longitude"), latitude=False), text(item.get("source"), "Source"),
                   text(item.get("attribution"), "Attribution", 4000), license_text, retrieved_at)


@dataclass(frozen=True)
class MapItem:
    id: str
    title: str
    filename: str
    kind: str
    size: int
    sha256: str
    coverage: str
    updated: str
    source: str
    attribution: str
    license: str

    @classmethod
    def parse(cls, item):
        if not isinstance(item, dict):
            raise OnlineError("Invalid map catalogue entry.")
        fields = {key: item.get(key) for key in cls.__dataclass_fields__}
        for key in fields.keys() - {"size"}:
            fields[key] = text(fields[key], key, 4000 if key == "attribution" else 2000 if key in {"license", "coverage"} else 500)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", fields["id"]):
            raise OnlineError("Invalid map identifier.")
        filename = fields["filename"]
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,179}", filename)
                or filename.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)),
                                                    *(f"LPT{i}" for i in range(10))}):
            raise OnlineError("Unsupported map filename.")
        suffix = Path(filename).suffix.lower()
        declared_format = next((kind for kind, suffixes in models.FORMATS.items() if suffix in suffixes), None)
        if declared_format is None or fields["kind"] != models.format_family(declared_format):
            raise OnlineError("This catalogue item is not a supported map format.")
        maximum = models.format_byte_limit(declared_format)
        if type(fields["size"]) is not int or not 1 <= fields["size"] <= maximum:
            raise OnlineError("Map size exceeds the supported limit.")
        if not re.fullmatch("[0-9a-f]{64}", fields["sha256"]):
            raise OnlineError("The map needs an exact SHA-256 checksum.")
        return cls(**fields)


def validate_route(value):
    if isinstance(value, dict) and "mode" in value:
        return _legacy_route(models.validate_route(value))
    if not isinstance(value, dict) or value.get("profile") != "driving":
        raise OnlineError("Unsupported route response.")
    positions = value.get("coordinates")
    if not isinstance(positions, list) or not 2 <= len(positions) <= 50_000:
        raise OnlineError("A route must have 2–50,000 points.")
    points = []
    for point in positions:
        if not isinstance(point, list) or len(point) != 2:
            raise OnlineError("Invalid route geometry.")
        points.append([coordinate(point[0], latitude=False), coordinate(point[1], latitude=True)])
    result = {key: text(value.get(key), key, 2000) for key in ("source", "attribution", "created_at")}
    for key in ("distance_m", "duration_s"):
        number = value.get(key)
        if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= 1e9:
            raise OnlineError("Invalid route estimate.")
        result[key] = number
    if "license" in value:
        result["license"] = models.text(value["license"], "License", 2000, multiline=True)
    return {**result, "profile": "driving", "coordinates": points}


def route_gpx(route) -> bytes:
    route = validate_route(route)
    root = ET.Element("gpx", {"xmlns": "http://www.topografix.com/GPX/1/1", "version": "1.1", "creator": "FieldForge"})
    metadata = ET.SubElement(root, "metadata")
    description = (f"PLANNED driving route, not a recorded GPS trip. Requested {route['created_at']}. "
                   f"Source: {route['source']}. {route['attribution']}. "
                   "Saved geometry only; no offline rerouting or current road-condition guarantee.")
    if route.get("license"):
        description += " License: " + route["license"]
    ET.SubElement(metadata, "desc").text = description
    track = ET.SubElement(root, "trk")
    ET.SubElement(track, "name").text = "PLANNED driving route — not recorded"
    ET.SubElement(track, "desc").text = description
    segment = ET.SubElement(track, "trkseg")
    for lon, lat in route["coordinates"]:
        ET.SubElement(segment, "trkpt", {"lat": coordinate_text(lat), "lon": coordinate_text(-180 if lon == 180 else lon)})
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def address_csv(address: Address) -> bytes:
    address = Address.parse(asdict(address))
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["name", "latitude", "longitude", "source"])
    details = f"{address.source}; {address.attribution}; online address result, not a GPS fix"
    if address.license:
        details += "; License: " + address.license
    if address.retrieved_at:
        details += "; Retrieved: " + address.retrieved_at
    # The portable GPS catalog has tighter label/source limits than rich portal
    # metadata. Refuse an unusable export instead of silently discarding credit.
    clean_text(address.label, "GPS CSV place name", limit=160, required=True)
    clean_text(details, "GPS CSV source notes", limit=512, required=True)
    writer.writerow([address.label, coordinate_text(address.latitude), coordinate_text(address.longitude),
                     details])
    return stream.getvalue().encode("utf-8")


def publish_file(temp: Path, destination: Path):
    """Original exact-file publication helper; never replaces an existing name."""
    temp, destination = Path(temp), Path(destination)
    if os.name == "nt":
        os.rename(temp, destination)
    else:
        os.link(temp, destination)
        temp.unlink()


def save_new(destination, data: bytes):
    target = Path(destination).expanduser().absolute()
    parent = target.parent.resolve()
    check_directory(parent)
    write_new_bytes(parent / target.name, data)


def _map_item(asset: dict, portal: str) -> MapItem:
    return MapItem.parse({
        "id": asset["id"], "title": asset["title"], "filename": asset["filename"],
        "kind": models.format_family(asset["format"]),
        "size": asset["bytes"], "sha256": asset["sha256"], "coverage":
            asset["coverage"] if isinstance(asset["coverage"], str) else json.dumps(asset["coverage"]),
        "updated": asset["version"], "source": asset.get("source", "Served by " + portal),
        "attribution": asset["attribution"], "license": asset["license"],
    })


def _legacy_route(route: dict) -> dict:
    return {"profile": route["mode"], "coordinates": route["geometry"],
            "distance_m": route["distance_m"], "duration_s": route["duration_s"],
            "source": route["source"], "attribution": route["attribution"],
            "license": route["license"], "created_at": route["created_at"]}


class PortalSession:
    """Published API façade over the same client used by the primary desktop."""

    def __init__(self):
        self.cancel = threading.Event()
        self.ready = False
        self.url = ""
        self.capabilities = {}
        self._client = None
        self._lock = threading.RLock()
        self._generation = 0

    def disconnect(self):
        with self._lock:
            self.ready = False
            self._generation += 1
            self.cancel.set()
            if self._client is not None:
                self._client.disconnect()

    def connect(self, url, *, consent=False):
        if consent is not True:
            self.disconnect()
            raise OnlineError("Choose to connect before sending any requests.")
        with self._lock:
            self.disconnect()
            self.cancel = threading.Event()
            cancel, token = self.cancel, self._generation
            self.url = base_url(url)
            client = PortalClient(self.url, timeout=8, opener=_CompatOpener())
            self._client = client
            client_token = client._generation
        # Keep this public hook for existing integrations and tests. Its default
        # implementation already uses PortalClient's bounded reader.
        status = request_json(self.url + "/api/v1/status", cancel=cancel)
        with self._lock:
            checked(cancel)
            if token != self._generation:
                raise Cancelled("This connection attempt is obsolete.")
            accepted = client._accept_status(status, client_token, cancel)
            self.capabilities = {key: accepted[key] for key in ("geocoding", "routing", "catalog")}
            self.ready = True
            return {"version": 1, "name": accepted["name"],
                    "capabilities": {key: accepted[key] for key in ("geocoding", "routing")},
                    "providers": accepted.get("providers", {})}

    def _run(self, action, *args, **kwargs):
        checked(self.cancel)
        if not self.ready or self._client is None or not self._client.connected:
            raise OnlineError("Connect to the portal first. Offline tools remain available.")
        try:
            return action(*args, cancel=self.cancel, **kwargs)
        except (PortalError, OSError):
            self.disconnect()
            raise

    def search(self, query):
        checked(self.cancel)
        query = text(query, "Address search", 300)
        if not self.capabilities.get("geocoding") or self._client is None:
            raise OnlineError("Address search is not available on this portal.")
        return tuple(Address.parse(item) for item in self._run(self._client.search, query))

    def maps(self):
        checked(self.cancel)
        if self._client is None:
            raise OnlineError("Connect to the portal first.")
        return tuple(_map_item(item, self.url) for item in self._run(self._client.catalog))

    def route(self, start, end):
        checked(self.cancel)
        if not self.capabilities.get("routing") or self._client is None:
            raise OnlineError("Driving routes are not available on this portal.")
        if any(not isinstance(point, (tuple, list)) or len(point) != 2 for point in (start, end)):
            raise OnlineError("Enter start and destination as latitude, longitude pairs.")
        positions = tuple((coordinate(p[0], latitude=True), coordinate(p[1], latitude=False))
                          for p in (start, end))
        routes = self._run(self._client.routes, *positions)
        if not routes:
            raise OnlineError("No driving route was returned for those coordinates.")
        return _legacy_route(routes[0])

    def download(self, item: MapItem, destination):
        item = MapItem.parse(asdict(item))
        destination = Path(destination)
        if destination.suffix.lower() != Path(item.filename).suffix.lower():
            raise OnlineError("Keep the map's original file extension.")
        checked(self.cancel)
        if self._client is None:
            raise OnlineError("Connect before downloading a map.")
        asset = models.normalize_legacy_asset(asdict(item))
        note = {**asdict(item), "portal": self.url}
        return self._run(self._client._download_to, asset, destination, legacy_note=note)
