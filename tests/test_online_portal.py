"""Real local HTTP integration; never query a public geocoder or personal address."""

import hashlib
import io
import json
import shutil
import threading
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from wsgiref.simple_server import make_server

import pytest

import fieldforge_gps
from fieldforge import map_portal, online
from fieldforge_gps.gpx_review import parse_gpx
from fieldforge_gps.places import read_catalog


@contextmanager
def serving(app):
    server = make_server("127.0.0.1", 0, app, handler_class=map_portal.QuietHandler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        assert not thread.is_alive()


@pytest.fixture
def map_entry(tmp_path):
    source = Path(fieldforge_gps.__file__).parent / "data/FICTIONAL-MAP.mbtiles"
    destination = tmp_path / "fictional.mbtiles"
    shutil.copyfile(source, destination)
    return {"id": "fictional-grid", "title": "FICTIONAL test grid — not real coverage",
            "filename": destination.name, "kind": "mbtiles", "size": source.stat().st_size,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "coverage": "Fictional only",
            "updated": "2026-10-04", "source": "FieldForge original test fixture",
            "attribution": "FieldForge fictional fixture", "license": "Synthetic fixture; retain notice"}


@pytest.fixture
def portal(tmp_path, map_entry):
    provider_calls = []
    def provider(environ, start):
        provider_calls.append((environ["PATH_INFO"], environ.get("QUERY_STRING", "")))
        if environ["PATH_INFO"] == "/search":
            value = [{"display_name": "Fictional Beacon Plaza <test>", "lat": "10.125", "lon": "20.25"},
                     {"display_name": "Fictional Beacon Park", "lat": "10.2", "lon": "20.3"}]
        else:
            value = {"code": "Ok", "routes": [{"distance": 1234.5, "duration": 321,
                     "geometry": {"type": "LineString", "coordinates": [[20.25, 10.125], [20.3, 10.2], [20.5, 10.4]]}}]}
        return map_portal.Portal.reply(start, "200 OK", value)
    with serving(provider) as provider_url:
        config = {"version": 1, "maps": [map_entry],
                  "geocoder": {"url": provider_url, "name": "Fictional geocoder", "attribution": "Original fixture"},
                  "router": {"url": provider_url, "name": "Fictional routing", "attribution": "Original fixture"}}
        app = map_portal.Portal(config, folder=tmp_path)
        with serving(app) as url:
            yield url, app, provider_calls


def connected(portal):
    client = online.PortalSession()
    client.connect(portal[0], consent=True)
    return client


def invoke(app, path, method="GET", payload=None, headers=None):
    raw = json.dumps(payload).encode() if payload is not None else b""
    environ = {"PATH_INFO": path, "REQUEST_METHOD": method, "wsgi.input": io.BytesIO(raw),
               "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)),
               "wsgi.url_scheme": "https", "HTTP_HOST": "portal.example", **(headers or {})}
    captured = []
    response = app(environ, lambda status, fields: captured.append((status, dict(fields))))
    try:
        body = b"".join(response)
    finally:
        if hasattr(response, "close"):
            response.close()
    return *captured[0], body


def test_offline_default_and_unconsented_connect_do_not_touch_network(monkeypatch):
    monkeypatch.setattr(online, "open_request", lambda *a, **kw: pytest.fail("No network allowed"))
    client = online.PortalSession()
    assert not client.ready
    with pytest.raises(online.OnlineError):
        client.connect("https://portal.example")
    for action in (client.maps, lambda: client.search("Fictional"), lambda: client.route((1, 2), (3, 4))):
        with pytest.raises(online.OnlineError):
            action()


def test_real_http_search_select_save_and_read_offline(portal, tmp_path):
    client = connected(portal)
    results = client.search("Fictional Beacon")
    assert len(results) == 2 and results[0].latitude == 10.125 and results[0].longitude == 20.25
    assert len(portal[2]) == 1
    assert client.search("Fictional Beacon") == results  # Provider cache, no second upstream call.
    assert len(portal[2]) == 1
    client.disconnect()
    path = tmp_path / "saved-place.csv"
    online.save_new(path, online.address_csv(results[0]))
    catalog = read_catalog(path, consent=True, wgs84_confirmed=True)
    assert catalog.places[0].latitude == results[0].latitude
    assert "Original fixture" in catalog.places[0].source
    assert "<test>" in catalog.places[0].name
    with pytest.raises(online.Cancelled):
        client.search("another query")
    assert len(portal[2]) == 1


def test_real_route_uses_lon_lat_upstream_but_exports_correct_gpx(portal, tmp_path):
    client = connected(portal)
    value = client.route((10.125, 20.25), (10.4, 20.5))
    assert "/20.25,10.125;20.5,10.4" in portal[2][0][0]
    client.disconnect()
    path = tmp_path / "planned.gpx"
    raw = online.route_gpx(value)
    online.save_new(path, raw)
    document = parse_gpx(raw)
    assert document.point_count == 3
    assert "PLANNED" in document.tracks[0].name
    assert b"not a recorded GPS trip" in raw and b"Original fixture" in raw
    assert b"<time>" not in raw  # Do not invent a recorded trip or point timestamps.


def test_map_download_verified_and_opens_offline_without_overwriting(portal, tmp_path, map_entry):
    client = connected(portal)
    item, = client.maps()
    path = tmp_path / "download.mbtiles"
    assert client.download(item, path) == path
    client.disconnect()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == map_entry["sha256"]
    note = json.loads(path.with_name(path.name + ".source.json").read_text())
    assert note["attribution"] == item.attribution
    from fieldforge_gps.mbtiles import inspect_pack
    assert inspect_pack(path, consent=True).levels
    client = connected(portal)
    with pytest.raises(FileExistsError):
        client.download(item, path)
    assert not list(tmp_path.glob(".fieldforge-*"))


def test_map_checksum_failure_discards_partial_and_preserves_other_files(portal, tmp_path):
    client = connected(portal)
    item, = client.maps()
    item = online.MapItem.parse({**asdict(item), "sha256": "0" * 64})
    path = tmp_path / "bad.mbtiles"
    with pytest.raises(online.OnlineError, match="checksum"):
        client.download(item, path)
    assert not path.exists() and not path.with_name(path.name + ".source.json").exists()
    assert not list(tmp_path.glob(".fieldforge-*"))


def test_disconnect_during_download_removes_temporary_file(portal, tmp_path, monkeypatch):
    client = connected(portal)
    item, = client.maps()
    original = online.open_request
    def cancel_after_open(*args, **kwargs):
        response = original(*args, **kwargs)
        client.disconnect()
        return response
    monkeypatch.setattr(online, "open_request", cancel_after_open)
    path = tmp_path / "cancelled.mbtiles"
    with pytest.raises(online.Cancelled):
        client.download(item, path)
    assert not path.exists() and not list(tmp_path.glob(".fieldforge-*"))


def test_connection_loss_does_not_erase_saved_results_or_retry(monkeypatch, portal):
    client = connected(portal)
    old = client.search("Fictional")
    calls = []
    def failed(*args, **kwargs):
        calls.append(args)
        raise OSError("unreachable")
    monkeypatch.setattr(online, "open_request", failed)
    with pytest.raises(online.OnlineError, match="reach"):
        client.search("Another")
    assert not client.ready and old[0].latitude == 10.125
    with pytest.raises(online.Cancelled):
        client.maps()
    assert len(calls) == 1


@pytest.mark.parametrize("url", ["http://remote.example", "file:///etc/passwd", "https://user:secret@portal.example",
                                 "https://portal.example/?secret=1", "https://portal.example/#fragment",
                                 "https://portal.example/\n", "https://portal.example:999999", "https://x\\y"])
def test_invalid_portal_urls_rejected_without_requests(url, monkeypatch):
    monkeypatch.setattr(online, "open_request", lambda *a, **kw: pytest.fail("Must reject before network"))
    with pytest.raises(ValueError):
        online.PortalSession().connect(url, consent=True)


def test_redirect_is_not_followed():
    calls = []
    def app(environ, start):
        calls.append(environ["PATH_INFO"])
        start("302 Found", [("Location", "http://127.0.0.1:9/not-authorized"), ("Content-Length", "0")])
        return [b""]
    with serving(app) as url:
        with pytest.raises(online.OnlineError, match="redirect"):
            online.PortalSession().connect(url, consent=True)
    assert calls == ["/api/v1/status"]


@pytest.mark.parametrize("change", [{"filename": "../secret.mbtiles"}, {"filename": "CON.mbtiles"},
                                    {"filename": "map.exe"}, {"size": True}, {"size": online.MAX_MAP + 1},
                                    {"sha256": "missing"}, {"id": "../map"}, {"license": ""}, {"kind": "vector"}])
def test_catalogue_limits_and_portable_paths(map_entry, change):
    with pytest.raises(ValueError):
        online.MapItem.parse({**map_entry, **change})


def test_map_changed_after_catalogue_is_not_served(portal, tmp_path):
    (tmp_path / "fictional.mbtiles").write_bytes(b"replaced")
    status, _, _ = invoke(portal[1], "/api/v1/maps/fictional-grid/file")
    assert status.startswith("503")


def test_unconfigured_provider_and_same_origin_controls(tmp_path):
    app = map_portal.Portal({"version": 1}, folder=tmp_path)
    status, _, data = invoke(app, "/api/v1/status")
    assert status.startswith("200") and json.loads(data)["capabilities"] == {"geocoding": False, "routing": False}
    status, _, _ = invoke(app, "/api/v1/search", "POST", {"query": "Fictional"})
    assert status.startswith("503")
    status, _, _ = invoke(app, "/api/v1/search", "POST", {"query": "Fictional"}, {"HTTP_ORIGIN": "https://other.example"})
    assert status.startswith("403")


def test_provider_gate_has_no_background_queue_or_public_default(portal):
    client = connected(portal)
    client.search("first")
    with pytest.raises(online.OnlineError, match="busy"):
        client.search("second")
    assert len(portal[2]) == 1
    for url in ("https://nominatim.openstreetmap.org", "https://router.project-osrm.org"):
        with pytest.raises(ValueError, match="owned or contracted"):
            map_portal.Provider({"url": url, "name": "No default", "attribution": "Example"}, "geocoder")


@pytest.mark.parametrize("coordinates", [[[0, float("nan")], [1, 1]], [[0, 91], [1, 1]], [[True, 0], [1, 1]], [[0, 0]]])
def test_invalid_route_geometry_never_becomes_a_saved_file(coordinates):
    with pytest.raises(ValueError):
        online.route_gpx({"profile": "driving", "coordinates": coordinates, "source": "Fixture", "attribution": "Fixture",
                          "created_at": "2026-10-04", "distance_m": 1, "duration_s": 1})


def test_new_file_write_preserves_existing_destination(tmp_path):
    path = tmp_path / "saved.csv"
    path.write_bytes(b"already saved")
    with pytest.raises(FileExistsError):
        online.save_new(path, b"replacement")
    assert path.read_bytes() == b"already saved" and not list(tmp_path.glob(".fieldforge-*"))


def test_portal_assets_are_local_with_restrictive_csp(portal):
    status, headers, body = invoke(portal[1], "/")
    assert status.startswith("200") and b"Address" in body
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert b"https://" not in body and b"cdn" not in body
    assert invoke(portal[1], "/api/v1/maps/../../file")[0].startswith("404")


@pytest.mark.parametrize("suffix", ["png", "jpg", "tiff", "webp"])
def test_image_map_download_decodes_and_preserves_exact_original_bytes(tmp_path, map_entry, suffix):
    from PIL import Image

    from fieldforge_gps.raster import read_reference
    source = tmp_path / ("reference." + suffix)
    Image.new("RGB", (80, 60), "green").save(source)
    entry = {**map_entry, "filename": source.name, "kind": "image", "size": source.stat().st_size,
             "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    app = map_portal.Portal({"version": 1, "maps": [entry]}, folder=tmp_path)
    with serving(app) as url:
        client = connected((url,))
        item, = client.maps()
        destination = tmp_path / ("saved." + suffix)
        client.download(item, destination)
        client.disconnect()
    assert destination.read_bytes() == source.read_bytes()
    assert read_reference(destination, consent=True)


def test_checksum_matching_but_undecodable_image_is_never_published(tmp_path, map_entry):
    source = tmp_path / "fake.png"
    source.write_bytes(b"not an image")
    entry = {**map_entry, "filename": source.name, "kind": "image", "size": source.stat().st_size,
             "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    app = map_portal.Portal({"version": 1, "maps": [entry]}, folder=tmp_path)
    with serving(app) as url:
        client = connected((url,))
        item, = client.maps()
        with pytest.raises(ValueError):
            client.download(item, tmp_path / "saved.png")
    assert not (tmp_path / "saved.png").exists() and not list(tmp_path.glob(".fieldforge-*"))
    assert not list(tmp_path.glob("*.source.json"))


@pytest.mark.parametrize("change", [{"version": True}, {"providers": []}, {"providers": {"geocoding": None}},
                                   {"name": None}, {"capabilities": {"geocoding": "true", "routing": False}}])
def test_malformed_status_does_not_enable_connection(monkeypatch, change):
    status = {"version": 1, "name": "Fixture", "providers": {"geocoding": {"name": "Fixture", "attribution": "Fixture"}},
              "capabilities": {"geocoding": True, "routing": False}, **change}
    monkeypatch.setattr(online, "request_json", lambda *a, **kw: status)
    client = online.PortalSession()
    with pytest.raises(ValueError):
        client.connect("https://portal.example", consent=True)
    assert not client.ready


def test_concurrent_provider_request_rejected_without_queuing(portal):
    provider = portal[1].geocoder
    with provider.lock:
        with pytest.raises(map_portal.Busy):
            provider.search("Fictional")
    assert not portal[2]
