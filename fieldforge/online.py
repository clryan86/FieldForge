"""Explicit portal access and portable results. Importing this module does no I/O.

The offline readers never call this module. Only an enabled PortalSession may
send requests; changing mode cancels outstanding work and rejects late results.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

from fieldforge.navigation.places import coordinate, coordinate_text
from fieldforge_gps.places import clean_text

USER_AGENT = "FieldForge/0.1 (+https://github.com/clryan86/FieldForge)"
MAX_JSON = 8 * 1024**2
MAX_MAP = 16 * 1024**3
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif",
                  ".ico", ".ppm", ".pgm", ".pbm", ".pnm", ".tga", ".jp2", ".j2k", ".avif"}


class OnlineError(ValueError):
    pass


class Cancelled(OnlineError):
    pass


def checked(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled("Online operation cancelled. No new result accepted.")


def base_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
        raise OnlineError("Enter a portal URL without spaces or control characters.")
    try:
        parts = urllib.parse.urlsplit(value)
        valid_port = parts.port is None or 1 <= parts.port <= 65535
    except ValueError as exc:
        raise OnlineError("Invalid portal URL.") from exc
    if (not parts.hostname or not valid_port or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or parts.scheme not in {"https", "http"}
            or (parts.scheme == "http" and parts.hostname not in {"127.0.0.1", "localhost", "::1"})
            or "\\" in value):
        raise OnlineError("Use HTTPS for a portal, or HTTP on localhost for development. No credentials in URLs.")
    return value.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OnlineError("The portal redirected this request. Check its configured URL before reconnecting.")


def open_request(url, *, payload=None):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "identity"}
    raw = None
    if payload is not None:
        raw = json.dumps(payload, allow_nan=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=raw, headers=headers)
    # No redirects, browser cookies, credential discovery, or environment proxy.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open(request, timeout=8)


def request_json(url, *, payload=None, cancel=None):
    checked(cancel)
    try:
        with open_request(url, payload=payload) as response:
            if response.headers.get_content_type() != "application/json":
                raise OnlineError("The portal returned an unsupported response.")
            data = bytearray()
            deadline = time.monotonic() + 30
            while True:
                checked(cancel)
                if time.monotonic() > deadline:
                    raise OnlineError("The portal request timed out.")
                block = response.read(min(65536, MAX_JSON + 1 - len(data)))
                if not block:
                    break
                data.extend(block)
                if len(data) > MAX_JSON:
                    raise OnlineError("The portal response exceeds the supported size.")
        checked(cancel)
        return json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        message = {429: "The service is busy. Wait before trying again.",
                   503: "This portal service is not configured or is temporarily unavailable.",
                   404: "That portal resource is unavailable."}.get(code, "The portal rejected the request.")
        raise OnlineError(message) from None
    except (OSError, urllib.error.URLError) as exc:
        raise OnlineError("Could not reach the portal. Saved offline files are still available.") from exc
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise OnlineError("The portal returned invalid JSON.") from exc


def text(value, label, limit=500):
    return clean_text(value, label, limit=limit, required=True)


@dataclass(frozen=True)
class Address:
    label: str
    latitude: float
    longitude: float
    source: str
    attribution: str

    @classmethod
    def parse(cls, item):
        if not isinstance(item, dict):
            raise OnlineError("Invalid address result.")
        return cls(text(item.get("label"), "Address"), coordinate(item.get("latitude"), latitude=True),
                   coordinate(item.get("longitude"), latitude=False), text(item.get("source"), "Source"),
                   text(item.get("attribution"), "Attribution", 2000))


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
            fields[key] = text(fields[key], key, 2000 if key in {"attribution", "license"} else 500)
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", fields["id"]):
            raise OnlineError("Invalid map identifier.")
        filename = fields["filename"]
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}", filename)
                or filename.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)),
                                                    *(f"LPT{i}" for i in range(10))}):
            raise OnlineError("Unsupported map filename.")
        suffix = Path(filename).suffix.lower()
        if not ((fields["kind"] == "mbtiles" and suffix == ".mbtiles")
                or (fields["kind"] == "image" and suffix in IMAGE_SUFFIXES)):
            raise OnlineError("This catalogue item is not a supported map format.")
        maximum = MAX_MAP if fields["kind"] == "mbtiles" else 64 * 1024**2
        if type(fields["size"]) is not int or not 1 <= fields["size"] <= maximum:
            raise OnlineError("Map size exceeds the supported limit.")
        if not re.fullmatch("[0-9a-f]{64}", fields["sha256"]):
            raise OnlineError("The map needs an exact SHA-256 checksum.")
        return cls(**fields)


def validate_route(value):
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
    return {**result, "profile": "driving", "coordinates": points}


def route_gpx(route) -> bytes:
    route = validate_route(route)
    root = ET.Element("gpx", {"xmlns": "http://www.topografix.com/GPX/1/1", "version": "1.1", "creator": "FieldForge"})
    metadata = ET.SubElement(root, "metadata")
    description = (f"PLANNED driving route, not a recorded GPS trip. Requested {route['created_at']}. "
                   f"Source: {route['source']}. {route['attribution']}. "
                   "Saved geometry only; no offline rerouting or current road-condition guarantee.")
    ET.SubElement(metadata, "desc").text = description
    track = ET.SubElement(root, "trk")
    ET.SubElement(track, "name").text = "PLANNED driving route — not recorded"
    ET.SubElement(track, "desc").text = description
    segment = ET.SubElement(track, "trkseg")
    for lon, lat in route["coordinates"]:
        ET.SubElement(segment, "trkpt", {"lat": coordinate_text(lat), "lon": coordinate_text(lon)})
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def address_csv(address: Address) -> bytes:
    address = Address.parse(asdict(address))
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["name", "latitude", "longitude", "source"])
    writer.writerow([address.label, coordinate_text(address.latitude), coordinate_text(address.longitude),
                     f"{address.source}; {address.attribution}; online address result, not a GPS fix"])
    return stream.getvalue().encode("utf-8")


def publish_file(temp: Path, destination: Path):
    """Publish without overwriting an existing file, including a raced-in one."""
    if os.name == "nt":
        os.rename(temp, destination)  # Windows rename fails if destination exists.
    else:
        os.link(temp, destination)
        temp.unlink()


def save_new(destination, data: bytes):
    destination = Path(destination)
    fd, name = tempfile.mkstemp(prefix=".fieldforge-", suffix=".part", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        publish_file(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


class PortalSession:
    def __init__(self):
        self.cancel = threading.Event()
        self.ready = False
        self.url = ""
        self.capabilities = {}

    def disconnect(self):
        self.ready = False
        self.cancel.set()

    def connect(self, url, *, consent=False):
        self.ready = False
        if consent is not True:
            raise OnlineError("Choose to connect before sending any requests.")
        checked(self.cancel)
        self.url = base_url(url)
        status = request_json(self.url + "/api/v1/status", cancel=self.cancel)
        if (not isinstance(status, dict) or type(status.get("version")) is not int or status["version"] != 1
                or not isinstance(status.get("capabilities"), dict)
                or not isinstance(status.get("providers"), dict)
                or any(type(status["capabilities"].get(key)) is not bool for key in ("geocoding", "routing"))):
            raise OnlineError("This server does not implement the FieldForge portal protocol.")
        status["name"] = text(status.get("name"), "Portal name")
        providers = {}
        for key in ("geocoding", "routing"):
            if status["capabilities"][key]:
                provider = status["providers"].get(key)
                if not isinstance(provider, dict):
                    raise OnlineError("The portal must identify its configured providers.")
                providers[key] = {"name": text(provider.get("name"), "Provider name"),
                                  "attribution": text(provider.get("attribution"), "Attribution", 2000)}
        status["providers"] = providers
        checked(self.cancel)
        self.capabilities = status["capabilities"]
        self.ready = True
        return status

    def _request(self, path, payload=None):
        checked(self.cancel)
        if not self.ready:
            raise OnlineError("Connect to the portal first. Offline tools remain available.")
        try:
            result = request_json(self.url + path, payload=payload, cancel=self.cancel)
            checked(self.cancel)
            return result
        except (ValueError, OSError):
            self.disconnect()
            raise

    def search(self, query):
        query = text(query, "Address search", 300)
        if not self.capabilities.get("geocoding"):
            raise OnlineError("Address search is not available on this portal.")
        result = self._request("/api/v1/search", {"query": query})
        if not isinstance(result, dict) or not isinstance(result.get("results"), list) or len(result["results"]) > 10:
            raise OnlineError("Invalid address search response.")
        return tuple(Address.parse(item) for item in result["results"])

    def maps(self):
        result = self._request("/api/v1/maps")
        if not isinstance(result, dict) or not isinstance(result.get("maps"), list) or len(result["maps"]) > 500:
            raise OnlineError("Invalid map catalogue response.")
        items = tuple(MapItem.parse(item) for item in result["maps"])
        if len({item.id for item in items}) != len(items):
            raise OnlineError("Duplicate map identifiers in catalogue.")
        return items

    def route(self, start, end):
        if not self.capabilities.get("routing"):
            raise OnlineError("Driving routes are not available on this portal.")
        points = [[coordinate(p[0], latitude=True), coordinate(p[1], latitude=False)] for p in (start, end)]
        return validate_route(self._request("/api/v1/route", {"start": points[0], "end": points[1]}))

    def download(self, item: MapItem, destination):
        item = MapItem.parse(asdict(item))
        destination = Path(destination)
        if destination.suffix.lower() != Path(item.filename).suffix.lower():
            raise OnlineError("Keep the map's original file extension.")
        checked(self.cancel)
        if not self.ready:
            raise OnlineError("Connect before downloading a map.")
        provenance = destination.with_name(destination.name + ".source.json")
        if destination.exists() or destination.is_symlink() or provenance.exists() or provenance.is_symlink():
            raise FileExistsError("Choose a new filename; existing maps and source notes are never overwritten.")
        fd, name = tempfile.mkstemp(prefix=".fieldforge-", suffix=destination.suffix, dir=destination.parent)
        temporary = Path(name)
        published_note = False
        try:
            checksum, count = hashlib.sha256(), 0
            deadline = time.monotonic() + 3600
            with os.fdopen(fd, "wb") as output, open_request(self.url + f"/api/v1/maps/{item.id}/file") as response:
                declared = response.headers.get("Content-Length")
                if declared is not None and declared != str(item.size):
                    raise OnlineError("Map size changed. Refresh the catalogue before downloading.")
                while True:
                    checked(self.cancel)
                    if time.monotonic() > deadline:
                        raise OnlineError("Map download exceeded the one-hour limit.")
                    block = response.read(min(128 * 1024, item.size + 1 - count))
                    if not block:
                        break
                    count += len(block)
                    if count > item.size:
                        raise OnlineError("Map download exceeds the declared size.")
                    checksum.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            checked(self.cancel)
            if count != item.size or checksum.hexdigest() != item.sha256:
                raise OnlineError("Map checksum or size does not match. The incomplete download was discarded.")
            if item.kind == "mbtiles":
                from fieldforge_gps.mbtiles import inspect_pack
                inspect_pack(temporary, consent=True, cancel=self.cancel)
            else:
                from fieldforge_gps.raster import read_reference
                read_reference(temporary, consent=True, cancel=self.cancel)
            checked(self.cancel)
            note = {**asdict(item), "portal": self.url}
            save_new(provenance, (json.dumps(note, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
            published_note = True
            checked(self.cancel)
            publish_file(temporary, destination)
            return destination
        except Exception:
            if published_note:
                provenance.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)
