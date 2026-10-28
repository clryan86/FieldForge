"""Bounded, explicit WGS84 schemas shared by the optional online map tools.

All functions are local validation only. Addresses and latitude/longitude pairs
use latitude first; route geometry uses GeoJSON's longitude/latitude order.
"""

from __future__ import annotations

import ipaddress
import json
import math
import re
from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import urlsplit

MAX_JSON_BYTES = 8 * 1024**2
# A normalized route must leave room for the complete saved-file envelope and
# its timestamp. This also accounts for browser integer spellings being restored
# to canonical Python floats before saving an imported route.
MAX_ROUTE_JSON_BYTES = MAX_JSON_BYTES - 512
MAX_DOWNLOAD_BYTES = 64 * 1024**3
MAX_MBTILES_BYTES = 16 * 1024**3
MAX_REGIONAL_BYTES = 4 * 1024**3
MAX_IMAGE_BYTES = 64 * 1024**2
MAX_MAPS = 5000
MAX_RESULTS = 20
MAX_ROUTES = 8
MAX_ROUTE_POINTS = 50_000
MAX_ROUTE_STEPS = 10_000
MAX_DISTANCE_M = 100_000_000
MAX_DURATION_S = 366 * 24 * 60 * 60
LEGACY_LICENSE = "Not supplied by legacy portal"
FORMATS = {
    "mbtiles": (".mbtiles",),
    "ffmap": (".ffmap",),
    "png": (".png",),
    "jpeg": (".jpg", ".jpeg"),
    "webp": (".webp",),
    "tiff": (".tif", ".tiff"),
    "gif": (".gif",),
    "bmp": (".bmp",),
    "ico": (".ico",),
    "ppm": (".ppm", ".pgm", ".pbm", ".pnm"),
    "tga": (".tga",),
    "jpeg2000": (".jp2", ".j2k"),
    "avif": (".avif",),
}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"
)


class ValidationError(ValueError):
    """An untrusted record is outside the supported schema or work budget."""


def format_family(declared_format: str) -> str:
    """Return a supported format's explicit catalog/filter family."""
    if not isinstance(declared_format, str) or declared_format not in FORMATS:
        raise ValidationError("Map format is unsupported; choose MBTiles, a prepared regional map or a map image.")
    return {"mbtiles": "mbtiles", "ffmap": "regional"}.get(declared_format, "image")


def format_byte_limit(declared_format: str) -> int:
    """Keep publication, download metadata and compatibility limits aligned."""
    return {"mbtiles": MAX_MBTILES_BYTES, "regional": MAX_REGIONAL_BYTES,
            "image": MAX_IMAGE_BYTES}[format_family(declared_format)]


def text(value, name: str, maximum: int, *, multiline: bool = False) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValidationError(f"{name} must contain 1 to {maximum} characters.")
    if len(value) > maximum:
        raise ValidationError(f"{name} is too long.")
    for char in value:
        n = ord(char)
        if (
            (n < 32 and not (multiline and n in (9, 10, 13)))
            or 127 <= n <= 159
            or 0xD800 <= n <= 0xDFFF
            or n in (0xFFFE, 0xFFFF)
            or 0x202A <= n <= 0x202E
            or 0x2066 <= n <= 0x2069
        ):
            raise ValidationError(f"{name} contains unsupported control characters.")
    return value.strip()


def object_fields(value, required: set[str], name: str, optional=()) -> dict:
    if not isinstance(value, dict) or not required <= value.keys():
        raise ValidationError(f"{name} is missing required fields.")
    if value.keys() - required - set(optional):
        raise ValidationError(f"{name} contains unsupported fields.")
    return value


def number(value, name: str, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float):
        raise ValidationError(f"{name} must be a finite number.")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValidationError(f"{name} must be a finite number.") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValidationError(f"{name} must be between {minimum:g} and {maximum:g}.")
    return result


def validate_coordinates(value) -> tuple[float, float]:
    """Validate an explicit (latitude, longitude) pair; never guess or swap axes."""
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValidationError("Coordinates must be a (latitude, longitude) pair.")
    return number(value[0], "Latitude", -90, 90), number(value[1], "Longitude", -180, 180)


def validate_point(value) -> dict:
    value = object_fields(value, {"latitude", "longitude"}, "Coordinate")
    lat, lon = validate_coordinates((value["latitude"], value["longitude"]))
    return {"latitude": lat, "longitude": lon}


def validate_timestamp(value, name: str = "Timestamp") -> str:
    value = text(value, name, 40)
    if not _TIME.fullmatch(value):
        raise ValidationError(f"{name} must be an ISO 8601 timestamp with a timezone.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{name} is not a valid timestamp.") from exc
    offset = parsed.utcoffset()
    if offset is None or abs(offset.total_seconds()) > 14 * 3600:
        raise ValidationError(f"{name} has an unsupported timezone offset.")
    return value


def validate_query(value) -> str:
    return text(value, "Address search", 300)


def validate_id(value) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValidationError("Identifiers must use 1–80 ASCII letters, digits, '_' or '-'.")
    return value


def validate_portal_url(value) -> str:
    """Return an origin only: HTTPS, or HTTP at an explicit loopback host."""
    value = text(value, "Portal URL", 2048)
    if any(c.isspace() for c in value) or any(c in value for c in ("?", "#", "\\", "%")):
        raise ValidationError("Portal URL must not contain spaces, escapes, query or fragment.")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValidationError("Portal URL has an invalid host or port.") from exc
    if (
        parsed.scheme not in ("https", "http")
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValidationError("Use a portal origin without credentials or a path.")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", host):
            raise ValidationError("Portal host must be a valid ASCII hostname or IP address.")
    if parsed.scheme == "http" and not loopback:
        raise ValidationError("HTTPS is required except for a local loopback portal.")
    normalized_host = f"[{host.lower()}]" if ":" in host else host.lower()
    suffix = f":{port}" if port is not None else ""
    return f"{parsed.scheme}://{normalized_host}{suffix}"


def validate_status(value) -> dict:
    value = object_fields(
        value, {"api_version", "name", "geocoding", "routing", "catalog", "route_modes"},
        "Portal status", {"version", "capabilities", "providers"},
    )
    if type(value["api_version"]) is not int or value["api_version"] != 1:
        raise ValidationError("Unsupported portal API version; expected version 1.")
    for key in ("geocoding", "routing", "catalog"):
        if type(value[key]) is not bool:
            raise ValidationError(f"Portal capability {key} must be boolean.")
    modes = value["route_modes"]
    if not isinstance(modes, list) or modes not in ([], ["driving"]):
        raise ValidationError("Unsupported portal route modes.")
    if value["routing"] and "driving" not in modes:
        raise ValidationError("A routing portal must advertise driving support.")
    if "version" in value and (type(value["version"]) is not int or value["version"] != 1):
        raise ValidationError("Legacy status version conflicts with the portal API version.")
    if "capabilities" in value:
        aliases = object_fields(value["capabilities"], {"geocoding", "routing"}, "Legacy capabilities")
        if any(type(aliases[key]) is not bool or aliases[key] != value[key] for key in aliases):
            raise ValidationError("Legacy status capabilities conflict with the portal capabilities.")
    result = {
        "api_version": 1, "name": text(value["name"], "Portal name", 500),
        "geocoding": value["geocoding"], "routing": value["routing"],
        "catalog": value["catalog"], "route_modes": list(modes),
    }
    if "providers" in value:
        providers = value["providers"]
        if not isinstance(providers, dict) or set(providers) - {"geocoding", "routing"}:
            raise ValidationError("Invalid provider identity metadata.")
        result["providers"] = {}
        for kind, provider in providers.items():
            provider = object_fields(provider, {"name", "attribution"}, "Provider identity",
                                     {"license", "source"})
            result["providers"][kind] = {
                "name": text(provider["name"], "Provider name", 500),
                "attribution": text(provider["attribution"], "Provider attribution", 4000, multiline=True),
            }
            if "source" in provider:
                result["providers"][kind]["source"] = text(provider["source"], "Provider source", 500)
            if "license" in provider:
                result["providers"][kind]["license"] = text(provider["license"], "Provider license", 2000, multiline=True)
    return result


def _provenance(value) -> dict:
    return {
        "source": text(value["source"], "Source", 500),
        "attribution": text(value["attribution"], "Attribution", 4000, multiline=True),
        "license": text(value["license"], "License", 2000, multiline=True),
    }


def validate_search_result(value) -> dict:
    value = object_fields(
        value, {"label", "latitude", "longitude", "source", "attribution", "license",
                "retrieved_at"}, "Address result",
    )
    lat, lon = validate_coordinates((value["latitude"], value["longitude"]))
    return {
        "label": text(value["label"], "Address label", 1000),
        "latitude": lat, "longitude": lon, **_provenance(value),
        "retrieved_at": validate_timestamp(value["retrieved_at"], "Retrieval timestamp"),
    }


def validate_filename(value, declared_format: str) -> str:
    value = text(value, "Map filename", 180)
    if (
        value in (".", "..") or value.startswith(".")
        or any(c in value for c in '/\\:<>"|?*')
        or value.endswith((" ", "."))
        or PurePosixPath(value).suffix.lower() not in FORMATS[declared_format]
    ):
        raise ValidationError("Map filename must be a basename with the declared format's suffix.")
    return value


def safe_filename(value: str) -> str:
    """Make one portable local filename from an already validated basename."""
    result = re.sub(r"[^A-Za-z0-9._-]+", "_", value).lstrip(".")
    if not result or result.split(".", 1)[0].upper() in {
        "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        result = "map_" + result
    return result


def validate_asset(value) -> dict:
    value = object_fields(
        value, {"id", "title", "filename", "format", "download_path", "bytes", "sha256",
                "attribution", "license", "coverage", "version"}, "Map catalog entry",
        {"kind", "size", "updated", "source"},
    )
    asset_id = validate_id(value["id"])
    declared_format = value["format"]
    family = format_family(declared_format)
    filename = validate_filename(value["filename"], declared_format)
    if value["download_path"] != f"/api/v1/maps/{asset_id}/download":
        raise ValidationError("Map downloads must use the catalog entry's same-origin path.")
    maximum = format_byte_limit(declared_format)
    if type(value["bytes"]) is not int or not 1 <= value["bytes"] <= min(maximum, MAX_DOWNLOAD_BYTES):
        raise ValidationError("Map size is invalid or exceeds the supported format's limit.")
    digest = value["sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise ValidationError("Map requires a SHA-256 fingerprint.")
    coverage = value["coverage"]
    if isinstance(coverage, str):
        coverage = text(coverage, "Map coverage", 2000)
    elif isinstance(coverage, (list, tuple)) and len(coverage) == 4:
        west = number(coverage[0], "Western bound", -180, 180)
        south = number(coverage[1], "Southern bound", -90, 90)
        east = number(coverage[2], "Eastern bound", -180, 180)
        north = number(coverage[3], "Northern bound", -90, 90)
        if south > north:
            raise ValidationError("Map coverage has reversed latitude bounds.")
        coverage = [west, south, east, north]
    else:
        raise ValidationError("Map coverage must be a label or [west,south,east,north] bounds.")
    if "kind" in value and value["kind"] != family:
        raise ValidationError("Legacy map kind conflicts with its format.")
    if "size" in value and (type(value["size"]) is not int or value["size"] != value["bytes"]):
        raise ValidationError("Legacy map size conflicts with its byte count.")
    if "updated" in value and value["updated"] != value["version"]:
        raise ValidationError("Legacy map revision conflicts with its version.")
    result = {
        "id": asset_id, "title": text(value["title"], "Map title", 500),
        "filename": filename, "format": declared_format,
        "download_path": value["download_path"], "bytes": value["bytes"],
        "sha256": digest.lower(),
        "attribution": text(value["attribution"], "Map attribution", 4000, multiline=True),
        "license": text(value["license"], "Map license", 2000, multiline=True),
        "coverage": coverage, "version": text(value["version"], "Map version", 500),
    }
    if "source" in value:
        result["source"] = text(value["source"], "Map source", 500)
    return result


def validate_route(value) -> dict:
    value = object_fields(
        value, {"id", "title", "mode", "distance_m", "duration_s", "geometry", "steps",
                "start", "end", "source", "attribution", "license", "created_at"},
        "Planned route",
    )
    if value["mode"] != "driving":
        raise ValidationError("This portal supports driving routes only.")
    geometry = value["geometry"]
    if not isinstance(geometry, (list, tuple)) or not 2 <= len(geometry) <= MAX_ROUTE_POINTS:
        raise ValidationError(f"Route geometry must contain 2 to {MAX_ROUTE_POINTS:,} points.")
    points = []
    for point in geometry:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValidationError("Route geometry must use [longitude,latitude] pairs.")
        lat, lon = validate_coordinates((point[1], point[0]))
        points.append([lon, lat])
    raw_steps = value["steps"]
    if not isinstance(raw_steps, (list, tuple)) or len(raw_steps) > MAX_ROUTE_STEPS:
        raise ValidationError(f"Route may contain at most {MAX_ROUTE_STEPS:,} instructions.")
    steps = []
    for step in raw_steps:
        step = object_fields(
            step, {"instruction", "distance_m", "duration_s", "latitude", "longitude"},
            "Route instruction",
        )
        lat, lon = validate_coordinates((step["latitude"], step["longitude"]))
        steps.append({
            "instruction": text(step["instruction"], "Instruction", 1000),
            "distance_m": number(step["distance_m"], "Instruction distance", 0, MAX_DISTANCE_M),
            "duration_s": number(step["duration_s"], "Instruction duration", 0, MAX_DURATION_S),
            "latitude": lat, "longitude": lon,
        })
    route = {
        "id": validate_id(value["id"]), "title": text(value["title"], "Route title", 240),
        "mode": "driving",
        "distance_m": number(value["distance_m"], "Route distance", 0, MAX_DISTANCE_M),
        "duration_s": number(value["duration_s"], "Route duration", 0, MAX_DURATION_S),
        "geometry": points, "steps": steps,
        "start": validate_point(value["start"]), "end": validate_point(value["end"]),
        **_provenance(value),
        "created_at": validate_timestamp(value["created_at"], "Route timestamp"),
    }
    if len(encode_json(route)) > MAX_ROUTE_JSON_BYTES:
        raise ValidationError("Planned route is too large for the saved JSON envelope's 8 MiB limit.")
    return route


def normalize_legacy_status(value) -> dict:
    """Accept the published v1 nested handshake without guessing capabilities."""
    value = object_fields(value, {"version", "name", "capabilities", "providers"}, "Legacy portal status")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValidationError("Unsupported legacy portal protocol version.")
    capabilities = object_fields(value["capabilities"], {"geocoding", "routing"}, "Legacy capabilities")
    if any(type(capabilities[key]) is not bool for key in capabilities):
        raise ValidationError("Legacy portal capabilities must be boolean.")
    providers = value["providers"]
    if not isinstance(providers, dict) or any(capabilities[key] and key not in providers for key in capabilities):
        raise ValidationError("Legacy portal must identify each enabled provider.")
    return validate_status({
        "api_version": 1, "name": value["name"], **capabilities,
        "catalog": True, "route_modes": ["driving"] if capabilities["routing"] else [],
        "providers": providers,
    })


def normalize_legacy_asset(value) -> dict:
    value = object_fields(
        value, {"id", "title", "filename", "kind", "size", "sha256", "coverage", "updated",
                "source", "attribution", "license"}, "Legacy map entry",
    )
    filename = text(value["filename"], "Map filename", 180)
    suffix = PurePosixPath(filename).suffix.lower()
    declared_format = next((kind for kind, extensions in FORMATS.items() if suffix in extensions), None)
    if declared_format is None or value["kind"] != format_family(declared_format):
        raise ValidationError("Legacy map filename and format disagree.")
    return validate_asset({
        "id": value["id"], "title": value["title"], "filename": filename, "format": declared_format,
        "download_path": f"/api/v1/maps/{value['id']}/download", "bytes": value["size"],
        "sha256": value["sha256"], "coverage": value["coverage"], "version": value["updated"],
        "source": value["source"], "attribution": value["attribution"], "license": value["license"],
    })


def normalize_legacy_address(value, received_at: str) -> dict:
    from fieldforge.navigation.places import coordinate

    value = object_fields(value, {"label", "latitude", "longitude", "source", "attribution"},
                          "Legacy address", {"license", "retrieved_at"})
    try:
        latitude = coordinate(value["latitude"], latitude=True)
        longitude = coordinate(value["longitude"], latitude=False)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return validate_search_result({
        **value, "latitude": latitude, "longitude": longitude,
        "license": value.get("license") or LEGACY_LICENSE,
        "retrieved_at": value.get("retrieved_at") or received_at,
    })


def normalize_legacy_route(value, start, end) -> dict:
    import hashlib

    value = object_fields(
        value, {"profile", "coordinates", "distance_m", "duration_s", "source", "attribution",
                "created_at"}, "Legacy planned route", {"license"},
    )
    if value["profile"] != "driving":
        raise ValidationError("Legacy portal returned an unsupported route profile.")
    start_lat, start_lon = validate_coordinates(start)
    end_lat, end_lon = validate_coordinates(end)
    # Legacy responses do not contain instructions or license terms. The stored
    # plan makes these absences explicit instead of inventing navigation data.
    identifier = hashlib.sha256(encode_json(value)).hexdigest()[:24]
    return validate_route({
        "id": "legacy-" + identifier, "title": "Driving route from legacy portal", "mode": "driving",
        "distance_m": value["distance_m"], "duration_s": value["duration_s"],
        "geometry": value["coordinates"], "steps": [],
        "start": {"latitude": start_lat, "longitude": start_lon},
        "end": {"latitude": end_lat, "longitude": end_lon},
        "source": value["source"], "attribution": value["attribution"],
        "license": value.get("license", LEGACY_LICENSE), "created_at": value["created_at"],
    })


def decode_json(data: bytes):
    """Reject oversized, ambiguous, non-finite or excessively nested JSON."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_JSON_BYTES:
        raise ValidationError("Portal JSON exceeds the supported 8 MiB limit or is empty.")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValidationError("Portal JSON contains duplicate fields.")
            result[key] = value
        return result

    def constant(_):
        raise ValidationError("Portal JSON must not contain non-finite numbers.")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ValidationError("Portal returned invalid UTF-8 JSON: " + str(exc)[:160]) from exc
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 12 or count > 500_000:
            raise ValidationError("Portal JSON exceeds the nesting or item limit.")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def encode_json(value) -> bytes:
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValidationError("Cannot encode unsupported portal data.") from exc
    if len(data) > MAX_JSON_BYTES:
        raise ValidationError("Portal JSON exceeds the supported 8 MiB limit.")
    return data
