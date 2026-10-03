"""Build-input checks without pretending to execute Windows binaries on Linux."""

import json
from types import SimpleNamespace

import pytest

from scripts import build_windows


@pytest.fixture
def components(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    prefix = tmp_path / "Python runtime"
    prefix.mkdir()
    (prefix / "LICENSE.txt").write_bytes(b"Synthetic Python license fixture\r\n")
    directories = {name: prefix / "tcl" / name for name in ("tcl8.6", "tk8.6")}
    for name, directory in directories.items():
        directory.mkdir(parents=True)
        (directory / "license.terms").write_bytes(f"Synthetic {name} terms\r\n".encode())
    class TclPath:
        # A real Windows Tk call may return Tcl_Obj, not a PathLike/string.
        def __init__(self, path):
            self.path = path
        def __str__(self):
            return str(self.path)
    closed = []
    def call(*args):
        if args[:2] == ("package", "provide"):
            return "fixture"
        return TclPath(directories["tcl8.6" if args == ("info", "library") else "tk8.6"])
    monkeypatch.setattr(tk, "Tk", lambda: SimpleNamespace(tk=SimpleNamespace(call=call),
                        withdraw=lambda: None, destroy=lambda: closed.append(True)))
    monkeypatch.setattr(build_windows.sys, "base_prefix", str(prefix))
    def distribution(name):
        path = prefix / f"{name}.dist-info" / "licenses" / "LICENSE.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"Synthetic {name} license\n".encode())
        return SimpleNamespace(version="fixture", files=(path.relative_to(prefix),),
                               locate_file=lambda item: prefix / item)
    monkeypatch.setattr(build_windows.importlib.metadata, "distribution", distribution)
    return prefix, directories, closed, tmp_path / "notices"


def test_component_notices_handle_tcl_objects_and_copy_exact_license_bytes(components):
    prefix, directories, closed, destination = components
    build_windows.component_notices(destination)
    assert closed == [True]
    assert (destination / "CPython-LICENSE.txt").read_bytes() == (prefix / "LICENSE.txt").read_bytes()
    for name, directory in zip(("Tcl", "Tk"), directories.values()):
        assert (destination / f"{name}-license.terms").read_bytes() == (directory / "license.terms").read_bytes()
    assert json.loads((destination / "COMPONENTS.json").read_text())["pypdf"] == "fixture"
    assert (destination / "pyinstaller-0-LICENSE.txt").read_bytes() == b"Synthetic pyinstaller license\n"
    assert (destination / "pyserial-0-LICENSE.txt").read_bytes() == b"Synthetic pyserial license\n"
    assert (destination / "Pillow-0-LICENSE.txt").read_bytes() == b"Synthetic Pillow license\n"


def test_missing_tk_notice_still_blocks_distribution(components):
    _, directories, closed, destination = components
    (directories["tk8.6"] / "license.terms").unlink()
    with pytest.raises(FileNotFoundError, match="Tk license.terms is required"):
        build_windows.component_notices(destination)
    assert closed == [True]
    assert not (destination / "COMPONENTS.json").exists()


def test_bundle_allows_only_exact_fictional_map_at_expected_path(tmp_path):
    import shutil
    from pathlib import Path

    bundle = tmp_path / "bundle"
    fixture = bundle / "_internal/fieldforge_gps/data/FICTIONAL-MAP.mbtiles"
    fixture.parent.mkdir(parents=True)
    source = Path(build_windows.ROOT) / "fieldforge_gps/data/FICTIONAL-MAP.mbtiles"
    shutil.copy2(source, fixture)
    build_windows.validate_bundle_file(fixture, bundle)
    fixture.write_bytes(b"Unrelated private map content")
    with pytest.raises(ValueError, match="Unexpected data file"):
        build_windows.validate_bundle_file(fixture, bundle)
    wrong_path = bundle / "private.mbtiles"
    shutil.copy2(source, wrong_path)
    with pytest.raises(ValueError, match="Unexpected data file"):
        build_windows.validate_bundle_file(wrong_path, bundle)
    database = bundle / "household.db"
    database.write_bytes(b"Private data")
    with pytest.raises(ValueError, match="Unexpected data file"):
        build_windows.validate_bundle_file(database, bundle)


@pytest.mark.parametrize("name", ["Tcl", "Tk"])
def test_matching_upstream_notice_fills_missing_installer_file(tmp_path, name):
    notice = build_windows.tcltk_notice(name, tmp_path, "8.6.15")
    assert build_windows.digest(notice) == build_windows.TCLTK_NOTICE_HASHES[name]
    assert b"notice is included verbatim" in notice.read_bytes()
    with pytest.raises(FileNotFoundError, match="runtime 8.6.16"):
        build_windows.tcltk_notice(name, tmp_path, "8.6.16")


def test_modified_upstream_notice_still_blocks_distribution(tmp_path, monkeypatch):
    notice = tmp_path / "packaging/notices/tcltk-8.6.15/Tcl-license.terms"
    notice.parent.mkdir(parents=True)
    notice.write_bytes(b"Not the original terms")
    monkeypatch.setattr(build_windows, "ROOT", tmp_path)
    with pytest.raises(FileNotFoundError, match="Tcl license.terms is required"):
        build_windows.tcltk_notice("Tcl", tmp_path / "runtime", "8.6.15")


def test_pyserial_wheel_without_license_uses_exact_upstream_notice(components, monkeypatch):
    _, _, _, destination = components
    original = build_windows.importlib.metadata.distribution
    monkeypatch.setattr(build_windows.importlib.metadata, "distribution", lambda name:
                        SimpleNamespace(version="3.5", files=None) if name == "pyserial" else original(name))
    build_windows.component_notices(destination)
    source = build_windows.ROOT / "packaging/notices/pyserial-3.5/LICENSE.txt"
    assert (destination / "pyserial-0-LICENSE.txt").read_bytes() == source.read_bytes()
    provenance = json.loads((destination / "pyserial-NOTICE-SOURCES.json").read_text())
    assert provenance["version"] == "3.5"
    assert provenance["sha256"] == build_windows.digest(source) == build_windows.PYSERIAL_NOTICE_HASH
    assert json.loads((destination / "COMPONENTS.json").read_text())["pyserial"] == "3.5"


@pytest.mark.parametrize("version", ["3.4", "3.6", "3.5.dev0"])
def test_pyserial_unknown_version_cannot_borrow_notice(version):
    with pytest.raises(FileNotFoundError, match="version-matched license"):
        build_windows.distribution_notices("pyserial", SimpleNamespace(version=version, files=()))


@pytest.mark.parametrize("altered", [False, True])
def test_missing_or_changed_pyserial_notice_blocks_distribution(tmp_path, monkeypatch, altered):
    if altered:
        path = tmp_path / "packaging/notices/pyserial-3.5/LICENSE.txt"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"Changed notice")
    monkeypatch.setattr(build_windows, "ROOT", tmp_path)
    with pytest.raises(FileNotFoundError, match="version-matched license"):
        build_windows.distribution_notices("pyserial", SimpleNamespace(version="3.5", files=()))


def test_recorded_but_absent_installed_license_blocks_distribution(tmp_path):
    package = SimpleNamespace(version="fixture", files=("licenses/LICENSE.txt",),
                              locate_file=lambda item: tmp_path / item)
    with pytest.raises(FileNotFoundError, match="version-matched license"):
        build_windows.distribution_notices("Pillow", package)
