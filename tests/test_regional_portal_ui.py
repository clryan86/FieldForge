"""Prepared regional-map handoffs and desktop ownership; synthetic map data only."""

from __future__ import annotations

import copy
import hashlib
import socket
import threading
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_gps_desktop import root as root
from test_regional_index import build

from fieldforge.online.compat import MapItem
from fieldforge.online.discovery import filter_maps
from fieldforge.ui.gps import GPSWorkspace
from fieldforge.ui.online_compat import OnlineMapWindow
from fieldforge.ui.online_maps import OnlineMapsTab
from fieldforge.ui.portal_integration import install_online_maps


def forbidden(*_args, **_kwargs):
    pytest.fail("A prepared regional map must not open GPS, an image viewer, or a network connection")


@pytest.fixture
def prepared(tmp_path):
    return build(tmp_path)


def catalog(path):
    regional = {
        "id": "regional", "title": "Éclair regional fixture", "filename": path.name,
        "format": "ffmap", "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "download_path": "/api/v1/maps/regional/download",
        "source": "Original synthetic PBF fixture", "attribution": "FieldForge test author",
        "license": "Synthetic test fixture only", "coverage": [-71, 39, -69, 41],
        "version": "1",
    }
    return (
        regional,
        dict(regional, id="image", title="Image fixture", filename="reference.png",
             format="png", bytes=100),
        dict(regional, id="tiles", title="Tiles fixture", filename="tiles.mbtiles",
             format="mbtiles", bytes=200),
    )


def legacy(item):
    return MapItem.parse({
        "id": item["id"], "title": item["title"], "filename": item["filename"],
        "kind": {"ffmap": "regional", "png": "image", "mbtiles": "mbtiles"}[item["format"]],
        "size": item["bytes"], "sha256": item["sha256"], "coverage": "Fictional test area",
        "updated": item["version"],
        **{key: item[key] for key in ("source", "attribution", "license")},
    })


class Value:
    def __init__(self, value=""):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class Viewer:
    """No Tk dependency, so wrong dispatch cannot hide behind a missing display."""

    def __init__(self, parent=None):
        self.parent = parent
        self._disposed = self.busy = self._closing = False
        self.opened = []
        self.result = True

    def open_path(self, path):
        self.opened.append(path)
        return self.result

    def deiconify(self):
        pass

    def lift(self):
        pass

    def winfo_exists(self):
        return not self._disposed

    def destroy(self):
        self._disposed = True


def installed_callback(monkeypatch, viewer):
    maps = SimpleNamespace(open_prepared_region=lambda: viewer, open_path=forbidden)
    selected = []
    navigation = SimpleNamespace(add_separator=lambda: None, add_command=lambda **kw: None)
    notebook = SimpleNamespace(
        select=selected.append, add=lambda *args, **kw: None,
        winfo_toplevel=lambda: SimpleNamespace(nametowidget=lambda name: navigation),
    )
    monkeypatch.setattr("fieldforge.ui.online_maps.OnlineMapsTab",
                        lambda *args, **kwargs: SimpleNamespace(**kwargs))
    panel = install_online_maps(notebook, "unused.db", object(), maps,
                                SimpleNamespace(open=forbidden),
                                SimpleNamespace(entrycget=lambda *args: "navigation"))
    return panel.on_open_map, maps, selected


def test_regional_catalog_filters_keep_native_and_legacy_identity_and_rights(prepared, monkeypatch):
    items = catalog(prepared.path)
    old_items = tuple(legacy(item) for item in items)
    before = copy.deepcopy(items), tuple(asdict(item) for item in old_items)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    for values in (items, old_items):
        assert filter_maps(values, kind="regional") == (values[0],)
        assert filter_maps(values, "prepared regional eclair local search")[0] is values[0]
        assert filter_maps(values, kind="image") == (values[1],)
        assert filter_maps(values, kind="mbtiles") == (values[2],)
        assert filter_maps(values, order="smallest") == (values[1], values[2], values[0])
    assert filter_maps(items, kind="regional", point=(40, -70)) == (items[0],)
    assert filter_maps(items, kind="regional", point=(42, -70)) == ()
    # A compatibility label does not invent numeric geographic coverage.
    assert filter_maps(old_items, kind="regional", point=(40, -70)) == ()
    assert (items, tuple(asdict(item) for item in old_items)) == before


def test_desktop_callback_opens_regional_in_maps_without_starting_gps(monkeypatch):
    viewer = Viewer()
    callback, maps, selected = installed_callback(monkeypatch, viewer)
    callback("synthetic.FFMAP")
    assert viewer.opened == [Path("synthetic.FFMAP")]
    assert selected == [maps]


@pytest.mark.parametrize("state", ("missing", "_disposed", "busy", "_closing", "refused"))
def test_desktop_callback_reports_unavailable_regional_viewers(monkeypatch, state):
    viewer = Viewer()
    if state == "missing":
        viewer = None
    elif state == "refused":
        viewer.result = False
    else:
        setattr(viewer, state, True)
    callback, _maps, selected = installed_callback(monkeypatch, viewer)
    with pytest.raises(ValueError, match="regional"):
        callback("synthetic.ffmap")
    if state != "refused":
        assert not selected
        assert viewer is None or not viewer.opened


def fallback_panel():
    return SimpleNamespace(_disposed=False, on_open_map=None, _regional_window=None,
                           _map_windows=[], status=Value())


def test_standalone_fallback_uses_one_owned_regional_viewer(monkeypatch):
    panel = fallback_panel()
    created = []

    def create(parent):
        created.append(Viewer(parent))
        return created[-1]

    monkeypatch.setattr("fieldforge.ui.regional_index.RegionalIndexWindow", create)
    monkeypatch.setattr("fieldforge_gps.image_map_ui.ImageMapFrame", forbidden)
    monkeypatch.setattr("fieldforge.ui.online_maps.tk.Toplevel", forbidden)
    for filename in ("first.ffmap", "second.FFMAP"):
        assert OnlineMapsTab._open_map_path(panel, filename) is True
    assert len(created) == 1
    assert panel._regional_window.parent is panel
    assert panel._map_windows == created
    assert created[0].opened == [Path("first.ffmap"), Path("second.FFMAP")]


@pytest.mark.parametrize("state", ("busy", "_closing", "refused"))
def test_fallback_rejection_preserves_the_existing_viewer(monkeypatch, state):
    panel = fallback_panel()
    viewer = panel._regional_window = Viewer()
    if state == "refused":
        viewer.result = False
    else:
        setattr(viewer, state, True)
    monkeypatch.setattr("fieldforge.ui.regional_index.RegionalIndexWindow", forbidden)
    assert OnlineMapsTab._open_map_path(panel, "synthetic.ffmap") is False
    assert panel._regional_window is viewer and not viewer._disposed
    assert "Could not open" in panel.status.get()
    assert bool(viewer.opened) is (state == "refused")


def test_failed_new_fallback_is_destroyed_and_a_retry_gets_a_fresh_viewer(monkeypatch):
    panel = fallback_panel()
    created = []

    def create(parent):
        viewer = Viewer(parent)
        viewer.result = bool(created)
        created.append(viewer)
        return viewer

    monkeypatch.setattr("fieldforge.ui.regional_index.RegionalIndexWindow", create)
    assert OnlineMapsTab._open_map_path(panel, "synthetic.ffmap") is False
    assert created[0]._disposed
    assert OnlineMapsTab._open_map_path(panel, "synthetic.ffmap") is True
    assert panel._regional_window is created[1] and not created[1]._disposed
    panel._disposed = True
    assert OnlineMapsTab._open_map_path(panel, "synthetic.ffmap") is False
    assert len(created) == 2


@pytest.mark.parametrize("kind", ("regional", "image"))
def test_gps_portal_dispatches_ffmap_before_opening_receiver(monkeypatch, kind):
    monkeypatch.setattr("fieldforge.ui.online_maps.OnlineMapWindow",
                        lambda parent, **kwargs: SimpleNamespace(**kwargs))
    workspace = GPSWorkspace(object())
    monkeypatch.setattr(workspace, "open", forbidden)
    opened = []
    monkeypatch.setattr(workspace, "open_regional_map", lambda path: opened.append(path) or True)
    portal = workspace.open_portal()
    assert portal.open_asset(Path("synthetic.FFMAP"), kind) is True
    assert opened == [Path("synthetic.FFMAP")]
    assert workspace.receiver is workspace.window is None


@pytest.mark.parametrize("outcome", (False, None, "value-error", "os-error"))
def test_compatibility_open_reports_callback_failure_without_losing_download(outcome):
    opened = []

    def callback(*args):
        opened.append(args)
        if outcome == "value-error":
            raise ValueError("Prepared regional map viewer is busy")
        if outcome == "os-error":
            raise OSError("Saved map was moved")
        return outcome

    downloaded = (Path("synthetic.ffmap"), "regional")
    window = SimpleNamespace(_closed=False, _choosing_file=False, _saving=False,
                             downloaded=downloaded, open_asset=callback, status=Value())
    assert OnlineMapWindow.open_download(window) is (outcome is None)
    assert opened == [downloaded] and window.downloaded is downloaded
    if outcome is not None:
        assert window.status.get()


@pytest.mark.parametrize("guard", ("_closed", "_choosing_file", "_saving"))
def test_compatibility_open_does_not_dispatch_during_close_or_file_actions(guard):
    window = SimpleNamespace(_closed=False, _choosing_file=False, _saving=False,
                             downloaded=(Path("synthetic.ffmap"), "regional"), open_asset=forbidden)
    setattr(window, guard, True)
    assert OnlineMapWindow.open_download(window) is False


def wait_until(root, condition, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if condition():
            return
        time.sleep(.005)
    pytest.fail("Regional map UI did not finish its task")


def wait_regional(root, window):
    wait_until(root, lambda: not window.busy and not window._pending_refresh
               and window._refresh_id is None and window._resize_id is None)


@pytest.fixture
def native(root, tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("fieldforge_gps.image_map_ui.ImageMapFrame", forbidden)
    monkeypatch.setattr("fieldforge.ui.gps.GPSWindow", forbidden)
    sentinel = tmp_path / "household.db"
    sentinel.write_bytes(b"Unrelated household data must remain unread and unchanged")
    panel = OnlineMapsTab(root, sentinel, client_factory=forbidden)
    panel.pack(fill="both", expand=True)
    wait_until(root, lambda: not panel.busy)
    yield panel
    regional = panel._regional_window
    panel.destroy()
    panel._worker.shutdown(wait=True, cancel_futures=True)
    if regional is not None:
        regional._worker.shutdown(wait=True, cancel_futures=True)
    assert sentinel.read_bytes() == b"Unrelated household data must remain unread and unchanged"


def test_native_catalog_and_local_selection_remain_usable_after_disconnect(root, native, prepared):
    items = catalog(prepared.path)
    before = copy.deepcopy(items)
    native._complete("catalog", items)
    native.maps_tree.selection_set("0")
    native.select_map()
    native.catalog_filters.kind.set("Prepared regional maps")
    assert native.maps_tree.get_children() == ("0",)
    assert native.maps_tree.selection() == ("0",)
    assert "Prepared regional map (.ffmap)" in native.maps_tree.item("0", "values")
    details = native.map_info.get()
    assert "local display and search; not a routing graph" in details
    assert items[0]["attribution"] in details and items[0]["license"] in details
    native._display_local((prepared.path,), (), [(prepared.path.name, "synthetic index")])
    native.local_maps_tree.selection_set("0")
    native.disconnect()
    assert native.maps_tree.selection() == native.local_maps_tree.selection() == ("0",)
    assert native.map_info.get() == details and native._catalog == before
    native.catalog_filters.query.set("eclair")
    assert native.maps_tree.get_children() == ("0",)
    assert native.download_button.instate(["disabled"])
    native.catalog_filters.kind.set("Images")
    assert not native.maps_tree.get_children() and not native.maps_tree.selection()
    native.catalog_filters.query.set("")
    assert native.maps_tree.get_children() == ("1",)
    assert native.local_maps_tree.selection() == ("0",) and native._local_maps == (prepared.path,)


def test_standalone_regional_map_reopens_and_searches_without_original_source(root, native, prepared):
    before = prepared.path.read_bytes()
    (prepared.path.parent / "source.osm.pbf").unlink()
    assert native._open_map_path(prepared.path) is True
    window = native._regional_window
    wait_regional(root, window)
    assert window.index.path == prepared.path and window.master is native
    window.query.set("Map Street")
    wait_regional(root, window)
    assert len(window.matches) == 2
    assert native._open_map_path(prepared.path) is True
    assert native._regional_window is window and native._map_windows == [window]
    wait_regional(root, window)
    assert prepared.path.read_bytes() == before
    assert native.can_close()
    native.close()
    window._worker.shutdown(wait=True, cancel_futures=True)
    assert window._disposed and native._regional_window is None
    assert all(not thread.is_alive() for thread in window._worker._threads)


def delayed_inspection(monkeypatch, prepared):
    started, release = threading.Event(), threading.Event()

    def delayed(*_args, **_kwargs):
        started.set()
        if not release.wait(4):
            raise RuntimeError("Test did not release the delayed regional reader")
        return prepared  # Intentionally late result after cancellation.

    monkeypatch.setattr("fieldforge.ui.regional_index.inspect_index", delayed)
    return started, release


def test_normal_portal_close_cancels_and_defers_a_busy_owned_regional_window(
    root, native, prepared, monkeypatch,
):
    started, release = delayed_inspection(monkeypatch, prepared)
    try:
        assert native._open_map_path(prepared.path) is True
        window = native._regional_window
        assert started.wait(2)
        assert native.can_close() is False
        assert window._cancel.is_set() and window._closing
        assert native.close() is False
        assert not native._disposed and native._regional_window is window
        assert native._open_map_path(prepared.path) is False
        release.set()
        wait_until(root, lambda: window._disposed)
        assert window.index is None
        assert native.can_close()
        native.close()
        assert native._disposed
    finally:
        release.set()
        if native._regional_window is not None:
            native._regional_window._worker.shutdown(wait=True, cancel_futures=True)


def test_direct_portal_destruction_cancels_regional_worker_and_discards_late_result(
    root, native, prepared, monkeypatch,
):
    started, release = delayed_inspection(monkeypatch, prepared)
    try:
        native._open_map_path(prepared.path)
        window = native._regional_window
        assert started.wait(2)
        native.destroy()
        assert native._disposed and window._disposed and window._cancel.is_set()
        release.set()
        window._worker.shutdown(wait=True, cancel_futures=True)
        root.update()
        assert window.index is None and window._done is None
        assert all(not thread.is_alive() for thread in window._worker._threads)
    finally:
        release.set()


def test_compatibility_labels_filter_and_open_regional_download_while_offline(root, prepared):
    opened = []
    window = OnlineMapWindow(root, open_asset=lambda *args: opened.append(args))
    try:
        window.items = tuple(legacy(item) for item in catalog(prepared.path))
        window._catalog_loaded = True
        window._render_catalog(preserve_selection=False)
        window.catalog_filters.kind.set("Prepared regional maps")
        assert window.map_table.get_children() == ("0",)
        window.map_table.selection_set("0")
        window._map_selected()
        details = window.map_detail.get()
        assert "Prepared regional map (.ffmap)" in details
        assert "not a routing graph" in details
        item = window.items[0]
        assert all(value in details for value in (item.source, item.attribution, item.license))
        window.downloaded = (prepared.path, "regional")
        window.disconnect()
        assert window.map_detail.get() == details and window.map_table.selection() == ("0",)
        assert window.download_button.instate(["disabled"])
        assert not window.open_button.instate(["disabled"])
        assert window.open_download() is True
        assert opened == [(prepared.path, "regional")]
        window.catalog_filters.kind.set("Images")
        assert window.map_table.get_children() == ("1",) and not window.map_table.selection()
    finally:
        window.destroy()
        window.worker.join(2)
    assert not window.worker.is_alive()


@pytest.mark.parametrize("destroy_parent", (False, True))
def test_gps_portal_regional_open_owns_cleanup_without_creating_receiver(
    root, prepared, monkeypatch, destroy_parent,
):
    import tkinter as tk

    monkeypatch.setattr("fieldforge.ui.gps.GPSWindow", forbidden)
    monkeypatch.setattr("fieldforge_gps.image_map_ui.ImageMapFrame", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    owner = tk.Toplevel(root)
    workspace = GPSWorkspace(owner)
    portal = workspace.open_portal()
    window = None
    try:
        portal.downloaded = (prepared.path, "regional")
        assert portal.open_download() is True
        window = workspace._regional_window
        wait_regional(root, window)
        window.query.set("Map Street")
        wait_regional(root, window)
        assert len(window.matches) == 2
        assert workspace.receiver is workspace.window is None
        assert portal.open_download() is True
        assert workspace._regional_window is window
        wait_regional(root, window)
        if destroy_parent:
            owner.destroy()
        else:
            assert workspace.can_close()
            workspace.close()
            assert owner.winfo_exists()
        assert workspace._regional_window is None and window._disposed
        assert workspace.receiver is workspace.window is None
    finally:
        if owner.winfo_exists():
            owner.destroy()
        portal.worker.join(2)
        if window is not None:
            window._worker.shutdown(wait=True, cancel_futures=True)
    assert not portal.worker.is_alive()
