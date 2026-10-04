"""Portal integration checks using synthetic data and loopback-only providers.

These tests also run without pytest:
    python -m unittest discover -s tests -p test_online_server.py
"""

import contextlib
import hashlib
import http.client
import io
import json
import os
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fieldforge.online.catalog import Catalog, publish_map
from fieldforge.online.models import validate_asset, validate_route, validate_search_result
from fieldforge.online.server import PortalApplication, PortalConfig, PortalError, make_server


def _png_bytes(width=1, height=1):
    """A valid synthetic PNG, compressing large grayscale fixtures a row at a time."""
    def chunk(kind, body):
        checksum = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", checksum)

    if width == height == 1:
        color_type = 2
        compressed = zlib.compress(b"\x00\x11\x22\x33")
    else:
        color_type = 0
        compressor = zlib.compressobj()
        row = b"\x00" + b"\x55" * width
        pieces = []
        for _ in range(height):
            part = compressor.compress(row)
            if part:
                pieces.append(part)
        pieces.append(compressor.flush())
        compressed = b"".join(pieces)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def _provider_route(*, distance=1234.0, duration=180.0, via=(-75.005, 40.01)):
    return {
        "distance": distance,
        "duration": duration,
        "geometry": {
            "type": "LineString",
            "coordinates": [[-75.0, 40.0], list(via), [-75.01, 40.02]],
        },
        "legs": [{
            "summary": "Fixture Road",
            "steps": [
                {"name": "Fixture Road", "distance": 800, "duration": 90,
                 "maneuver": {"type": "depart", "location": [-75.0, 40.0]}},
                {"name": "Test Lane", "distance": 434, "duration": 90,
                 "maneuver": {"type": "turn", "modifier": "right",
                              "location": list(via)}},
                {"name": "", "distance": 0, "duration": 0,
                 "maneuver": {"type": "arrive", "location": [-75.01, 40.02]}},
            ],
        }],
    }


class _FakeProvider:
    """Actual HTTP provider with captured requests and replaceable fixture bodies."""

    def __init__(self):
        self.requests = []
        self.geocoding = [{
            "place_id": 17,
            "display_name": "Fixture Depot A, Test County",
            "lat": "40.0", "lon": "-75.0",
            "boundingbox": ["39.99", "40.01", "-75.01", "-74.99"],
            "licence": "Fixture data only",
        }]
        self.routing = {"code": "Ok", "routes": [
            _provider_route(),
            _provider_route(distance=1500, duration=210, via=(-75.008, 40.012)),
        ]}
        self.http_status = 200
        self.raw_body = None
        self.redirect = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append({
                    "path": self.path,
                    "headers": dict(self.headers),
                })
                if owner.redirect:
                    self.send_response(302)
                    self.send_header("Location", owner.redirect)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                payload = owner.routing if "/route/" in self.path else owner.geocoding
                data = owner.raw_body if owner.raw_body is not None else json.dumps(payload).encode()
                self.send_response(owner.http_status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True,
        )
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _raw_config(root, provider=None):
    raw = {"host": "127.0.0.1", "port": 0, "catalog_root": str(root),
           "allow_loopback_http": True}
    if provider is not None:
        raw["providers"] = {
            "geocoding": {"url": provider.url + "/search", "attribution": "Fixture geocoder",
                          "license": "Original fixture data"},
            "routing": {"url": provider.url, "attribution": "Fixture router",
                        "license": "Original fixture data"},
        }
    return raw


class ConfigSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_provider_connections_require_explicit_attribution_and_license(self):
        for field in ("attribution", "license"):
            with self.subTest(field=field):
                provider = {"url": "https://geocoder.example.test/search",
                            "attribution": "Fixture", "license": "Fixture"}
                del provider[field]
                raw = _raw_config(self.root)
                raw["providers"] = {"geocoding": provider}
                with self.assertRaises(ValueError):
                    PortalConfig.from_dict(raw)

    def test_provider_url_rejects_insecure_or_ambiguous_destinations(self):
        urls = (
            "http://public.example.test/search",
            "https://user:secret@example.test/search",
            "https://example.test/search?token=secret",
            "https://example.test/search#fragment",
            "file:///etc/passwd",
            "https://nominatim.openstreetmap.org/search",
            "https://router.project-osrm.org",
        )
        for url in urls:
            with self.subTest(url=url):
                raw = _raw_config(self.root)
                raw["providers"] = {"geocoding": {
                    "url": url, "attribution": "Fixture", "license": "Fixture",
                }}
                with self.assertRaises(ValueError):
                    PortalConfig.from_dict(raw)

    def test_loopback_http_is_opt_in(self):
        raw = _raw_config(self.root)
        raw["allow_loopback_http"] = False
        raw["providers"] = {"geocoding": {
            "url": "http://127.0.0.1:8766/search", "attribution": "Fixture", "license": "Fixture",
        }}
        with self.assertRaises(ValueError):
            PortalConfig.from_dict(raw)
        raw["allow_loopback_http"] = True
        self.assertIsInstance(PortalConfig.from_dict(raw), PortalConfig)

    def test_boolean_fields_do_not_accept_truthy_strings(self):
        for value in ("true", "false", 1):
            with self.subTest(value=value):
                raw = _raw_config(self.root)
                raw["allow_loopback_http"] = value
                with self.assertRaises(ValueError):
                    PortalConfig.from_dict(raw)

    def test_unconfigured_services_are_disabled_and_cannot_silently_use_public_providers(self):
        app = PortalApplication(PortalConfig.from_dict(_raw_config(self.root)))
        status = app.status()
        self.assertIs(status["geocoding"], False)
        self.assertIs(status["routing"], False)
        self.assertEqual(status["route_modes"], [])
        with self.assertRaises(ValueError):
            app.search("Fixture Depot A")
        with self.assertRaises(ValueError):
            app.routes({"latitude": 40, "longitude": -75},
                       {"latitude": 40.02, "longitude": -75.01}, "driving")


class ProviderIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.provider = _FakeProvider()
        self.addCleanup(self.provider.close)
        self.app = PortalApplication(PortalConfig.from_dict(_raw_config(self.root, self.provider)))

    def test_invalid_queries_never_reach_provider(self):
        for query in ("", "   ", "x" * 10000, "depot\x00name", True, 12, None, []):
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    self.app.search(query)
        self.assertEqual(self.provider.requests, [])

    def test_invalid_route_coordinates_never_reach_provider(self):
        invalid = (True, float("nan"), float("inf"), -float("inf"), 91, -91, 10**1000)
        for latitude in invalid:
            with self.subTest(latitude=latitude):
                with self.assertRaises(ValueError):
                    self.app.routes({"latitude": latitude, "longitude": -75},
                                    {"latitude": 40.02, "longitude": -75.01}, "driving")
        for longitude in (True, float("nan"), 181, -181):
            with self.subTest(longitude=longitude):
                with self.assertRaises(ValueError):
                    self.app.routes({"latitude": 40, "longitude": longitude},
                                    {"latitude": 40.02, "longitude": -75.01}, "driving")
        self.assertEqual(self.provider.requests, [])

    def test_non_driving_mode_is_rejected_before_provider_request(self):
        with self.assertRaises(ValueError):
            self.app.routes({"latitude": 40, "longitude": -75},
                            {"latitude": 40.02, "longitude": -75.01}, "flying")
        self.assertEqual(self.provider.requests, [])

    def test_provider_redirects_are_not_followed(self):
        # Even a same-host redirect must not become an implicit new provider.
        self.provider.redirect = self.provider.url + "/redirect-target"
        with self.assertRaises(ValueError):
            self.app.search("Fixture Depot A")
        self.assertEqual(len(self.provider.requests), 1)

    def test_provider_http_error_does_not_expose_response_body(self):
        self.provider.http_status = 500
        self.provider.raw_body = b"PRIVATE_PROVIDER_DEBUG_STRING_392"
        with self.assertRaises(ValueError) as raised:
            self.app.search("Fixture Depot A")
        self.assertNotIn("PRIVATE_PROVIDER_DEBUG_STRING_392", str(raised.exception))

    def test_invalid_or_oversized_provider_json_is_rejected(self):
        config = _raw_config(self.root, self.provider)
        config["max_upstream_bytes"] = 1024
        app = PortalApplication(PortalConfig.from_dict(config))
        for body in (b"not json", b"[NaN]", b"[" + b" " * 1024 + b"]"):
            with self.subTest(bytes=len(body)):
                self.provider.raw_body = body
                with self.assertRaises(ValueError):
                    app.search("Fixture Depot A")

    def test_search_preserves_location_and_provenance(self):
        result = self.app.search("Fixture Depot A")
        rows = result["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "Fixture Depot A, Test County")
        self.assertEqual(rows[0]["latitude"], 40.0)
        self.assertEqual(rows[0]["longitude"], -75.0)
        self.assertEqual(rows[0]["attribution"], "Fixture geocoder")
        self.assertEqual(rows[0]["license"], "Original fixture data")
        self.assertTrue(rows[0]["source"])
        self.assertTrue(rows[0]["retrieved_at"])
        self.assertEqual(validate_search_result(rows[0]), rows[0])
        request = urllib.parse.urlsplit(self.provider.requests[0]["path"])
        query = urllib.parse.parse_qs(request.query)
        self.assertEqual(request.path, "/search")
        self.assertEqual(query["q"], ["Fixture Depot A"])
        self.assertEqual(query["format"], ["jsonv2"])

    def test_search_empty_response_does_not_reuse_previous_results(self):
        self.assertTrue(self.app.search("Fixture Depot A")["results"])
        self.provider.geocoding = []
        self.assertEqual(self.app.search("Missing fixture depot"), {"results": []})

    def test_route_alternatives_keep_distinct_geometry_and_written_steps(self):
        start = {"latitude": 40, "longitude": -75}
        end = {"latitude": 40.02, "longitude": -75.01}
        routes = self.app.routes(start, end, "driving")["routes"]
        self.assertEqual(len(routes), 2)
        self.assertNotEqual(routes[0]["id"], routes[1]["id"])
        self.assertEqual(routes[0]["distance_m"], 1234)
        self.assertEqual(routes[1]["distance_m"], 1500)
        for actual, expected in zip(routes, self.provider.routing["routes"]):
            self.assertEqual(validate_route(actual), actual)
            self.assertEqual(actual["geometry"], expected["geometry"]["coordinates"])
            self.assertEqual(actual["start"], start)
            self.assertEqual(actual["end"], end)
            self.assertEqual(actual["mode"], "driving")
            self.assertEqual(actual["attribution"], "Fixture router")
            self.assertEqual(actual["license"], "Original fixture data")
            self.assertEqual(len(actual["steps"]), 3)
            self.assertTrue(all(step["instruction"].strip() for step in actual["steps"]))
            turn = actual["steps"][1]
            self.assertIn("right", turn["instruction"].lower())
            self.assertIn("Test Lane", turn["instruction"])
            self.assertEqual(turn["latitude"], expected["geometry"]["coordinates"][1][1])
            self.assertEqual(turn["longitude"], expected["geometry"]["coordinates"][1][0])
        request = urllib.parse.urlsplit(self.provider.requests[0]["path"])
        query = urllib.parse.parse_qs(request.query)
        self.assertIn("/route/v1/driving/", request.path)
        pairs = request.path.rsplit("/", 1)[1].split(";")
        self.assertEqual([[float(v) for v in pair.split(",")] for pair in pairs],
                         [[-75.0, 40.0], [-75.01, 40.02]])
        self.assertEqual(query["geometries"], ["geojson"])
        self.assertEqual(query["steps"], ["true"])
        self.assertEqual(query["alternatives"], ["true"])

    def test_no_route_is_empty_and_never_becomes_a_straight_line_route(self):
        self.provider.routing = {"code": "NoRoute", "routes": []}
        response = self.app.routes({"latitude": 40, "longitude": -75},
                                   {"latitude": 40.02, "longitude": -75.01}, "driving")
        self.assertEqual(response, {"routes": []})

    def test_osrm_http400_no_route_and_no_segment_are_empty_results(self):
        self.provider.http_status = 400
        for code in ("NoRoute", "NoSegment"):
            for message in (None, "Impossible route between points"):
                with self.subTest(code=code, message=message):
                    self.provider.routing = {"code": code}
                    if message is not None:
                        self.provider.routing["message"] = message
                    response = self.app.routes({"latitude": 40, "longitude": -75},
                                               {"latitude": 40.02, "longitude": -75.01}, "driving")
                    self.assertEqual(response, {"routes": []})

    def test_osrm_http400_special_case_does_not_swallow_other_upstream_errors(self):
        config = _raw_config(self.root, self.provider)
        config["max_upstream_bytes"] = 1024
        app = PortalApplication(PortalConfig.from_dict(config))
        cases = (
            (400, b"not JSON"),
            (400, b"[]"),
            (400, b'{"code":["NoRoute"]}'),
            (400, b'{"code":"NoRoute","message":[]}'),
            (400, b'{"code":"NoRoute","message":"\\ud800"}'),
            (400, b'{"code":"NoRoute","code":"NoSegment"}'),
            (400, b'{"code":"InvalidQuery","message":"Invalid request"}'),
            (400, b'{"code":"Ok","routes":[]}'),
            (400, json.dumps({"code": "NoRoute", "message": "x" * 1100}).encode()),
            (500, b'{"code":"NoRoute","message":"Impossible route between points"}'),
        )
        for status, body in cases:
            with self.subTest(status=status, body=body[:80], bytes=len(body)):
                self.provider.http_status = status
                self.provider.raw_body = body
                with self.assertRaises(PortalError) as raised:
                    app.routes({"latitude": 40, "longitude": -75},
                               {"latitude": 40.02, "longitude": -75.01}, "driving")
                self.assertEqual(raised.exception.status, 502)

    def test_geocoder_http400_does_not_gain_routing_error_exemption(self):
        self.provider.http_status = 400
        self.provider.raw_body = b'{"code":"NoRoute","message":"Impossible route between points"}'
        with self.assertRaises(PortalError) as raised:
            self.app.search("Fixture Depot A")
        self.assertEqual(raised.exception.status, 502)

    def test_invalid_provider_coordinates_cannot_become_saved_locations(self):
        for value in ("NaN", "Infinity", "91", True):
            with self.subTest(latitude=value):
                self.provider.geocoding[0]["lat"] = value
                with self.assertRaises(ValueError):
                    self.app.search("Fixture Depot A")

    def test_invalid_provider_labels_fail_before_emitting_incompatible_json(self):
        for label in ("\ud800", "name\x85control", "\u202ereversed label"):
            with self.subTest(label=ascii(label)):
                self.provider.geocoding[0]["display_name"] = label
                with self.assertRaises(ValueError):
                    self.app.search("Fixture Depot A")


class CatalogIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "catalog"
        self.source = Path(self.temp.name) / "private-source-grid.png"
        self.source.write_bytes(_png_bytes())

    def publish(self, **changes):
        values = {"map_id": "fixture-grid-v1", "title": "Synthetic test grid",
                  "attribution": "Original FieldForge fixture", "license": "Original test data",
                  "coverage": "Synthetic one-pixel image; no real geographic coverage", "version": "1"}
        values.update(changes)
        return publish_map(self.root, self.source, **values)

    def test_published_digest_and_download_match_exact_source_bytes(self):
        source_bytes = self.source.read_bytes()
        asset = self.publish()
        self.assertEqual(asset["bytes"], len(source_bytes))
        self.assertEqual(asset["sha256"], hashlib.sha256(source_bytes).hexdigest())
        self.assertEqual(asset["download_path"], "/api/v1/maps/fixture-grid-v1/download")
        self.assertEqual(asset["format"], "png")
        self.assertEqual(validate_asset(asset), asset)
        self.assertEqual(Catalog(self.root).assets(), [asset])
        published, stream = Catalog(self.root).open_asset(asset["id"])
        with stream:
            self.assertEqual(stream.read(), source_bytes)
        self.assertEqual(published, asset)
        self.assertNotIn("storage_path", asset)
        self.assertNotIn(str(self.source), (self.root / "catalog.json").read_text())

    def test_source_changes_after_publication_do_not_change_published_map(self):
        original = self.source.read_bytes()
        asset = self.publish()
        self.source.write_bytes(b"User changed the original source after publication")
        _, stream = Catalog(self.root).open_asset(asset["id"])
        with stream:
            self.assertEqual(stream.read(), original)

    def test_duplicate_id_cannot_replace_a_published_asset(self):
        first = self.publish()
        index_before = (self.root / "catalog.json").read_bytes()
        with self.assertRaises(ValueError):
            self.publish(title="Unexpected replacement")
        self.assertEqual((self.root / "catalog.json").read_bytes(), index_before)
        self.assertEqual(Catalog(self.root).assets(), [first])

    def test_republished_bytes_can_share_storage_under_distinct_immutable_ids(self):
        first = self.publish()
        second = self.publish(map_id="fixture-grid-v2", version="2")
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(len(Catalog(self.root).assets()), 2)
        self.assertEqual(len(list((self.root / "objects").iterdir())), 1)

    def test_publish_rejects_unlicensed_and_traversal_metadata(self):
        cases = ({"license": ""}, {"attribution": ""}, {"map_id": "../escape"},
                 {"map_id": "a/b"}, {"map_id": "a\\b"}, {"map_id": "%2e%2e"},
                 {"coverage": [0, False, 1, 1]}, {"coverage": [0, 0, 1, float("nan")]})
        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.publish(**changes)
        self.assertEqual(Catalog(self.root).assets(), [])

    def test_catalog_cannot_redirect_storage_outside_object_directory(self):
        asset = self.publish()
        index = self.root / "catalog.json"
        data = json.loads(index.read_text())
        data["maps"][0]["storage_path"] = "../private-source-grid.png"
        index.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            Catalog(self.root).open_asset(asset["id"])

    def test_object_symlink_is_rejected_even_when_file_size_matches(self):
        asset = self.publish()
        object_path = next((self.root / "objects").iterdir())
        object_path.unlink()
        try:
            object_path.symlink_to(self.source)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable on this platform")
        with self.assertRaises(ValueError):
            Catalog(self.root).open_asset(asset["id"])

    def test_wrong_image_signature_does_not_publish_catalog_entry(self):
        self.source.write_bytes(b"not an image")
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(Catalog(self.root).assets(), [])

    def test_catalog_format_has_a_controlled_validation_error_for_non_text(self):
        self.publish()
        index = self.root / "catalog.json"
        data = json.loads(index.read_text())
        data["maps"][0]["format"] = []
        index.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            Catalog(self.root).assets()

    def test_image_above_desktop_limit_is_rejected_before_publication(self):
        with self.source.open("r+b") as stream:
            stream.truncate(64 * 1024**2 + 1)
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(Catalog(self.root).assets(), [])

    def test_png_at_exact_32_million_pixel_limit_can_be_published(self):
        self.source.write_bytes(_png_bytes(width=8000, height=4000))
        asset = self.publish()
        self.assertEqual(asset["format"], "png")
        self.assertEqual(asset["sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(validate_asset(asset), asset)
        self.assertEqual(Catalog(self.root).assets(), [asset])

    def test_small_compressed_png_above_pixel_limit_cannot_be_published(self):
        self.source.write_bytes(_png_bytes(width=8000, height=4100))
        self.assertLess(self.source.stat().st_size, 1024 * 1024)
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(Catalog(self.root).assets(), [])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Named pipes require POSIX")
    def test_pipe_source_is_rejected_without_waiting_for_a_writer(self):
        self.source.unlink()
        os.mkfifo(self.source)
        # A timeout contains the regression if opening a source ever becomes blocking again.
        result = subprocess.run([
            sys.executable, "-m", "fieldforge.online.catalog", "add",
            "--root", str(self.root), "--file", str(self.source),
            "--id", "pipe-fixture", "--title", "Synthetic pipe fixture",
            "--attribution", "Original fixture", "--license", "Original test data",
            "--coverage", "None", "--version", "1",
        ], capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("regular", result.stderr)
        self.assertEqual(Catalog(self.root).assets(), [])

    def test_raster_mbtiles_publishes_but_vector_mbtiles_does_not(self):
        self.source = Path(self.temp.name) / "fixture.mbtiles"
        with sqlite3.connect(self.source) as db:
            db.execute("CREATE TABLE metadata(name TEXT,value TEXT)")
            db.execute("CREATE TABLE tiles(zoom_level INTEGER,tile_column INTEGER,"
                       "tile_row INTEGER,tile_data BLOB)")
            db.execute("CREATE UNIQUE INDEX tile_index ON tiles(zoom_level,tile_column,tile_row)")
            db.execute("INSERT INTO metadata VALUES('format','png')")
            db.execute("INSERT INTO metadata VALUES('name','Synthetic raster fixture')")
            db.execute("INSERT INTO tiles VALUES(0,0,0,?)", (_png_bytes(),))
        asset = self.publish()
        self.assertEqual(asset["format"], "mbtiles")
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE metadata SET value='pbf' WHERE name='format'")
        with self.assertRaises(ValueError):
            self.publish(map_id="vector-fixture")
        self.assertEqual(Catalog(self.root).assets(), [asset])


class PortalHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "catalog"
        self.provider = _FakeProvider()
        self.addCleanup(self.provider.close)
        self.server = make_server(PortalConfig.from_dict(_raw_config(self.root, self.provider)))
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True,
        )
        self.thread.start()
        self.addCleanup(self.close_portal)

    def close_portal(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, payload=None, *, headers=None, raw=None):
        data = raw if raw is not None else (
            None if payload is None else json.dumps(payload).encode()
        )
        request_headers = {"Content-Type": "application/json"} if data is not None else {}
        request_headers.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=data, headers=request_headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_status_reports_explicit_providers_and_no_automatic_provider_calls(self):
        status, headers, raw = self.request("GET", "/api/v1/status")
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertEqual(data["api_version"], 1)
        self.assertTrue(data["geocoding"])
        self.assertTrue(data["routing"])
        self.assertEqual(data["route_modes"], ["driving"])
        self.assertNotEqual(headers.get("Access-Control-Allow-Origin"), "*")
        self.assertEqual(self.provider.requests, [])

    def test_search_requires_post_and_does_not_put_addresses_in_server_logs(self):
        query = "PRIVATE_QUERY_MARKER_5814 Fixture Depot A"
        logs = io.StringIO()
        with contextlib.redirect_stderr(logs), contextlib.redirect_stdout(logs):
            status, headers, body = self.request("POST", "/api/v1/search", {"query": query})
            bad_status, _, _ = self.request("GET", "/api/v1/search?query=" +
                                            urllib.parse.quote(query))
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["results"])
        self.assertIn(bad_status, (400, 404, 405))
        self.assertNotIn(query, logs.getvalue())
        self.assertNotIn("PRIVATE_QUERY_MARKER_5814", logs.getvalue())
        self.assertNotEqual(headers.get("Access-Control-Allow-Origin"), "*")
        self.assertEqual(len(self.provider.requests), 1)

    def test_cross_origin_browser_post_is_blocked_without_reaching_provider(self):
        status, headers, _ = self.request("POST", "/api/v1/search", {"query": "Fixture Depot A"},
                                          headers={"Origin": "https://unrelated.example.test"})
        self.assertEqual(status, 403)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(self.provider.requests, [])

    def test_same_origin_browser_can_submit_an_address(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        status, _, body = self.request("POST", "/api/v1/search", {"query": "Fixture Depot A"},
                                       headers={"Origin": origin})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["results"])
        self.assertEqual(len(self.provider.requests), 1)

    def test_invalid_and_oversized_json_requests_never_reach_provider(self):
        bodies = (b"not json", b"[]", b"null", b'{"query":true}',
                  b'{"query":"\\ud800"}', b'{"query":"first","query":"second"}',
                  json.dumps({"query": "x" * 200000}).encode())
        for body in bodies:
            with self.subTest(bytes=len(body)):
                status, _, _ = self.request("POST", "/api/v1/search", raw=body)
                self.assertIn(status, (400, 413))
        self.assertEqual(self.provider.requests, [])

    def test_json_api_rejects_form_or_plain_text_submissions(self):
        for content_type in ("application/x-www-form-urlencoded", "text/plain"):
            with self.subTest(content_type=content_type):
                status, _, _ = self.request("POST", "/api/v1/search", {"query": "Fixture Depot A"},
                                             headers={"Content-Type": content_type})
                self.assertEqual(status, 415)
        self.assertEqual(self.provider.requests, [])

    def test_osrm_http400_no_route_is_portal_http200_with_empty_routes(self):
        self.provider.http_status = 400
        payload = {"start": {"latitude": 40, "longitude": -75},
                   "end": {"latitude": 40.02, "longitude": -75.01}, "mode": "driving"}
        for code in ("NoRoute", "NoSegment"):
            with self.subTest(code=code):
                self.provider.routing = {"code": code, "message": "Impossible route between points"}
                status, _, raw = self.request("POST", "/api/v1/routes", payload)
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(raw), {"routes": []})

    def test_published_map_download_and_catalog_have_matching_checksum(self):
        source = Path(self.temp.name) / "fixture.png"
        source.write_bytes(_png_bytes())
        asset = publish_map(self.root, source, map_id="map-v1", title="Synthetic grid",
                            attribution="Original fixture", license="Original test data",
                            coverage="Test image only", version="1")
        status, _, raw = self.request("GET", "/api/v1/maps")
        self.assertEqual(status, 200)
        wire, = json.loads(raw)["maps"]
        self.assertEqual({key: wire[key] for key in asset}, asset)
        self.assertEqual(wire["kind"], "image")
        self.assertEqual(wire["size"], asset["bytes"])
        self.assertEqual(wire["updated"], asset["version"])
        self.assertEqual(validate_asset(wire), {**asset, "source": "Source not supplied; served by FieldForge"})
        status, headers, data = self.request("GET", asset["download_path"])
        self.assertEqual(status, 200)
        self.assertEqual(data, source.read_bytes())
        self.assertEqual(headers["Content-Length"], str(asset["bytes"]))
        self.assertEqual(hashlib.sha256(data).hexdigest(), asset["sha256"])
        self.assertNotIn(str(self.root), raw.decode())

    def test_download_paths_cannot_traverse_outside_catalog(self):
        for path in ("/api/v1/maps/../download", "/api/v1/maps/%2e%2e/download",
                     "/api/v1/maps/..%2f..%2fprivate-source-grid.png/download",
                     "/api/v1/maps/catalog.json/download"):
            with self.subTest(path=path):
                status, _, _ = self.request("GET", path)
                self.assertIn(status, (400, 404))


if __name__ == "__main__":
    unittest.main()
