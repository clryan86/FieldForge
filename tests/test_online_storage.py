"""Saved portal plans are local, bounded, reviewable and never overwritten."""

import json
import socket
from xml.etree import ElementTree as ET

import pytest
from test_online_client import Response, asset, connected, png, route

from fieldforge.online import PortalLibrary, models
from fieldforge.online.models import ValidationError
from fieldforge_gps.gpx_review import parse_gpx


def test_route_and_instructions_survive_restart_and_network_failure(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Offline route storage attempted network I/O")

    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    library = PortalLibrary(tmp_path / "offline")
    saved = library.save_route(route())
    original = saved.read_bytes()
    restarted = PortalLibrary(library.root)
    assert restarted.routes() == (saved,)
    assert restarted.load_route(saved) == route()
    assert restarted.save_route(route()) == saved and saved.read_bytes() == original
    assert json.loads(original)["kind"] == "planned-route"
    assert restarted.load_route(saved)["steps"][0]["instruction"] == route()["steps"][0]["instruction"]


def test_browser_route_download_imports_then_reopens_offline_without_changing_source(tmp_path, monkeypatch):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    source = downloads / "browser-route.json"
    envelope = {"schema_version": 1, "kind": "planned-route",
                "saved_at": "2026-10-04T00:10:00Z", "route": route()}
    source.write_text(json.dumps(envelope), encoding="utf-8")
    original = source.read_bytes()
    library = PortalLibrary(tmp_path / "workspace")

    def fail(*args, **kwargs):
        raise AssertionError("Importing a downloaded route must work without network")

    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    imported = library.import_route(source)
    assert imported.parent == library.routes_directory and imported != source
    assert source.read_bytes() == original
    reopened = PortalLibrary(library.root)
    assert reopened.load_route(imported) == route()
    assert reopened.routes() == (imported,)
    saved_bytes = imported.read_bytes()
    assert reopened.import_route(source) == imported
    assert imported.read_bytes() == saved_bytes and source.read_bytes() == original


@pytest.mark.parametrize("change", [
    {"schema_version": True}, {"schema_version": 2}, {"kind": "recorded-trip"},
    {"saved_at": "2026-10-04T00:10:00"}, {"destination": "../../outside.json"},
    {"route": {**route(), "geometry": [[-75, 99], [-75, 39]]}},
    {"route": {**route(), "id": "../../outside"}},
    {"route": {**route(), "geometry": [[-75, float("nan")], [-75, 39]]}},
])
def test_invalid_downloaded_route_is_not_published_and_source_stays_unchanged(tmp_path, change):
    source = tmp_path / "unsafe-route.json"
    envelope = {"schema_version": 1, "kind": "planned-route",
                "saved_at": "2026-10-04T00:10:00Z", "route": route(), **change}
    source.write_text(json.dumps(envelope))
    original = source.read_bytes()
    library = PortalLibrary(tmp_path / "workspace")
    with pytest.raises(ValidationError):
        library.import_route(source)
    assert not list(library.routes_directory.iterdir())
    assert source.read_bytes() == original


def test_import_rejects_symbolic_links_and_oversized_json_before_publication(tmp_path):
    source = tmp_path / "route.json"
    source.write_text(json.dumps({"schema_version": 1, "kind": "planned-route",
                                 "saved_at": "2026-10-04T00:10:00Z", "route": route()}))
    link = tmp_path / "linked-route.json"
    link.symlink_to(source)
    original = source.read_bytes()
    library = PortalLibrary(tmp_path / "workspace")
    with pytest.raises(ValidationError):
        library.import_route(link)
    assert source.read_bytes() == original
    oversized = tmp_path / "oversized-route.json"
    with oversized.open("wb") as stream:
        stream.truncate(8 * 1024**2 + 1)
    with pytest.raises(ValidationError, match="8 MiB"):
        library.import_route(oversized)
    assert not list(library.routes_directory.iterdir())


def test_normalized_route_byte_budget_reserves_complete_saved_envelope(tmp_path):
    # A maximum-geometry/step route near the byte limit also exercises browser
    # JSON's shorter integer spelling and UTF-8 text, not just an ASCII toy case.
    planned = route()
    planned["geometry"] = [[-75, 39] for _ in range(models.MAX_ROUTE_POINTS)]
    planned["steps"] = [
        {"instruction": "é", "distance_m": 1, "duration_s": 1,
         "latitude": 39, "longitude": -75}
        for _ in range(models.MAX_ROUTE_STEPS)
    ]
    baseline = len(models.encode_json(models.validate_route(planned)))
    remaining = models.MAX_ROUTE_JSON_BYTES - baseline
    for step in planned["steps"]:
        addition = min(999, remaining)
        step["instruction"] += "x" * addition
        remaining -= addition
    assert remaining == 0
    normalized = models.validate_route(planned)
    assert len(models.encode_json(normalized)) == models.MAX_ROUTE_JSON_BYTES

    source = tmp_path / "browser-large-route.json"
    envelope = {"schema_version": 1, "kind": "planned-route",
                "saved_at": "2026-10-04T00:10:00.123Z", "route": planned}
    browser_bytes = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(browser_bytes) < models.MAX_JSON_BYTES
    source.write_bytes(browser_bytes)
    library = PortalLibrary(tmp_path / "workspace")
    imported = library.import_route(source)
    assert imported.stat().st_size <= models.MAX_JSON_BYTES
    assert library.load_route(imported) == normalized
    assert source.read_bytes() == browser_bytes
    original = imported.read_bytes()
    assert library.import_route(source) == imported and imported.read_bytes() == original

    # A raw browser file can fit while its canonical route exceeds the reserve.
    # Validation must fail before another local route becomes available.
    planned["steps"][-1]["instruction"] += "x"
    with pytest.raises(ValidationError, match="saved JSON envelope"):
        models.validate_route(planned)
    source.write_text(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    assert source.stat().st_size < models.MAX_JSON_BYTES
    with pytest.raises(ValidationError, match="saved JSON envelope"):
        library.import_route(source)
    assert library.routes() == (imported,)


def test_routes_with_same_provider_id_keep_distinct_versions(tmp_path):
    library = PortalLibrary(tmp_path)
    old = library.save_route(route())
    updated = {**route(), "title": "Updated planned route"}
    new = library.save_route(updated)
    assert old != new and library.load_route(old) == route()
    assert set(library.routes()) == {old, new}


def test_route_files_and_metadata_are_revalidated_when_loaded(tmp_path):
    library = PortalLibrary(tmp_path)
    saved = library.save_route(route())
    value = json.loads(saved.read_text())
    value["route"]["geometry"][0][1] = 100
    saved.write_text(json.dumps(value))
    with pytest.raises(ValidationError, match="Latitude"):
        library.load_route(saved)
    with pytest.raises(ValidationError):
        library.routes()
    assert saved.exists()


@pytest.mark.parametrize("change", [{"schema_version": True}, {"schema_version": 2},
                                   {"kind": "recorded-trip"}, {"saved_at": "yesterday"},
                                   {"unexpected": "untrusted"}])
def test_invalid_route_envelopes_preserve_the_existing_file(tmp_path, change):
    library = PortalLibrary(tmp_path)
    saved = library.save_route(route())
    data = {**json.loads(saved.read_text()), **change}
    saved.write_text(json.dumps(data))
    before = saved.read_bytes()
    with pytest.raises(ValidationError):
        library.load_route(saved)
    assert saved.read_bytes() == before


def test_routes_cannot_be_loaded_outside_the_selected_workspace(tmp_path):
    first = PortalLibrary(tmp_path / "first")
    second = PortalLibrary(tmp_path / "second")
    outside = second.save_route(route())
    with pytest.raises(ValidationError, match="workspace"):
        first.load_route(outside)
    linked = first.routes_directory / "linked.route.json"
    linked.symlink_to(outside)
    with pytest.raises(ValidationError):
        first.load_route(linked)
    assert second.load_route(outside) == route()


def test_symlink_library_roots_and_replaced_storage_folders_are_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValidationError):
        PortalLibrary(linked)
    library = PortalLibrary(tmp_path / "workspace")
    library.routes_directory.rmdir()
    library.routes_directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValidationError):
        library.save_route(route())
    assert list(outside.iterdir()) == []


def test_planned_route_gpx_opens_in_existing_review_with_provenance_and_no_fake_times(tmp_path):
    library = PortalLibrary(tmp_path / "workspace")
    planned = route()
    planned["title"] = "<&> Planned " + "A" * 180
    planned["attribution"] = "Original test <geometry> & contributors"
    planned["geometry"] = [[180, 12.0000000001], [-179, 13.0000000001]]
    target = library.export_gpx(planned, tmp_path / "exported.gpx")
    raw = target.read_bytes()
    reviewed = parse_gpx(raw)
    assert reviewed.point_count == 2 and reviewed.ignored_routes == 0
    assert reviewed.tracks[0].name.startswith("PLANNED ROUTE")
    assert len(reviewed.tracks[0].name) <= 160
    assert reviewed.tracks[0].segments[0][0].longitude == -180
    assert reviewed.tracks[0].segments[0][0].latitude == 12.0000000001
    assert all(point.time_text is None for point in reviewed.tracks[0].segments[0])
    root = ET.fromstring(raw)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    assert root.find("g:metadata/g:time", ns).text == planned["created_at"]
    assert planned["attribution"] in root.find("g:metadata/g:desc", ns).text
    assert planned["license"] in root.find("g:trk/g:desc", ns).text
    assert root.find("g:trk/g:type", ns).text == "planned-route"


def test_export_never_replaces_an_existing_file_or_symlink(tmp_path):
    library = PortalLibrary(tmp_path / "workspace")
    target = tmp_path / "protected.gpx"
    target.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        library.export_gpx(route(), target)
    link = tmp_path / "linked.gpx"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        library.export_gpx(route(), link)
    assert target.read_bytes() == b"original" and link.is_symlink()


def test_failed_atomic_route_write_leaves_no_available_or_temporary_file(tmp_path, monkeypatch):
    from fieldforge.online import storage

    def fail(*args, **kwargs):
        raise OSError("Simulated publication failure")

    library = PortalLibrary(tmp_path)
    monkeypatch.setattr(storage, "_publish_new_path", fail)
    with pytest.raises(OSError):
        library.save_route(route())
    assert list(library.routes_directory.iterdir()) == [] and library.routes() == ()


def test_unfinished_or_unmanaged_maps_are_not_listed_as_downloaded(tmp_path):
    library = PortalLibrary(tmp_path)
    (library.maps_directory / "unmanaged.png").write_bytes(png(2))
    (library.maps_directory / ".partial-download.png").write_bytes(png(2))
    assert library.maps() == ()


def test_map_metadata_cannot_escape_folder_or_claim_a_partial_file(tmp_path):
    library = PortalLibrary(tmp_path)
    client, _ = connected(Response(png(2), binary=True))
    saved = client.download(asset(), library.maps_directory)
    metadata = saved.with_name(saved.name + ".fieldforge.json")
    original = metadata.read_bytes()
    data = json.loads(original)
    data["local_filename"] = "../../outside.png"
    metadata.write_text(json.dumps(data))
    with pytest.raises(ValidationError, match="filename"):
        library.maps()
    metadata.write_bytes(original)
    saved.write_bytes(b"truncated")
    with pytest.raises(ValidationError, match="incomplete"):
        library.maps()
