import threading
import time

import pytest

from fieldforge_gps import review_ui
from fieldforge_gps.gpx_review import parse_gpx

from .test_gpx_review import point_fields, xml


@pytest.fixture
def review():
    import tkinter as tk

    root = tk.Tk()
    root.geometry("1120x860")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    frame = review_ui.ReviewFrame(root)
    root.update()
    frame.draw()
    yield root, frame
    frame.close()
    root.destroy()
    assert not errors


def wait(root, frame, timeout=4):
    deadline = time.monotonic() + timeout
    while frame._busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    assert not frame._busy
    root.update()
    frame.draw()


def example(review):
    root, frame = review
    frame.datum.set(True)
    frame.consent.set(True)
    frame.example_button.invoke()
    wait(root, frame)
    assert frame.document is not None
    return root, frame


def test_startup_never_reads_private_history_and_overview_is_bundled(review):
    root, frame = review
    assert frame.document is None and not frame._busy
    assert not frame.datum.get() and not frame.consent.get()
    assert str(frame.open_button["state"]) == "disabled"
    assert not frame.canvas.find_withtag("track-line")
    assert frame.canvas.find_withtag("coastline")
    assert "NOT LIVE" in review_ui.BANNER


def test_programmatic_read_without_permissions_does_not_read(review, tmp_path):
    _, frame = review
    assert frame.start_read(tmp_path / "absent") is False
    assert frame.document is None and not frame._busy
    assert "Nothing was read" in frame.status.get()


def test_actual_example_controls_load_all_tracks_and_preserve_gaps(review):
    root, frame = example(review)
    assert frame.document.point_count == 34 and frame.document.segment_count == 4
    assert len(frame.track_box["values"]) == 2
    assert "FICTIONAL" in frame.track_box.get()
    assert "NOT LIVE" in frame.status.get()
    assert len(frame.canvas.find_withtag("segment-start")) == 3
    assert len(frame.canvas.find_withtag("segment-end")) == 3
    assert all(frame.canvas.find_withtag(f"review-segment-{i}") for i in range(3))
    assert "30/30" in frame.render_notice.get()
    assert len(frame.canvas.find_withtag("selected-file-point")) == 1


def test_select_second_track_has_no_fabricated_time_and_fits_dateline(review):
    root, frame = example(review)
    frame.track_box.current(1)
    frame.track_box.event_generate("<<ComboboxSelected>>")
    root.update()
    frame.draw()
    assert len(frame._points) == 4 and abs(frame.view.longitude) > 170
    assert frame.view.span < 20
    assert "Time: not supplied" in frame.point_detail.get()
    assert "4/4" in frame.render_notice.get()


def test_inspect_specific_point_reports_original_segment_and_values(review):
    root, frame = example(review)
    frame.point_number.set("12")
    frame.inspect_button.invoke()
    assert "segment 2, point 2" in frame.point_detail.get()
    assert "FILE POINT 12" in frame.point_detail.get()
    assert "NOT current position" in frame.point_detail.get()
    frame.center_button.invoke()
    point = frame._points[11][2]
    assert frame.view.latitude == point.latitude and frame.view.longitude == point.longitude


@pytest.mark.parametrize("value", ["0", "35", "-1", "abc", "1.5", "500001", ""])
def test_invalid_point_index_cannot_change_selection(review, value):
    _, frame = example(review)
    before = frame._selection
    frame.point_number.set(value)
    assert not frame.inspect_point()
    assert frame._selection == before
    assert "Selection is unchanged" in frame.point_detail.get()


def test_naive_timestamp_not_assumed_utc(review, tmp_path):
    root, frame = review
    path = tmp_path / "naive.gpx"
    path.write_bytes(point_fields("<time>2024-01-01T12:30:00</time>"))
    frame.datum.set(True)
    frame.consent.set(True)
    frame.start_read(path)
    wait(root, frame)
    assert "timezone not supplied; NOT assumed UTC" in frame.point_detail.get()


def test_bad_new_file_does_not_replace_successful_review(review, tmp_path):
    root, frame = example(review)
    original = frame.document
    path = tmp_path / "bad.gpx"
    path.write_bytes(b"<broken>")
    frame.start_read(path)
    wait(root, frame)
    assert frame.document is original
    assert "GPX not loaded" in frame.status.get()
    assert len(frame._points) == 30


def test_cancelled_dialog_leaves_previous_review_untouched(review, monkeypatch):
    _, frame = example(review)
    original = frame.document
    monkeypatch.setattr(review_ui.filedialog, "askopenfilename", lambda **kwargs: "")
    frame.open_button.invoke()
    assert frame.document is original and not frame._busy


def test_permission_rechecked_after_modal_dialog(review, monkeypatch, tmp_path):
    _, frame = example(review)

    def dialog(**kwargs):
        frame.consent.set(False)
        return str(tmp_path / "absent")

    monkeypatch.setattr(review_ui.filedialog, "askopenfilename", dialog)
    frame.open_button.invoke()
    assert not frame._busy and frame.document is None


def test_read_worker_is_not_tk_thread_and_publish_is_tk_thread(review, monkeypatch):
    root, frame = review
    main_thread = threading.get_ident()
    observations = {}
    old_read = review_ui.read_gpx
    old_publish = frame._publish

    def read(*args, **kwargs):
        observations["read"] = threading.get_ident()
        return old_read(*args, **kwargs)

    def publish(document):
        observations["publish"] = threading.get_ident()
        return old_publish(document)

    monkeypatch.setattr(review_ui, "read_gpx", read)
    monkeypatch.setattr(frame, "_publish", publish)
    example(review)
    assert observations["read"] != main_thread and observations["publish"] == main_thread


def test_late_result_after_cancel_is_not_published_and_one_worker_only(review, monkeypatch):
    root, frame = example(review)
    old = frame.document
    started = threading.Event()
    release = threading.Event()
    replacement = parse_gpx(xml())

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return replacement  # Simulate a result racing with cancellation.

    monkeypatch.setattr(review_ui, "read_gpx", delayed)
    assert frame.start_read("not-opened")
    assert started.wait(2)
    assert not frame.start_read("second-not-opened")
    frame.cancel_button.invoke()
    release.set()
    wait(root, frame)
    assert frame.document is old
    assert "cancelled" in frame.status.get()


@pytest.mark.parametrize("permission", ["consent", "datum"])
def test_revoke_permission_clears_history_and_rechecking_does_not_reload(review, permission):
    root, frame = example(review)
    getattr(frame, permission).set(False)
    root.update()
    frame.draw()
    assert frame.document is None and not frame._points
    assert not frame.canvas.find_withtag("track-line")
    assert "No recorded point" in frame.point_detail.get()
    getattr(frame, permission).set(True)
    assert frame.document is None and not frame._busy


def test_clear_and_close_do_not_modify_original_file(review, tmp_path):
    root, frame = review
    path = tmp_path / "private.gpx"
    raw = xml()
    path.write_bytes(raw)
    frame.datum.set(True)
    frame.consent.set(True)
    frame.start_read(path)
    wait(root, frame)
    frame.clear_button.invoke()
    assert frame.document is None
    frame.close()
    assert path.read_bytes() == raw
    assert list(tmp_path.iterdir()) == [path]


def test_close_during_worker_read_never_calls_destroyed_tk(review, monkeypatch):
    root, frame = review
    started = threading.Event()
    release = threading.Event()

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return parse_gpx(xml())

    monkeypatch.setattr(review_ui, "read_gpx", delayed)
    frame.datum.set(True)
    frame.consent.set(True)
    frame.start_read("not-opened")
    assert started.wait(2)
    worker = frame._thread
    frame.close()
    frame.destroy()
    release.set()
    worker.join(3)
    root.update()
    assert not worker.is_alive() and frame.document is None


def test_actual_world_zoom_drag_and_fit_controls(review):
    root, frame = example(review)
    frame.world_button.invoke()
    assert frame.view.span == 360
    frame.plus_button.invoke()
    assert frame.view.span == 180
    frame.minus_button.invoke()
    assert frame.view.span == 360
    frame.canvas.event_generate("<ButtonPress-1>", x=200, y=100)
    frame.canvas.event_generate("<B1-Motion>", x=280, y=130)
    frame.canvas.event_generate("<ButtonRelease-1>", x=280, y=130)
    root.update()
    assert frame.view.longitude != 0 and frame._drag is None
    frame.fit_button.invoke()
    assert frame.view.span < 100


def test_smallest_supported_window_shows_all_controls(review):
    root, frame = example(review)
    root.geometry("980x820")
    root.update()
    frame.draw()
    for widget in (
        frame.open_button,
        frame.example_button,
        frame.datum_check,
        frame.consent_check,
        frame.track_box,
        frame.fit_button,
        frame.world_button,
        frame.canvas,
        frame.point_spin,
        frame.center_button,
        frame.provenance_label,
    ):
        assert widget.winfo_ismapped() and widget.winfo_height() > 1
        assert (
            widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + root.winfo_width()
        )
        assert (
            widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
        )


def test_missing_coastline_data_is_visible_not_silently_replaced(monkeypatch):
    import tkinter as tk

    root = tk.Tk()

    def missing():
        raise ValueError("test integrity failure")

    monkeypatch.setattr(review_ui, "load_overview", missing)
    frame = review_ui.ReviewFrame(root)
    root.update()
    frame.draw()
    texts = [
        frame.canvas.itemcget(i, "text")
        for i in frame.canvas.find_all()
        if frame.canvas.type(i) == "text"
    ]
    assert any("COASTLINE LAYER UNAVAILABLE" in text for text in texts)
    assert not frame.canvas.find_withtag("coastline")
    frame.close()
    root.destroy()


def test_separate_gpx_window_does_not_change_active_trip_or_receiver():
    import tkinter as tk

    from fieldforge_gps.__main__ import GPSWindow

    from .test_nmea import rmc
    from .test_trip_ui import serial_stub

    root = tk.Tk()
    app = GPSWindow(root)
    root.update()
    session = serial_stub(app)
    session.start_trip(consent=True, wgs84_confirmed=True)
    session._feed(rmc())
    app.open_trips()
    root.update()
    app.trip_window.review_button.invoke()
    root.update()
    frame = app.review_window.review
    same_window = app.review_window
    app.open_review()
    assert app.review_window is same_window
    frame.datum.set(True)
    frame.consent.set(True)
    frame.example_button.invoke()
    wait(root, frame)
    assert app.session is session and session.trip_summary().state == "recording"
    assert session.trip_summary().point_count == 1
    frame.clear_button.invoke()
    session._feed(rmc(time="120001"))
    assert session.trip_summary().point_count == 2
    frame.close()
    app.review_window.destroy()
    session._feed(rmc(time="120002"))
    assert session.trip_summary().point_count == 3
    app.close()
    root.destroy()


@pytest.mark.parametrize("kind", ["review", "receiver", "trips"])
def test_destroy_releases_owned_tk_variables_before_worker_gc(kind):
    import gc
    import tkinter as tk
    import weakref

    from fieldforge_gps.__main__ import GPSWindow

    root = tk.Tk()
    if kind == "review":
        frame = review_ui.ReviewFrame(root)
        app = None
    else:
        app = GPSWindow(root)
        if kind == "trips":
            app.open_trips()
            frame = app.trip_window
        else:
            frame = app
    root.update()
    refs = [
        weakref.ref(value) for value in frame.__dict__.values() if isinstance(value, tk.Variable)
    ]
    assert refs
    frame.destroy()
    # No explicit gc.collect() is needed to finalize owned variables after destroy.
    assert all(ref() is None for ref in refs)
    assert frame.master is None
    frame.destroy()  # Destruction is idempotent.
    if app is not None and app is not frame:
        app.close()
    root.destroy()
    worker = threading.Thread(target=gc.collect)
    worker.start()
    worker.join(2)
    assert not worker.is_alive()
