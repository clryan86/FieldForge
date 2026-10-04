"""Inventory publication is local, all-or-nothing and preserves exact map identities."""

import hashlib
import json
import os
from types import SimpleNamespace

import pytest
from map_fixture import make_map
from PIL import Image

from fieldforge.online.catalog import Catalog, CatalogError, main
from fieldforge.online.discovery import coverage_bounds, filter_maps, filter_point
from fieldforge.online.inventory import publish_inventory


@pytest.fixture
def inventory(tmp_path):
    folder = tmp_path / "assets"
    folder.mkdir()
    make_map(folder / "north.mbtiles", zooms=(0,))
    Image.new("RGB", (8, 8), "green").save(folder / "south.png")
    data = {"schema_version": 1, "asset_folder": "assets", "maps": [
        {"id": key, "filename": filename, "title": title, "coverage": region,
         "version": "2026-10", "source": "Original fixture", "attribution": "Test author",
         "license": "Test fixture only"}
        for key, filename, title, region in (
            ("north", "north.mbtiles", "Éclair North", "North region"),
            ("south", "south.png", "Bay image", "South region"),
        )
    ]}
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, data, tmp_path / "published", folder


def test_inventory_publishes_exact_files_with_provenance(inventory):
    path, data, root, folder = inventory
    progress = []
    assets = publish_inventory(root, path, progress=lambda *args: progress.append(args))
    assert assets == Catalog(root).assets()
    assert [item["id"] for item in assets] == ["north", "south"]
    assert progress == [(1, 2, "north.mbtiles"), (2, 2, "south.png")]
    for asset, entry in zip(assets, data["maps"]):
        raw = (folder / entry["filename"]).read_bytes()
        assert asset["sha256"] == hashlib.sha256(raw).hexdigest()
        assert asset["bytes"] == len(raw)
        assert all(asset[key] == entry[key] for key in ("title", "coverage", "version", "source", "attribution", "license"))
        assert asset["download_path"] == f"/api/v1/maps/{entry['id']}/download"
        published = next((root / "objects").glob(asset["sha256"] + ".*"))
        assert published.read_bytes() == raw
        assert (folder / entry["filename"]).stat().st_mode & 0o200
    assert not list(root.parent.glob(".fieldforge-catalog-*"))


@pytest.mark.parametrize("corruption", ["damaged", "duplicate", "path", "missing-rights", "source-change", "symbolic-link"])
def test_bad_inventory_never_publishes_partial_catalog(inventory, corruption):
    path, data, root, folder = inventory
    progress = None
    if corruption == "damaged":
        (folder / "south.png").write_bytes(b"not an image")
    elif corruption == "duplicate":
        data["maps"][1]["id"] = "north"
    elif corruption == "path":
        data["maps"][1]["filename"] = "../outside.png"
    elif corruption == "missing-rights":
        data["maps"][1]["license"] = ""
    elif corruption == "source-change":
        def progress(done, *_args):
            if done == 2:
                (folder / "north.mbtiles").write_bytes(b"changed after copy")
    else:
        if os.name == "nt":
            pytest.skip("Creating symlinks requires Windows privileges")
        (folder / "south.png").unlink()
        (folder / "south.png").symlink_to(folder / "north.mbtiles")
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises((ValueError, OSError)):
        publish_inventory(root, path, progress=progress)
    assert not root.exists()
    assert not list(root.parent.glob(".fieldforge-catalog-*"))


def test_existing_catalog_is_not_overwritten(inventory):
    path, _data, root, _folder = inventory
    publish_inventory(root, path)
    before = (root / "catalog.json").read_bytes()
    with pytest.raises(CatalogError, match="new catalog directory"):
        publish_inventory(root, path)
    assert (root / "catalog.json").read_bytes() == before


def test_failed_final_publication_cleans_only_owned_files(inventory, monkeypatch):
    path, _data, root, _folder = inventory
    from fieldforge.online import inventory as publisher

    original = publisher._publish_new_path
    def fail_index(source, destination, *args, **kwargs):
        if destination == root / "catalog.json":
            raise OSError("Synthetic publication failure")
        return original(source, destination, *args, **kwargs)
    monkeypatch.setattr(publisher, "_publish_new_path", fail_index)
    with pytest.raises(OSError, match="Synthetic"):
        publish_inventory(root, path)
    assert not root.exists()
    assert not list(root.parent.glob(".fieldforge-catalog-*"))


@pytest.mark.parametrize("raw", ['{"schema_version":1,"schema_version":1}', '{broken', '\ufffd', '{}'])
def test_invalid_inventory_is_readable_cli_error(inventory, raw, capsys):
    path, _data, root, _folder = inventory
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main(["build", "--root", str(root), "--inventory", str(path)])
    assert error.value.code == 2
    assert "Map publishing failed" in capsys.readouterr().err
    assert not root.exists()


def test_cli_prints_shared_catalog(inventory, capsys):
    path, _data, root, _folder = inventory
    assert main(["build", "--root", str(root), "--inventory", str(path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"maps": Catalog(root).assets()}


def test_map_filters_keep_original_identity_and_do_not_change_catalog(inventory):
    path, _data, root, _folder = inventory
    assets = publish_inventory(root, path)
    before = json.dumps(assets)
    assert filter_maps(assets, "north eclair original", "mbtiles") == (assets[0],)
    assert filter_maps(assets, "", "image") == (assets[1],)
    assert filter_maps(assets, "", order="smallest")[0] is assets[1]
    assert filter_maps(assets, "", order="largest")[0] is assets[0]
    assert filter_maps(assets, "[.*]") == ()
    assert json.dumps(assets) == before
    legacy = SimpleNamespace(id="image", title="Éclair", kind="image", size=1, coverage="North", filename="x.png", source="author")
    assert filter_maps([legacy], "eclair north", "image")[0] is legacy


@pytest.mark.parametrize("kwargs", [{"query": "x" * 301}, {"query": None}, {"kind": "bad"}, {"order": "bad"}])
def test_filters_reject_invalid_controls(kwargs):
    with pytest.raises(ValueError):
        filter_maps([], **kwargs)


@pytest.mark.parametrize("coverage,point,match", [
    ([-80, 35, -70, 45], (40, -75), True),
    ([-80, 35, -70, 45], (35, -80), True),
    ([-80, 35, -70, 45], (45, -70), True),
    ([-80, 35, -70, 45], (45.001, -75), False),
    ([-80, 35, -70, 45], (40, -69.999), False),
    ([170, -20, -170, 20], (0, 175), True),
    ([170, -20, -170, 20], (0, -175), True),
    ([170, -20, -170, 20], (0, 180), True),
    ([170, -20, -170, 20], (0, -180), True),
    ([170, -20, -170, 20], (0, 0), False),
    ([-180, -90, 180, 90], (90, 0), True),
    ([170, -20, 180, 20], (0, -180), True),
    ([-180, -20, -170, 20], (0, 180), True),
    ([180, 0, 180, 0], (0, -180), True),
    ([0, 0, 0, 0], (0, 0), True),
    ([0, 0, 0, 0], (0, 0.001), False),
    ("North region", (40, -75), False),
    ("[-80,35,-70,45]", (40, -75), False),
])
def test_coordinate_filter_uses_declared_bounds_including_date_line(coverage, point, match):
    item = {"id": "test", "title": "Éclair", "coverage": coverage, "format": "mbtiles"}
    assert filter_maps([item], "eclair", "mbtiles", point=point) == ((item,) if match else ())
    assert filter_maps([item], "", "image", point=point) == ()
    assert filter_maps([item]) == (item,)  # Clearing the point restores labeled maps.


@pytest.mark.parametrize("coverage", [None, [], [0, 0, 0], [0, 1, 0, -1],
                                     [True, 0, 1, 1], [0, 0, float("nan"), 1],
                                     [0, 0, 181, 1], [0, -91, 0, 0], ["0", 0, 1, 1]])
def test_invalid_coverage_never_becomes_a_coordinate_match(coverage):
    assert coverage_bounds({"coverage": coverage}) is None
    assert filter_maps([{"coverage": coverage}], point=(0, 0)) == ()


@pytest.mark.parametrize("point", [(91, 0), (0, -181), (True, 0), (float("nan"), 0),
                                  ("40", "-75"), (0,), "0,0"])
def test_point_validation_applies_even_to_an_empty_catalog(point):
    with pytest.raises(ValueError):
        filter_maps([], point=point)


def test_coordinate_fields_are_explicit_and_blank_is_not_zero():
    assert filter_point(" ", "") is None
    assert filter_point("+0.0", "-0") == (0, 0)
    assert filter_point("40.123456789", "-75.987654321") == (40.123456789, -75.987654321)
    for pair in (("0", ""), ("", "0"), ("1e1", "0"), ("0x10", "0"),
                 ("NaN", "0"), ("1,2", "0"), ("91", "0"), ("0", "-181"), ("0" * 41, "0")):
        with pytest.raises(ValueError):
            filter_point(*pair)
