import time

import pytest

from fieldforge_gps.session import Session

from .test_nmea import rmc
from .test_session import WALL


@pytest.fixture
def screen(monkeypatch):
    import tkinter as tk

    from fieldforge_gps.__main__ import GPSWindow

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display not available")
    root.geometry("960x740")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    dialogs = []
    monkeypatch.setattr(
        "tkinter.messagebox.showerror", lambda *args, **kwargs: dialogs.append(args)
    )
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *args, **kwargs: dialogs.append(args))
    app = GPSWindow(root)
    root.update()
    yield root, app, dialogs
    app.close()
    root.destroy()
    assert not errors


def pump(root, seconds=0.3):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        root.update()
        time.sleep(0.005)


def test_startup_private_no_session(screen):
    root, app, _ = screen
    assert app.session is None and not app.datum.get()
    assert not app.port.get()
    assert str(app.export_button["state"]) == "disabled"
    assert str(app.copy_button["state"]) == "disabled"


def test_recording_banner_datum_gating_and_disconnect(screen, tmp_path):
    root, app, _ = screen
    p = tmp_path / "sample.nmea"
    p.write_bytes(rmc())
    app.load_recording(p)
    assert app.session.wait(1)
    pump(root)
    assert "NOT LIVE" in app.mode.get()
    assert "10.00000000" in app.coords.get()
    assert str(app.copy_button["state"]) == "disabled"
    app.datum.set(True)
    pump(root)
    assert str(app.copy_button["state"]) == "normal"
    app.disconnect()
    assert app.coords.get() == "No current position"
    assert str(app.copy_button["state"]) == "disabled"


def test_copy_labels_recorded_data(screen, tmp_path):
    root, app, _ = screen
    p = tmp_path / "sample.nmea"
    p.write_bytes(rmc())
    app.load_recording(p)
    assert app.session.wait(1)
    app.datum.set(True)
    app.copy_coordinates()
    text = root.clipboard_get()
    assert "RECORDED — NOT LIVE" in text and "receiver UTC" in text


def test_export_rechecks_after_dialog(screen, tmp_path, monkeypatch):
    root, app, dialogs = screen
    now = [0]
    s = Session("serial", clock=lambda: now[0], utc_now=lambda: WALL)
    s._feed(rmc())
    app._replace(s)
    app.datum.set(True)
    out = tmp_path / "must-not-exist.gpx"

    def dialog(**kwargs):
        now[0] = 6
        return str(out)

    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", dialog)
    app.export()
    assert not out.exists() and dialogs


def test_export_recording_and_no_other_files(screen, tmp_path, monkeypatch):
    root, app, dialogs = screen
    p = tmp_path / "sample.nmea"
    p.write_bytes(rmc())
    app.load_recording(p)
    assert app.session.wait(1)
    app.datum.set(True)
    out = tmp_path / "position.gpx"
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kwargs: str(out))
    app.export()
    assert out.exists()
    assert len(list(tmp_path.iterdir())) == 2
    assert b"NOT live" in out.read_bytes()


def test_actual_fieldforge_map_opens_without_household_db(screen, monkeypatch):
    pytest.importorskip("fieldforge.ui.maps")
    root, app, _ = screen

    def forbidden(*args, **kwargs):
        pytest.fail("Household database or saved places accessed")

    monkeypatch.setattr("fieldforge.ui.maps.read_markers", forbidden)
    app.open_map()
    root.update()
    assert app.map_tab.database is None
    assert app.map_tab.pack_info is None
    assert not app.map_tab.markers
    app.map_window.destroy()
    app.map_tab._worker.shutdown(wait=True, cancel_futures=True)


def test_minimum_size_controls_visible(screen):
    root, app, _ = screen
    root.geometry("880x700")
    root.update()
    for widget in (
        app.connect_button,
        app.record_button,
        app.stop_button,
        app.export_button,
        app.center_button,
    ):
        assert widget.winfo_ismapped()
        bottom = widget.winfo_rooty() + widget.winfo_height()
        assert bottom <= root.winfo_rooty() + root.winfo_height()


def test_loaded_map_centers_recorded_point_without_database(screen, tmp_path, monkeypatch):
    pytest.importorskip("fieldforge.ui.maps")
    fixture = pytest.importorskip("map_fixture")
    root, app, _ = screen
    p = tmp_path / "source.nmea"
    p.write_bytes(rmc())
    app.load_recording(p)
    assert app.session.wait(1)
    app.datum.set(True)
    app.open_map()
    root.update()
    local = fixture.make_map(tmp_path / "synthetic.mbtiles", zooms=(0, 1))
    before = local.read_bytes()
    app.map_tab.open_path(local)
    until = time.monotonic() + 4
    while (app.map_tab.busy or app.map_tab._resize_id is not None) and time.monotonic() < until:
        pump(root, 0.03)
    assert app.map_tab.view is not None
    app.center_map()
    assert app.map_tab.view.latitude == 10
    assert app.map_tab.view.longitude == 20
    assert "RECORDED position — NOT live" in app.map_window.title()
    assert app.map_tab.database is None and not app.map_tab.markers
    assert local.read_bytes() == before
    app.map_window.destroy()
    app.map_tab._worker.shutdown(wait=True, cancel_futures=True)


def test_polar_map_center_refused_without_moving(screen, tmp_path):
    pytest.importorskip("fieldforge.ui.maps")
    fixture = pytest.importorskip("map_fixture")
    root, app, dialogs = screen
    p = tmp_path / "polar.nmea"
    p.write_bytes(rmc(lat="9000.0"))
    app.load_recording(p)
    assert app.session.wait(1)
    app.datum.set(True)
    app.open_map()
    root.update()
    app.map_tab.open_path(fixture.make_map(tmp_path / "synthetic.mbtiles", zooms=(0,)))
    until = time.monotonic() + 4
    while (app.map_tab.busy or app.map_tab._resize_id is not None) and time.monotonic() < until:
        pump(root, 0.03)
    before = app.map_tab.view
    app.center_map()
    assert app.map_tab.view == before
    assert "polar" in dialogs[-1][1]
    app.map_window.destroy()
    app.map_tab._worker.shutdown(wait=True, cancel_futures=True)
