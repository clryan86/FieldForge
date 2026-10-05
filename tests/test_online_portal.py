"""Real local HTTP integration; never query a public geocoder or personal address."""

import base64
import hashlib
import io
import json
import re
import shutil
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from wsgiref.simple_server import make_server

import pytest

import fieldforge_gps
from fieldforge import map_portal, online
from fieldforge.online import compat
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
                     "geometry": {"type": "LineString", "coordinates": [[20.25, 10.125], [20.3, 10.2], [20.5, 10.4]]},
                     "legs": [{"summary": "Fictional Beacon Road", "steps": [
                         {"name": "Fictional Beacon Road", "distance": 700, "duration": 180,
                          "maneuver": {"type": "depart", "location": [20.25, 10.125]}},
                         {"name": "Fictional Plaza Lane", "distance": 534.5, "duration": 141,
                          "maneuver": {"type": "turn", "modifier": "right", "location": [20.3, 10.2]}},
                         {"name": "", "distance": 0, "duration": 0,
                          "maneuver": {"type": "arrive", "location": [20.5, 10.4]}},
                     ]}]}]}
        return map_portal.Portal.reply(start, "200 OK", value)
    with serving(provider) as provider_url:
        config = {"version": 1, "maps": [map_entry],
                  "geocoder": {"url": provider_url, "name": "Fictional geocoder", "attribution": "Original fixture",
                               "license": "Original synthetic fixture data"},
                  "router": {"url": provider_url, "name": "Fictional routing", "attribution": "Original fixture",
                             "license": "Original synthetic fixture data"}}
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
               "wsgi.url_scheme": "http", "HTTP_HOST": "127.0.0.1:8765",
               "SERVER_NAME": "127.0.0.1", "SERVER_PORT": "8765", "SERVER_PROTOCOL": "HTTP/1.1",
               "QUERY_STRING": "", "SCRIPT_NAME": "", **(headers or {})}
    captured = []
    response = app(environ, lambda status, fields: captured.append((status, dict(fields))))
    try:
        body = b"".join(response)
    finally:
        if hasattr(response, "close"):
            response.close()
    return *captured[0], body


def test_offline_default_and_unconsented_connect_do_not_touch_network(monkeypatch):
    monkeypatch.setattr(compat, "open_request", lambda *a, **kw: pytest.fail("No network allowed"))
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
    upstream_path, upstream_query = portal[2][0]
    positions = upstream_path.rsplit("/", 1)[1].split(";")
    assert [[float(number) for number in point.split(",")] for point in positions] == [
        [20.25, 10.125], [20.5, 10.4],
    ]
    query = urllib.parse.parse_qs(upstream_query)
    assert query["steps"] == ["true"] and query["alternatives"] == ["true"]
    client.disconnect()
    path = tmp_path / "planned.gpx"
    raw = online.route_gpx(value)
    online.save_new(path, raw)
    document = parse_gpx(raw)
    assert document.point_count == 3
    assert "PLANNED" in document.tracks[0].name
    assert b"not a recorded" in raw and b"Original fixture" in raw
    root = ET.fromstring(raw)
    assert not root.findall(".//{*}trkpt/{*}time")  # Planning metadata may have a time; GPS fixes may not.


def test_legacy_singular_route_endpoint_preserves_geometry_and_provenance(portal):
    status, _, raw = invoke(portal[1], "/api/v1/route", "POST",
                            {"start": [10.125, 20.25], "end": [10.4, 20.5]})
    assert status.startswith("200")
    route = json.loads(raw)
    assert route["profile"] == "driving"
    assert route["coordinates"] == [[20.25, 10.125], [20.3, 10.2], [20.5, 10.4]]
    assert route["distance_m"] == 1234.5 and route["duration_s"] == 321
    assert route["source"] == "Fictional routing" and route["attribution"] == "Original fixture"
    assert route["license"] == "Original synthetic fixture data"
    query = urllib.parse.parse_qs(portal[2][0][1])
    assert query["steps"] == ["true"] and query["alternatives"] == ["true"]
    assert parse_gpx(online.route_gpx(route)).point_count == 3


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
    with pytest.raises(online.OnlineError, match="checksum|SHA-256"):
        client.download(item, path)
    assert not path.exists() and not path.with_name(path.name + ".source.json").exists()
    assert not list(tmp_path.glob(".fieldforge-*"))


def test_disconnect_during_download_removes_temporary_file(portal, tmp_path, monkeypatch):
    client = connected(portal)
    item, = client.maps()
    original = compat.open_request
    def cancel_after_open(*args, **kwargs):
        response = original(*args, **kwargs)
        client.disconnect()
        return response
    monkeypatch.setattr(compat, "open_request", cancel_after_open)
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
    monkeypatch.setattr(compat, "open_request", failed)
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
    monkeypatch.setattr(compat, "open_request", lambda *a, **kw: pytest.fail("Must reject before network"))
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


def test_legacy_file_download_alias_serves_the_exact_catalogued_bytes(portal, map_entry):
    status, headers, raw = invoke(portal[1], "/api/v1/maps/fictional-grid/file")
    assert status.startswith("200")
    assert len(raw) == map_entry["size"] == int(headers["Content-Length"])
    assert hashlib.sha256(raw).hexdigest() == map_entry["sha256"]


def test_legacy_long_source_and_version_survive_catalogue_and_download(tmp_path, map_entry):
    source = "Original synthetic source: " + "reference-record-" * 20
    version = "2026-10-04-" + "licensed-export-" * 16
    entry = {**map_entry, "source": source, "updated": version}
    app = map_portal.Portal({"version": 1, "maps": [entry]}, folder=tmp_path)
    status, _, raw = invoke(app, "/api/v1/maps")
    assert status.startswith("200")
    wire, = json.loads(raw)["maps"]
    assert wire["source"] == source and wire["updated"] == version
    assert wire["version"] == version
    with serving(app) as url:
        client = connected((url,))
        item, = client.maps()
        assert item.source == source and item.updated == version
        destination = tmp_path / "long-metadata.mbtiles"
        client.download(item, destination)
        client.disconnect()
    note = json.loads(destination.with_name(destination.name + ".source.json").read_text())
    assert note["source"] == source and note["updated"] == version


@pytest.mark.parametrize("kind", ["geocoder", "router"])
def test_legacy_provider_without_license_has_an_explicit_migration_error(tmp_path, kind):
    configuration = {"version": 1, kind: {
        "url": "https://provider.example", "name": "Original synthetic provider",
        "attribution": "Original synthetic fixture attribution",
    }}
    with pytest.raises(ValueError, match="(?i)license") as raised:
        map_portal.Portal(configuration, folder=tmp_path)
    message = str(raised.value).lower()
    assert any(word in message for word in ("required", "add", "must", "missing", "supply"))


@pytest.mark.parametrize("host", ["portal.example", "localhost.attacker.example", "127.0.0.1:8766"])
def test_wsgi_rejects_unconfigured_host_even_with_matching_origin(portal, host):
    status, _, _ = invoke(portal[1], "/api/v1/search", "POST", {"query": "Fictional"},
                          {"HTTP_HOST": host, "HTTP_ORIGIN": "http://" + host})
    assert status.startswith("403")
    assert not portal[2]


def test_wsgi_accepts_explicit_public_origin_for_https_proxy_host(tmp_path):
    app = map_portal.Portal({"version": 1, "public_origin": "https://maps.example"}, folder=tmp_path)
    status, _, raw = invoke(app, "/api/v1/status", headers={
        "HTTP_HOST": "maps.example", "HTTP_ORIGIN": "https://maps.example", "wsgi.url_scheme": "https",
    })
    assert status.startswith("200") and json.loads(raw)["api_version"] == 1


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
        with pytest.raises(ValueError, match="owned or contracted|licensed service|community.*demo"):
            map_portal.Provider({"url": url, "name": "No default", "attribution": "Example",
                                 "license": "Original synthetic fixture data"}, "geocoder")


@pytest.mark.parametrize("coordinates", [[[0, float("nan")], [1, 1]], [[0, 91], [1, 1]], [[True, 0], [1, 1]], [[0, 0]]])
def test_invalid_route_geometry_never_becomes_a_saved_file(coordinates):
    valid = {"profile": "driving", "coordinates": [[0, 0], [1, 1]], "source": "Fixture",
             "attribution": "Fixture", "license": "Original synthetic fixture data",
             "created_at": "2026-10-04T00:00:00Z", "distance_m": 1, "duration_s": 1}
    assert parse_gpx(online.route_gpx(valid)).point_count == 2
    with pytest.raises(ValueError):
        online.route_gpx({**valid, "coordinates": coordinates})


def test_new_file_write_preserves_existing_destination(tmp_path):
    path = tmp_path / "saved.csv"
    path.write_bytes(b"already saved")
    with pytest.raises(FileExistsError):
        online.save_new(path, b"replacement")
    assert path.read_bytes() == b"already saved" and not list(tmp_path.glob(".fieldforge-*"))


def test_portal_assets_are_local_with_restrictive_csp(portal):
    status, headers, body = invoke(portal[1], "/")
    assert status.startswith("200") and b"Address" in body
    assert b"Worldwide map sources and purchase holds" in body
    assert b"MapTiler On-prem Standard" in body and b"excludes B2C/B2B" in body
    assert b"basic offline preview style" in body and b"bounded labels for named points, roads, and areas" in body
    assert b"four user-shared OSM packages cover Kansas, Nebraska, North Dakota and South Dakota" in body
    assert b"Prepared regional map" in body and b"Import package ZIP" in body
    assert b"portal does not host these files yet" in body
    assert body.count(b'href="https://download.geofabrik.de/north-america/us/') == 53
    assert b"Download a regional PBF (53 areas)" in body
    assert b"U.S. Virgin Islands" in body and b"district-of-columbia-latest.osm.pbf" in body
    assert b"not a routing graph or driving directions" in body
    external_links = re.findall(rb'<a href="(https://[^"]+)"[^>]*>', body)
    allowed_hosts = (b"download.geofabrik.de", b"operations.osmfoundation.org",
                     b"www.maptiler.com", b"distribution.charts.noaa.gov", b"www.redcross.org",
                     b"www.ready.gov", b"www.dla.mil", b"www.gsa.gov", b"www.usa.gov")
    assert len(external_links) == 14
    for link in external_links:
        assert any(host in link for host in allowed_hosts)
        element = re.search(rb'<a href="' + re.escape(link) + rb'"[^>]*>', body).group(0)
        assert b'target="_blank"' in element and b'rel="noopener noreferrer"' in element
    policy = headers["Content-Security-Policy"]
    assert "default-src 'none'" in policy and "connect-src 'self'" in policy
    assert "'unsafe-inline'" not in policy and "'unsafe-eval'" not in policy
    inline_scripts = re.findall(rb"<script>(.*?)</script>", body, flags=re.S)
    if inline_scripts:
        for script in inline_scripts:
            digest = base64.b64encode(hashlib.sha256(script).digest()).decode()
            assert f"'sha256-{digest}'" in policy
    else:
        assert "script-src 'self'" in policy
    assert b"cdn" not in body
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


def test_checksum_matching_but_undecodable_image_is_rejected_before_serving(tmp_path, map_entry):
    source = tmp_path / "fake.png"
    source.write_bytes(b"not an image")
    entry = {**map_entry, "filename": source.name, "kind": "image", "size": source.stat().st_size,
             "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    with pytest.raises(ValueError):
        map_portal.Portal({"version": 1, "maps": [entry]}, folder=tmp_path)
    assert not (tmp_path / "saved.png").exists() and not list(tmp_path.glob(".fieldforge-*"))
    assert not list(tmp_path.glob("*.source.json"))


@pytest.mark.parametrize("change", [{"version": True}, {"providers": []}, {"providers": {"geocoding": None}},
                                   {"name": None}, {"capabilities": {"geocoding": "true", "routing": False}}])
def test_malformed_status_does_not_enable_connection(monkeypatch, change):
    valid = {"version": 1, "name": "Fixture", "providers": {"geocoding": {
        "name": "Fixture", "attribution": "Fixture", "license": "Original synthetic fixture data"}},
        "capabilities": {"geocoding": True, "routing": False}}
    monkeypatch.setattr(compat, "request_json", lambda *a, **kw: valid)
    baseline = online.PortalSession()
    baseline.connect("https://portal.example", consent=True)
    assert baseline.ready
    baseline.disconnect()
    status = {**valid, **change}
    monkeypatch.setattr(compat, "request_json", lambda *a, **kw: status)
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
