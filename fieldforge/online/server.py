"""Run the opt-in, self-hosted FieldForge map and route portal.

Start locally with ``python -m fieldforge.online.server --config portal.json``.
Example configuration (paths are relative to the configuration file)::

    {
      "host": "127.0.0.1",
      "port": 8765,
      "catalog_root": "./portal-maps",
      "providers": {
        "geocoding": {
          "url": "https://geocoder.example.org",
          "source": "Our Nominatim database",
          "attribution": "© OpenStreetMap contributors; https://www.openstreetmap.org/copyright",
          "license": "Open Database License (ODbL) 1.0"
        },
        "routing": {
          "url": "https://routing.example.org",
          "source": "Our OSRM driving graph",
          "attribution": "© OpenStreetMap contributors; https://www.openstreetmap.org/copyright",
          "license": "Open Database License (ODbL) 1.0"
        }
      }
    }

Provider URLs must identify services the operator controls or is licensed to use.
There are no public provider defaults. Attribution and license are mandatory for
each configured provider. Set ``allow_loopback_http: true`` only to develop with
an HTTP provider on localhost/127.0.0.1/::1. All other provider URLs require HTTPS.
Nominatim's base URL (or its /search URL) is accepted. Routing uses OSRM's driving
API; the OSRM data must actually be built with a driving profile.

The service binds to loopback by default. For public hosting, terminate HTTPS at
a maintained reverse proxy, set ``public_origin`` to the exact HTTPS portal
origin, and preserve its Host header. Put authentication, abuse/rate controls,
traffic limits, and access-log redaction in that deployment. This small stdlib
service does not provision a domain, provider databases, routing graphs or maps.
Its access/error logs intentionally omit request paths, addresses and coordinates.

Optional settings: ``request_timeout_seconds`` (1-30, default 10),
``max_upstream_bytes`` (1024-8388608, default 8388608). Port 0 is available for
local integration tests. An omitted provider advertises its capability as false;
requests to it return 503. An omitted catalog_root disables the map catalog.
An empty catalog_root directory provides an honest empty catalog.

API v1: GET /api/v1/status, POST /api/v1/search {query}, GET /api/v1/maps,
GET /api/v1/maps/{id}/download, POST /api/v1/routes {start,end,mode:"driving"}.
Searches and route coordinates travel in POST bodies from clients to the portal.
The configured providers receive the queries needed for their respective APIs.
Saved routes are plans with geometry and written steps, not live navigation or
an offline routing engine. See ``fieldforge.online.catalog`` to publish maps.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import ipaddress
import json
import math
import re
import socket
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from http.client import HTTPException, responses
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from fieldforge.online.catalog import MIME_TYPES, Catalog, CatalogError, LegacyCatalog
from fieldforge.online.models import (
    text,
    validate_asset,
    validate_coordinates,
    validate_portal_url,
    validate_query,
    validate_route,
    validate_search_result,
    validate_status,
)

MAX_BODY_BYTES = 4096
MAX_ROUTES = 8
MAX_GEOMETRY_POINTS = 50_000
MAX_STEPS = 10_000
PUBLIC_DEMO_HOSTS = {
    "nominatim.openstreetmap.org", "router.project-osrm.org", "routing.openstreetmap.de",
}


class PortalError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class Busy(PortalError):
    def __init__(self, message="The provider is busy. Please wait before requesting again."):
        super().__init__(429, "busy", message)


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON fields are not supported.")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("JSON numbers must be finite.")


def _json(raw):
    return json.loads(raw, object_pairs_hook=_strict_pairs, parse_constant=_invalid_constant)


def _bounded_text(value, name, maximum, *, multiline=False):
    return text(value, name, maximum, multiline=multiline)


def _number(value, name, minimum, maximum, *, upstream_string=False):
    if upstream_string and isinstance(value, str):
        if len(value) > 80:
            raise ValueError(f"Invalid {name}.")
        try:
            value = float(value)
        except ValueError:
            raise ValueError(f"Invalid {name}.") from None
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be a finite number.")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or not minimum <= value <= maximum:
        raise ValueError(f"{name} is outside the supported range.")
    return float(value)


def _coordinates(value):
    if not isinstance(value, dict) or set(value) != {"latitude", "longitude"}:
        raise ValueError("Coordinates require latitude and longitude numbers.")
    return {
        "latitude": _number(value["latitude"], "latitude", -90, 90),
        "longitude": _number(value["longitude"], "longitude", -180, 180),
    }


def _loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _service_url(value, allow_loopback_http):
    value = _bounded_text(value, "Provider URL", 2048)
    if "\\" in value or "%" in value or any(c.isspace() for c in value):
        raise ValueError("Provider URL must not contain whitespace, percent escapes or backslashes.")
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError:
        raise ValueError("Provider URL has an invalid port.") from None
    if (not parts.hostname or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or parts.scheme not in {"http", "https"}
            or port is not None and not 1 <= port <= 65535):
        raise ValueError("Provider URL must be an HTTP(S) base URL without credentials, query or fragment.")
    hostname = parts.hostname.lower().rstrip(".")
    if hostname in PUBLIC_DEMO_HOSTS or any(hostname.endswith("." + h) for h in PUBLIC_DEMO_HOSTS):
        raise ValueError("Public community demo providers are not supported; configure your own licensed service.")
    if parts.scheme != "https" and not (allow_loopback_http and _loopback(hostname)):
        raise ValueError("Provider URLs require HTTPS; HTTP is allowed only for explicitly enabled loopback development.")
    if any(segment in {".", ".."} for segment in parts.path.split("/")) or "%" in parts.path:
        raise ValueError("Provider base paths must not contain dot segments or percent escapes.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _origin(value):
    value = validate_portal_url(value)
    parts = urlsplit(value)
    if parts.scheme != "https":
        raise ValueError("Public origin must be an exact HTTPS origin, e.g. https://maps.example.org.")
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    suffix = f":{parts.port}" if parts.port not in {None, 443} else ""
    return f"https://{host}{suffix}"


@dataclass(frozen=True)
class ProviderConfig:
    url: str
    attribution: str
    license: str
    source: str
    name: str = ""
    minimum_interval_seconds: float = 0
    cache_ttl_seconds: float = 0


@dataclass(frozen=True)
class PortalConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    catalog_root: Path | None = None
    geocoding: ProviderConfig | None = None
    routing: ProviderConfig | None = None
    allow_loopback_http: bool = False
    public_origin: str | None = None
    request_timeout_seconds: float = 10.0
    max_upstream_bytes: int = 8 * 1024**2
    name: str = "FieldForge Maps"
    legacy_maps: tuple | None = None
    legacy_root: Path | None = None

    @classmethod
    def from_dict(cls, value, *, base_dir: Path | None = None):
        if not isinstance(value, dict):
            raise ValueError("Portal configuration must be a JSON object.")
        if "version" in value:
            return cls._legacy(value, base_dir=base_dir)
        known = {"host", "port", "catalog_root", "providers", "allow_loopback_http",
                 "public_origin", "request_timeout_seconds", "max_upstream_bytes", "name"}
        if set(value) - known:
            raise ValueError("Portal configuration contains unsupported fields.")
        host = _bounded_text(value.get("host", "127.0.0.1"), "host", 253)
        if not (host == "localhost" or re.fullmatch(r"[A-Za-z0-9_.:-]+", host, re.ASCII)):
            raise ValueError("host must be a bind hostname or IP address.")
        port = value.get("port", 8765)
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port must be an integer from 0 to 65535.")
        allow = value.get("allow_loopback_http", False)
        if type(allow) is not bool:
            raise ValueError("allow_loopback_http must be a boolean.")
        upstream_limit = value.get("max_upstream_bytes", 8 * 1024**2)
        if type(upstream_limit) is not int or not 1024 <= upstream_limit <= 8 * 1024**2:
            raise ValueError("max_upstream_bytes must be 1024 through 8388608.")
        timeout = _number(value.get("request_timeout_seconds", 10), "request timeout", 1, 30)
        root = value.get("catalog_root")
        if root is not None:
            root = Path(_bounded_text(root, "catalog_root", 4096)).expanduser()
            if not root.is_absolute():
                root = (base_dir or Path.cwd()) / root
            root = root.resolve()
        providers = value.get("providers", {})
        if not isinstance(providers, dict) or set(providers) - {"geocoding", "routing"}:
            raise ValueError("providers may contain only geocoding and routing configuration.")
        parsed = {}
        for kind, default_source in (("geocoding", "Nominatim"), ("routing", "OSRM driving")):
            provider = providers.get(kind)
            if provider is None:
                parsed[kind] = None
                continue
            if not isinstance(provider, dict) or set(provider) - {
                "url", "source", "name", "attribution", "license", "minimum_interval_seconds", "cache_ttl_seconds",
            }:
                raise ValueError(f"Invalid {kind} provider configuration.")
            parsed[kind] = ProviderConfig(
                url=_service_url(provider.get("url"), allow),
                attribution=_bounded_text(provider.get("attribution"), "Provider attribution", 4000, multiline=True),
                license=_bounded_text(provider.get("license"), "Provider license", 2000, multiline=True),
                source=_bounded_text(provider.get("source", default_source), "Provider source", 500),
                name=_bounded_text(provider.get("name", provider.get("source", default_source)), "Provider name", 500),
                minimum_interval_seconds=_number(provider.get("minimum_interval_seconds", 0), "Provider request interval", 0, 3600),
                cache_ttl_seconds=_number(provider.get("cache_ttl_seconds", 0), "Provider cache lifetime", 0, 3600),
            )
        public_origin = _origin(value["public_origin"]) if value.get("public_origin") is not None else None
        return cls(host=host, port=port, catalog_root=root, geocoding=parsed["geocoding"],
                   routing=parsed["routing"], allow_loopback_http=allow, public_origin=public_origin,
                   request_timeout_seconds=timeout, max_upstream_bytes=upstream_limit,
                   name=_bounded_text(value.get("name", "FieldForge Maps"), "Portal name", 500))

    @classmethod
    def _legacy(cls, value, *, base_dir=None):
        known = {"version", "name", "asset_folder", "geocoder", "router", "maps", "host", "port",
                 "public_origin", "allow_loopback_http", "request_timeout_seconds", "max_upstream_bytes"}
        if type(value.get("version")) is not int or value["version"] != 1 or set(value) - known:
            raise ValueError("Legacy portal configuration must use version 1 and supported fields.")
        providers = {}
        for legacy, kind in (("geocoder", "geocoding"), ("router", "routing")):
            item = value.get(legacy)
            if item is None:
                continue
            if not isinstance(item, dict):
                raise ValueError(f"Legacy {legacy} configuration must be an object.")
            # Validate the destination first; known public demo endpoints remain blocked.
            _service_url(item.get("url"), True)
            if not item.get("license"):
                raise ValueError(f"Legacy {legacy} needs an explicit license field. Add the actual provider/data license; it cannot be inferred.")
            if set(item) - {"url", "name", "source", "attribution", "license", "minimum_interval_seconds", "cache_ttl_seconds"}:
                raise ValueError(f"Legacy {legacy} contains unsupported settings.")
            providers[kind] = {
                **item, "source": item.get("source", item.get("name")),
                "minimum_interval_seconds": item.get("minimum_interval_seconds", 1.1),
                "cache_ttl_seconds": item.get("cache_ttl_seconds", 600),
            }
        modern = {key: value[key] for key in known & value.keys()
                  if key in {"name", "host", "port", "public_origin", "request_timeout_seconds", "max_upstream_bytes"}}
        modern.update(providers=providers, allow_loopback_http=value.get("allow_loopback_http", True))
        config = cls.from_dict(modern, base_dir=base_dir)
        entries = value.get("maps", [])
        if not isinstance(entries, list) or len(entries) > 500:
            raise ValueError("Legacy inline catalogs are limited to 500 map files.")
        folder = Path(_bounded_text(value.get("asset_folder", "maps"), "Legacy asset folder", 4096)).expanduser()
        if not folder.is_absolute():
            folder = (base_dir or Path.cwd()) / folder
        return replace(config, legacy_maps=tuple(copy.deepcopy(entries)), legacy_root=folder.resolve())


def load_config(path: str | Path) -> PortalConfig:
    path = Path(path).expanduser().resolve()
    if path.stat().st_size > 1024**2:
        raise ValueError("Portal configuration exceeds 1 MiB.")
    with path.open("rb") as stream:
        raw = stream.read(1024**2 + 1)
    if len(raw) > 1024**2:
        raise ValueError("Portal configuration exceeds 1 MiB.")
    return PortalConfig.from_dict(_json(raw), base_dir=path.parent)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise PortalError(502, "upstream_redirect", "Configured provider redirected the request; update its exact URL.")


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def portal_assets():
    """Read the one primary browser UI, including compatibility asset URLs."""
    page = Path(__file__).with_name("portal.html").read_bytes()
    bodies, hashes = {}, {}
    for tag in ("script", "style"):
        sections = re.findall(rb"<" + tag.encode() + rb">(.*?)</" + tag.encode() + rb">", page, flags=re.S)
        bodies[tag] = b"\n".join(sections)
        hashes[tag] = " ".join("'sha256-" + base64.b64encode(hashlib.sha256(body).digest()).decode() + "'"
                               for body in sections)
    policy = ("default-src 'none'; script-src 'self' " + hashes["script"]
              + "; style-src 'self' " + hashes["style"]
              + "; connect-src 'self'; img-src 'self' blob:; base-uri 'none'; object-src 'none';"
              " frame-ancestors 'none'; form-action 'self'")
    return {
        "/": (page, "text/html; charset=utf-8"),
        "/portal.js": (bodies["script"], "text/javascript; charset=utf-8"),
        "/portal.css": (bodies["style"], "text/css; charset=utf-8"),
    }, policy


@dataclass
class PortalResponse:
    """One bounded JSON/static or streaming map response for HTTP and WSGI."""

    status: int
    body: bytes = b""
    content_type: str = "application/json; charset=utf-8"
    stream: object | None = None
    length: int | None = None
    attachment: str | None = None
    etag: str | None = None
    extra_headers: tuple = ()

    @classmethod
    def json(cls, status, value):
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > 8 * 1024**2:
            raw = b'{"error":{"code":"response_limit","message":"Portal response exceeds the supported limit."}}'
            status = 502
        return cls(status, raw)

    @classmethod
    def error(cls, error):
        result = cls.json(error.status, {"error": {"code": error.code, "message": error.message}})
        if error.status == 429:
            result.extra_headers = (("Retry-After", "2"),)
        return result

    def headers(self, policy):
        result = [
            ("Content-Type", self.content_type),
            ("Content-Length", str(len(self.body) if self.length is None else self.length)),
            ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer"),
            ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"),
            ("Content-Security-Policy", policy),
            ("Permissions-Policy", "geolocation=(), camera=(), microphone=()"),
        ]
        if self.attachment:
            result.append(("Content-Disposition", f'attachment; filename="{self.attachment}"'))
        if self.etag:
            result.append(("ETag", '"' + self.etag + '"'))
        return result + list(self.extra_headers)

    def __iter__(self):
        if self.stream is None:
            yield self.body
            return
        try:
            remaining = self.length
            while remaining:
                chunk = self.stream.read(min(128 * 1024, remaining))
                if not chunk:
                    raise OSError("Published map changed during download.")
                remaining -= len(chunk)
                yield chunk
        finally:
            self.close()

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


def _map_response(asset, stream, ranges=(), if_ranges=()):
    """Serve one byte range; unsupported range units/lists receive the full map.

    RFC 9110 sections 13.1.5 and 14: only an exact strong If-Range match
    authorizes a partial response. Dates/weak or changed tags fall back to 200.
    """
    size = asset["bytes"]
    response = PortalResponse(200, content_type=MIME_TYPES[asset["format"]], stream=stream,
                              length=size, attachment=asset["filename"], etag=asset["sha256"],
                              extra_headers=(("Accept-Ranges", "bytes"),))
    try:
        if len(ranges) > 1 or len(if_ranges) > 1 or any(len(value) > 200 for value in (*ranges, *if_ranges)):
            raise PortalError(400, "invalid_range", "Supply at most one bounded Range and If-Range header.")
        if not ranges or (if_ranges and if_ranges[0] != '"' + asset["sha256"] + '"'):
            return response
        value = ranges[0].strip()
        if "=" in value and (value.split("=", 1)[0].lower() != "bytes" or "," in value):
            return response
        match = re.fullmatch(r"bytes=([0-9]{0,20})-([0-9]{0,20})", value, re.IGNORECASE)
        if match and any(match.groups()):
            first, last = match.groups()
            if first:
                start, end = int(first), min(int(last), size - 1) if last else size - 1
            else:
                start, end = max(0, size - int(last)), size - 1
            if 0 <= start <= end < size:
                stream.seek(start)
                response.status, response.length = 206, end - start + 1
                response.extra_headers += (("Content-Range", f"bytes {start}-{end}/{size}"),)
                return response
        response.close()
        response = PortalResponse.error(PortalError(416, "invalid_range", "The requested map byte range is not satisfiable."))
        response.etag = asset["sha256"]
        response.extra_headers = (("Accept-Ranges", "bytes"), ("Content-Range", f"bytes */{size}"))
        return response
    except BaseException:
        response.close()
        raise


def _check_request(config, port, path, hosts, origins=(), *, fetch_site=None, transfer_encoding=False):
    if len(hosts) != 1:
        raise PortalError(400, "invalid_host", "A single valid Host header is required.")
    host = hosts[0].lower()
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    bind_host = config.host.lower()
    if bind_host not in {"0.0.0.0", "::"}:
        allowed.add(f"[{bind_host}]:{port}" if ":" in bind_host else f"{bind_host}:{port}")
    if port == 80:
        allowed.update({"127.0.0.1", "localhost", "[::1]"})
        if bind_host not in {"0.0.0.0", "::"}:
            allowed.add(bind_host)
    if config.public_origin:
        allowed.add(urlsplit(config.public_origin).netloc.lower())
    if host not in allowed:
        raise PortalError(403, "invalid_host", "Host is not configured for this portal.")
    if len(origins) > 1:
        raise PortalError(403, "cross_origin", "Cross-origin requests are not allowed.")
    if origins:
        expected = config.public_origin if config.public_origin and host == urlsplit(config.public_origin).netloc.lower() else "http://" + host
        if origins[0].rstrip("/") != expected:
            raise PortalError(403, "cross_origin", "Cross-origin requests are not allowed.")
    if fetch_site == "cross-site":
        raise PortalError(403, "cross_origin", "Cross-origin requests are not allowed.")
    if transfer_encoding:
        raise PortalError(400, "invalid_request", "Transfer-encoded request bodies are unsupported.")
    if (not path.startswith("/") or path.startswith("//")
            or "?" in path or "#" in path or "\\" in path):
        raise PortalError(400, "invalid_request", "Use the portal API paths without URL queries.")


def _request_body(stream, lengths, types, *, maximum=MAX_BODY_BYTES):
    if len(lengths) != 1 or not lengths[0].isdecimal() or len(lengths[0]) > 12:
        raise PortalError(411, "length_required", "A single Content-Length is required.")
    size = int(lengths[0])
    if not 1 <= size <= maximum:
        raise PortalError(413, "request_limit", f"Request body must be between 1 and {maximum:,} bytes.")
    if len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != "application/json":
        raise PortalError(415, "json_required", "Send an application/json request body.")
    try:
        raw = stream.read(size)
        if len(raw) != size:
            raise ValueError("Incomplete request body.")
        value = _json(raw)
        if not isinstance(value, dict):
            raise ValueError("Request body must be an object.")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise PortalError(400, "invalid_json", "Request body must be valid finite JSON without duplicate fields.") from None
    except (socket.timeout, TimeoutError):
        raise PortalError(408, "request_timeout", "Request body was not received in time.") from None


def _legacy_route(route):
    """Project a verified route onto the original geometry-only wire format."""
    return {"profile": route["mode"], "coordinates": route["geometry"],
            **{key: route[key] for key in ("distance_m", "duration_s", "source", "attribution", "license", "created_at")}}


def _location(pair):
    if not isinstance(pair, list) or len(pair) != 2:
        raise ValueError("Invalid provider coordinate pair.")
    return [_number(pair[0], "longitude", -180, 180), _number(pair[1], "latitude", -90, 90)]


def _maneuver_instruction(step):
    maneuver = step.get("maneuver")
    if not isinstance(maneuver, dict):
        raise ValueError("Missing maneuver.")
    kind = _bounded_text(maneuver.get("type"), "maneuver type", 100)
    modifier = maneuver.get("modifier", "straight")
    permitted = {"uturn", "sharp right", "right", "slight right", "straight", "slight left", "left", "sharp left"}
    if modifier not in permitted:
        raise ValueError("Invalid maneuver modifier.")
    name = step.get("name", "")
    if name:
        name = _bounded_text(name, "road name", 500)
    elif step.get("ref"):
        name = _bounded_text(step["ref"], "road reference", 500)
    road = f" onto {name}" if name else ""
    on_road = f" on {name}" if name else ""
    direction = {
        "straight": "straight", "uturn": "back", "sharp right": "sharply right",
        "sharp left": "sharply left", "slight right": "slightly right", "slight left": "slightly left",
        "right": "right", "left": "left",
    }[modifier]
    if kind == "depart":
        bearing = maneuver.get("bearing_after")
        if bearing is None:
            return f"Start{on_road}."
        bearing = _number(bearing, "departure bearing", 0, 360)
        cardinal = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")
        return f"Head {cardinal[int((bearing + 22.5) // 45) % 8]}{on_road}."
    if kind == "arrive":
        side = f" on the {modifier}" if modifier in {"left", "right"} else ""
        return f"Arrive at your destination{side}."
    if kind in {"roundabout", "rotary", "roundabout turn"}:
        exit_number = maneuver.get("exit")
        if exit_number is not None and (type(exit_number) is not int or not 1 <= exit_number <= 100):
            raise ValueError("Invalid roundabout exit.")
        exit_text = f" and take exit {exit_number}" if exit_number is not None else ""
        return f"Enter the roundabout{exit_text}{road}."
    if kind in {"exit roundabout", "exit rotary"}:
        return f"Exit the roundabout{road}."
    if modifier == "uturn":
        return f"Make a U-turn{road}."
    if kind == "turn":
        return f"Turn {direction}{road}." if modifier != "straight" else f"Continue straight{on_road}."
    if kind == "fork":
        return f"Keep {direction} at the fork{road}."
    if kind == "merge":
        return f"Merge {direction}{road}."
    if kind in {"on ramp", "ramp", "off ramp"}:
        label = "exit ramp" if kind == "off ramp" else "ramp"
        return f"Take the {label} {direction}{road}."
    if kind == "end of road":
        return f"At the end of the road, turn {direction}{road}."
    if kind == "new name":
        return f"Continue{on_road}."
    return f"Continue {direction}{on_road}."


class ProviderGate:
    """One-process nonblocking request gate with optional bounded memory cache."""

    def __init__(self, provider):
        self.provider = provider
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.next_request = 0.0

    def call(self, key, operation):
        if not self.lock.acquire(blocking=False):
            raise Busy("Another request to this provider is already in progress.")
        try:
            now = time.monotonic()
            key = hashlib.sha256(key.encode("utf-8")).hexdigest()
            ttl = self.provider.cache_ttl_seconds
            # Expired records are removed even when a different address is requested.
            for old_key in list(self.cache):
                if now - self.cache[old_key][0] >= ttl:
                    self.cache_bytes -= self.cache.pop(old_key)[2]
            if ttl and key in self.cache:
                self.cache.move_to_end(key)
                return copy.deepcopy(self.cache[key][1])
            if now < self.next_request:
                raise Busy()
            self.next_request = now + self.provider.minimum_interval_seconds
            result = operation()
            if ttl:
                size = len(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))
                if size <= 16 * 1024**2:
                    self.cache[key] = (time.monotonic(), copy.deepcopy(result), size)
                    self.cache_bytes += size
                    while len(self.cache) > 128 or self.cache_bytes > 16 * 1024**2:
                        self.cache_bytes -= self.cache.popitem(last=False)[1][2]
            return result
        finally:
            self.lock.release()


@dataclass
class PortalApplication:
    config: PortalConfig
    catalog: Catalog | LegacyCatalog | None = field(init=False)
    assets: dict = field(init=False, repr=False)
    csp: str = field(init=False, repr=False)
    _upstream_slots: threading.BoundedSemaphore = field(init=False, repr=False)
    _gates: dict = field(init=False, repr=False)

    def __post_init__(self):
        self.assets, self.csp = portal_assets()
        if self.config.legacy_maps is not None:
            self.catalog = LegacyCatalog(list(self.config.legacy_maps), self.config.legacy_root or Path.cwd())
        else:
            self.catalog = Catalog(self.config.catalog_root) if self.config.catalog_root is not None else None
        self._upstream_slots = threading.BoundedSemaphore(4)
        self._gates = {kind: ProviderGate(provider) for kind, provider in (
            ("geocoding", self.config.geocoding), ("routing", self.config.routing),
        ) if provider is not None}

    def status(self):
        return validate_status({
            "api_version": 1, "name": self.config.name,
            "geocoding": self.config.geocoding is not None,
            "routing": self.config.routing is not None,
            "catalog": self.catalog is not None,
            "route_modes": ["driving"] if self.config.routing is not None else [],
        })

    def wire_status(self):
        result = self.status()
        result.update(version=1, capabilities={key: result[key] for key in ("geocoding", "routing")},
                      providers={kind: {"name": provider.name or provider.source,
                                        "source": provider.source, "attribution": provider.attribution,
                                        "license": provider.license}
                                 for kind, provider in (("geocoding", self.config.geocoding),
                                                        ("routing", self.config.routing)) if provider is not None})
        validate_status(result)  # Reject conflicting aliases before either protocol sees them.
        return result

    @staticmethod
    def wire_asset(value):
        result = validate_asset(value)
        result.update(kind="mbtiles" if result["format"] == "mbtiles" else "image",
                      size=result["bytes"], updated=result["version"])
        result.setdefault("source", "Source not supplied; served by FieldForge")
        validate_asset(result)
        return result

    def dispatch(self, method, path, payload=None, *, range_headers=(), if_range_headers=()):
        """Shared endpoint behavior for native HTTP and WSGI hosting."""
        if method == "POST":
            if path == "/api/v1/search":
                if set(payload) != {"query"}:
                    raise PortalError(400, "invalid_request", "Address search requires a query field.")
                return PortalResponse.json(200, self.search(payload["query"]))
            if path == "/api/v1/routes":
                if set(payload) != {"start", "end", "mode"}:
                    raise PortalError(400, "invalid_request", "Route planning requires start, end and mode fields.")
                return PortalResponse.json(200, self.routes(payload["start"], payload["end"], payload["mode"]))
            if path == "/api/v1/route":
                if set(payload) != {"start", "end"}:
                    raise PortalError(400, "invalid_request", "Route planning requires start and end coordinate pairs.")
                try:
                    start, end = (dict(zip(("latitude", "longitude"), validate_coordinates(payload[key])))
                                  for key in ("start", "end"))
                except ValueError as exc:
                    raise PortalError(400, "invalid_request", str(exc)) from None
                routes = self.routes(start, end)["routes"]
                if not routes:
                    raise PortalError(404, "no_route", "No driving route was returned for those coordinates.")
                return PortalResponse.json(200, _legacy_route(routes[0]))
            raise PortalError(404, "not_found", "Portal endpoint not found.")
        if method != "GET":
            raise PortalError(405, "method_not_allowed", "Use GET for maps/status or POST for search/routes.")
        if path in self.assets:
            data, content_type = self.assets[path]
            return PortalResponse(200, data, content_type)
        if path == "/api/v1/status":
            return PortalResponse.json(200, self.wire_status())
        if path == "/api/v1/maps":
            if self.catalog is None:
                raise PortalError(503, "not_configured", "Map downloads are not configured on this portal.")
            return PortalResponse.json(200, {"maps": [self.wire_asset(value) for value in self.catalog.assets()]})
        match = re.fullmatch(r"/api/v1/maps/([A-Za-z0-9][A-Za-z0-9_-]{0,79})/(?:download|file)", path, re.ASCII)
        if match:
            if self.catalog is None:
                raise PortalError(503, "not_configured", "Map downloads are not configured on this portal.")
            try:
                asset, stream = self.catalog.open_asset(match[1])
            except KeyError:
                raise PortalError(404, "not_found", "Map not found in this portal catalog.") from None
            return _map_response(asset, stream, range_headers, if_range_headers)
        raise PortalError(404, "not_found", "Portal endpoint not found.")

    def _read_provider_json(self, response, deadline, *, maximum=None):
        """Read a bounded response, including OSRM's documented HTTP 400 body."""
        maximum = min(maximum or self.config.max_upstream_bytes, self.config.max_upstream_bytes)
        if response.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
            raise PortalError(502, "upstream_error", "Provider returned an unsupported encoded response.")
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type not in {"application/json", "application/geo+json"}:
            raise PortalError(502, "upstream_error", "Provider did not return JSON.")
        length = response.headers.get("Content-Length")
        if length is not None and (not length.isdecimal() or int(length) > maximum):
            raise PortalError(502, "upstream_limit", "Provider response exceeds the supported download limit.")
        chunks, total = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PortalError(504, "upstream_timeout", "Configured provider took too long to respond.")
            # HTTPError wraps an HTTPResponse; both paths use its underlying socket.
            buffered = getattr(response, "fp", None)
            if buffered is not None and not hasattr(buffered, "raw"):
                buffered = getattr(buffered, "fp", None)
            transport = getattr(getattr(buffered, "raw", None), "_sock", None)
            if transport is not None:
                transport.settimeout(remaining)
            reader = getattr(response, "read1", response.read)
            chunk = reader(min(64 * 1024, maximum + 1 - total))
            if time.monotonic() > deadline:
                raise PortalError(504, "upstream_timeout", "Configured provider took too long to respond.")
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise PortalError(502, "upstream_limit", "Provider response exceeds the supported download limit.")
            chunks.append(chunk)
        if length is not None and total != int(length):
            raise PortalError(502, "upstream_error", "Provider response was incomplete.")
        return _json(b"".join(chunks))

    def _get_json(self, url, *, allow_no_route=False):
        if not self._upstream_slots.acquire(blocking=False):
            raise PortalError(503, "busy", "The provider is busy. Please retry shortly.")
        deadline = time.monotonic() + self.config.request_timeout_seconds
        try:
            opener = build_opener(ProxyHandler({}), _NoRedirect())
            request = Request(url, headers={"Accept": "application/json", "Accept-Encoding": "identity",
                                           "User-Agent": "FieldForge-Portal/1"})
            try:
                response = opener.open(request, timeout=self.config.request_timeout_seconds)
            except HTTPError as exc:
                with exc:
                    if not allow_no_route or exc.code != 400:
                        raise PortalError(502, "upstream_error", "Configured provider is unavailable or returned an invalid response.") from None
                    document = self._read_provider_json(exc, deadline, maximum=64 * 1024)
                if (not isinstance(document, dict) or set(document) - {"code", "message", "routes"}
                        or document.get("code") not in ("NoRoute", "NoSegment")
                        or document.get("routes", []) != []):
                    raise PortalError(502, "upstream_error", "Configured provider is unavailable or returned an invalid response.")
                if "message" in document:
                    _bounded_text(document["message"], "OSRM error message", 1000)
                # Preserve only the known outcome; never expose a provider diagnostic body.
                return {"code": document["code"]}
            with response:
                if response.status != 200:
                    raise PortalError(502, "upstream_error", "Configured provider could not complete the request.")
                return self._read_provider_json(response, deadline)
        except PortalError:
            raise
        except (socket.timeout, TimeoutError):
            raise PortalError(504, "upstream_timeout", "Configured provider took too long to respond.") from None
        except HTTPError as exc:
            exc.close()
            raise PortalError(502, "upstream_error", "Configured provider is unavailable or returned an invalid response.") from None
        except (URLError, OSError, HTTPException, ValueError, RecursionError):
            # Do not expose provider URLs, queries, coordinates or diagnostic response bodies.
            raise PortalError(502, "upstream_error", "Configured provider is unavailable or returned an invalid response.") from None
        finally:
            self._upstream_slots.release()

    def search(self, query):
        try:
            query = validate_query(query)
        except ValueError as exc:
            raise PortalError(400, "invalid_request", str(exc)) from None
        provider = self.config.geocoding
        if provider is None:
            raise PortalError(503, "not_configured", "Address search is not configured on this portal.")
        return self._gates["geocoding"].call(query, lambda: self._search(provider, query))

    def _search(self, provider, query):
        endpoint = provider.url if provider.url.endswith("/search") else provider.url + "/search"
        document = self._get_json(endpoint + "?" + urlencode({
            "q": query, "format": "jsonv2", "addressdetails": "1", "limit": "5",
        }))
        try:
            if not isinstance(document, list) or len(document) > 20:
                raise ValueError("Invalid search results.")
            results, retrieved = [], _stamp()
            for item in document:
                if not isinstance(item, dict):
                    raise ValueError("Invalid search result.")
                results.append(validate_search_result({
                    "label": _bounded_text(item.get("display_name"), "result label", 1000),
                    "latitude": _number(item.get("lat"), "latitude", -90, 90, upstream_string=True),
                    "longitude": _number(item.get("lon"), "longitude", -180, 180, upstream_string=True),
                    "source": provider.source, "attribution": provider.attribution,
                    "license": provider.license, "retrieved_at": retrieved,
                }))
            return {"results": results}
        except (ValueError, TypeError, OverflowError):
            raise PortalError(502, "invalid_provider_data", "Address provider returned invalid results.") from None

    def routes(self, start, end, mode="driving"):
        try:
            start, end = _coordinates(start), _coordinates(end)
            if mode != "driving":
                raise ValueError("This portal supports driving routes only.")
        except (ValueError, TypeError) as exc:
            raise PortalError(400, "invalid_request", str(exc)) from None
        provider = self.config.routing
        if provider is None:
            raise PortalError(503, "not_configured", "Route planning is not configured on this portal.")
        key = json.dumps({"start": start, "end": end, "mode": mode}, sort_keys=True, allow_nan=False)
        return self._gates["routing"].call(key, lambda: self._routes(provider, start, end))

    def _routes(self, provider, start, end):
        positions = (f"{start['longitude']:.8f},{start['latitude']:.8f};"
                     f"{end['longitude']:.8f},{end['latitude']:.8f}")
        endpoint = provider.url + "/route/v1/driving/" + positions
        document = self._get_json(endpoint + "?" + urlencode({
            "alternatives": "true", "steps": "true", "geometries": "geojson", "overview": "full",
        }), allow_no_route=True)
        try:
            if not isinstance(document, dict):
                raise ValueError("Invalid route response.")
            if document.get("code") in {"NoRoute", "NoSegment"}:
                return {"routes": []}
            candidates = document.get("routes")
            if (document.get("code") != "Ok" or not isinstance(candidates, list)
                    or not 1 <= len(candidates) <= MAX_ROUTES):
                raise ValueError("Invalid route response.")
            routes, created = [], _stamp()
            for index, candidate in enumerate(candidates):
                if not isinstance(candidate, dict):
                    raise ValueError("Invalid route.")
                shape = candidate.get("geometry")
                if not isinstance(shape, dict) or shape.get("type") != "LineString":
                    raise ValueError("Route geometry is missing.")
                geometry = shape.get("coordinates")
                if not isinstance(geometry, list) or not 2 <= len(geometry) <= MAX_GEOMETRY_POINTS:
                    raise ValueError("Invalid route geometry size.")
                geometry = [_location(pair) for pair in geometry]
                legs = candidate.get("legs")
                if not isinstance(legs, list) or not 1 <= len(legs) <= 100:
                    raise ValueError("Route legs are missing.")
                steps = []
                for leg in legs:
                    if not isinstance(leg, dict) or not isinstance(leg.get("steps"), list) or not leg["steps"]:
                        raise ValueError("Written route steps are missing.")
                    if len(steps) + len(leg["steps"]) > MAX_STEPS:
                        raise ValueError("Too many route steps.")
                    for step in leg["steps"]:
                        if not isinstance(step, dict):
                            raise ValueError("Invalid route step.")
                        instruction = _maneuver_instruction(step)
                        longitude, latitude = _location(step["maneuver"].get("location"))
                        steps.append({
                            "instruction": instruction,
                            "distance_m": _number(step.get("distance"), "step distance", 0, 100_000_000),
                            "duration_s": _number(step.get("duration"), "step duration", 0, 365 * 86400),
                            "latitude": latitude, "longitude": longitude,
                        })
                routes.append(validate_route({
                    "id": "route-" + uuid.uuid4().hex,
                    "title": "Driving route" if index == 0 else f"Driving alternative {index + 1}",
                    "mode": "driving",
                    "distance_m": _number(candidate.get("distance"), "route distance", 0, 100_000_000),
                    "duration_s": _number(candidate.get("duration"), "route duration", 0, 365 * 86400),
                    "geometry": geometry, "steps": steps, "start": start, "end": end,
                    "source": provider.source, "attribution": provider.attribution,
                    "license": provider.license, "created_at": created,
                }))
            return {"routes": routes}
        except (ValueError, TypeError, KeyError, OverflowError):
            raise PortalError(502, "invalid_provider_data", "Routing provider returned invalid or incomplete route data.") from None


class PortalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, app):
        self.app = app
        self._request_slots = threading.BoundedSemaphore(16)
        self.page = app.assets["/"][0]
        self.csp = app.csp
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, PortalHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(15)
        return connection, address

    def process_request(self, request, client_address):
        if not self._request_slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()

    def handle_error(self, request, client_address):
        # Base implementation prints full tracebacks which can expose request values.
        return


class PortalHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FieldForgePortal/1"
    sys_version = ""

    def log_message(self, format, *args):
        return

    def _send(self, response):
        try:
            self.send_response(response.status)
            for name, value in response.headers(self.server.csp):
                self.send_header(name, value)
            self.end_headers()
            self._response_started = True
            if self.command != "HEAD":
                for block in response:
                    self.wfile.write(block)
        finally:
            response.close()

    def _dispatch(self):
        app = self.server.app
        _check_request(app.config, self.server.server_address[1], self.path,
                       self.headers.get_all("Host", []), self.headers.get_all("Origin", []),
                       fetch_site=self.headers.get("Sec-Fetch-Site"),
                       transfer_encoding=bool(self.headers.get_all("Transfer-Encoding")))
        payload = None
        if self.command == "POST":
            payload = _request_body(self.rfile, self.headers.get_all("Content-Length", []),
                                    self.headers.get_all("Content-Type", []))
        elif self.command == "GET" and self.headers.get_all("Content-Length", []) not in ([], ["0"]):
            raise PortalError(400, "invalid_request", "GET request bodies are unsupported.")
        self._send(app.dispatch(self.command, self.path, payload,
                                range_headers=self.headers.get_all("Range", []),
                                if_range_headers=self.headers.get_all("If-Range", [])))

    def _handle(self):
        self._response_started = False
        try:
            self._dispatch()
        except PortalError as exc:
            # Closing also discards any rejected, unread body before another request.
            self.close_connection = True
            if not self._response_started:
                self._send(PortalResponse.error(exc))
        except CatalogError:
            self.close_connection = True
            if not self._response_started:
                self._send(PortalResponse.error(PortalError(503, "catalog_unavailable", "Published map catalog is unavailable or invalid.")))
        except (BrokenPipeError, ConnectionResetError, socket.timeout, TimeoutError):
            self.close_connection = True
        except OSError:
            self.close_connection = True
            if not self._response_started:
                self._send(PortalResponse.error(PortalError(503, "unavailable", "Portal storage is temporarily unavailable.")))

    do_GET = do_POST = do_OPTIONS = do_HEAD = do_PUT = do_DELETE = do_PATCH = _handle


class WSGIApplication:
    """PEP 3333 adapter over the same dispatch, validators and provider clients.

    Configure public_origin for a TLS reverse proxy and preserve Host. The WSGI
    host must bound incoming body/header reads, concurrent requests and runtime;
    the native development server supplies its own bounded socket/worker limits.
    """

    def __init__(self, config):
        self.app = config if isinstance(config, PortalApplication) else PortalApplication(config)

    def __call__(self, environ, start_response):
        response = None
        try:
            path = environ.get("PATH_INFO", "")
            if environ.get("QUERY_STRING"):
                path += "?" + environ["QUERY_STRING"]
            if environ.get("SCRIPT_NAME"):
                raise PortalError(400, "invalid_request", "Host this portal at its configured origin root.")
            try:
                port = int(environ.get("SERVER_PORT", ""))
                if not 1 <= port <= 65535:
                    raise ValueError("Invalid server port.")
            except (TypeError, ValueError):
                raise PortalError(400, "invalid_host", "WSGI server must supply a valid local server port.") from None
            _check_request(self.app.config, port, path,
                           [environ["HTTP_HOST"]] if "HTTP_HOST" in environ else [],
                           [environ["HTTP_ORIGIN"]] if "HTTP_ORIGIN" in environ else [],
                           fetch_site=environ.get("HTTP_SEC_FETCH_SITE"),
                           transfer_encoding="HTTP_TRANSFER_ENCODING" in environ)
            method, payload = environ.get("REQUEST_METHOD", "GET"), None
            if method == "POST":
                payload = _request_body(environ["wsgi.input"],
                                        [environ["CONTENT_LENGTH"]] if "CONTENT_LENGTH" in environ else [],
                                        [environ["CONTENT_TYPE"]] if "CONTENT_TYPE" in environ else [])
            elif method == "GET" and environ.get("CONTENT_LENGTH", "") not in ("", "0"):
                raise PortalError(400, "invalid_request", "GET request bodies are unsupported.")
            response = self.app.dispatch(method, path, payload,
                                         range_headers=[environ["HTTP_RANGE"]] if "HTTP_RANGE" in environ else [],
                                         if_range_headers=[environ["HTTP_IF_RANGE"]] if "HTTP_IF_RANGE" in environ else [])
        except PortalError as exc:
            response = PortalResponse.error(exc)
        except CatalogError:
            response = PortalResponse.error(PortalError(503, "catalog_unavailable", "Published map catalog is unavailable or invalid."))
        except OSError:
            response = PortalResponse.error(PortalError(503, "unavailable", "Portal storage is temporarily unavailable."))
        try:
            start_response(f"{response.status} {responses.get(response.status, 'Unknown')}", response.headers(self.app.csp))
        except Exception:
            response.close()
            raise
        if environ.get("REQUEST_METHOD") == "HEAD":
            response.close()
            return []
        return response


def create_app(config_path):
    """Create a WSGI app from either supported config schema without binding a socket."""
    return WSGIApplication(load_config(config_path))


def make_server(config: PortalConfig) -> PortalHTTPServer:
    return PortalHTTPServer((config.host, config.port), PortalApplication(config))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, help="Portal JSON configuration; omission starts a local unconfigured portal.")
    parser.add_argument("--port", type=int, help="Override the configured listening port (0-65535).")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config) if args.config else PortalConfig()
        if args.port is not None:
            if not 0 <= args.port <= 65535:
                raise ValueError("port must be an integer from 0 to 65535.")
            config = replace(config, port=args.port)
        server = make_server(config)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Portal configuration failed: {exc}\n")
    host, port = server.server_address[:2]
    display_host = f"[{host}]" if ":" in host else host
    print(f"FieldForge Maps is listening on http://{display_host}:{port}", flush=True)
    print("Provider and map availability are shown in the portal. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
