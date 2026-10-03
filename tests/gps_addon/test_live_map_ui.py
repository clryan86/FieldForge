import hashlib
import queue
import threading
import time
from types import SimpleNamespace

import pytest

from fieldforge_gps.__main__ import GPSWindow
from fieldforge_gps.mercator import MercatorView
from fieldforge_gps.review_map import View
from fieldforge_gps.session import Session

from .test_local_map_ui import settle
from .test_nmea import gga, rmc
from .test_session import WALL


@pytest.fixture
def ui(monkeypatch):
    import tkinter as tk

    root = tk.Tk()
    root.geometry("960x740")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("tkinter.messagebox.showerror", lambda *args, **kw: None)
    gps = GPSWindow(root)
    frame = gps.open_live_map()
    root.update()
    frame.draw()
    yield root, gps, frame
    reader = frame._map_reader
    gps.close()
    root.destroy()
    reader._thread.join(2)
    assert not reader._thread.is_alive()
    assert not errors


def fresh(ui, **changes):
    root, gps, frame = ui
    now = [0.0]
    s = Session("serial", clock=lambda: now[0], utc_now=lambda: WALL)
    s._running = True
    gps._replace(s)
    gps.datum.set(True)
    s._feed(rmc(**changes))
    frame.show_live.set(True)
    frame.refresh_live()
    return now, s


def has_fix(frame):
    return bool(frame.canvas.find_withtag("live-position"))


def pump(root, seconds=0.3):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        root.update()
        time.sleep(0.005)


def local(ui):
    root, gps, f = ui
    f.map_trust.set(True)
    f.example_map()
    settle(root, f)
    return f


def test_default_no_receiver_no_location_no_history(ui):
    _, gps, f = ui
    assert gps.session is None and f.document is None and f.map_pack is None
    assert not f.show_live.get() and not f.follow_live.get() and not has_fix(f)
    assert not f._history_visible
    assert str(f.center_live_button["state"]) == "disabled"


def test_header_and_footer_do_not_mislabel_live_workspace(ui):
    _, _, f = ui
    assert "Maps + GPS" in f.title_label.cget("text")
    assert "separate" in f.point_detail.get()
    assert "No GPX history" in f.render_notice.get()


def test_new_map_does_not_enable_receiver_or_location(ui):
    _, gps, f = ui
    local(ui)
    assert gps.session is None and not f.show_live.get() and not has_fix(f)


def test_fresh_serial_marker_and_explicit_center(ui):
    _, _, f = ui
    fresh(ui)
    assert f.center_live()
    assert f.view.latitude == 10 and f.view.longitude == 20
    assert has_fix(f)
    assert "receiver UTC" in f.live_notice.get()
    assert "FOLLOW OFF" in f.live_notice.get()
    assert f.canvas.find_withtag("live-fix-label")


def test_live_marker_over_readonly_png_tiles(ui):
    root, _, f = ui
    local(ui)
    fresh(ui)
    f.center_live()
    settle(root, f)
    assert f.canvas.find_withtag("map-tile") and has_fix(f)
    assert isinstance(f.view, MercatorView)
    assert "FICTIONAL" in f.map_status.get()


def test_stale_removes_marker_coordinates_and_follow_then_requires_resume(ui):
    _, _, f = ui
    now, s = fresh(ui)
    f.follow_live.set(True)
    assert has_fix(f) and f.follow_live.get()
    before = f.view
    now[0] = 5
    f.refresh_live()
    assert not has_fix(f) and not f.follow_live.get() and f.view == before
    assert "10.000000" not in f.live_notice.get()
    assert "Stale" in f.live_notice.get()
    s._feed(rmc(time="120001", lat="1100.0"))
    f.refresh_live()
    assert not f.follow_live.get() and f.view == before
    assert "11.000000" in f.live_notice.get()


def test_poll_clears_stale_without_user_action(ui):
    root, _, f = ui
    now, _ = fresh(ui)
    f.center_live()
    now[0] = 5
    pump(root)
    assert not has_fix(f) and "Stale" in f.live_notice.get()


def test_redraw_rechecks_freshness_without_poll(ui):
    _, _, f = ui
    now, _ = fresh(ui)
    f.center_live()
    now[0] = 5
    f.draw()
    assert not has_fix(f)


def test_disconnect_clears_live_layer_synchronously(ui):
    _, gps, f = ui
    fresh(ui)
    f.follow_live.set(True)
    gps.disconnect()
    assert not has_fix(f) and not f.follow_live.get()
    assert "10.000000" not in f.live_notice.get()


def test_datum_revocation_clears_synchronously_and_never_reenables(ui):
    _, gps, f = ui
    fresh(ui)
    f.follow_live.set(True)
    gps.datum.set(False)
    assert not f.show_live.get() and not f.follow_live.get() and not has_fix(f)
    gps.datum.set(True)
    assert not f.show_live.get() and not has_fix(f)


def test_display_consent_off_leaves_receiver_running_without_recording(ui):
    _, _, f = ui
    _, s = fresh(ui)
    f.follow_live.set(True)
    f.show_live.set(False)
    assert not has_fix(f) and not f.follow_live.get()
    assert s.snapshot().running and s.trip_summary().state == "idle"
    assert s.trip_summary().point_count == 0


def test_new_serial_source_requires_fresh_consent(ui):
    _, gps, f = ui
    fresh(ui)
    f.follow_live.set(True)
    second = Session("serial", clock=lambda: 0, utc_now=lambda: WALL)
    second._running = True
    second._feed(rmc(lat="1500.0"))
    gps._replace(second)
    assert not f.show_live.get() and not f.follow_live.get() and not has_fix(f)
    assert "Input changed" in f.live_notice.get()
    f.show_live.set(True)
    assert "15.000000" in f.live_notice.get()


def test_recorded_nmea_cannot_be_live_or_followed(ui, tmp_path):
    _, gps, f = ui
    path = tmp_path / "recording.nmea"
    path.write_bytes(rmc())
    gps.datum.set(True)
    assert gps.load_recording(path)
    assert gps.session.wait(1)
    f.show_live.set(True)
    f.follow_live.set(True)
    f.refresh_live()
    assert not has_fix(f) and not f.follow_live.get()
    assert "NOT LIVE" in f.live_notice.get()


@pytest.mark.parametrize(
    "bad", [rmc(status="V"), gga(quality="0"), b"$GNRMC,bad*00\r\n", rmc(mode="S")]
)
def test_invalid_data_does_not_keep_last_marker(ui, bad):
    _, _, f = ui
    _, s = fresh(ui)
    f.center_live()
    s._feed(bad)
    f.refresh_live()
    assert not has_fix(f) and "10.000000" not in f.live_notice.get()


def test_center_rechecks_receiver_not_displayed_text(ui):
    _, _, f = ui
    now, _ = fresh(ui)
    before = f.view
    now[0] = 5
    assert not f.center_live() and f.view == before
    assert not has_fix(f)


def test_pan_pauses_follow(ui):
    _, _, f = ui
    fresh(ui)
    f.follow_live.set(True)
    f._start_drag(SimpleNamespace(x=100, y=100))
    f._move_drag(SimpleNamespace(x=200, y=100))
    f.refresh_live()
    assert not f.follow_live.get() and "manual map movement" in f.live_notice.get()
    assert f.view.longitude != 20


def test_keyboard_pan_pauses_follow(ui):
    _, _, f = ui
    fresh(ui)
    f.follow_live.set(True)
    before = f.view
    f.pan(50, 0)
    assert not f.follow_live.get() and f.view != before


def test_zoom_keeps_follow_and_projection_level(ui):
    root, _, f = ui
    local(ui)
    fresh(ui)
    f.follow_live.set(True)
    settle(root, f)
    level = f.view.level
    f.zoom(0.5)
    settle(root, f)
    assert f.follow_live.get() and f.view.level < level


def test_dead_zone_no_new_map_requests_for_small_changes(ui):
    root, _, f = ui
    local(ui)
    now, s = fresh(ui)
    f._live_clock = lambda: now[0]
    f.follow_live.set(True)
    settle(root, f)
    before, token = f.view, f._map_reader.token
    now[0] = 2
    s._feed(rmc(time="120001", lat="1000.0001"))
    f.refresh_live()
    assert f.view == before and f._map_reader.token == token


def test_recenter_throttled_and_never_starves_pending_tile_read(ui):
    root, _, f = ui
    local(ui)
    now, s = fresh(ui)
    f._live_clock = lambda: now[0]
    f.follow_live.set(True)
    settle(root, f)
    before = f.view
    now[0] = 0.5
    s._feed(rmc(time="120001", lon="15000.0"))
    f.refresh_live()
    assert f.view == before
    now[0] = 1
    f._map_task = ("pending-test", "tiles", f._viewport_key())
    f.refresh_live()
    assert f.view == before
    f._map_task = None
    f.refresh_live()
    assert f.view.longitude == 150
    assert not f.canvas.find_withtag("map-tile")  # New view never keeps old imagery.
    settle(root, f)
    assert f.view.longitude == 150


def test_poles_not_clamped_while_overview_can_center(ui):
    root, _, f = ui
    local(ui)
    fresh(ui, lat="9000.0")
    before = f.view
    assert not f.center_live() and f.view == before and not has_fix(f)
    assert "outside Web Mercator" in f.live_notice.get()
    f.world()
    settle(root, f)
    assert f.center_live() and f.view.latitude == 90


def test_dateline_center_wraps_without_spurious_pan(ui):
    _, _, f = ui
    fresh(ui, lon="18000.0")
    assert f.center_live()
    assert f.view.longitude == -180


def test_history_and_live_consent_independent(ui):
    root, gps, f = ui
    fresh(ui)
    f.datum.set(True)
    f.consent.set(True)
    f.example()
    settle(root, f)
    assert f.document
    f.consent.set(False)
    settle(root, f)
    assert f.document is None and f.show_live.get() and gps.datum.get()
    assert "10.000000" in f.live_notice.get()


def test_history_controls_expand_collapse_without_clearing(ui):
    root, _, f = ui
    f.datum.set(True)
    f.consent.set(True)
    f.example()
    settle(root, f)
    doc = f.document
    f.toggle_history()
    root.update()
    assert f._history_visible and f.open_button.winfo_ismapped()
    f.toggle_history()
    root.update()
    assert not f._history_visible and f.document is doc


def test_history_and_live_markers_have_distinct_tags(ui):
    root, _, f = ui
    f.datum.set(True)
    f.consent.set(True)
    f.example()
    settle(root, f)
    fresh(ui)
    f.center_live()
    f.draw()
    assert has_fix(f) and f.document is not None
    banner = f.canvas.itemcget(f.canvas.find_withtag("live-banner")[0], "text")
    assert "SERIAL FIX" in banner and "GPX IS HISTORY" in banner


def test_map_permission_revocation_retains_live_permission_but_stops_follow(ui):
    root, _, f = ui
    local(ui)
    fresh(ui)
    f.follow_live.set(True)
    f.map_trust.set(False)
    settle(root, f)
    assert f.map_pack is None and isinstance(f.view, View)
    assert f.show_live.get() and not f.follow_live.get()


def test_live_display_does_not_write_map_or_record_history(ui, tmp_path):
    root, _, f = ui
    from .test_mbtiles import pack_file

    mapfile = pack_file(tmp_path)
    sentinel = tmp_path / "household.db"
    sentinel.write_bytes(b"NOT A REAL DATABASE - DO NOT OPEN")
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (mapfile, sentinel)}
    f.map_trust.set(True)
    f.start_map(mapfile)
    settle(root, f)
    _, s = fresh(ui)
    f.follow_live.set(True)
    settle(root, f)
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
    assert set(tmp_path.iterdir()) == set(before)
    assert s.trip_summary().point_count == 0 and s.trip_summary().state == "idle"


def test_close_map_view_clears_private_text_but_keeps_receiver(ui):
    _, _, f = ui
    _, s = fresh(ui)
    f.follow_live.set(True)
    f.close()
    assert not has_fix(f) and "10.000000" not in f.live_notice.get()
    assert f._live_after is None and s.snapshot().running
    assert f._gps is None and f._source is None


def test_receiver_close_stops_session_and_map_timers(ui):
    _, gps, f = ui
    _, s = fresh(ui)
    gps.close()
    assert s.snapshot().position is None and f._closed and f._live_after is None


def test_direct_toplevel_destruction_then_reopen(ui):
    root, gps, f = ui
    gps.live_map_window.destroy()
    root.update()
    assert f._closed and f._live_after is None
    replacement = gps.open_live_map()
    root.update()
    assert replacement is not f and not replacement.show_live.get()
    reader = replacement._map_reader
    replacement.close()
    reader._thread.join(2)


def test_existing_map_button_does_not_duplicate_window(ui):
    _, gps, f = ui
    assert gps.open_live_map() is f


def test_minimum_size_has_visible_live_and_map_controls(ui):
    root, gps, f = ui
    gps.live_map_window.geometry("1020x800")
    root.update()
    top = gps.live_map_window.winfo_rooty()
    bottom = top + gps.live_map_window.winfo_height()
    for widget in (
        f.receiver_button,
        f.show_live_check,
        f.follow_check,
        f.center_live_button,
        f.open_map_button,
        f.canvas,
        f.base_label,
    ):
        assert widget.winfo_ismapped()
        assert widget.winfo_rooty() >= top
        assert widget.winfo_rooty() + widget.winfo_height() <= bottom
    assert f.canvas.winfo_height() >= 180


def test_mock_serial_worker_disconnect_path(ui):
    root, gps, f = ui
    chunks = queue.Queue()
    closed = threading.Event()

    class Stream:
        def read(self, n):
            try:
                item = chunks.get(timeout=0.02)
            except queue.Empty:
                return b""
            if isinstance(item, Exception):
                raise item
            return item

        def close(self):
            closed.set()

    s = Session("serial", clock=lambda: 0, utc_now=lambda: WALL)
    s.start_serial("COM4", 9600, wgs84_confirmed=True, opener=lambda *a: Stream())
    gps._replace(s)
    gps.datum.set(True)
    f.show_live.set(True)
    chunks.put(rmc())
    pump(root)
    f.center_live()
    assert has_fix(f)
    chunks.put(OSError("simulated unplug"))
    assert s.wait(1) and closed.is_set()
    pump(root)
    assert not has_fix(f) and not f.follow_live.get()


def test_disabled_live_layer_does_not_request_a_snapshot(ui, monkeypatch):
    _, _, f = ui
    _, s = fresh(ui)
    f.show_live.set(False)

    def forbidden():
        raise AssertionError("Disabled map layer requested a receiver position")

    monkeypatch.setattr(s, "snapshot", forbidden)
    f.refresh_live()
    assert not has_fix(f)
