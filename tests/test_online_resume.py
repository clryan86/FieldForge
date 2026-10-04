"""Real byte-range handoffs and durable, explicit map-download retries."""

import hashlib
import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from wsgiref.simple_server import WSGIRequestHandler
from wsgiref.simple_server import make_server as make_wsgi_server

import pytest
from map_fixture import make_map, png
from test_online_client import Response, asset, connected

from fieldforge.online.catalog import publish_map
from fieldforge.online.client import PortalCancelled, PortalClient, PortalError, PortalOffline
from fieldforge.online.download_list import download_maps, make_download_list
from fieldforge.online.models import ValidationError
from fieldforge.online.partial_download import PartialDownload, discard_partials
from fieldforge.online.server import PortalConfig, WSGIApplication, make_server
from fieldforge.online.storage import PortalLibrary

ORIGIN = "https://portal.example"


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *_args):
        pass


@pytest.fixture(params=["http", "wsgi"])
def published(tmp_path, request):
    source = make_map(tmp_path / "source.mbtiles", zooms=(0,))
    root = tmp_path / "published"
    publish_map(root, source, map_id="resume-test", title="Original fixture", attribution="Original test grid",
                license="Test fixture only", coverage="Synthetic grid", version="1")
    config = PortalConfig(port=0, catalog_root=root)
    server = (make_server(config) if request.param == "http" else
              make_wsgi_server("127.0.0.1", 0, WSGIApplication(config), handler_class=QuietHandler))
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", source.read_bytes()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(3)
    assert not worker.is_alive()


@pytest.mark.parametrize("mode", ["open", "bounded", "suffix", "clamped", "unsatisfied", "reversed", "zero-suffix",
                                 "invalid", "unknown-unit", "multiple", "changed-tag", "weak-tag"])
def test_native_and_wsgi_ranges_have_exact_bodies_and_lengths(published, mode):
    origin, data = published
    tag = '"' + hashlib.sha256(data).hexdigest() + '"'
    ranges = {"open": "bytes=17-", "bounded": "bytes=17-31", "suffix": "bytes=-13",
              "clamped": f"bytes=17-{len(data) + 100}", "unsatisfied": f"bytes={len(data)}-",
              "reversed": "bytes=31-17", "zero-suffix": "bytes=-0", "invalid": "bytes=wrong",
              "unknown-unit": "items=17-31", "multiple": "bytes=0-4,10-14",
              "changed-tag": "bytes=17-", "weak-tag": "bytes=17-"}
    expected = {"open": data[17:], "bounded": data[17:32], "suffix": data[-13:], "clamped": data[17:]}
    validator = '"changed"' if mode == "changed-tag" else "W/" + tag if mode == "weak-tag" else tag
    request = Request(origin + "/api/v1/maps/resume-test/download", headers={"Range": ranges[mode], "If-Range": validator})
    try:
        response = urlopen(request, timeout=3)
    except HTTPError as error:
        response = error
    with response:
        body = response.read()
        assert response.headers["ETag"] == tag and response.headers["Accept-Ranges"] == "bytes"
        assert int(response.headers["Content-Length"]) == len(body)
        if mode in expected:
            assert response.status == 206 and body == expected[mode]
            assert response.headers["Content-Range"].endswith(f"/{len(data)}")
        elif mode in {"unsatisfied", "reversed", "zero-suffix", "invalid"}:
            assert response.status == 416 and response.headers["Content-Range"] == f"bytes */{len(data)}"
        else:
            assert response.status == 200 and body == data and response.headers.get("Content-Range") is None


def test_real_cancel_then_fresh_client_downloads_only_missing_bytes(published, tmp_path, monkeypatch):
    origin, data = published
    monkeypatch.setattr("fieldforge.online.client.CHUNK_BYTES", 512)
    library = PortalLibrary(tmp_path / "offline")
    first = PortalClient(origin)
    first.connect()
    document = make_download_list(origin, list(first.catalog()))
    cancel = threading.Event()
    def stop(done, total, detail):
        if detail.startswith("Downloading") and 0 < done < total:
            cancel.set()
    with pytest.raises(PortalCancelled):
        download_maps(first, document, library.maps_directory, cancel=cancel, progress=stop, resume=True)
    assert library.maps() == ()
    first.disconnect()
    item = document["maps"][0]
    cache = PartialDownload(library.maps_directory / item["filename"], item, origin)
    saved = json.loads(cache.note.read_bytes())["bytes"]
    assert 0 < saved < len(data) and cache.path.read_bytes() == data[:saved]
    fresh = PortalClient(origin)
    with pytest.raises(PortalOffline):
        download_maps(fresh, document, library.maps_directory, resume=True)
    fresh.connect()
    requests, received = [], []
    real_open = fresh._opener.open
    class Counted:
        def __init__(self, wrapped):
            self.wrapped = wrapped
        def __getattr__(self, name):
            return getattr(self.wrapped, name)
        def read1(self, size):
            chunk = self.wrapped.read1(size)
            received.append(len(chunk))
            return chunk
    def opened(request, **kwargs):
        response = real_open(request, **kwargs)
        if request.full_url.endswith("/download"):
            requests.append((request.get_header("Range"), request.get_header("If-range"), response.status))
            return Counted(response)
        return response
    fresh._opener.open = opened
    ready, = download_maps(fresh, document, library.maps_directory, resume=True)
    assert requests == [(f"bytes={saved}-", '"' + item["sha256"] + '"', 206)]
    assert sum(received) == len(data) - saved
    assert ready.read_bytes() == data and library.maps() == (ready,)
    assert not cache.path.exists() and not cache.note.exists()
    assert cache.lock_path.stat().st_size == 0


@contextmanager
def seeded(tmp_path, data=None):
    data = png(2) if data is None else data
    entry = asset(data)
    target = tmp_path / entry["filename"]
    with PartialDownload(target, entry, ORIGIN) as partial:
        partial.prepare(lambda: None)
        partial.append(data[:20])
        partial.checkpoint()
    yield entry, data, partial


def ranged(data, start=20, **headers):
    return Response(data[start:], binary=True, status=206,
                    headers={"ETag": '"' + hashlib.sha256(data).hexdigest() + '"',
                             "Content-Range": f"bytes {start}-{len(data)-1}/{len(data)}", **headers})


@pytest.mark.parametrize("damage", ["tag", "weak", "missing-tag", "start", "total", "length", "compressed"])
def test_inconsistent_range_preserves_checked_prefix_without_appending(tmp_path, damage):
    with seeded(tmp_path) as (entry, data, partial):
        response = ranged(data)
        if damage == "tag":
            response.headers["ETag"] = '"changed"'
        elif damage == "weak":
            response.headers["ETag"] = "W/" + response.headers["ETag"]
        elif damage == "missing-tag":
            del response.headers["ETag"]
        elif damage == "start":
            response.headers["Content-Range"] = f"bytes 19-{len(data)-1}/{len(data)}"
        elif damage == "total":
            response.headers["Content-Range"] = f"bytes 20-{len(data)-1}/{len(data)+1}"
        elif damage == "length":
            response.headers["Content-Length"] = "1"
        else:
            response.headers["Content-Encoding"] = "gzip"
        client, _ = connected(response)
        with pytest.raises(PortalError) as error:
            client.download(entry, tmp_path, resume=True)
        assert not isinstance(error.value, PortalCancelled)
        assert partial.path.read_bytes() == data[:20]
        assert json.loads(partial.note.read_bytes())["bytes"] == 20
        assert response.closed and not partial.target.exists()


def test_server_ignoring_range_restarts_without_appending_full_body(tmp_path):
    with seeded(tmp_path) as (entry, data, partial):
        client, opener = connected(Response(data, binary=True))
        progress = []
        result = client.download(entry, tmp_path, resume=True, progress=lambda done, total: progress.append(done))
        assert opener.requests[-1].get_header("Range") == "bytes=20-"
        assert progress[:2] == [20, 0] and result.read_bytes() == data
        assert not partial.path.exists()


def test_short_response_keeps_prefix_and_requires_explicit_reconnection(tmp_path):
    data = png(2)
    entry = asset(data)
    response = Response(data[:20], binary=True, headers={"Content-Length": str(len(data))})
    client, opener = connected(response)
    with pytest.raises(PortalOffline, match="Kept partial"):
        client.download(entry, tmp_path, resume=True)
    partial = PartialDownload(tmp_path / entry["filename"], entry, ORIGIN)
    assert partial.path.read_bytes() == data[:20]
    assert not client.connected and len(opener.requests) == 2
    fresh, _ = connected(ranged(data))
    assert fresh.download(entry, tmp_path, resume=True).read_bytes() == data


def test_corrupt_prefix_is_preserved_and_rejected_before_network(tmp_path):
    with seeded(tmp_path) as (entry, data, partial):
        partial.path.write_bytes(b"x" + data[1:20])
        client, opener = connected()
        with pytest.raises(PortalError, match="checkpoint checksum"):
            client.download(entry, tmp_path, resume=True)
        assert partial.path.read_bytes() == b"x" + data[1:20] and len(opener.requests) == 1
        count = discard_partials(make_download_list(ORIGIN, [entry]), tmp_path)
        assert count == 20 and not partial.path.exists() and not partial.note.exists()


def test_crash_tail_is_trimmed_to_verified_checkpoint(tmp_path):
    with seeded(tmp_path) as (entry, data, partial):
        with partial.path.open("ab") as stream:
            stream.write(data[20:30])
        client, opener = connected(ranged(data))
        assert client.download(entry, tmp_path, resume=True).read_bytes() == data
        assert opener.requests[-1].get_header("Range") == "bytes=20-"


def test_os_lock_rejects_parallel_transfers_and_is_released_on_process_exit(tmp_path):
    data = png(2)
    entry = asset(data)
    target = tmp_path / entry["filename"]
    with PartialDownload(target, entry, ORIGIN):
        with pytest.raises(ValidationError, match="Another transfer"):
            with PartialDownload(target, entry, ORIGIN):
                pytest.fail("Two owners acquired one checkpoint")
    script = ("import json,os,sys; from pathlib import Path; "
              "from fieldforge.online.partial_download import PartialDownload; "
              "p=PartialDownload(Path(sys.argv[1]),json.loads(sys.argv[2]),sys.argv[3]); "
              "p.__enter__(); p.prepare(lambda:None); p.append(bytes.fromhex(sys.argv[4])); "
              "p.checkpoint(); os._exit(0)")
    subprocess.run([sys.executable, "-c", script, str(target), json.dumps(entry), ORIGIN, data[:20].hex()],
                   check=True, timeout=15)
    client, _ = connected(ranged(data))
    assert client.download(entry, tmp_path, resume=True).read_bytes() == data


def test_hardlinked_partial_never_modifies_another_local_file(tmp_path):
    entry = asset()
    partial = PartialDownload(tmp_path / entry["filename"], entry, ORIGIN)
    original = tmp_path / "preserve-original.bin"
    original.write_bytes(b"original private file")
    try:
        os.link(original, partial.path)
    except OSError:
        pytest.skip("This filesystem does not support hard links")
    with pytest.raises(ValidationError, match="without links"):
        discard_partials(make_download_list(ORIGIN, [entry]), tmp_path)
    assert original.read_bytes() == b"original private file" and partial.path.exists()


def test_final_checksum_failure_discards_bad_partial_without_publication(tmp_path):
    data = png(2)
    entry = asset(data)
    damaged = bytes([data[0] ^ 1]) + data[1:]
    client, _ = connected(Response(damaged, binary=True))
    with pytest.raises(PortalError, match="SHA-256"):
        client.download(entry, tmp_path, resume=True)
    partial = PartialDownload(tmp_path / entry["filename"], entry, ORIGIN)
    assert not partial.path.exists() and not partial.note.exists() and not partial.target.exists()


def test_complete_checkpoint_publishes_after_verification_without_another_transfer(tmp_path):
    data = png(2)
    entry = asset(data)
    target = tmp_path / entry["filename"]
    with PartialDownload(target, entry, ORIGIN) as partial:
        partial.prepare(lambda: None)
        partial.append(data)
        partial.checkpoint()
    client, opener = connected()
    assert client.download(entry, tmp_path, resume=True).read_bytes() == data
    assert len(opener.requests) == 1


def test_connection_failure_preserves_prefix_without_automatic_retry(tmp_path):
    with seeded(tmp_path) as (entry, data, partial):
        client, opener = connected(URLError("Simulated unavailable connection"))
        with pytest.raises(PortalOffline):
            client.download(entry, tmp_path, resume=True)
        assert partial.path.read_bytes() == data[:20] and len(opener.requests) == 2
        assert not client.connected


@pytest.mark.parametrize("damage", ["binding", "count", "unknown", "orphan"])
def test_invalid_checkpoint_never_requests_or_overwrites_data(tmp_path, damage):
    with seeded(tmp_path) as (entry, data, partial):
        value = json.loads(partial.note.read_bytes())
        if damage == "binding":
            value["binding"]["portal"] = "https://different.example"
        elif damage == "count":
            value["bytes"] = True
        elif damage == "unknown":
            value["local_path"] = "untrusted"
        if damage == "orphan":
            partial.note.unlink()
        else:
            partial.note.write_text(json.dumps(value))
        client, opener = connected()
        with pytest.raises(PortalError):
            client.download(entry, tmp_path, resume=True)
        assert partial.path.read_bytes() == data[:20] and len(opener.requests) == 1


def test_periodic_checkpoint_keeps_a_durable_prefix_before_normal_close(tmp_path, monkeypatch):
    monkeypatch.setattr("fieldforge.online.partial_download.CHECKPOINT_BYTES", 8)
    data = png(2)
    entry = asset(data)
    with PartialDownload(tmp_path / entry["filename"], entry, ORIGIN) as partial:
        partial.prepare(lambda: None)
        partial.append(data[:10])
        assert json.loads(partial.note.read_bytes())["bytes"] == 10
        assert partial.path.read_bytes() == data[:10]
        partial.append(data[10:13])
    client, opener = connected(ranged(data, start=10))
    assert client.download(entry, tmp_path, resume=True).read_bytes() == data
    assert opener.requests[-1].get_header("Range") == "bytes=10-"


def test_cancel_during_publication_restores_complete_checkpoint_for_retry(tmp_path, monkeypatch):
    from fieldforge.online import client as module

    original = module.publish_map
    cancel = threading.Event()
    data = png(2)
    entry = asset(data)
    def interrupted(temporary, target, asset, portal, guard, **kwargs):
        checks = []
        def guarded():
            checks.append(True)
            if len(checks) == 2:
                cancel.set()
            guard()
        return original(temporary, target, asset, portal, guarded, **kwargs)
    monkeypatch.setattr(module, "publish_map", interrupted)
    client, _ = connected(Response(data, binary=True))
    with pytest.raises(PortalCancelled):
        client.download(entry, tmp_path, resume=True, cancel=cancel)
    partial = PartialDownload(tmp_path / entry["filename"], entry, ORIGIN)
    assert partial.path.read_bytes() == data and not partial.target.exists()
    monkeypatch.setattr(module, "publish_map", original)
    fresh, opener = connected()
    assert fresh.download(entry, tmp_path, resume=True).read_bytes() == data
    assert len(opener.requests) == 1
