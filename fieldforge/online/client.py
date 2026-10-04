"""Explicit-connect client for a FieldForge map, geocoding and routing portal.

Construction/import never performs network I/O. All requests are bounded and
remain on the configured origin. A disconnected or cancelled worker cannot
restore online state or publish a late download.
"""

from __future__ import annotations

import copy
import hashlib
import http.client
import math
import os
import re
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from . import models
from .storage import check_directory, ensure_directory, publish_map

USER_AGENT = "FieldForge/0.1 (offline map and route client)"
CHUNK_BYTES = 64 * 1024


class PortalError(ValueError):
    """A portal operation failed; previously saved offline data is preserved."""


class PortalOffline(PortalError):
    """Connect explicitly before using an online portal operation."""


class PortalCancelled(PortalError):
    """A cancelled or obsolete operation must not publish its result."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Portal redirects are not allowed.", headers, fp)


def _cancelled(cancel) -> bool:
    if cancel is None:
        return False
    if callable(getattr(cancel, "is_set", None)):
        return bool(cancel.is_set())
    if callable(cancel):
        return bool(cancel())
    raise PortalError("Cancellation must be an Event or a callable.")


def _validated(function, *args):
    try:
        return function(*args)
    except models.ValidationError as exc:
        raise PortalError(str(exc)) from exc


def _read_chunk(response, size):
    # HTTPResponse.read(n) can wait to fill all n bytes even while a peer drips
    # data forever. read1 returns after one buffered/socket read, so cancellation
    # and total JSON deadlines are checked between arriving chunks.
    reader = getattr(response, "read1", None)
    return reader(size) if callable(reader) else response.read(size)


def _collection(value, key: str, validator, maximum: int) -> tuple[dict, ...]:
    value = models.object_fields(value, {key}, f"Portal {key} response")
    rows = value[key]
    if not isinstance(rows, list) or len(rows) > maximum:
        raise models.ValidationError(f"Portal {key} response exceeds the {maximum:,}-item limit.")
    result = tuple(validator(row) for row in rows)
    if key in ("maps", "routes") and len({row["id"] for row in result}) != len(result):
        raise models.ValidationError(f"Portal {key} response contains duplicate identifiers.")
    return result


class _OperationSignal:
    def __init__(self, client, token, cancel):
        self.client, self.token, self.cancel = client, token, cancel

    def is_set(self):
        if _cancelled(self.cancel):
            return True
        with self.client._lock:
            return self.client._generation != self.token


class PortalClient:
    def __init__(self, base_url: str, *, timeout: float = 10, opener=None):
        self._base_url = _validated(models.validate_portal_url, base_url)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise PortalError("Portal timeout must be a finite number between 0 and 120 seconds.")
        self.timeout = float(timeout)
        self._opener = opener if opener is not None else build_opener(ProxyHandler({}), _NoRedirect())
        self._lock = threading.RLock()
        self._generation = 0
        self._connected = False
        self._capabilities: dict = {}
        self._legacy_protocol = False

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def capabilities(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._capabilities)

    @property
    def legacy_protocol(self) -> bool:
        with self._lock:
            return self._legacy_protocol

    def disconnect(self) -> None:
        with self._lock:
            self._generation += 1
            self._connected = False
            self._capabilities = {}

    def _active(self, token, cancel):
        if _cancelled(cancel):
            raise PortalCancelled("Portal request cancelled; no late result was accepted.")
        with self._lock:
            if token != self._generation:
                raise PortalCancelled("This portal request is obsolete; connect again to retry.")

    def _begin(self, capability: str, cancel) -> int:
        if _cancelled(cancel):
            raise PortalCancelled("Portal request cancelled.")
        with self._lock:
            if not self._connected:
                raise PortalOffline("Connect to your online portal before using this feature.")
            if not self._capabilities.get(capability, False):
                raise PortalError(f"This portal does not currently provide {capability}.")
            return self._generation

    def _invalidate(self, token):
        with self._lock:
            if token == self._generation:
                self._generation += 1
                self._connected = False
                self._capabilities = {}

    def _transport_failed(self, token, cancel, message, cause):
        self._active(token, cancel)
        self._invalidate(token)
        raise PortalOffline(message + " Saved offline maps and routes are still available.") from cause

    def _request(self, path, payload, token, cancel, *, binary=False):
        self._active(token, cancel)
        data = None if payload is None else _validated(models.encode_json, payload)
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity",
                   "Accept": "application/octet-stream" if binary else "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(self.base_url + path, data=data, headers=headers,
                          method="GET" if payload is None else "POST")
        open_request = getattr(self._opener, "open", self._opener)
        response = None
        try:
            response = open_request(request, timeout=self.timeout)
            self._active(token, cancel)
            status = getattr(response, "status", None)
            if status is None and callable(getattr(response, "getcode", None)):
                status = response.getcode()
            if status != 200:
                raise PortalError(f"Portal request failed (HTTP {status}).")
            if callable(getattr(response, "geturl", None)) and response.geturl() != request.full_url:
                raise PortalError("Portal redirects are not allowed.")
            encoding = response.headers.get("Content-Encoding", "identity").lower().strip()
            if encoding not in ("", "identity"):
                raise PortalError("Compressed portal responses are not accepted.")
            if not binary:
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/json":
                    raise PortalError("Portal returned a response other than JSON.")
            return response
        except HTTPError as exc:
            message = ("The portal is busy (HTTP 429); wait before retrying." if exc.code == 429
                       else f"Portal request failed (HTTP {exc.code}).")
            if 300 <= exc.code <= 399:
                message = "Portal redirects are not allowed."
            else:
                try:
                    body = self._read(exc, token, cancel, 64 * 1024)
                    if len(body) <= 64 * 1024:
                        details = models.decode_json(body)
                        error = details.get("error", {})
                        candidate = error if isinstance(error, str) else error.get("message")
                        message += " " + models.text(candidate, "Portal error", 500)
                except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException):
                    pass
            exc.close()
            self._transport_failed(token, cancel, message, exc)
        except (OSError, URLError, http.client.HTTPException) as exc:
            if response is not None:
                response.close()
            self._transport_failed(token, cancel, "The online portal could not be reached.", exc)
        except PortalCancelled:
            if response is not None:
                response.close()
            raise
        except PortalError:
            if response is not None:
                response.close()
            self._invalidate(token)
            raise

    @staticmethod
    def _length(response):
        value = response.headers.get("Content-Length")
        if value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,20}", value):
            raise PortalError("Portal returned an invalid response length.")
        return int(value)

    def _read(self, response, token, cancel, maximum: int) -> bytes:
        deadline = time.monotonic() + self.timeout * 2
        length = self._length(response)
        if length is not None and length > maximum:
            raise PortalError("Portal response exceeds its supported size limit.")
        chunks = []
        size = 0
        while True:
            self._active(token, cancel)
            if time.monotonic() > deadline:
                raise PortalOffline("Portal response exceeded its total time limit.")
            chunk = _read_chunk(response, min(CHUNK_BYTES, maximum + 1 - size))
            self._active(token, cancel)
            if time.monotonic() > deadline:
                raise PortalOffline("Portal response exceeded its total time limit.")
            if not isinstance(chunk, bytes):
                raise PortalError("Portal returned an invalid response body.")
            if not chunk:
                break
            size += len(chunk)
            if size > maximum:
                raise PortalError("Portal response exceeds its supported size limit.")
            chunks.append(chunk)
        if length is not None and size != length:
            raise PortalError("Portal response was incomplete.")
        return b"".join(chunks)

    def _json(self, path, payload, token, cancel):
        response = self._request(path, payload, token, cancel)
        try:
            data = self._read(response, token, cancel, models.MAX_JSON_BYTES)
            value = _validated(models.decode_json, data)
            self._active(token, cancel)
            return value
        except (OSError, http.client.HTTPException) as exc:
            self._transport_failed(token, cancel, "The portal response was interrupted.", exc)
        except PortalCancelled:
            raise
        except PortalError:
            self._invalidate(token)
            raise
        finally:
            response.close()

    def _operation(self, path, payload, key, validator, maximum, capability, cancel):
        token = self._begin(capability, cancel)
        result = self._json(path, payload, token, cancel)
        try:
            result = _validated(_collection, result, key, validator, maximum)
        except PortalError:
            self._invalidate(token)
            raise
        self._active(token, cancel)
        return result

    def connect(self, cancel=None) -> dict:
        if _cancelled(cancel):
            raise PortalCancelled("Portal connection cancelled.")
        with self._lock:
            self._generation += 1
            token = self._generation
            self._connected = False
            self._capabilities = {}
        value = self._json("/api/v1/status", None, token, cancel)
        return self._accept_status(value, token, cancel)

    def _accept_status(self, value, token, cancel=None) -> dict:
        """Validate an already received explicit handshake; used by the API façade."""
        legacy = isinstance(value, dict) and "api_version" not in value
        try:
            validator = models.normalize_legacy_status if legacy else models.validate_status
            status = _validated(validator, value)
        except PortalError:
            self._invalidate(token)
            raise
        with self._lock:
            self._active(token, cancel)
            self._connected = True
            self._capabilities = status
            self._legacy_protocol = legacy
            return copy.deepcopy(status)

    def search(self, query: str, cancel=None) -> tuple[dict, ...]:
        self._begin("geocoding", cancel)
        query = _validated(models.validate_query, query)
        if self.legacy_protocol:
            def validate(item):
                received_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                return models.normalize_legacy_address(item, received_at)
        else:
            validate = models.validate_search_result
        return self._operation("/api/v1/search", {"query": query}, "results",
                               validate, models.MAX_RESULTS, "geocoding", cancel)

    def catalog(self, cancel=None) -> tuple[dict, ...]:
        validator = models.normalize_legacy_asset if self.legacy_protocol else models.validate_asset
        return self._operation("/api/v1/maps", None, "maps", validator,
                               models.MAX_MAPS, "catalog", cancel)

    def routes(self, start: tuple[float, float], end: tuple[float, float],
               cancel=None) -> tuple[dict, ...]:
        self._begin("routing", cancel)
        start_lat, start_lon = _validated(models.validate_coordinates, start)
        end_lat, end_lon = _validated(models.validate_coordinates, end)
        if self.legacy_protocol:
            token = self._begin("routing", cancel)
            value = self._json("/api/v1/route", {"start": [start_lat, start_lon],
                                               "end": [end_lat, end_lon]}, token, cancel)
            try:
                route = _validated(models.normalize_legacy_route, value,
                                   (start_lat, start_lon), (end_lat, end_lon))
            except PortalError:
                self._invalidate(token)
                raise
            self._active(token, cancel)
            return (route,)
        return self._operation(
            "/api/v1/routes",
            {"start": {"latitude": start_lat, "longitude": start_lon},
             "end": {"latitude": end_lat, "longitude": end_lon}, "mode": "driving"},
            "routes", models.validate_route, models.MAX_ROUTES, "routing", cancel,
        )

    def download(self, asset: dict, directory: Path, cancel=None, progress=None) -> Path:
        return self._download(asset, directory, cancel, progress)

    def _download_to(self, asset: dict, destination: Path, cancel=None, *, legacy_note=None) -> Path:
        destination = Path(destination).expanduser().absolute()
        return self._download(asset, destination.parent, cancel, None,
                              destination_name=destination.name, legacy_note=legacy_note,
                              decode_image=True)

    def _download(self, asset, directory, cancel, progress, *, destination_name=None,
                  legacy_note=None, decode_image=False):
        token = self._begin("catalog", cancel)
        asset = _validated(models.validate_asset, asset)
        if progress is not None and not callable(progress):
            raise PortalError("Download progress must be a callable.")
        directory = ensure_directory(directory)
        if destination_name is not None:
            filename = _validated(models.validate_filename, destination_name, asset["format"])
            if filename != destination_name:
                raise PortalError("Choose a destination filename without leading or trailing whitespace.")
        else:
            filename = models.safe_filename(asset["filename"])
        target = directory / filename
        manifest = target.with_name(target.name + ".fieldforge.json")
        source_note = target.with_name(target.name + ".source.json")
        if (target.exists() or target.is_symlink() or manifest.exists() or manifest.is_symlink()
                or (legacy_note is not None and (source_note.exists() or source_note.is_symlink()))):
            raise FileExistsError("This map filename already exists; existing files were preserved.")
        self._active(token, cancel)
        path = f"/api/v1/maps/{asset['id']}/file" if self.legacy_protocol else asset["download_path"]
        response = self._request(path, None, token, cancel, binary=True)
        temporary = None
        try:
            length = self._length(response)
            if length is not None and length != asset["bytes"]:
                raise PortalError("Download length differs from the map catalog; nothing was saved.")
            fd, name = tempfile.mkstemp(prefix=".fieldforge-download-", suffix=target.suffix, dir=directory)
            temporary = Path(name)
            digest = hashlib.sha256()
            received = 0
            with os.fdopen(fd, "wb") as stream:
                if progress is not None:
                    progress(0, asset["bytes"])
                while True:
                    self._active(token, cancel)
                    chunk = _read_chunk(response, min(CHUNK_BYTES, asset["bytes"] + 1 - received))
                    self._active(token, cancel)
                    if not isinstance(chunk, bytes):
                        raise PortalError("Portal returned an invalid download body.")
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > asset["bytes"]:
                        raise PortalError("Download exceeded the catalog size; nothing was saved.")
                    stream.write(chunk)
                    digest.update(chunk)
                    if progress is not None:
                        progress(received, asset["bytes"])
                self._active(token, cancel)
                if received != asset["bytes"] or digest.hexdigest() != asset["sha256"]:
                    raise PortalError("Map download failed its length or SHA-256 check; nothing was saved.")
                stream.flush()
                os.fsync(stream.fileno())
            _verify_map_file(temporary, asset, _OperationSignal(self, token, cancel), decode_image=decode_image)
            with self._lock:
                self._active(token, cancel)
                check_directory(directory)
                return publish_map(temporary, target, asset, self.base_url,
                                   lambda: self._active(token, cancel), legacy_note=legacy_note)
        except (OSError, http.client.HTTPException) as exc:
            if isinstance(exc, FileExistsError):
                raise
            self._transport_failed(token, cancel, "The map download could not be completed.", exc)
        except PortalCancelled:
            raise
        except (models.ValidationError, PortalError) as exc:
            self._active(token, cancel)
            self._invalidate(token)
            if isinstance(exc, PortalError):
                raise
            raise PortalError(str(exc)) from exc
        finally:
            response.close()
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _verify_map_file(path: Path, asset: dict, cancel, *, decode_image=False) -> None:
    """Preflight actual bytes before a checksum-verified map becomes available."""
    if cancel.is_set():
        raise PortalCancelled("Map download cancelled before verification.")
    if asset["format"] == "mbtiles":
        from fieldforge.navigation.mbtiles import MapCancelled, inspect_pack
        from fieldforge_gps.mbtiles import MapReadCancelled
        from fieldforge_gps.mbtiles import inspect_pack as inspect_gps_pack

        try:
            inspect_pack(path, cancel=cancel)
            inspect_gps_pack(path, consent=True, cancel=cancel)
        except (MapCancelled, MapReadCancelled) as exc:
            raise PortalCancelled("Map verification cancelled.") from exc
        except (ValueError, TimeoutError, sqlite3.Error) as exc:
            raise PortalError("Downloaded MBTiles is not supported: " + str(exc)) from exc
        return
    from .map_validation import RasterCancelled, RasterValidationError, validate_raster_image

    try:
        validate_raster_image(path, asset["format"], cancel=cancel)
    except RasterCancelled as exc:
        raise PortalCancelled("Map verification cancelled.") from exc
    except RasterValidationError as exc:
        raise PortalError("Downloaded map image is not supported: " + str(exc)) from exc
    if decode_image:
        from fieldforge_gps.raster import read_reference

        try:
            decoded = read_reference(path, consent=True, cancel=cancel)
            decoded.pixels.close()
        except ValueError as exc:
            if cancel.is_set():
                raise PortalCancelled("Map verification cancelled.") from exc
            raise PortalError("Downloaded map cannot be decoded: " + str(exc)) from exc
