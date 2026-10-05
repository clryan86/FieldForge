"""Explicit collection selection produces real, independently usable regional maps."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_osm_source import fixture as pbf_fixture
from test_osm_source import integer
from test_regional_index import build
from test_regional_portal import portal

from fieldforge.navigation import regional_index as regional
from fieldforge.navigation.mbtiles import MapCancelled
from fieldforge.online import collection
from fieldforge.online.catalog import Catalog, CatalogError, main
from fieldforge.online.client import PortalClient
from fieldforge.online.inventory import publish_inventory
from fieldforge.online.storage import PortalLibrary

SNAPSHOT = 1_700_000_000


def digest(value):
    return hashlib.sha256(value).hexdigest()


def write_collection(case):
    case.collection.write_text(json.dumps(case.document, ensure_ascii=False), encoding="utf-8")


def zip_entries(case, position, entries):
    pack = case.document["packs"][position]
    path = case.archives / pack["filename"]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, body in entries:
            archive.writestr(name, body)
    pack["expanded_bytes"] = sum(len(body) for _name, body in entries)
    refresh_archive(case, position)


def refresh_archive(case, position):
    pack = case.document["packs"][position]
    raw = (case.archives / pack["filename"]).read_bytes()
    pack.update(bytes=len(raw), sha256=digest(raw))
    write_collection(case)


def make_case(tmp_path, *, snapshot=SNAPSHOT):
    archives = tmp_path / "archives"
    archives.mkdir()
    case = SimpleNamespace(root=tmp_path, archives=archives,
                           collection=tmp_path / "collection.json", output=tmp_path / "prepared",
                           indexes=[], document={
                               "format": "fieldforge-map-collection-v1",
                               "checked_utc": "2026-10-05T12:00:00Z",
                               "notice": "TEST FIXTURE: prepared display/search data; no navigation validation.",
                               "packs": [], "totals": {},
                           })
    for position in range(2):
        source_folder = tmp_path / f"source-{position}"
        source_folder.mkdir()
        raw = pbf_fixture(extra_header=b"" if snapshot is None else integer(32, snapshot))
        index = build(source_folder, raw)
        case.indexes.append(index)
        meta = index.metadata
        case.document["packs"].append({
            "filename": f"TEST-region-{position + 1}.zip",
            "bytes": 1, "sha256": "0" * 64,
            "region_id": f"{position + 1:032x}", "label": f"TEST Synthetic region {position + 1}",
            "source_name": meta["source_name"], "source_sha256": meta["source_sha256"],
            "replication_timestamp": meta["replication_timestamp"],
            "expanded_bytes": index.path.stat().st_size,
            "map_features": meta["features"], "address_tagged_objects": meta["address_features"],
            "missing_node_ways": meta["missing_node_ways"],
            "road_preparation": {"state": "blocked", "reason": "TEST fixture has no route graph."},
            "license": meta["license"], "status": "verified-download",
            "installed_on_device": "not-checked", "validated_navigation": False,
        })
        zip_entries(case, position, [(f"region-{position}/map.ffmap", index.path.read_bytes()),
                                    ("README.txt", b"Synthetic regression data only.")])
    return case


@pytest.fixture
def case(tmp_path):
    return make_case(tmp_path)


def prepare(case, *, filenames=None, **kwargs):
    if filenames is None:
        filenames = [case.document["packs"][0]["filename"]]
    return collection.prepare_collection(case.collection, case.archives, case.output,
                                         filenames=filenames, **kwargs)


def assert_no_publication(case, before):
    assert not case.output.exists() and not case.output.is_symlink()
    assert set(case.root.iterdir()) == before


def test_explicit_subset_preserves_index_bytes_and_ignores_missing_unselected_archive(case):
    selected, unselected = case.document["packs"]
    (case.archives / unselected["filename"]).unlink()
    original_json = case.collection.read_bytes()
    original_zip = (case.archives / selected["filename"]).read_bytes()
    original_map = case.indexes[0].path.read_bytes()
    result = prepare(case)
    assert result["map_count"] == 1
    assert Path(result["inventory"]).resolve() == (case.output / "inventory.json").resolve()
    assert Path(result["receipt"]).resolve() == (case.output / "preparation-receipt.json").resolve()
    assert set(case.output.iterdir()) == {case.output / "inventory.json", case.output / "maps",
                                        case.output / "preparation-receipt.json"}
    target = case.output / "maps" / (selected["region_id"] + ".ffmap")
    assert tuple((case.output / "maps").iterdir()) == (target,)
    assert target.read_bytes() == original_map
    assert case.collection.read_bytes() == original_json
    assert (case.archives / selected["filename"]).read_bytes() == original_zip
    assert case.indexes[0].path.read_bytes() == original_map
    reopened = regional.inspect_index(target)
    assert reopened.metadata == case.indexes[0].metadata
    assert len(regional.search_index(reopened, "Map Street").features) == 2


def test_existing_directory_aliases_resolve_to_the_same_chosen_inputs_and_new_output(case):
    result = collection.prepare_collection(
        case.archives / ".." / case.collection.name,
        case.archives / ".." / case.archives.name,
        case.archives / ".." / case.output.name,
        filenames=[case.document["packs"][0]["filename"]],
    )
    assert Path(result["inventory"]).resolve() == (case.output / "inventory.json").resolve()
    assert Path(result["receipt"]).resolve() == (case.output / "preparation-receipt.json").resolve()
    entry, = json.loads((case.output / "inventory.json").read_bytes())["maps"]
    assert (case.output / "maps" / entry["filename"]).read_bytes() == case.indexes[0].path.read_bytes()


@pytest.mark.parametrize("length", (240, 241))
def test_preparation_title_limit_matches_the_ordinary_inventory_publisher(case, length):
    title = "T" * length
    case.document["packs"][0]["label"] = title
    write_collection(case)
    before = set(case.root.iterdir())
    if length == 241:
        with pytest.raises(CatalogError):
            prepare(case)
        assert_no_publication(case, before)
    else:
        result = prepare(case)
        asset, = publish_inventory(case.root / "catalog", result["inventory"])
        assert asset["title"] == title
        assert Catalog(case.root / "catalog").assets() == [asset]


def test_inventory_and_receipt_preserve_three_digest_layers_then_publish_download_and_search_offline(
    case, monkeypatch,
):
    original_collection = case.collection.read_bytes()
    originals = [index.path.read_bytes() for index in case.indexes]
    selected = [pack["filename"] for pack in case.document["packs"]]
    result = prepare(case, filenames=selected)
    inventory = json.loads(Path(result["inventory"]).read_bytes())
    receipt = json.loads(Path(result["receipt"]).read_bytes())
    assert set(inventory) == {"schema_version", "asset_folder", "maps"}
    assert inventory["schema_version"] == 1 and inventory["asset_folder"] == "maps"
    assert result["map_count"] == len(inventory["maps"]) == len(receipt["maps"]) == 2
    assert receipt["format"] == "fieldforge-map-collection-preparation-v1"
    assert receipt["scope"] == "display/search"
    assert "PBF" in receipt["notice"] and "routing" in receipt["notice"].casefold()
    assert receipt["collection"] == {
        "filename": case.collection.name, "bytes": len(original_collection),
        "sha256": digest(original_collection), "checked_utc": case.document["checked_utc"],
        "notice": case.document["notice"],
    }
    version = datetime.fromtimestamp(SNAPSHOT, timezone.utc).isoformat().replace("+00:00", "Z")
    for entry, note, pack, index, original in zip(
        inventory["maps"], receipt["maps"], case.document["packs"], case.indexes, originals,
    ):
        meta = index.metadata
        assert set(entry) == {"id", "title", "filename", "coverage", "version",
                              "source", "attribution", "license"}
        assert entry["id"] == note["id"] == "regional-" + pack["region_id"]
        assert entry["filename"] == note["map"]["filename"] == pack["region_id"] + ".ffmap"
        assert entry["title"] == note["title"] == pack["label"]
        assert entry["coverage"] == note["coverage"] == meta["bounds"]
        assert entry["version"] == note["version"] == version
        assert entry["attribution"] == note["attribution"] == meta["attribution"]
        assert entry["license"] == note["license"] == meta["license"]
        assert entry["source"] == meta["source_name"]
        assert note["region_id"] == pack["region_id"]
        assert note["archive"] == {"filename": pack["filename"], "bytes": pack["bytes"],
                                   "sha256": pack["sha256"]}
        assert note["map"] == {"filename": entry["filename"], "bytes": len(original),
                               "sha256": digest(original)}
        assert note["source"] == {
            "name": meta["source_name"], "bytes": meta["source_bytes"],
            "sha256": meta["source_sha256"], "replication_timestamp": SNAPSHOT,
            "verification": "receipt-matched-collection",
        }
        assert len({note["archive"]["sha256"], note["map"]["sha256"],
                    note["source"]["sha256"]}) == 3
        assert note["features"] == meta["features"]
        assert note["address_features"] == meta["address_features"]
        assert note["missing_node_ways"] == meta["missing_node_ways"]
        assert note["declared_road_preparation"] == pack["road_preparation"]
        # No source PBF is included in these ZIPs: its fingerprint is a matched declaration.
        with zipfile.ZipFile(case.archives / pack["filename"]) as archive:
            assert not any(name.endswith(".pbf") for name in archive.namelist())

    catalog_root = case.root / "catalog"
    assets = publish_inventory(catalog_root, result["inventory"])
    assert Catalog(catalog_root).assets() == assets
    assert all(asset["format"] == "ffmap" for asset in assets)
    library = PortalLibrary(case.root / "offline")
    with portal(catalog_root) as origin:
        client = PortalClient(origin)
        client.connect()
        try:
            assert list(client.catalog()) == assets
            downloaded = [client.download(asset, library.maps_directory) for asset in assets]
        finally:
            client.disconnect()
    for index in case.indexes:
        shutil.rmtree(index.path.parent)
    shutil.rmtree(case.archives)
    case.collection.unlink()
    shutil.rmtree(case.output)
    # Published objects are read-only; removing them explicitly also works on Windows.
    for path in (catalog_root / "objects").iterdir():
        path.chmod(0o600)
    shutil.rmtree(catalog_root)
    monkeypatch.setattr(socket, "create_connection",
                        lambda *_args, **_kwargs: pytest.fail("Offline search requested a network connection"))
    assert set(library.maps()) == set(downloaded)
    for path, original in zip(downloaded, originals):
        assert path.read_bytes() == original
        reopened = regional.inspect_index(path)
        found = regional.search_index(reopened, "Map Street").features
        assert len(found) == 2 and {feature.id for feature in found} == {"node/1", "way/10"}


def test_cli_unknown_snapshot_uses_source_digest_instead_of_collection_check_date(tmp_path, capsys):
    case = make_case(tmp_path, snapshot=None)
    pack = case.document["packs"][0]
    code = main(["prepare-collection", "--collection", str(case.collection),
                 "--archives", str(case.archives), "--output", str(case.output),
                 "--select", pack["filename"]])
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    inventory = json.loads(Path(result["inventory"]).read_bytes())
    receipt = json.loads(Path(result["receipt"]).read_bytes())
    assert inventory["maps"][0]["version"] == "source-sha256:" + pack["source_sha256"]
    assert receipt["maps"][0]["source"]["replication_timestamp"] is None
    assert receipt["maps"][0]["version"] == inventory["maps"][0]["version"]
    assert case.document["checked_utc"] not in inventory["maps"][0]["version"]


@pytest.mark.parametrize("choices", ([], ["missing.zip"], ["TEST-region-1.zip", "TEST-region-1.zip"]))
def test_missing_duplicate_and_unknown_explicit_choices_publish_nothing(case, choices):
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case, filenames=choices)
    assert_no_publication(case, before)


@pytest.mark.parametrize("damage", ("malformed", "duplicate-field", "duplicate-pack", "oversized"))
def test_invalid_collection_document_fails_before_archive_import(case, monkeypatch, damage):
    if damage == "malformed":
        case.collection.write_bytes(b'{"format":\xff}')
    elif damage == "duplicate-field":
        raw = case.collection.read_text(encoding="utf-8")
        case.collection.write_text(raw.replace('{', '{"format":"fieldforge-map-collection-v1",', 1),
                                   encoding="utf-8")
    elif damage == "duplicate-pack":
        case.document["packs"].append(copy.deepcopy(case.document["packs"][0]))
        write_collection(case)
    else:
        with case.collection.open("wb") as stream:
            stream.truncate(8 * 1024**2 + 1)
    monkeypatch.setattr(collection, "import_archive",
                        lambda *_args, **_kwargs: pytest.fail("Invalid collection reached archive import"))
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)


@pytest.mark.parametrize("field,value", (("filename", "../outside.zip"),
                                         ("filename", "C:outside.zip"),
                                         ("region_id", "../outside")))
def test_collection_names_cannot_escape_archive_or_output_folders(case, field, value):
    case.document["packs"][0][field] = value
    write_collection(case)
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case, filenames=[case.document["packs"][0]["filename"]])
    assert_no_publication(case, before)


@pytest.mark.parametrize("source", ("collection", "archive"))
def test_collection_and_selected_archive_must_be_regular_files_not_symlinks(case, source):
    path = case.collection if source == "collection" else case.archives / case.document["packs"][0]["filename"]
    real = path.with_name(path.name + ".real")
    path.rename(real)
    path.symlink_to(real)
    original = real.read_bytes()
    before = set(case.root.iterdir())
    with pytest.raises((CatalogError, OSError)):
        prepare(case)
    assert path.is_symlink() and real.read_bytes() == original
    assert_no_publication(case, before)


@pytest.mark.parametrize("kind", ("missing", "directory"))
def test_selected_archive_must_exist_as_a_regular_file(case, kind):
    path = case.archives / case.document["packs"][0]["filename"]
    path.unlink()
    if kind == "directory":
        path.mkdir()
    before = set(case.root.iterdir())
    with pytest.raises((CatalogError, OSError)):
        prepare(case)
    assert_no_publication(case, before)


@pytest.mark.parametrize("field", ("bytes", "sha256"))
def test_zip_integrity_is_checked_before_import(case, monkeypatch, field):
    pack = case.document["packs"][0]
    pack[field] = pack[field] + 1 if field == "bytes" else "f" * 64
    write_collection(case)
    monkeypatch.setattr(collection, "import_archive",
                        lambda *_args, **_kwargs: pytest.fail("Unverified ZIP reached the index importer"))
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)


@pytest.mark.parametrize("field,value", (("source_name", "another.osm.pbf"),
                                         ("source_sha256", "f" * 64),
                                         ("map_features", 1),
                                         ("address_tagged_objects", 1),
                                         ("missing_node_ways", 1),
                                         ("replication_timestamp", SNAPSHOT + 1),
                                         ("license", "CC0-1.0")))
def test_declared_source_counts_snapshot_and_license_must_match_real_index(case, field, value):
    case.document["packs"][0][field] = value
    write_collection(case)
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)


@pytest.mark.parametrize("damage", ("damaged", "unsafe", "duplicate-index", "missing-index"))
def test_archive_structure_checks_remain_owned_by_real_regional_importer(case, damage):
    raw_map = case.indexes[0].path.read_bytes()
    if damage == "unsafe":
        entries = [("../map.ffmap", raw_map)]
    elif damage == "duplicate-index":
        entries = [("map.ffmap", raw_map), ("another/map.ffmap", raw_map)]
    elif damage == "missing-index":
        entries = [("other.sqlite", raw_map)]
    else:
        entries = [("map.ffmap", raw_map)]
    zip_entries(case, 0, entries)
    if damage == "damaged":
        archive = case.archives / case.document["packs"][0]["filename"]
        raw = bytearray(archive.read_bytes())
        offset = raw.index(b"SQLite format 3\x00") + 20
        raw[offset] ^= 1  # ZIP CRC no longer matches, while declared outer integrity does.
        archive.write_bytes(raw)
        refresh_archive(case, 0)
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)


def test_damaged_index_is_rejected_and_staged_extract_is_removed(case):
    index = case.indexes[0].path
    with closing(sqlite3.connect(index)) as db, db:
        db.execute("DELETE FROM feature_bounds")
    zip_entries(case, 0, [("map.ffmap", index.read_bytes())])
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)


@pytest.mark.parametrize("source", ("archive", "collection"))
def test_replacement_after_integrity_checks_is_detected_even_with_identical_bytes(case, monkeypatch, source):
    original_import = collection.import_archive

    def replaced(archive, target, **kwargs):
        path = Path(archive) if source == "archive" else case.collection
        replacement = path.with_name(path.name + ".replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
        return original_import(archive, target, **kwargs)

    monkeypatch.setattr(collection, "import_archive", replaced)
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)


def test_all_selected_archives_are_rechecked_after_import_before_output_is_published(case, monkeypatch):
    original_import = collection.import_archive
    imported = []

    def changed(archive, target, **kwargs):
        result = original_import(archive, target, **kwargs)
        imported.append(Path(archive))
        if len(imported) == 2:
            with imported[0].open("ab") as stream:
                stream.write(b"Changed after the first selected index was imported")
        return result

    monkeypatch.setattr(collection, "import_archive", changed)
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case, filenames=[pack["filename"] for pack in case.document["packs"]])
    assert len(imported) == 2
    assert_no_publication(case, before)


@pytest.mark.parametrize("kind", ("file", "directory", "symlink"))
def test_existing_output_is_preserved_without_any_preparation(case, monkeypatch, kind):
    if kind == "directory":
        case.output.mkdir()
        protected = case.output / "unrelated.txt"
    elif kind == "symlink":
        protected = case.root / "unrelated.txt"
        case.output.symlink_to(protected)
    else:
        protected = case.output
    protected.write_bytes(b"Existing user data")
    before = set(case.root.iterdir())
    monkeypatch.setattr(collection, "import_archive",
                        lambda *_args, **_kwargs: pytest.fail("Existing output reached archive import"))
    with pytest.raises((CatalogError, FileExistsError)):
        prepare(case)
    assert protected.read_bytes() == b"Existing user data"
    assert set(case.root.iterdir()) == before
    if kind == "symlink":
        assert case.output.is_symlink()


@pytest.mark.parametrize("kind", ("file", "directory"))
def test_concurrent_output_claim_survives_preparation_failure(case, kind):
    protected = case.output if kind == "file" else case.output / "unrelated.txt"

    def competitor(_done, _total, _filename):
        if kind == "directory":
            case.output.mkdir()
        protected.write_bytes(b"Concurrent owner's data")

    before = set(case.root.iterdir())
    with pytest.raises((CatalogError, FileExistsError)):
        prepare(case, progress=competitor)
    assert protected.read_bytes() == b"Concurrent owner's data"
    assert set(case.root.iterdir()) == before | {case.output}


@pytest.mark.parametrize("failure", ("io", "cancel", "interrupt"))
def test_multimap_failure_cancel_and_interruption_remove_all_staged_output(case, monkeypatch, failure):
    original_import = collection.import_archive
    imported = []
    cancel = threading.Event()

    def interrupted(archive, target, **kwargs):
        if imported:
            if failure == "interrupt":
                raise KeyboardInterrupt("Interrupted while preparing the second map")
            raise OSError("Second selected map could not be read")
        result = original_import(archive, target, **kwargs)
        imported.append(Path(target))
        if failure == "cancel":
            cancel.set()
        return result

    monkeypatch.setattr(collection, "import_archive", interrupted)
    before = set(case.root.iterdir())
    expected = MapCancelled if failure == "cancel" else KeyboardInterrupt if failure == "interrupt" else (CatalogError, OSError)
    with pytest.raises(expected):
        prepare(case, filenames=[pack["filename"] for pack in case.document["packs"]], cancel=cancel)
    assert len(imported) == 1 and not imported[0].exists()
    assert_no_publication(case, before)


def test_failed_inventory_publication_removes_already_installed_maps_and_receipt(case, monkeypatch):
    original_publish = collection._publish_new_path
    installed = []

    def fail_inventory(temporary, target):
        target = Path(target)
        if target.name == "inventory.json":
            assert installed
            raise OSError("Could not install completed inventory")
        original_publish(temporary, target)
        installed.append(target)

    monkeypatch.setattr(collection, "_publish_new_path", fail_inventory)
    before = set(case.root.iterdir())
    with pytest.raises((CatalogError, OSError)):
        prepare(case)
    assert installed and all(not path.exists() for path in installed)
    assert_no_publication(case, before)


@pytest.mark.parametrize("change", ("collection", "archive", "cancel"))
def test_final_publication_rechecks_inputs_and_cancellation_before_reporting_success(case, monkeypatch, change):
    original_publish = collection._publish_new_path
    cancel = threading.Event()
    installed = []

    def changed_after_install(temporary, target):
        original_publish(temporary, target)
        installed.append(Path(target))
        if Path(target).name == "inventory.json":
            if change == "cancel":
                cancel.set()
            else:
                path = case.collection if change == "collection" else case.archives / case.document["packs"][0]["filename"]
                with path.open("ab") as stream:
                    stream.write(b" ")

    monkeypatch.setattr(collection, "_publish_new_path", changed_after_install)
    before = set(case.root.iterdir())
    with pytest.raises(MapCancelled if change == "cancel" else CatalogError):
        prepare(case, cancel=cancel)
    assert any(path.name == "inventory.json" for path in installed)
    assert all(not path.exists() for path in installed)
    assert_no_publication(case, before)


def test_failed_publication_keeps_a_competitor_created_map_file(case, monkeypatch):
    destination = case.output / "maps" / (case.document["packs"][0]["region_id"] + ".ffmap")

    def competitor(_temporary, target):
        assert Path(target).resolve() == destination.resolve()
        Path(target).write_bytes(b"Concurrent map owner")
        raise FileExistsError("A competing map appeared before publication")

    monkeypatch.setattr(collection, "_publish_new_path", competitor)
    before = set(case.root.iterdir())
    with pytest.raises((CatalogError, FileExistsError)):
        prepare(case)
    assert destination.read_bytes() == b"Concurrent map owner"
    assert not (case.output / "inventory.json").exists()
    assert set(case.root.iterdir()) == before | {case.output}


def test_cli_requires_selection_and_reports_bad_archive_without_traceback(case, capsys):
    arguments = ["prepare-collection", "--collection", str(case.collection),
                 "--archives", str(case.archives), "--output", str(case.output)]
    with pytest.raises(SystemExit) as missing:
        main(arguments)
    assert missing.value.code == 2
    assert "--select" in capsys.readouterr().err
    pack = case.document["packs"][0]
    (case.archives / pack["filename"]).write_bytes(b"Damaged ZIP fixture")
    with pytest.raises(SystemExit) as invalid:
        main(arguments + ["--select", pack["filename"]])
    assert invalid.value.code == 2
    error = capsys.readouterr().err
    assert "failed" in error.casefold() and "Traceback" not in error
    assert not case.output.exists()


@pytest.mark.parametrize("command", ("prepare-collection", "build"))
def test_cli_module_reports_validation_errors_without_a_python_traceback(case, command):
    before = set(case.root.iterdir())
    arguments = (["prepare-collection", "--collection", str(case.collection),
                  "--archives", str(case.archives), "--output", str(case.output),
                  "--select", "unlisted.zip"] if command == "prepare-collection" else
                 ["build", "--root", str(case.output), "--inventory", str(case.collection)])
    result = subprocess.run([sys.executable, "-m", "fieldforge.online.catalog", *arguments],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 2, result.stderr
    assert "Map publishing failed:" in result.stderr
    assert "Traceback" not in result.stderr and not result.stdout
    assert_no_publication(case, before)
