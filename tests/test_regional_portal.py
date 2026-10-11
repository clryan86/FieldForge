"""Prepared regional maps cross the portal boundary and remain usable offline."""

import hashlib
import json
import socket
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.request import urlopen

import pytest
from map_fixture import make_map, png
from test_online_client import Response, asset, connected
from test_online_portal import serving
from test_osm_source import binary, header, node, primitive
from test_regional_index import build

from fieldforge import map_portal
from fieldforge.navigation import regional_index as regional
from fieldforge.navigation.mbtiles import MapCancelled
from fieldforge.online import compat, models
from fieldforge.online.catalog import Catalog, CatalogError, LegacyCatalog, publish_map
from fieldforge.online.client import PortalCancelled, PortalClient, PortalError
from fieldforge.online.download_list import (
    download_maps,
    load_download_list,
    make_download_list,
    save_download_list,
    verified_local_map,
)
from fieldforge.online.inventory import publish_inventory
from fieldforge.online.partial_download import PartialDownload
from fieldforge.online.server import PortalConfig, make_server
from fieldforge.online.storage import PortalLibrary

RIGHTS = {
    "source": "Original synthetic PBF fixture", "attribution": "FieldForge test author",
    "license": "Synthetic test fixture only", "coverage": "Fictional test area", "version": "1",
}


@pytest.fixture
def prepared(tmp_path):
    return build(tmp_path)


def entry(path):
    return asset(path.read_bytes(), filename=path.name, format="ffmap", **RIGHTS)


def legacy(value):
    return {
        "id": value["id"], "title": value["title"], "filename": value["filename"],
        "kind": "regional", "size": value["bytes"], "sha256": value["sha256"],
        "coverage": value["coverage"], "updated": value["version"],
        **{field: value[field] for field in ("source", "attribution", "license")},
    }


def publish(root, path, map_id="regional-v1"):
    return publish_map(
        root, path, map_id=map_id, title="Synthetic prepared map", source_name=RIGHTS["source"],
        **{field: RIGHTS[field] for field in ("attribution", "license", "coverage", "version")})


@contextmanager
def portal(root):
    server = make_server(PortalConfig(port=0, catalog_root=root))
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(3)
    assert not worker.is_alive()


def empty_index(tmp_path):
    tmp_path.mkdir()
    return build(tmp_path, header() + primitive(binary(1, node(1, -70, 40))))


def test_regional_format_family_and_canonical_legacy_metadata_share_four_gib_limit(prepared):
    value = entry(prepared.path)
    old = legacy(value)
    assert models.FORMATS["ffmap"] == (".ffmap",)
    assert models.MAX_REGIONAL_BYTES == 4 * 1024**3
    assert models.format_family("ffmap") == "regional"
    assert models.format_family("mbtiles") == "mbtiles"
    assert models.format_family("png") == "image"
    assert models.format_byte_limit("ffmap") == models.MAX_REGIONAL_BYTES
    assert ".ffmap" not in compat.IMAGE_SUFFIXES
    assert models.validate_asset({**value, "kind": "regional", "size": value["bytes"],
                                  "updated": value["version"]}) == value
    assert models.normalize_legacy_asset(old) == value
    assert compat.MapItem.parse(old).kind == "regional"
    assert models.validate_asset({**value, "bytes": models.MAX_REGIONAL_BYTES})["bytes"] == 4 * 1024**3
    assert compat.MapItem.parse({**old, "size": models.MAX_REGIONAL_BYTES}).size == 4 * 1024**3
    for wrong_kind in ("image", "mbtiles"):
        with pytest.raises(models.ValidationError):
            models.validate_asset({**value, "kind": wrong_kind})
        with pytest.raises((ValueError, compat.OnlineError)):
            compat.MapItem.parse({**old, "kind": wrong_kind})
    for size in (0, models.MAX_REGIONAL_BYTES + 1):
        with pytest.raises(models.ValidationError):
            models.validate_asset({**value, "bytes": size})
        with pytest.raises(models.ValidationError):
            models.normalize_legacy_asset({**old, "size": size})
        with pytest.raises((ValueError, compat.OnlineError)):
            compat.MapItem.parse({**old, "size": size})


def test_single_publication_http_and_compatibility_downloads_reopen_and_search_offline(prepared, tmp_path, monkeypatch):
    original = prepared.path.read_bytes()
    expected = regional.search_index(prepared, "Map Street").features
    root = tmp_path / "published"
    published = publish(root, prepared.path)
    assert published["format"] == "ffmap"
    assert published["sha256"] == hashlib.sha256(original).hexdigest()
    assert published["sha256"] != prepared.metadata["source_sha256"]
    assert {field: published[field] for field in RIGHTS} == RIGHTS
    before_catalog = (root / "catalog.json").read_bytes()
    with pytest.raises(CatalogError):
        publish(root, prepared.path)
    assert (root / "catalog.json").read_bytes() == before_catalog
    library = PortalLibrary(tmp_path / "offline")
    with portal(root) as origin:
        with urlopen(origin + published["download_path"], timeout=5) as response:
            assert response.headers.get_content_type() == "application/vnd.sqlite3"
            assert response.headers["Content-Length"] == str(len(original))
            assert response.headers["ETag"] == '"' + published["sha256"] + '"'
            assert response.read() == original
        client = PortalClient(origin)
        client.connect()
        selected, = client.catalog()
        assert selected == published
        downloaded = client.download(selected, library.maps_directory)
        with pytest.raises(FileExistsError):
            client.download(selected, library.maps_directory)
        note = json.loads(downloaded.with_name(downloaded.name + ".fieldforge.json").read_bytes())
        assert note["asset"] == selected and note["portal"] == origin
        session = compat.PortalSession()
        session.connect(origin, consent=True)
        item, = session.maps()
        assert item.kind == "regional" and item.filename.endswith(".ffmap")
        compatible = session.download(item, tmp_path / "compat-copy.ffmap")
        source_note = json.loads(compatible.with_name(compatible.name + ".source.json").read_bytes())
        assert source_note["kind"] == "regional" and source_note["sha256"] == published["sha256"]
        assert all(source_note[field] == RIGHTS[field] for field in ("source", "attribution", "license"))
        client.disconnect()
        session.disconnect()
    assert prepared.path.read_bytes() == original
    prepared.path.unlink()
    (tmp_path / "source.osm.pbf").unlink()
    monkeypatch.setattr(socket, "create_connection",
                        lambda *args, **kwargs: pytest.fail("Offline regional search requested the network"))
    assert library.maps() == (downloaded,)
    for target in (downloaded, compatible):
        assert target.read_bytes() == original
        reopened = regional.inspect_index(target)
        assert reopened.metadata == prepared.metadata
        assert regional.search_index(reopened, "Map Street").features == expected


def test_legacy_inline_catalog_serves_regional_bytes_without_copying_or_mutating_source(prepared, tmp_path):
    value = entry(prepared.path)
    manifest = legacy(value)
    before = prepared.path.read_bytes()
    catalog = LegacyCatalog([manifest], prepared.path.parent)
    assert catalog.assets() == [value]
    listed, stream = catalog.open_asset(value["id"])
    with stream:
        assert listed == value and stream.read() == before
    app = map_portal.Portal({"version": 1, "maps": [manifest]}, folder=prepared.path.parent)
    with serving(app) as origin:
        client = PortalClient(origin)
        client.connect()
        selected, = client.catalog()
        assert selected == value
        target = client.download(selected, tmp_path / "legacy-downloads")
        client.disconnect()
    assert regional.search_index(regional.inspect_index(target), "Map Street").features
    assert prepared.path.read_bytes() == before
    prepared.path.write_bytes(before + b"changed after verification")
    with pytest.raises(CatalogError, match="changed"):
        catalog.open_asset(value["id"])


def test_mixed_inventory_list_resumes_regional_bytes_reuses_completed_files_and_preserves_provenance(
    prepared, tmp_path, monkeypatch,
):
    folder = tmp_path / "licensed"
    folder.mkdir()
    (folder / "region.ffmap").write_bytes(prepared.path.read_bytes())
    make_map(folder / "tiles.mbtiles", zooms=(0,))
    (folder / "reference.png").write_bytes(png(2))
    entries = [{"id": key, "filename": filename, "title": "Synthetic " + key, **RIGHTS}
               for key, filename in (("regional", "region.ffmap"), ("tiles", "tiles.mbtiles"),
                                     ("image", "reference.png"))]
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"schema_version": 1, "asset_folder": "licensed", "maps": entries}))
    root = tmp_path / "inventory-published"
    published = publish_inventory(root, inventory)
    assert [item["format"] for item in published] == ["ffmap", "mbtiles", "png"]
    assert Catalog(root).assets() == published
    library = PortalLibrary(tmp_path / "mixed-offline")
    monkeypatch.setattr("fieldforge.online.client.CHUNK_BYTES", 512)
    with portal(root) as origin:
        first = PortalClient(origin)
        first.connect()
        document = make_download_list(origin, list(first.catalog()))
        selected = tmp_path / "selected-maps.json"
        save_download_list(document, selected)
        assert load_download_list(selected) == document
        cancel = threading.Event()

        def stop(done, _total, detail):
            if detail.startswith("Downloading") and 0 < done < document["maps"][0]["bytes"]:
                cancel.set()

        with pytest.raises(PortalCancelled):
            download_maps(first, document, library.maps_directory, cancel=cancel, progress=stop, resume=True)
        first.disconnect()
        assert library.maps() == ()
        regional_asset = document["maps"][0]
        partial = PartialDownload(library.maps_directory / regional_asset["filename"], regional_asset, origin)
        saved = json.loads(partial.note.read_bytes())["bytes"]
        assert 0 < saved < regional_asset["bytes"]
        assert partial.path.read_bytes() == prepared.path.read_bytes()[:saved]
        fresh = PortalClient(origin)
        fresh.connect()
        transfers = []
        original_open = fresh._opener.open

        def opened(request, **kwargs):
            response = original_open(request, **kwargs)
            if request.full_url.endswith("/download"):
                transfers.append((request.get_header("Range"), request.get_header("If-range"), response.status))
            return response

        fresh._opener.open = opened
        ready = download_maps(fresh, document, library.maps_directory, resume=True)
        assert transfers == [(f"bytes={saved}-", '"' + regional_asset["sha256"] + '"', 206),
                             (None, None, 200), (None, None, 200)]
        assert not partial.path.exists() and not partial.note.exists()
        assert len(ready) == 3 and set(library.maps()) == set(ready)
        assert regional.inspect_index(ready[0]).metadata == prepared.metadata
        assert regional.search_index(regional.inspect_index(ready[0]), "Map Street").features
        assert download_maps(fresh, document, library.maps_directory, resume=True) == ready
        assert len(transfers) == 3
        target = ready[0]
        assert verified_local_map(library.maps_directory, regional_asset, origin) == target
        note_path = target.with_name(target.name + ".fieldforge.json")
        note = json.loads(note_path.read_bytes())
        assert note["asset"] == regional_asset
        note["asset"]["license"] = "Changed provenance must not be accepted"
        note_path.write_text(json.dumps(note))
        before = target.read_bytes(), note_path.read_bytes()
        with pytest.raises(models.ValidationError, match="preserved"):
            download_maps(fresh, document, library.maps_directory)
        assert (target.read_bytes(), note_path.read_bytes()) == before and len(transfers) == 3
        fresh.disconnect()


@pytest.mark.parametrize("damage", ["wrong-sqlite", "empty-index", "wal-mode", "-wal", "-shm", "-journal"])
def test_publication_and_legacy_catalog_reject_unusable_regional_files_without_publishing(
    prepared, tmp_path, damage,
):
    source = prepared.path
    if damage == "wrong-sqlite":
        source.unlink()
        with sqlite3.connect(source) as db:
            db.execute("CREATE TABLE unrelated(value TEXT)")
    elif damage == "empty-index":
        source = empty_index(tmp_path / "empty").path
        assert regional.inspect_index(source).metadata["features"] == 0
    elif damage == "wal-mode":
        with sqlite3.connect(source) as db:
            assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        assert source.read_bytes()[18:20] == b"\x02\x02"
    else:
        Path(str(source) + damage).touch()
    before = source.read_bytes()
    root = tmp_path / "rejected"
    with pytest.raises(CatalogError):
        publish(root, source)
    assert Catalog(root).assets() == [] and not list((root / "objects").glob("*"))
    with pytest.raises(CatalogError):
        LegacyCatalog([legacy(entry(source))], source.parent)
    assert source.read_bytes() == before


def test_source_sidecar_appearing_during_staging_cannot_be_hidden_by_the_copy(prepared, tmp_path, monkeypatch):
    from fieldforge.online import catalog

    original = catalog.inspect_raster

    def changed_source(staged, kind):
        original(staged, kind)
        assert staged != prepared.path
        Path(str(prepared.path) + "-wal").touch()

    monkeypatch.setattr(catalog, "inspect_raster", changed_source)
    root = tmp_path / "racing-publication"
    with pytest.raises(CatalogError):
        publish(root, prepared.path)
    assert Catalog(root).assets() == [] and not list((root / "objects").glob("*"))


def test_regional_source_larger_than_four_gib_is_rejected_before_copy_or_hash(prepared, tmp_path):
    value = entry(prepared.path)
    limit = 4 * 1024**3
    with prepared.path.open("r+b") as stream:
        stream.truncate(limit + 1)
    root = tmp_path / "oversize"
    with pytest.raises(CatalogError):
        publish(root, prepared.path)
    with pytest.raises(CatalogError):
        LegacyCatalog([{**legacy(value), "size": limit + 1}], prepared.path.parent)
    assert prepared.path.stat().st_size == limit + 1
    assert Catalog(root).assets() == [] and not list((root / "objects").glob("*"))


@pytest.mark.parametrize("damage", ["wrong-sqlite", "empty-index"])
def test_client_rejects_checksum_matching_but_unusable_index_before_local_publication(
    prepared, tmp_path, damage,
):
    if damage == "empty-index":
        source = empty_index(tmp_path / "empty-download").path
    else:
        source = tmp_path / "unrelated.ffmap"
        with sqlite3.connect(source) as db:
            db.execute("CREATE TABLE unrelated(value TEXT)")
    raw = source.read_bytes()
    value = entry(source)
    client, _ = connected(Response(raw, binary=True))
    directory = tmp_path / "bad-download"
    with pytest.raises(PortalError):
        client.download(value, directory)
    assert not list(directory.iterdir())
    assert hashlib.sha256(raw).hexdigest() == value["sha256"]


@pytest.mark.parametrize("resume", [False, True])
def test_inspector_cancellation_becomes_portal_cancelled_without_ready_files(prepared, tmp_path, monkeypatch, resume):
    seen = []
    original = regional.inspect_index

    def cancelled(path, *, cancel=None, progress=None):
        seen.append(path)
        assert cancel is not None
        raise MapCancelled("TEST regional verification cancelled")

    monkeypatch.setattr(regional, "inspect_index", cancelled)
    client, _ = connected(Response(prepared.path.read_bytes(), binary=True))
    directory = tmp_path / "cancelled-download"
    value = entry(prepared.path)
    with pytest.raises(PortalCancelled):
        client.download(value, directory, resume=resume)
    assert len(seen) == 1
    target = directory / value["filename"]
    assert not target.exists() and not target.with_name(target.name + ".fieldforge.json").exists()
    if resume:
        partial = PartialDownload(target, value, client.base_url)
        assert partial.path.read_bytes() == prepared.path.read_bytes()
        monkeypatch.setattr(regional, "inspect_index", original)
        fresh, opener = connected()
        ready = fresh.download(value, directory, resume=True)
        assert len(opener.requests) == 1  # Only the explicit handshake; no second body transfer.
        assert regional.inspect_index(ready).metadata == prepared.metadata
        assert not partial.path.exists() and not partial.note.exists()
    else:
        assert not list(directory.iterdir())


@pytest.mark.parametrize("resume", [False, True])
def test_disconnect_after_structural_inspection_cannot_publish_a_late_result(prepared, tmp_path, monkeypatch, resume):
    original = regional.inspect_index
    client, _ = connected(Response(prepared.path.read_bytes(), binary=True))
    seen = []

    def inspect_then_disconnect(path, **kwargs):
        result = original(path, **kwargs)
        seen.append(path)
        client.disconnect()
        return result

    monkeypatch.setattr(regional, "inspect_index", inspect_then_disconnect)
    directory = tmp_path / "disconnected-download"
    value = entry(prepared.path)
    with pytest.raises(PortalCancelled):
        client.download(value, directory, resume=resume)
    target = directory / value["filename"]
    assert seen and not client.connected and not target.exists()
    assert not target.with_name(target.name + ".fieldforge.json").exists()
    if resume:
        partial = PartialDownload(target, value, client.base_url)
        assert partial.path.read_bytes() == prepared.path.read_bytes() and partial.note.is_file()
    else:
        assert not list(directory.iterdir())
