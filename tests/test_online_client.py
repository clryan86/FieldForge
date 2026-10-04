"""Optional networking must never weaken the default offline workflow."""

import hashlib
import io
import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError

import pytest
from map_fixture import make_map, png

from fieldforge.online import (
    PortalCancelled,
    PortalClient,
    PortalError,
    PortalLibrary,
    PortalOffline,
    models,
)

STATUS = {
    "api_version": 1, "name": "Local test portal", "geocoding": True,
    "routing": True, "catalog": True, "route_modes": ["driving"],
}
STAMP = "2026-10-04T00:00:00Z"


def result():
    return {"label": "Fictional test address", "latitude": 39.0, "longitude": -75.0,
            "source": "Test geocoder", "attribution": "Original test coordinates",
            "license": "CC0-1.0", "retrieved_at": STAMP}


def route():
    return {
        "id": "test-route", "title": "Fictional test route", "mode": "driving",
        "distance_m": 1000, "duration_s": 120,
        "geometry": [[-75.0, 39.0], [-75.001, 39.001]],
        "steps": [{"instruction": "Continue on the fictional test road", "distance_m": 1000,
                   "duration_s": 120, "latitude": 39.0, "longitude": -75.0}],
        "start": {"latitude": 39.0, "longitude": -75.0},
        "end": {"latitude": 39.001, "longitude": -75.001},
        "source": "Test router", "attribution": "Original test geometry",
        "license": "CC0-1.0", "created_at": STAMP,
    }


def asset(data=None, **changes):
    data = png(2) if data is None else data
    value = {
        "id": "test-map", "title": "Original fictional map", "filename": "test-map.png",
        "format": "png", "download_path": "/api/v1/maps/test-map/download",
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "attribution": "Original fixture; no real geographic data", "license": "CC0-1.0",
        "coverage": "Fictional test coverage", "version": "1",
    }
    value.update(changes)
    return value


class Response(io.BytesIO):
    def __init__(self, value, *, binary=False, headers=None, status=200, before_read=None, url=None):
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        super().__init__(data)
        self.headers = {"Content-Type": "application/octet-stream" if binary else "application/json",
                        "Content-Length": str(len(data))}
        self.headers.update(headers or {})
        self.status, self.before_read, self.url = status, before_read, url
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        if self.before_read:
            callback, self.before_read = self.before_read, None
            callback()
        return super().read(size)

    def geturl(self):
        return self.url

    def read1(self, size=-1):
        return self.read(size)


class Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.lock = threading.Lock()

    def open(self, request, timeout):
        with self.lock:
            self.requests.append(request)
            response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if response.url is None:
            response.url = request.full_url
        return response


def connected(*responses, status=None):
    opener = Opener(Response(STATUS if status is None else status), *responses)
    client = PortalClient("https://portal.example", opener=opener)
    client.connect()
    return client, opener


def test_construction_and_offline_operations_never_contact_network(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Offline workflow tried to contact the network")

    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    client = PortalClient("https://portal.example", opener=fail)
    assert not client.connected and client.capabilities == {}
    for operation in (
        lambda: client.search("test address"), client.catalog,
        lambda: client.routes((39, -75), (40, -76)),
        lambda: client.download(asset(), tmp_path),
    ):
        with pytest.raises(PortalOffline, match="Connect"):
            operation()
    assert list(tmp_path.iterdir()) == []


def test_explicit_search_uses_post_and_preserves_coordinates_and_provenance():
    client, opener = connected(Response({"results": [result()]}))
    found, = client.search("  Fictional address  ")
    request = opener.requests[-1]
    assert request.method == "POST" and request.full_url.endswith("/api/v1/search")
    assert json.loads(request.data) == {"query": "Fictional address"}
    assert "Fictional" not in request.full_url
    assert request.get_header("User-agent").startswith("FieldForge/")
    assert found == result()
    assert found["latitude"] == 39 and found["longitude"] == -75
    assert client.connected


def test_empty_success_is_still_online_and_capabilities_are_copied():
    client, _ = connected(Response({"results": []}))
    capabilities = client.capabilities
    capabilities["geocoding"] = False
    capabilities["route_modes"].clear()
    assert client.search("No matching result") == ()
    assert client.connected and client.capabilities["geocoding"]
    assert client.capabilities["route_modes"] == ["driving"]


def test_missing_capability_is_gated_before_transport():
    client, opener = connected(status={**STATUS, "geocoding": False})
    with pytest.raises(PortalError, match="geocoding"):
        client.search("An address")
    assert len(opener.requests) == 1 and client.connected


def test_routes_keep_latitude_first_request_and_geojson_longitude_first_geometry():
    client, opener = connected(Response({"routes": [route()]}))
    planned, = client.routes((39.0, -75.0), (39.001, -75.001))
    body = json.loads(opener.requests[-1].data)
    assert body["start"] == {"latitude": 39.0, "longitude": -75.0}
    assert body["end"] == {"latitude": 39.001, "longitude": -75.001}
    assert body["mode"] == "driving"
    assert planned["geometry"][0] == [-75.0, 39.0]
    assert planned["steps"][0]["latitude"] == 39.0


@pytest.mark.parametrize("point", [(True, 0), (91, 0), (0, 181), (float("nan"), 0),
                                   (0, float("inf")), ("39", -75), (0,), (10**500, 0)])
def test_invalid_coordinates_do_not_send_a_request(point):
    client, opener = connected()
    with pytest.raises(PortalError):
        client.routes(point, (39, -75))
    assert len(opener.requests) == 1 and client.connected


@pytest.mark.parametrize("url", [
    "http://portal.example", "ftp://portal.example", "file:///tmp/map", "https://user@portal.example",
    "https://user:secret@portal.example", "https://portal.example/path", "https://portal.example?q=a",
    "https://portal.example?", "https://portal.example#fragment", "https://portal.example#",
    "https://portal.example\\@evil.example", "http://127.0.0.1.evil.example",
    "https://portal.example:70000", "https://portal.example/%2e%2e", "https://portal.example\n.evil",
])
def test_portal_origin_rejects_credentials_insecure_remote_hosts_and_ambiguous_paths(url):
    with pytest.raises(PortalError):
        PortalClient(url)


@pytest.mark.parametrize("url", ["https://portal.example/", "http://127.0.0.1:8000",
                                 "http://localhost:8000", "http://[::1]:8000"])
def test_secure_or_explicit_loopback_origins_do_not_connect_at_construction(url):
    assert not PortalClient(url).connected


def test_failed_transport_disconnects_without_automatic_reconnect():
    client, opener = connected(URLError("test disconnected"))
    with pytest.raises(PortalOffline):
        client.search("Fictional address")
    assert not client.connected and client.capabilities == {}
    with pytest.raises(PortalOffline):
        client.search("Retry")
    assert len(opener.requests) == 2


@pytest.mark.parametrize("value", [b'{"results":[],"results":[]}', b'{"results":[NaN]}',
                                  b"<html>Unexpected portal page</html>", b"[" * 1100])
def test_ambiguous_nonfinite_or_invalid_json_is_rejected(value):
    client, _ = connected(Response(value))
    with pytest.raises(PortalError):
        client.search("Fictional address")
    assert not client.connected


def test_json_stream_is_bounded_even_if_content_length_is_missing(monkeypatch):
    response = Response(b"x" * 300)
    del response.headers["Content-Length"]
    client, _ = connected(response)
    monkeypatch.setattr(models, "MAX_JSON_BYTES", 200)
    with pytest.raises(PortalError, match="size limit"):
        client.search("Fictional address")
    assert max(response.read_sizes) == 201


def test_slow_json_peer_cannot_extend_total_response_deadline(monkeypatch):
    from fieldforge.online import client as module

    class DrippingResponse(Response):
        def read(self, size=-1):
            raise AssertionError("read(n) must not wait for a slow peer to fill its buffer")

        def read1(self, size=-1):
            return io.BytesIO.read(self, min(size, 1))

    response = DrippingResponse({"results": [result()]})
    client, _ = connected(response)
    clock = iter(range(1000))
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    with pytest.raises(PortalOffline, match="total time"):
        client.search("Fictional address")
    assert response.closed and not client.connected


def test_slow_download_reader_observes_cancellation_on_first_chunk(tmp_path):
    cancel = threading.Event()

    class DrippingResponse(Response):
        def read(self, size=-1):
            raise AssertionError("A slow download must use read1 so cancellation is observed")

        def read1(self, size=-1):
            return io.BytesIO.read(self, min(size, 1))

    response = DrippingResponse(png(2), binary=True)
    client, _ = connected(response)

    def progress(done, total):
        if done:
            cancel.set()

    with pytest.raises(PortalCancelled):
        client.download(asset(), tmp_path, cancel=cancel, progress=progress)
    assert response.closed and not list(tmp_path.iterdir())


def test_cancelled_connect_cannot_turn_online():
    cancel = threading.Event()
    opener = Opener(Response(STATUS, before_read=cancel.set))
    client = PortalClient("https://portal.example", opener=opener)
    with pytest.raises(PortalCancelled):
        client.connect(cancel=cancel)
    assert not client.connected and client.capabilities == {}


def test_old_connect_finishing_after_new_connection_cannot_replace_it():
    entered, release = threading.Event(), threading.Event()

    def delayed():
        entered.set()
        assert release.wait(5)

    newer = {**STATUS, "name": "Newer portal status", "geocoding": False}
    opener = Opener(Response(STATUS, before_read=delayed), Response(newer))
    client = PortalClient("https://portal.example", opener=opener)
    with ThreadPoolExecutor(max_workers=1) as pool:
        stale = pool.submit(client.connect)
        assert entered.wait(5)
        client.disconnect()
        assert client.connect() == newer
        release.set()
        with pytest.raises(PortalCancelled):
            stale.result(timeout=5)
    assert client.connected and client.capabilities == newer


def test_download_is_verified_and_available_offline_with_attribution(tmp_path):
    data = png(2)
    entry = asset(data, filename="Fictional map.png")
    client, _ = connected(Response(data, binary=True))
    library = PortalLibrary(tmp_path / "offline")
    progress = []
    path = client.download(entry, library.maps_directory, progress=lambda done, total: progress.append((done, total)))
    assert path.name == "Fictional_map.png" and path.read_bytes() == data
    assert progress[0] == (0, len(data)) and progress[-1] == (len(data), len(data))
    metadata = json.loads(path.with_name(path.name + ".fieldforge.json").read_text())
    assert metadata["asset"]["attribution"] == entry["attribution"]
    assert metadata["asset"]["sha256"] == hashlib.sha256(data).hexdigest()
    client.disconnect()
    assert PortalLibrary(library.root).maps() == (path,)


def test_real_raster_mbtiles_is_inspected_before_publication(tmp_path):
    source = make_map(tmp_path / "source.mbtiles", zooms=(0,))
    data = source.read_bytes()
    entry = asset(data, filename="training.mbtiles", format="mbtiles")
    client, _ = connected(Response(data, binary=True))
    library = PortalLibrary(tmp_path / "offline")
    path = client.download(entry, library.maps_directory)
    assert path.read_bytes() == data and library.maps() == (path,)


@pytest.mark.parametrize("change", [
    {"filename": "../escape.png"}, {"filename": "nested/escape.png"},
    {"filename": "escape\\outside.png"}, {"filename": "wrong.html"},
    {"download_path": "https://outside.example/maps/test-map/download"},
    {"download_path": "//outside.example/api/v1/maps/test-map/download"},
    {"download_path": "/api/v1/maps/test-map/download?token=secret"},
    {"format": "zip", "filename": "archive.zip"}, {"bytes": True},
    {"sha256": "missing"}, {"bytes": models.MAX_IMAGE_BYTES + 1},
])
def test_unsafe_or_unsupported_catalog_entries_never_request_download(tmp_path, change):
    client, opener = connected()
    with pytest.raises(PortalError):
        client.download(asset(**change), tmp_path)
    assert len(opener.requests) == 1 and not list(tmp_path.iterdir())


@pytest.mark.parametrize("failure", ["checksum", "short", "extra", "signature", "length-header"])
def test_corrupt_downloads_leave_no_available_or_partial_files(tmp_path, failure):
    data = png(2)
    entry = asset(data)
    if failure == "checksum":
        data = png(2, color=(1, 2, 3))
    elif failure == "short":
        data = data[:-4]
    elif failure == "extra":
        data += b"extra"
    elif failure == "signature":
        data = b"this is not a PNG file"
        entry = asset(data)
    response = Response(data, binary=True)
    if failure == "length-header":
        response.headers["Content-Length"] = str(len(data) + 1)
    elif failure in ("short", "extra", "checksum"):
        del response.headers["Content-Length"]
    client, _ = connected(response)
    with pytest.raises(PortalError):
        client.download(entry, tmp_path)
    assert list(tmp_path.iterdir()) == [] and not client.connected


@pytest.mark.parametrize("at_end", [False, True])
def test_download_cancellation_cannot_publish_a_partial_or_late_map(tmp_path, at_end):
    cancel = threading.Event()
    data = png(2)
    client, _ = connected(Response(data, binary=True))

    def progress(done, total):
        if (at_end and done == total) or (not at_end and done == 0):
            cancel.set()

    with pytest.raises(PortalCancelled):
        client.download(asset(data), tmp_path, cancel=cancel, progress=progress)
    assert list(tmp_path.iterdir()) == []
    assert client.connected  # Cancelling one transfer is not a failed health check.


def test_disconnect_during_download_blocks_publication(tmp_path):
    data = png(2)
    client, _ = connected(Response(data, binary=True))

    def progress(done, total):
        if done == total:
            client.disconnect()

    with pytest.raises(PortalCancelled):
        client.download(asset(data), tmp_path, progress=progress)
    assert list(tmp_path.iterdir()) == [] and not client.connected


def test_download_refuses_overwrite_before_contacting_portal(tmp_path):
    path = tmp_path / "test-map.png"
    path.write_bytes(b"Keep the user's original")
    client, opener = connected()
    with pytest.raises(FileExistsError):
        client.download(asset(), tmp_path)
    assert path.read_bytes() == b"Keep the user's original" and len(opener.requests) == 1


def test_failed_manifest_publication_removes_only_our_new_map(tmp_path, monkeypatch):
    from fieldforge.online import storage

    def fail(*args):
        raise OSError("Simulated storage failure")

    client, _ = connected(Response(png(2), binary=True))
    monkeypatch.setattr(storage, "write_new_bytes", fail)
    with pytest.raises(PortalError):
        client.download(asset(), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_actual_http_redirect_is_never_followed():
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            hits.append(self.path)
            if self.path == "/api/v1/status":
                body = json.dumps(STATUS).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(302)
                self.send_header("Location", "/must-not-be-contacted")
                self.send_header("Content-Length", "0")
                self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = PortalClient(f"http://127.0.0.1:{server.server_address[1]}", timeout=2)
        client.connect()
        with pytest.raises(PortalError, match="redirects"):
            client.catalog()
        assert hits == ["/api/v1/status", "/api/v1/maps"] and not client.connected
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
