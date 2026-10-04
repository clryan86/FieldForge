"""Real Tk / localhost integration, required on Linux and Windows in CI."""

import threading
import time

from test_gps_desktop import root as root
from test_online_portal import map_entry as map_entry
from test_online_portal import portal as portal

from fieldforge.app import FieldForgeApp
from fieldforge.navigation.places import PlaceStore
from fieldforge.online.compat import Address, PortalSession
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
    monkeypatch.setattr("fieldforge.online.compat.open_request", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Offline")))
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


def test_existing_place_prefill_and_nested_file_action_guard_are_preserved(root, tmp_path, monkeypatch):
    store = PlaceStore(FieldForgeApp(tmp_path / "places.db").db.path)
    editor = PlaceEditor(root, store, initial={"name": "Fictional manual place", "latitude": 1.25,
                                             "longitude": 2.5, "kind": "waypoint"})
    initial = editor.initial
    window = editor.find_address()
    window.selected = Address("Fictional selected match", 3.25, 4.5, "Original fixture", "Original test data")
    window.apply()
    assert editor.initial == initial and editor._values() != initial

    def choose(**_kwargs):
        assert not window.can_close()
        editor.save()
        editor.close()
        assert editor.winfo_exists() and not editor.changed
        with store.connect() as database:
            assert database.execute("SELECT COUNT(*) FROM waypoints").fetchone()[0] == 0
        return ""

    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", choose)
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *_args, **_kwargs: False)
    window.save_place()
    window.close()
    assert editor.grab_current() is editor
    editor.close()
    assert editor.winfo_exists()  # The original unsaved-place guard still applies.
    editor.save()
    with store.connect() as database:
        row = database.execute("SELECT name,latitude,longitude FROM waypoints").fetchone()
    assert tuple(row) == ("Fictional selected match", 3.25, 4.5)


def test_gps_workspace_retains_portal_during_file_picker_then_releases_tk_references(root, monkeypatch):
    workspace = GPSWorkspace(root)
    window = workspace.open_portal()
    window.selected = Address("Fictional selected match", 1.25, 2.5, "Original fixture", "Original test data")

    def choose(**_kwargs):
        assert not workspace.can_close()
        workspace.close()
        assert workspace.portal_window is window and window.winfo_exists()
        assert workspace.receiver is None
        return ""

    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", choose)
    window.save_place()
    assert workspace.can_close()
    workspace.close()
    window.worker.join(2)
    assert not window.worker.is_alive() and workspace.portal_window is None
    assert window.url is None and window.status is None
    assert not window.route_fields and not window.route_entries
    assert window.use_coordinate is None and window.open_asset is None


def test_selected_plan_tracks_requested_endpoints_across_edits_and_releases_traces(root, portal):
    window = OnlineMapWindow(root)
    owned_variables = tuple(window.route_fields.values())
    requested = ((11.125, 21.25), (12.4, 22.5))
    mismatch = "Selected plan uses previous coordinates"

    def assert_requested_details(endpoints):
        lines = window.route_detail.get().splitlines()
        for label, point in zip(("Requested start", "Requested destination"), endpoints):
            line = next((value for value in lines if label.lower() in value.lower()), "")
            assert line, window.route_detail.get()
            assert all(str(number) in line for number in point), line

    try:
        connect(root, window, portal)
        search(root, window)
        for key, number in zip(
            ("start_lat", "start_lon", "end_lat", "end_lon"),
            (*requested[0], *requested[1]),
        ):
            window.route_fields[key].set(str(number))
        assert window.plan_route()
        pump(root, lambda: not window._busy)
        previous = window.planned_route
        assert previous is not None, window.status.get()
        assert window._planned_endpoints == requested
        # This provider intentionally returns fixed geometry. Snapped geometry
        # must never replace the coordinates actually submitted by the user.
        geometry = previous["coordinates"]
        assert (geometry[0][1], geometry[0][0]) != requested[0]
        assert (geometry[-1][1], geometry[-1][0]) != requested[1]
        assert_requested_details(requested)
        assert mismatch not in window.route_detail.get()
        provider_calls = len(portal[2])
        next_request_after = time.monotonic() + portal[1].router.config.minimum_interval_seconds

        for key, spelling in {
            "start_lat": "11.12500", "start_lon": "+021.250",
            "end_lat": "012.4000", "end_lon": "22.5000000",
        }.items():
            window.route_fields[key].set(spelling)
        root.update()
        assert window.planned_route is previous
        assert window._planned_endpoints == requested
        assert mismatch not in window.route_detail.get()

        window.route_fields["end_lat"].set("13.75")
        root.update()
        assert window.planned_route is previous
        assert window._planned_endpoints == requested
        assert mismatch in window.route_detail.get()
        assert_requested_details(requested)
        window.route_fields["end_lat"].set("12.4000")
        root.update()
        assert mismatch not in window.route_detail.get()

        window.route_point("end")
        root.update()
        assert window.planned_route is previous
        assert window._planned_endpoints == requested
        assert mismatch in window.route_detail.get()
        assert_requested_details(requested)
        assert not window.save_route_button.instate(["disabled"])
        assert len(portal[2]) == provider_calls

        replacement = (requested[0], (window.selected.latitude, window.selected.longitude))
        # The real fixture portal deliberately rejects provider request bursts.
        pump(root, lambda: time.monotonic() >= next_request_after)
        assert window.plan_route()
        pump(root, lambda: not window._busy)
        assert window._planned_endpoints == replacement, window.status.get()
        assert mismatch not in window.route_detail.get()
        assert_requested_details(replacement)
        geometry = window.planned_route["coordinates"]
        assert (geometry[-1][1], geometry[-1][0]) != replacement[1]
        assert all(variable.trace_info() for variable in owned_variables)
    finally:
        window.destroy()
        window.worker.join(2)
    assert not window.worker.is_alive()
    assert window.route_fields == {} and window.route_entries == []
    assert all(not variable.trace_info() for variable in owned_variables)


def test_unexportable_address_reports_csv_limit_before_opening_a_file_picker(root, monkeypatch):
    selected = Address.parse({
        "label": "F" * 161,
        "latitude": 1.25,
        "longitude": 2.5,
        "source": "Original fixture",
        "attribution": "Original synthetic test data",
    })
    window = OnlineMapWindow(root)

    def unexpected_picker(**_kwargs):
        raise AssertionError("An unexportable address must not open the save dialog")

    def unexpected_write(*_args, **_kwargs):
        raise AssertionError("An unexportable address must not write a file")

    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", unexpected_picker)
    monkeypatch.setattr("fieldforge.ui.online_compat.save_new", unexpected_write)
    try:
        window.selected = selected
        window._buttons()
        window.save_place_button.invoke()
        root.update()
        assert window.selected is selected and window.selected.label == "F" * 161
        assert window.status.get().startswith("Could not save place CSV: ")
        assert "160" in window.status.get()
        assert not window._choosing_file and not window._saving
        assert window.session is None and window.can_close()
    finally:
        window.destroy()
        window.worker.join(2)
    assert not window.worker.is_alive()
