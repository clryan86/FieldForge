import hashlib
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from fieldforge_gps import map_jobs
from fieldforge_gps.gpx_review import parse_gpx
from fieldforge_gps.local_map_ui import LocalMapReviewFrame
from fieldforge_gps.mercator import MercatorView, map_display_segments
from fieldforge_gps.review_map import View

from .test_gpx_review import xml
from .test_mbtiles import pack_file, png


@pytest.fixture
def ui():
    import tkinter as tk

    root = tk.Tk()
    root.geometry("1200x990")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    frame = LocalMapReviewFrame(root)
    root.update()
    frame.draw()
    yield root, frame
    reader = frame._map_reader
    frame.close()
    root.destroy()
    reader._thread.join(2)
    assert not reader._thread.is_alive()
    assert not errors


def settle(root, frame, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
        if (
            not frame._busy
            and not frame._map_loading
            and not frame._map_task
            and frame._draw_after is None
        ):
            break
    root.update()
    frame.draw()
    root.update()
    assert not frame._busy and not frame._map_loading and not frame._map_task


def open_sample(ui, history=False):
    root, f = ui
    if history:
        f.datum.set(True)
        f.consent.set(True)
        f.example_button.invoke()
    f.map_trust.set(True)
    f.demo_map_button.invoke()
    settle(root, f)
    assert f.map_pack is not None
    return root, f


def test_startup_does_not_load_map_or_history(ui):
    _, f = ui
    assert f.map_pack is None and f.document is None
    assert not f.map_trust.get()
    assert str(f.open_map_button["state"]) == "disabled"
    assert f.canvas.find_withtag("coastline") and not f.canvas.find_withtag("map-tile")


def test_map_open_requires_consent_before_path_read(ui, tmp_path):
    _, f = ui
    assert f.start_map(tmp_path / "absent.mbtiles") is False
    assert "Nothing was read" in f.map_status.get()


def test_actual_png_tiles_and_deliberate_missing_tile(ui):
    _, f = open_sample(ui)
    assert f.map_pack.levels == (0, 2, 4, 5)
    assert f.canvas.find_withtag("map-tile")
    assert f.canvas.find_withtag("missing-tile")
    assert "FICTIONAL" in f.map_status.get() and "missing" in f.map_status.get()
    assert f.document is None and not f.canvas.find_withtag("track-line")


def test_history_registered_over_tiles_and_file_segments_separate(ui):
    _, f = open_sample(ui, True)
    assert f.document.point_count == 34
    assert f.canvas.find_withtag("map-tile")
    assert all(f.canvas.find_withtag(f"review-segment-{i}") for i in range(3))
    assert len(f.canvas.find_withtag("segment-start")) == 3
    assert "30/30" in f.render_notice.get()
    p = f._points[f._selection][2]
    x, y = f.view.position(p.longitude, p.latitude, *f._dimensions())
    marker = f.canvas.coords(f.canvas.find_withtag("selected-file-point")[0])
    assert marker == pytest.approx([x - 8, y - 8, x + 8, y + 8])


def test_clear_history_preserves_map_and_closing_map_preserves_history(ui):
    root, f = open_sample(ui, True)
    original = f.document
    f.close_map_button.invoke()
    settle(root, f)
    assert f.document is original and f.map_pack is None
    f.demo_map_button.invoke()
    settle(root, f)
    pack = f.map_pack
    f.clear_button.invoke()
    settle(root, f)
    assert f.document is None and f.map_pack is pack
    assert f.canvas.find_withtag("map-tile") and not f.canvas.find_withtag("track-line")


def test_revoke_map_consent_discards_tiles_keeps_gpx(ui):
    root, f = open_sample(ui, True)
    doc = f.document
    f.map_trust.set(False)
    settle(root, f)
    assert f.map_pack is None and f.document is doc
    assert not f._images and not f._tiles
    assert isinstance(f.view, View) and not f.canvas.find_withtag("map-tile")


def test_revoke_gpx_consent_preserves_map_not_history(ui):
    root, f = open_sample(ui, True)
    pack = f.map_pack
    f.consent.set(False)
    settle(root, f)
    assert f.document is None and f.map_pack is pack
    assert not f.canvas.find_withtag("track-line")


def test_only_observed_zoom_levels_available(ui):
    root, f = open_sample(ui)
    f.view = MercatorView(0, 0, 2)
    f.plus_button.invoke()
    assert f.view.level == 4
    f.minus_button.invoke()
    assert f.view.level == 2
    f.map_zoom.set("3")
    f._choose_zoom()
    assert f.view.level == 2
    f.map_zoom.set("5")
    f._choose_zoom()
    assert f.view.level == 5
    settle(root, f)


def test_pan_blanks_old_tiles_before_accepting_new_frame(ui):
    root, f = open_sample(ui)
    old = f._frame_key
    f.view = f.view.pan(256, 0, *f._dimensions())
    f.draw()
    assert f._frame_key is None and old != f._viewport_key()
    assert not f.canvas.find_withtag("map-tile") and f.canvas.find_withtag("loading-tile")
    settle(root, f)
    assert f._frame_key == f._viewport_key()


def test_dialog_cancel_leaves_loaded_map_unchanged(ui, monkeypatch):
    _, f = open_sample(ui)
    pack = f.map_pack
    monkeypatch.setattr(
        "fieldforge_gps.local_map_ui.filedialog.askopenfilename", lambda **kwargs: ""
    )
    f.open_map_button.invoke()
    assert f.map_pack is pack


def test_dialog_rechecks_consent(ui, monkeypatch, tmp_path):
    root, f = open_sample(ui)

    def dialog(**kwargs):
        f.map_trust.set(False)
        return str(tmp_path / "absent.mbtiles")

    monkeypatch.setattr("fieldforge_gps.local_map_ui.filedialog.askopenfilename", dialog)
    f.open_map_button.invoke()
    settle(root, f)
    assert f.map_pack is None and not f._map_loading


def test_changed_map_clears_stale_images(ui, tmp_path):
    root, f = ui
    path = pack_file(tmp_path)
    f.map_trust.set(True)
    f.start_map(path)
    settle(root, f)
    assert f.canvas.find_withtag("map-tile")
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE metadata SET value='Changed' WHERE name='name'")
    f.zoom(2)
    settle(root, f)
    assert f.map_pack is None and not f.canvas.find_withtag("map-tile")
    assert "changed" in f.map_status.get()


def test_failed_new_map_clears_previous_but_not_gpx(ui, tmp_path):
    root, f = open_sample(ui, True)
    doc = f.document
    f.start_map(tmp_path / "absent.mbtiles")
    settle(root, f)
    assert f.map_pack is None and f.document is doc
    assert "unavailable" in f.map_status.get()


def test_corrupt_png_body_becomes_unreadable_not_missing(ui, tmp_path):
    root, f = ui
    data = png()
    data = data[:33] + b"bad compressed body" + data[-12:]
    path = pack_file(tmp_path, rows=[(0, 0, 0, data)])
    f.map_trust.set(True)
    f.start_map(path)
    settle(root, f)
    assert f.canvas.find_withtag("bad-tile") and not f.canvas.find_withtag("map-tile")
    assert "unreadable" in f.map_status.get()


def test_retina_png_uses_256_logical_pixels(ui, tmp_path):
    root, f = ui
    path = pack_file(tmp_path, rows=[(0, 0, 0, png(512))])
    f.map_trust.set(True)
    f.start_map(path)
    settle(root, f)
    assert f._images and all(image.width() == image.height() == 256 for image in f._images.values())


def test_polar_history_not_centered_or_connected(ui, tmp_path):
    root, f = open_sample(ui)
    doc = parse_gpx(
        xml(
            '<trk><trkseg><trkpt lat="0" lon="0"/><trkpt lat="90" lon="2"/><trkpt lat="0" lon="5"/></trkseg></trk>'
        )
    )
    f.datum.set(True)
    f.consent.set(True)
    f._publish(doc)
    settle(root, f)
    assert "1 full-track points outside projection" in f.render_notice.get()
    assert not f.canvas.find_withtag("track-line")
    before = f.view
    f.point_number.set("2")
    assert not f.center_point()
    assert f.view == before
    assert "not moved" in f.map_status.get()


def test_polar_split_occurs_before_display_decimation():
    a = SimpleNamespace(latitude=0, longitude=0)
    pole = SimpleNamespace(latitude=90, longitude=0)
    segments = ((a,) * 100 + (pole,) + (a,) * 100,)
    runs = map_display_segments(segments, 6)
    assert len(runs) == 2 and sum(map(len, runs)) <= 6


def test_world_control_returns_to_coarse_overview(ui):
    root, f = open_sample(ui, True)
    doc = f.document
    f.world_button.invoke()
    settle(root, f)
    assert f.map_pack is None and isinstance(f.view, View) and f.document is doc
    assert f.canvas.find_withtag("coastline")


def test_inert_metadata_details_window(ui):
    root, f = open_sample(ui)
    f.map_details_button.invoke()
    root.update()
    children = [w for w in f.winfo_children() if w.winfo_class() == "Toplevel"]
    assert children
    texts = [w for w in children[0].winfo_children() if w.winfo_class() == "Text"]
    assert texts and texts[0].cget("state") == "disabled"
    assert "unverified" in children[0].title()
    assert "source_data_vintage" in texts[0].get("1.0", "end")
    children[0].destroy()


def test_revoke_while_map_open_worker_pending(ui, monkeypatch):
    root, f = ui
    entered = threading.Event()
    release = threading.Event()
    old = map_jobs.inspect_pack

    def delayed(*args, **kwargs):
        entered.set()
        release.wait(2)
        return old(*args, **kwargs)

    monkeypatch.setattr(map_jobs, "inspect_pack", delayed)
    f.map_trust.set(True)
    f.demo_map_button.invoke()
    assert entered.wait(1)
    f.map_trust.set(False)
    release.set()
    settle(root, f)
    assert f.map_pack is None and not f.canvas.find_withtag("map-tile")


def test_database_and_gpx_bytes_not_changed_by_review(ui, tmp_path):
    root, f = ui
    path = pack_file(tmp_path)
    gpx = Path(__file__).resolve().parents[2] / "fieldforge_gps/data/FICTIONAL-REVIEW.gpx"
    sentinel = tmp_path / "household.db"
    sentinel.write_bytes(b"DO NOT OPEN")
    before = {p: hashlib.sha256(p.read_bytes()).digest() for p in (path, gpx, sentinel)}
    f.datum.set(True)
    f.consent.set(True)
    f.start_read(gpx)
    f.map_trust.set(True)
    f.start_map(path)
    settle(root, f)
    f.close_map()
    f.clear()
    settle(root, f)
    assert before == {p: hashlib.sha256(p.read_bytes()).digest() for p in before}


def test_status_updates_do_not_cause_endless_tile_reloads(ui):
    root, f = open_sample(ui)
    token = f._map_reader.token
    end = time.monotonic() + 0.4
    while time.monotonic() < end:
        root.update()
        time.sleep(0.005)
    assert f._map_reader.token == token and f._map_task is None
    assert f._frame_key == f._viewport_key()


def test_large_viewport_and_drag_report_error_without_tk_callback(ui, monkeypatch):
    root, f = open_sample(ui)
    monkeypatch.setattr(f, "_dimensions", lambda: (3000, 1800))
    f._start_drag(SimpleNamespace(x=0, y=0))
    f._move_drag(SimpleNamespace(x=20, y=20))
    f.draw()
    assert f.canvas.find_withtag("viewport-error")
    assert not f.canvas.find_withtag("map-tile") and f._map_task is None


def test_file_center_select_and_pack_start_are_distinct(ui):
    root, f = open_sample(ui, True)
    f.point_number.set("12")
    f.center_button.invoke()
    settle(root, f)
    p = f._points[11][2]
    assert f.view.longitude == p.longitude and f.view.latitude == p.latitude
    f.pack_start_button.invoke()
    settle(root, f)
    assert (f.view.longitude, f.view.latitude, f.view.level) == f.map_pack.start
    assert "NOT current position" in f.point_detail.get()
