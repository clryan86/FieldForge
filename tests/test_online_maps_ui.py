"""Real Tk / localhost integration, required on Linux and Windows in CI."""

import threading
import time

from test_gps_desktop import root as root
from test_online_portal import map_entry as map_entry
from test_online_portal import portal as portal

from fieldforge.app import FieldForgeApp
from fieldforge.navigation.places import PlaceStore
from fieldforge.online import PortalSession
from fieldforge.ui.gps import GPSWorkspace
from fieldforge.ui.online_maps import OnlineMapWindow
from fieldforge.ui.places import PlaceEditor
from fieldforge_gps.gpx_review import parse_gpx
from fieldforge_gps.places import read_catalog


def pump(root, predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        root.update()
        time.sleep(.005)
    root.update()
    assert predicate()


def connect(root, window, portal):
    window.url.set(portal[0])
    window.consent.set(True)
    assert window.connect()
    pump(root, lambda: not window._busy)
    assert window._online(), window.status.get()


def search(root, window):
    window.query.set("Fictional Beacon")
    assert window.search()
    pump(root, lambda: not window._busy)
    assert len(window.results) == 2
    assert window.selected is None  # No first-result guessing.
    window.table.selection_set("0")
    pump(root, lambda: window.selected is not None)


def test_search_disabled_offline_save_selected_result_and_route_without_network(root, portal, tmp_path, monkeypatch):
    applied = []
    window = OnlineMapWindow(root, use_coordinate=applied.append)
    assert window.search_entry.instate(["disabled"]) and not portal[2]
    assert not window.connect() and window.session is None
    connect(root, window, portal)
    search(root, window)
    window.apply()
    assert applied == [window.results[0]]
    window.route_point("start")
    window.route_point("end")
    window.route_fields["end_lat"].set("10.4")
    window.route_fields["end_lon"].set("20.5")
    assert window.plan_route()
    pump(root, lambda: not window._busy)
    assert window.planned_route is not None
    window.disconnect()
    assert window.search_entry.instate(["disabled"]) and window.plan_button.instate(["disabled"])
    monkeypatch.setattr("fieldforge.online.open_request", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Offline")))
    place, route = tmp_path / "place.csv", tmp_path / "route.gpx"
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kw: str(place))
    window.save_place()
    assert read_catalog(place, consent=True, wgs84_confirmed=True).places[0].latitude == 10.125
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kw: str(route))
    window.save_route()
    assert parse_gpx(route.read_bytes()).point_count == 3
    window.close()
    window.worker.join(2)
    assert not window.worker.is_alive()


def test_verified_download_can_be_opened_after_disconnect(root, portal, tmp_path, monkeypatch):
    opened = []
    window = OnlineMapWindow(root, open_asset=lambda *args: opened.append(args))
    connect(root, window, portal)
    assert window.catalogue()
    pump(root, lambda: not window._busy)
    window.map_table.selection_set("0")
    root.update()
    target = tmp_path / "saved.mbtiles"
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kw: str(target))
    assert window.download()
    pump(root, lambda: not window._busy)
    assert window.downloaded == (target, "mbtiles"), window.status.get()
    window.disconnect()
    assert window.download_button.instate(["disabled"]) and not window.open_button.instate(["disabled"])
    window.open_download()
    assert opened == [(target, "mbtiles")]
    window.destroy()


def test_place_editor_fill_is_reviewed_before_database_save_and_modal_grab_returns(root, portal, tmp_path):
    store = PlaceStore(FieldForgeApp(tmp_path / "places.db").db.path)
    editor = PlaceEditor(root, store)
    window = editor.find_address()
    assert editor.find_address() is window
    connect(root, window, portal)
    search(root, window)
    window.apply()
    assert editor.fields["latitude"].get() == "10.125"
    assert editor.fields["longitude"].get() == "20.25"
    with store.connect() as database:
        assert database.execute("SELECT COUNT(*) FROM waypoints").fetchone()[0] == 0
    window.close()
    root.update()
    assert editor.grab_current() is editor
    editor.save()
    assert editor.changed
    with store.connect() as database:
        row = database.execute("SELECT latitude,longitude,notes FROM waypoints").fetchone()
    assert tuple(row[:2]) == (10.125, 20.25) and "Original fixture" in row[2]


def test_navigation_portal_reuses_window_without_opening_receiver(root):
    workspace = GPSWorkspace(root)
    window = workspace.open_portal()
    assert workspace.open_portal() is window and workspace.receiver is None
    assert window.session is None
    workspace.close()
    window.worker.join(2)
    assert not window.worker.is_alive() and root.winfo_exists()


def test_cancelled_connection_cannot_enable_search_or_touch_destroyed_widgets(root, monkeypatch):
    started, release = threading.Event(), threading.Event()
    def delayed(session, url, *, consent):
        started.set()
        release.wait(3)
        session.ready = True  # Simulate a result arriving just after cancellation.
        return {"providers": {}, "capabilities": {}}
    monkeypatch.setattr(PortalSession, "connect", delayed)
    window = OnlineMapWindow(root)
    window.consent.set(True)
    window.url.set("https://portal.example")
    assert window.connect()
    assert started.wait(2)
    window.disconnect()
    release.set()
    pump(root, lambda: window.session.ready)
    root.update()
    assert not window._online() and window.search_entry.instate(["disabled"])
    root.destroy()
    window.worker.join(2)
    assert not window.worker.is_alive()
