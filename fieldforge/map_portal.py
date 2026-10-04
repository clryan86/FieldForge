"""Operator-configured WSGI map portal. No public provider is selected by default.

Run ``python -m fieldforge.map_portal --config portal.json`` for local development.
Deploy ``create_app(config_path)`` behind a TLS reverse proxy / WSGI server.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import time
import urllib.parse
from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

from fieldforge.online import (
    Address,
    MapItem,
    OnlineError,
    base_url,
    request_json,
    text,
    validate_route,
)


class Busy(OnlineError):
    pass


class Provider:
    """One-process request gate and bounded in-memory response cache."""

    def __init__(self, config, kind):
        self.url = base_url(config["url"])
        self.name = text(config.get("name"), "Provider name")
        self.attribution = text(config.get("attribution"), "Attribution", 2000)
        host = urllib.parse.urlsplit(self.url).hostname
        if host in {"nominatim.openstreetmap.org", "router.project-osrm.org", "routing.openstreetmap.de"}:
            raise ValueError("Configure an owned or contracted provider, not a community public/demo endpoint.")
        self.kind = kind
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.next_request = 0.0

    def call(self, path, key):
        # Reject bursts instead of accumulating background/bulk requests.
        if not self.lock.acquire(blocking=False):
            raise Busy("Another request is in progress.")
        try:
            now = time.monotonic()
            cached = self.cache.get(key)
            if cached and now - cached[0] < 600:
                self.cache.move_to_end(key)
                return cached[1]
            if cached:
                self.cache_bytes -= self.cache.pop(key)[2]
            if now < self.next_request:
                raise Busy("Wait before searching again.")
            self.next_request = now + 1.1
            result = request_json(self.url + path)
            size = len(json.dumps(result).encode())
            self.cache[key] = (time.monotonic(), result, size)
            self.cache_bytes += size
            while len(self.cache) > 128 or self.cache_bytes > 16 * 1024**2:
                self.cache_bytes -= self.cache.popitem(last=False)[1][2]
            return result
        finally:
            self.lock.release()

    def search(self, query):
        query = text(query, "Address", 300)
        params = urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": 5})
        values = self.call("/search?" + params, hashlib.sha256(query.casefold().encode()).hexdigest())
        if not isinstance(values, list) or len(values) > 10:
            raise OnlineError("Unsupported address provider response.")
        return [asdict(Address.parse({"label": value.get("display_name"), "latitude": value.get("lat"),
                                     "longitude": value.get("lon"), "source": self.name,
                                     "attribution": self.attribution})) for value in values if isinstance(value, dict)]

    def route(self, start, end):
        from fieldforge.navigation.places import coordinate, coordinate_text

        points = []
        for pair in (start, end):
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("Enter start and destination as latitude, longitude.")
            points.append((coordinate(pair[0], latitude=True), coordinate(pair[1], latitude=False)))
        positions = ";".join(f"{coordinate_text(lon)},{coordinate_text(lat)}" for lat, lon in points)
        path = f"/route/v1/driving/{positions}?overview=full&geometries=geojson&steps=false&alternatives=false"
        value = self.call(path, hashlib.sha256(positions.encode()).hexdigest())
        if (not isinstance(value, dict) or value.get("code") != "Ok"
                or not isinstance(value.get("routes"), list) or not value["routes"]):
            raise OnlineError("No driving route was returned for those coordinates.")
        route = value["routes"][0]
        if not isinstance(route, dict) or not isinstance(route.get("geometry"), dict):
            raise OnlineError("Invalid route geometry.")
        if route["geometry"].get("type") != "LineString":
            raise OnlineError("Unsupported route geometry.")
        return validate_route({"profile": "driving", "coordinates": route["geometry"].get("coordinates"),
                               "distance_m": route.get("distance"), "duration_s": route.get("duration"),
                               "source": self.name, "attribution": self.attribution,
                               "created_at": datetime.now(timezone.utc).isoformat()})


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


class Portal:
    def __init__(self, config, *, folder):
        if not isinstance(config, dict) or config.get("version") != 1:
            raise ValueError("Portal configuration must have version 1.")
        self.name = text(config.get("name", "FieldForge map portal"), "Portal name")
        self.geocoder = Provider(config["geocoder"], "geocoder") if config.get("geocoder") else None
        self.router = Provider(config["router"], "router") if config.get("router") else None
        entries = config.get("maps", [])
        if not isinstance(entries, list) or len(entries) > 500:
            raise ValueError("Map catalogue limit is 500 files.")
        self.maps = {}
        for entry in entries:
            item = MapItem.parse(entry)
            if item.id in self.maps:
                raise ValueError("Map IDs must be distinct.")
            path = Path(folder) / item.filename
            if path.is_symlink() or not path.is_file():
                raise ValueError("Catalogue maps must be regular files in the configured asset folder.")
            before = path.stat()
            checksum = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024**2), b""):
                    checksum.update(block)
            if (_identity(path.stat()) != _identity(before) or before.st_size != item.size
                    or checksum.hexdigest() != item.sha256):
                raise ValueError("Catalogue map checksum/size changed; rebuild the manifest before serving.")
            self.maps[item.id] = (item, path, _identity(before))

    @staticmethod
    def reply(start_response, status, payload, *, content_type="application/json; charset=utf-8", extra=()):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, allow_nan=False).encode("utf-8")
        headers = [("Content-Type", content_type), ("Content-Length", str(len(data))),
                   ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                   ("Referrer-Policy", "no-referrer"), *extra]
        start_response(status, headers)
        return [data]

    @staticmethod
    def body(environ):
        if environ.get("CONTENT_TYPE", "").split(";")[0] != "application/json":
            raise ValueError("Send a JSON request.")
        raw_length = environ.get("CONTENT_LENGTH", "")
        if not raw_length.isdigit() or not 1 <= int(raw_length) <= 4096:
            raise ValueError("Request size is invalid.")
        data = environ["wsgi.input"].read(int(raw_length))
        if len(data) != int(raw_length):
            raise ValueError("Incomplete request.")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("Send a JSON object.")
        return value

    def __call__(self, environ, start_response):
        path, method = environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", "GET")
        try:
            if method == "GET" and path in {"/", "/portal.js", "/portal.css"}:
                from fieldforge.portal_web import CSS, HTML, SCRIPT
                value, mime = {"/": (HTML, "text/html; charset=utf-8"),
                               "/portal.js": (SCRIPT, "text/javascript; charset=utf-8"),
                               "/portal.css": (CSS, "text/css; charset=utf-8")}[path]
                return self.reply(start_response, "200 OK", value.encode(), content_type=mime,
                                  extra=[("Content-Security-Policy", "default-src 'none'; script-src 'self'; "
                                          "style-src 'self'; connect-src 'self'; img-src 'self'; "
                                          "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")])
            if method == "GET" and path == "/api/v1/status":
                return self.reply(start_response, "200 OK", {"version": 1, "name": self.name,
                    "capabilities": {"geocoding": self.geocoder is not None, "routing": self.router is not None},
                    "providers": {key: {"name": provider.name, "attribution": provider.attribution}
                                  for key, provider in (("geocoding", self.geocoder), ("routing", self.router)) if provider}})
            if method == "GET" and path == "/api/v1/maps":
                return self.reply(start_response, "200 OK", {"maps": [asdict(v[0]) for v in self.maps.values()]})
            if method == "GET" and path.startswith("/api/v1/maps/") and path.endswith("/file"):
                identifier = path[len("/api/v1/maps/"):-len("/file")]
                if identifier not in self.maps:
                    return self.reply(start_response, "404 Not Found", {"error": "Map not found."})
                item, source, identity = self.maps[identifier]
                stream = source.open("rb")
                if _identity(os.fstat(stream.fileno())) != identity or source.is_symlink():
                    stream.close()
                    raise OnlineError("Map changed on server; the catalogue needs updating.")
                start_response("200 OK", [("Content-Type", "application/octet-stream"),
                    ("Content-Length", str(item.size)), ("X-Content-Type-Options", "nosniff"),
                    ("Content-Disposition", f'attachment; filename="{item.filename}"'),
                    ("ETag", '"' + item.sha256 + '"'), ("Cache-Control", "private, max-age=0")])
                def blocks():
                    try:
                        remaining = item.size
                        while remaining:
                            block = stream.read(min(128 * 1024, remaining))
                            if not block:
                                break
                            remaining -= len(block)
                            yield block
                    finally:
                        stream.close()
                return blocks()
            if method == "POST" and path in {"/api/v1/search", "/api/v1/route"}:
                # Reject cross-origin browser callers; native clients send no Origin.
                origin = environ.get("HTTP_ORIGIN")
                expected = environ.get("wsgi.url_scheme", "http") + "://" + environ.get("HTTP_HOST", "")
                if origin is not None and origin != expected:
                    return self.reply(start_response, "403 Forbidden", {"error": "Same-origin requests only."})
                payload = self.body(environ)
                provider = self.geocoder if path.endswith("search") else self.router
                if provider is None:
                    return self.reply(start_response, "503 Service Unavailable", {"error": "Provider not configured."})
                if path.endswith("search"):
                    if set(payload) != {"query"}:
                        raise ValueError("Send one address query.")
                    result = {"results": provider.search(payload["query"])}
                else:
                    if set(payload) != {"start", "end"}:
                        raise ValueError("Send a start and destination coordinate.")
                    result = provider.route(payload["start"], payload["end"])
                return self.reply(start_response, "200 OK", result)
            return self.reply(start_response, "404 Not Found", {"error": "Resource not found."})
        except Busy:
            return self.reply(start_response, "429 Too Many Requests", {"error": "Wait before requesting again."},
                              extra=[("Retry-After", "2")])
        except OnlineError:
            return self.reply(start_response, "503 Service Unavailable", {"error": "Provider or map unavailable. Try later."})
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            return self.reply(start_response, "400 Bad Request", {"error": "Invalid request or provider response."})
        except OSError:
            return self.reply(start_response, "503 Service Unavailable", {"error": "Portal resource unavailable."})


def create_app(config_path):
    path = Path(config_path).resolve()
    with path.open("rb") as stream:
        raw = stream.read(1024**2 + 1)
    if len(raw) > 1024**2:
        raise ValueError("Portal configuration exceeds one MiB.")
    config = json.loads(raw)
    folder = (path.parent / config.get("asset_folder", "maps")).resolve()
    return Portal(config, folder=folder)


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass  # No address/coordinate query logging in the development server.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    app = create_app(args.config)
    with make_server("127.0.0.1", args.port, app, handler_class=QuietHandler) as server:
        print(f"FieldForge development portal: http://127.0.0.1:{server.server_port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
