"""Published client interfaces and both portal wire formats interoperate."""

import json
from dataclasses import asdict
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

import pytest
from test_online_client import STATUS, Opener, Response, asset, png, result, route

from fieldforge.online import (
    PortalCancelled,
    PortalClient,
    PortalError,
    PortalLibrary,
    PortalSession,
    compat,
    models,
)
from fieldforge_gps.gpx_review import parse_gpx
from fieldforge_gps.places import read_catalog

LEGACY_STATUS = {
    "version": 1, "name": "Published legacy portal",
    "capabilities": {"geocoding": True, "routing": True},
    "providers": {"geocoding": {"name": "Legacy geocoder", "attribution": "Original fixture"},
                  "routing": {"name": "Legacy router", "attribution": "Original fixture"}},
}


def legacy_asset(data):
    modern = asset(data)
    return {"id": modern["id"], "title": modern["title"], "filename": modern["filename"],
            "kind": "image", "size": modern["bytes"], "sha256": modern["sha256"],
            "coverage": modern["coverage"], "updated": modern["version"],
            "source": "Actual fixture map source", "attribution": modern["attribution"],
            "license": modern["license"]}


def legacy_route():
    modern = route()
    return {"profile": "driving", "coordinates": modern["geometry"],
            "distance_m": modern["distance_m"], "duration_s": modern["duration_s"],
            "source": modern["source"], "attribution": modern["attribution"],
            "created_at": modern["created_at"]}


def install_hook(monkeypatch, *responses):
    opener = Opener(*responses)

    def opened(url, *, payload=None, timeout=8):
        data = None if payload is None else json.dumps(payload).encode()
        return opener.open(Request(url, data=data), timeout)

    monkeypatch.setattr(compat, "open_request", opened)
    return opener


def test_primary_client_uses_published_legacy_wire_and_saves_complete_offline_files(tmp_path):
    raw_address = {key: value for key, value in result().items() if key not in {"license", "retrieved_at"}}
    data = png(2)
    opener = Opener(Response(LEGACY_STATUS), Response({"results": [raw_address]}),
                    Response({"maps": [legacy_asset(data)]}), Response(legacy_route()),
                    Response(data, binary=True))
    client = PortalClient("https://portal.example", opener=opener)
    status = client.connect()
    assert client.legacy_protocol and status["catalog"] and status["geocoding"]
    found, = client.search("Fictional address")
    assert found["license"] == models.LEGACY_LICENSE
    assert models.validate_timestamp(found["retrieved_at"])
    assert (found["latitude"], found["longitude"]) == (39, -75)
    entry, = client.catalog()
    assert entry["source"] == "Actual fixture map source" and entry["format"] == "png"
    planned, = client.routes((39, -75), (39.001, -75.001))
    assert planned["steps"] == [] and planned["license"] == models.LEGACY_LICENSE
    assert opener.requests[-1].full_url.endswith("/api/v1/route")
    assert json.loads(opener.requests[-1].data)["start"] == [39, -75]
    library = PortalLibrary(tmp_path)
    saved_route = library.save_route(planned)
    saved_map = client.download(entry, library.maps_directory)
    assert opener.requests[-1].full_url.endswith("/api/v1/maps/test-map/file")
    client.disconnect()
    assert library.maps() == (saved_map,) and library.load_route(saved_route) == planned
    assert saved_map.read_bytes() == data


def test_published_session_uses_canonical_server_once_and_preserves_exact_destination_and_notes(tmp_path, monkeypatch):
    data = png(2)
    canonical_asset = asset(data, source="Actual canonical source")
    opener = install_hook(monkeypatch, Response(STATUS), Response({"results": [result()]}),
                          Response({"maps": [canonical_asset]}), Response({"routes": [route()]}),
                          Response(data, binary=True))
    session = PortalSession()
    status = session.connect("https://portal.example", consent=True)
    assert status["version"] == 1 and session.ready and len(opener.requests) == 1
    found, = session.search("Fictional address")
    assert isinstance(found, compat.Address) and found.license == result()["license"]
    assert found.retrieved_at == result()["retrieved_at"]
    item, = session.maps()
    assert item.source == "Actual canonical source"
    selected = session.route((39, -75), (39.001, -75.001))
    assert selected["coordinates"] == route()["geometry"] and selected["license"] == route()["license"]
    assert opener.requests[-1].full_url.endswith("/api/v1/routes")
    destination = tmp_path / "My chosen map name.png"
    assert session.download(item, destination) == destination
    assert opener.requests[-1].full_url.endswith("/api/v1/maps/test-map/download")
    note = json.loads(destination.with_name(destination.name + ".source.json").read_text())
    assert note["source"] == item.source and note["filename"] == item.filename
    manifest = json.loads(destination.with_name(destination.name + ".fieldforge.json").read_text())
    assert manifest["local_filename"] == destination.name and manifest["asset"]["filename"] == item.filename
    session.disconnect()
    assert destination.read_bytes() == data and parse_gpx(compat.route_gpx(selected)).point_count == 2
    csv_path = tmp_path / "address.csv"
    compat.save_new(csv_path, compat.address_csv(found))
    place, = read_catalog(csv_path, consent=True, wgs84_confirmed=True).places
    assert found.license in place.source and found.retrieved_at in place.source


def test_compat_download_disconnect_cannot_publish_late_results(tmp_path, monkeypatch):
    session = PortalSession()
    responses = Opener(Response(STATUS), Response({"maps": [asset()]}), Response(png(2), binary=True))

    def opened(url, *, payload=None, timeout=8):
        response = responses.open(Request(url), timeout)
        if url.endswith("/download"):
            session.disconnect()
        return response

    monkeypatch.setattr(compat, "open_request", opened)
    session.connect("https://portal.example", consent=True)
    item, = session.maps()
    with pytest.raises(PortalCancelled):
        session.download(item, tmp_path / "cancelled.png")
    assert not list(tmp_path.iterdir()) and not session.ready


def test_compat_failed_transport_clears_session_without_retry(monkeypatch):
    opener = install_hook(monkeypatch, Response(STATUS), URLError("unreachable"))
    session = PortalSession()
    session.connect("https://portal.example", consent=True)
    with pytest.raises(compat.OnlineError):
        session.search("A place")
    assert not session.ready
    with pytest.raises(compat.Cancelled):
        session.maps()
    assert len(opener.requests) == 2


@pytest.mark.parametrize("change", [
    {"version": 2}, {"version": True},
    {"capabilities": {"geocoding": False, "routing": True}},
    {"providers": {"routing": {"name": "Incomplete"}}},
])
def test_conflicting_status_aliases_never_enable_connection(change):
    value = {**STATUS, "version": 1,
             "capabilities": {"geocoding": True, "routing": True}, **change}
    client = PortalClient("https://portal.example", opener=Opener(Response(value)))
    with pytest.raises(PortalError):
        client.connect()
    assert not client.connected


@pytest.mark.parametrize("change", [{"kind": "mbtiles"}, {"size": True}, {"size": 1}, {"updated": "other"}])
def test_conflicting_map_aliases_are_rejected(change):
    value = asset()
    aliases = {"kind": "image", "size": value["bytes"], "updated": value["version"], "source": "Real source"}
    with pytest.raises(models.ValidationError):
        models.validate_asset({**value, **aliases, **change})


def test_consistent_aliases_are_removed_but_actual_source_and_provider_identity_are_retained():
    value = asset()
    normalized = models.validate_asset({**value, "kind": "image", "size": value["bytes"],
                                        "updated": value["version"], "source": "Real source"})
    assert normalized["source"] == "Real source"
    assert not {"kind", "size", "updated"} & normalized.keys()
    status = models.validate_status({**STATUS, "version": 1,
                                    "capabilities": {"geocoding": True, "routing": True},
                                    "providers": LEGACY_STATUS["providers"]})
    assert status["providers"] == LEGACY_STATUS["providers"] and "version" not in status


@pytest.mark.parametrize("kind,suffix,pillow_format", [
    ("ico", ".ico", "ICO"), ("ppm", ".ppm", "PPM"), ("tga", ".tga", "TGA"),
    ("jpeg2000", ".jp2", "JPEG2000"), ("avif", ".avif", "AVIF"),
])
def test_previously_published_image_families_download_with_optional_codecs(tmp_path, kind, suffix, pillow_format):
    Image = pytest.importorskip("PIL.Image")
    path = tmp_path / ("fixture" + suffix)
    try:
        Image.new("RGB", (32, 32), "green").save(path, format=pillow_format)
    except (OSError, KeyError):
        pytest.skip(f"Optional {pillow_format} encoder unavailable")
    data = path.read_bytes()
    value = asset(data, filename=path.name, format=kind)
    opener = Opener(Response(STATUS), Response(data, binary=True))
    client = PortalClient("https://portal.example", opener=opener)
    client.connect()
    target = client.download(value, tmp_path / "saved")
    assert target.read_bytes() == data


def test_csv_retains_optional_metadata_and_rejects_unusable_catalog_field_lengths():
    address = compat.Address("Fictional", 1, 2, "Source", "Credit", "License", "2026-10-04T00:00:00Z")
    assert b"License" in compat.address_csv(address) and b"Retrieved:" in compat.address_csv(address)
    later = compat.Address(**{**asdict(address), "retrieved_at": "2026-10-04T00:01:00Z"})
    assert later == address  # Retrieval metadata does not change the legacy address identity.
    with pytest.raises(ValueError, match="160"):
        compat.address_csv(compat.Address("A" * 161, 1, 2, "Source", "Credit"))
    with pytest.raises(ValueError, match="512"):
        compat.address_csv(compat.Address("A", 1, 2, "Source", "Credit" * 100))
    with pytest.raises(compat.OnlineError, match="must be text"):
        compat.Address.parse({**asdict(address), "license": False})


def test_shadow_module_removed_and_public_imports_share_the_compatibility_types():
    import fieldforge.online as public

    assert public.PortalSession is compat.PortalSession and public.Address is compat.Address
    assert not Path(public.__file__).parent.with_suffix(".py").exists()
