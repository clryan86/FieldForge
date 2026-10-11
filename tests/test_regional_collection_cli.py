"""The documented collection commands work in independent, core-only processes."""

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from test_regional_collection import make_case
from test_regional_portal import portal

from fieldforge.navigation import regional_index as regional
from fieldforge.online.client import PortalClient
from fieldforge.online.storage import PortalLibrary

SOURCE_ROOT = Path(__file__).resolve().parents[1]


def command(case, *arguments):
    environment = dict(os.environ, PYTHONPATH=str(SOURCE_ROOT))
    result = subprocess.run(
        [sys.executable, "-S", "-m", "fieldforge.online.catalog", *map(str, arguments)],
        cwd=case.root, env=environment, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    return json.loads(result.stdout)


def test_collection_module_commands_publish_download_and_search_without_inputs(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    originals = [index.path.read_bytes() for index in case.indexes]
    selections = [argument for pack in case.document["packs"]
                  for argument in ("--select", pack["filename"])]
    prepared = command(
        case, "prepare-collection", "--collection", case.collection,
        "--archives", case.archives, "--output", case.output, *selections,
    )
    assert prepared["map_count"] == 2
    assert Path(prepared["inventory"]).is_file() and Path(prepared["receipt"]).is_file()
    catalog = case.root / "published"
    built = command(case, "build", "--inventory", prepared["inventory"], "--root", catalog)
    assert command(case, "list", "--root", catalog) == built
    assert len(built["maps"]) == 2
    saved = PortalLibrary(case.root / "offline")
    with portal(catalog) as origin:
        client = PortalClient(origin)
        client.connect()
        try:
            assert list(client.catalog()) == built["maps"]
            downloaded = [client.download(asset, saved.maps_directory) for asset in built["maps"]]
        finally:
            client.disconnect()

    # All inputs and published objects are disposable copies owned by this test.
    for path in [*(index.path.parent for index in case.indexes), case.archives, case.output]:
        shutil.rmtree(path)
    case.collection.unlink()
    for path in (catalog / "objects").iterdir():
        path.chmod(0o600)
    shutil.rmtree(catalog)

    def no_connection(*_args, **_kwargs):
        pytest.fail("A disconnected regional map tried to open a network connection")

    monkeypatch.setattr(socket, "create_connection", no_connection)
    monkeypatch.setattr(socket.socket, "connect", no_connection)
    assert set(saved.maps()) == set(downloaded)
    for path, original in zip(downloaded, originals):
        assert path.read_bytes() == original
        index = regional.inspect_index(path)
        assert {item.id for item in regional.search_index(index, "Map Street").features} == {
            "node/1", "way/10",
        }
