"""Selections cross the browser/desktop boundary without starting network work."""

import copy
import json
import os
from threading import Event
from types import SimpleNamespace

import pytest
from test_online_integration import operated_portal as operated_portal

from fieldforge.online.catalog import publish_map
from fieldforge.online.client import PortalCancelled, PortalClient, PortalOffline
from fieldforge.online.download_list import (
    download_maps,
    load_download_list,
    make_download_list,
    save_download_list,
    validate_download_list,
    verified_local_map,
)
from fieldforge.online.models import ValidationError


@pytest.fixture
def selection(operated_portal, tmp_path):
    url, _provider, source, asset = operated_portal
    second = publish_map(source.parent / "published-maps", source, map_id="second-v1", title="Second test map",
                         attribution="Original fixture", license="Test fixture only", coverage="Test grid", version="1")
    client = PortalClient(url)
    client.connect()
    wire = {item["id"]: item for item in client.catalog()}
    document = make_download_list(url, [wire[asset["id"]], wire[second["id"]]])
    transferred = []
    original = client.download
    def download(item, *args, **kwargs):
        transferred.append(item["id"])
        return original(item, *args, **kwargs)
    client.download = download
    yield document, client, transferred, tmp_path / "downloaded"
    client.disconnect()


def test_roundtrip_copies_selection_and_never_overwrites(selection, tmp_path):
    document, _client, _calls, _directory = selection
    target = tmp_path / "selection.json"
    save_download_list(document, target)
    assert load_download_list(target) == document
    assert document["total_bytes"] == sum(item["bytes"] for item in document["maps"])
    copied = validate_download_list(document)
    copied["maps"][0]["title"] = "Changed copy"
    assert document["maps"][0]["title"] != "Changed copy"
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        save_download_list(copied, target)
    assert target.read_bytes() == before


@pytest.mark.parametrize("damage", ["total", "schema", "kind", "duplicate", "collision", "count", "origin", "path", "unknown"])
def test_invalid_lists_are_rejected_before_network(selection, damage):
    document, client, calls, directory = selection
    value = copy.deepcopy(document)
    if damage == "total":
        value["total_bytes"] += 1
    elif damage == "schema":
        value["schema_version"] = True
    elif damage == "kind":
        value["kind"] = "route"
    elif damage == "duplicate":
        value["maps"].append(value["maps"][0])
    elif damage == "collision":
        value["maps"][1]["filename"] = value["maps"][0]["filename"].upper()
    elif damage == "count":
        value["maps"] *= 51
    elif damage == "origin":
        value["portal"] = "https://user:secret@example.org"
    elif damage == "path":
        value["maps"][0]["download_path"] = "https://other.example.org/map"
    else:
        value["execute"] = "unwanted"
    client.catalog = lambda **kwargs: pytest.fail("Invalid selection made a catalog request")
    with pytest.raises(ValidationError):
        download_maps(client, value, directory)
    assert not calls and not directory.exists()


def test_wrong_portal_and_disconnected_list_never_request(selection):
    document, client, calls, directory = selection
    client.catalog = lambda **kwargs: pytest.fail("No request without matching explicit connection")
    foreign = dict(document, portal="https://another.example.org")
    with pytest.raises(ValidationError, match="Connect to the portal"):
        download_maps(client, foreign, directory)
    client.disconnect()
    with pytest.raises(PortalOffline):
        download_maps(client, document, directory)
    assert not calls and not directory.exists()


def test_stale_list_stops_before_any_file_transfer(selection):
    document, client, calls, directory = selection
    document["maps"][1]["version"] = "old-version"
    with pytest.raises(ValidationError, match="removed or changed"):
        download_maps(client, document, directory)
    assert not calls and not directory.exists()


def test_retry_reuses_exact_local_maps_and_reports_total(selection):
    document, client, calls, directory = selection
    progress = []
    ready = download_maps(client, document, directory, progress=lambda *values: progress.append(values))
    assert len(ready) == 2 and all(path.is_file() for path in ready)
    assert calls == [item["id"] for item in document["maps"]]
    assert progress[-1][:2] == (document["total_bytes"], document["total_bytes"])
    assert all(0 <= done <= total == document["total_bytes"] for done, total, _detail in progress)
    assert download_maps(client, document, directory) == ready
    assert len(calls) == 2  # No second download of either completed map.


@pytest.mark.parametrize("changes_during_read", [False, True])
def test_reuse_allows_distinct_path_handle_ctime_but_rejects_changes(selection, monkeypatch, changes_during_read):
    document, client, _calls, directory = selection
    target = download_maps(client, document, directory)[0]
    identity = target.stat()
    original = os.fstat
    reads = []

    def windows_handle_stat(fd):
        result = original(fd)
        if (result.st_dev, result.st_ino) != (identity.st_dev, identity.st_ino):
            return result
        reads.append(fd)
        fields = {name: getattr(result, name) for name in
                  ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")}
        fields["st_ctime_ns"] += 1000 + (len(reads) if changes_during_read else 0)
        return SimpleNamespace(**fields)

    monkeypatch.setattr(os, "fstat", windows_handle_stat)
    if changes_during_read:
        with pytest.raises(ValidationError, match="existing files were preserved"):
            verified_local_map(directory, document["maps"][0], document["portal"])
    else:
        assert verified_local_map(directory, document["maps"][0], document["portal"]) == target
    assert len(reads) == 2 and target.is_file()


@pytest.mark.parametrize("damage", ["bytes", "provenance", "orphan", "timestamp"])
def test_existing_changed_files_are_preserved_and_never_redownloaded(selection, damage):
    document, client, calls, directory = selection
    ready = download_maps(client, document, directory)
    target = ready[0]
    note = target.with_name(target.name + ".fieldforge.json")
    if damage == "bytes":
        raw = target.read_bytes()
        target.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    elif damage == "orphan":
        note.unlink()
    else:
        value = json.loads(note.read_text())
        if damage == "provenance":
            value["asset"]["license"] = "Different license"
        else:
            del value["saved_at"]
        note.write_text(json.dumps(value))
    before = target.read_bytes()
    with pytest.raises((ValidationError, OSError)):
        download_maps(client, document, directory)
    assert len(calls) == 2 and target.read_bytes() == before


def test_stop_retains_completed_maps_and_retry_downloads_only_remainder(selection):
    document, client, calls, directory = selection
    cancel = Event()
    def progress(done, _total, detail):
        if done == document["maps"][0]["bytes"] and detail.startswith("Verified and ready"):
            cancel.set()
    with pytest.raises(PortalCancelled):
        download_maps(client, document, directory, cancel=cancel, progress=progress)
    assert calls == [document["maps"][0]["id"]]
    assert (directory / document["maps"][0]["filename"]).is_file()
    cancel.clear()
    ready = download_maps(client, document, directory, cancel=cancel)
    assert len(ready) == 2
    assert calls == [item["id"] for item in document["maps"]]
    assert not list(directory.glob("*.tmp"))


def test_stop_during_first_transfer_cleans_partial_files(selection):
    document, client, calls, directory = selection
    cancel = Event()
    def progress(_done, _total, detail):
        if detail.startswith("Downloading"):
            cancel.set()
    with pytest.raises(PortalCancelled):
        download_maps(client, document, directory, cancel=cancel, progress=progress)
    assert calls == [document["maps"][0]["id"]]
    assert not list(directory.iterdir())


def test_large_or_nonregular_import_is_bounded(tmp_path):
    path = tmp_path / "too-large.json"
    with path.open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    with pytest.raises(ValidationError, match="8 MiB"):
        load_download_list(path)
    with pytest.raises(ValidationError):
        load_download_list(tmp_path)
