import pytest

from fieldforge_gps.session import Session

from .test_nmea import rmc
from .test_session import WALL
from .test_ui import pump
from .test_ui import screen as screen


def preview(screen):
    root, app, dialogs = screen
    app.open_trips()
    root.update()
    return root, app, app.trip_window, dialogs


def example(screen):
    root, app, window, dialogs = preview(screen)
    app.datum.set(True)
    app.trip_consent.set(True)
    window.example()
    assert app.session.wait(2)
    window.refresh()
    root.update()
    return root, app, window, dialogs


def serial_stub(app):
    # Deterministic GUI state machine; actual worker+fake-device I/O is covered
    # separately in test_trip_session, not claimed as hardware validation here.
    s = Session("serial", clock=lambda: 0, utc_now=lambda: WALL)
    s._started = s._running = True
    app._replace(s)
    app.datum.set(True)
    app.trip_consent.set(True)
    return s


def test_trips_default_idle_no_session_no_recording(screen):
    root, app, window, dialogs = preview(screen)
    assert app.session is None and not app.trip_consent.get()
    assert "NOT RECORDING" in window.mode.get()
    assert str(window.start_button["state"]) == "disabled"
    assert str(window.example_button["state"]) == "disabled"
    assert not window.canvas.find_withtag("segment")


def test_example_permission_gating(screen):
    root, app, window, dialogs = preview(screen)
    window.example()
    assert app.session is None and dialogs
    assert not app.datum.get() and not app.trip_consent.get()


def test_actual_recorded_preview_gap_lines_and_history_label(screen):
    root, app, window, dialogs = example(screen)
    assert app.session.trip_summary().point_count == 30
    assert "RECORDED FILE — NOT LIVE" in window.mode.get()
    assert len(window.canvas.find_withtag("segment")) == 3
    assert len(window.canvas.find_withtag("start")) == 3
    assert len(window.canvas.find_withtag("end")) == 3
    assert "30/30" in window.preview_notice.get()
    assert "gaps excluded" in window.summary.get()
    assert str(window.export_button["state"]) == "normal"
    assert not dialogs


def test_trip_controls_start_pause_resume_finish_and_no_autoresume(screen):
    root, app, window, dialogs = preview(screen)
    s = serial_stub(app)
    window.start()
    s._feed(rmc())
    window.pause()
    s._feed(rmc(time="120001"))
    assert s.trip_summary().point_count == 1
    window.resume()
    s._feed(rmc(time="120002"))
    window.finish()
    assert s.trip_summary().state == "finished"
    assert [len(seg) for seg in s.trip_snapshot().segments] == [1, 1]
    assert not dialogs


@pytest.mark.parametrize("variable", ["datum", "trip_consent"])
def test_revoke_permission_pauses_immediately_and_recheck_does_not_resume(screen, variable):
    root, app, window, dialogs = preview(screen)
    s = serial_stub(app)
    window.start()
    s._feed(rmc())
    getattr(app, variable).set(False)
    assert s.trip_summary().state == "paused"
    s._feed(rmc(time="120001"))
    assert s.trip_summary().point_count == 1
    getattr(app, variable).set(True)
    assert s.trip_summary().state == "paused"


def test_export_actual_recorded_track_no_household_write(screen, tmp_path, monkeypatch):
    root, app, window, dialogs = example(screen)
    sentinel = tmp_path / "household.db"
    sentinel.write_bytes(b"keep me")
    target = tmp_path / "trip.gpx"
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kwargs: str(target))
    window.export_button.invoke()
    assert target.is_file() and b"NOT LIVE" in target.read_bytes()
    assert b"FICTIONAL SOFTWARE EXAMPLE" in target.read_bytes()
    assert sentinel.read_bytes() == b"keep me"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["household.db", "trip.gpx"]
    assert app._trip_exported_revision is not None
    assert app.request_close() is True  # Exact exported revision needs no unsaved-history warning.


def test_export_rechecks_datum_after_file_dialog(screen, tmp_path, monkeypatch):
    root, app, window, dialogs = example(screen)
    target = tmp_path / "blocked.gpx"

    def dialog(**kwargs):
        app.datum.set(False)
        return str(target)

    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", dialog)
    window.export()
    assert not target.exists() and dialogs


def test_export_binds_to_trip_revision_after_dialog(screen, tmp_path, monkeypatch):
    root, app, window, dialogs = example(screen)
    target = tmp_path / "blocked.gpx"

    def dialog(**kwargs):
        app.session.discard_trip()
        return str(target)

    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", dialog)
    window.export()
    assert not target.exists() and "changed" in dialogs[-1][1]


def test_unsaved_trip_not_silently_replaced_by_different_source(screen, tmp_path):
    root, app, window, dialogs = example(screen)
    original = app.session
    source = tmp_path / "other.nmea"
    source.write_bytes(rmc())
    assert app.load_recording(source) is False
    assert app.session is original and original.trip_summary().point_count == 30
    assert "not been replaced" in dialogs[-1][1]


def test_discard_requires_confirmation_and_clears_preview(screen, monkeypatch):
    root, app, window, dialogs = example(screen)
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *args, **kwargs: False)
    window.discard()
    assert app.session.trip_summary().point_count == 30
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *args, **kwargs: True)
    window.discard()
    assert app.session.trip_summary().point_count == 0
    assert not window.canvas.find_withtag("segment")


def test_close_warning_can_cancel_exit(screen, monkeypatch):
    root, app, window, dialogs = example(screen)
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *args, **kwargs: False)
    assert app.request_close() is False
    assert app.session.trip_summary().point_count == 30
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *args, **kwargs: True)
    assert app.request_close() is True


def test_closing_trip_window_does_not_change_capture_and_receiver_shows_it(screen):
    root, app, window, dialogs = preview(screen)
    s = serial_stub(app)
    window.start()
    window.close()
    s._feed(rmc())
    pump(root)
    assert "RECORDING" in app.trip_status.get() and s.trip_summary().point_count == 1
    app.open_trips()
    root.update()
    assert app.trip_window.winfo_exists()


def test_minimum_trip_window_controls_fit(screen):
    root, app, window, dialogs = example(screen)
    window.geometry("940x750")
    root.update()
    for widget in (
        window.start_button,
        window.pause_button,
        window.resume_button,
        window.finish_button,
        window.discard_button,
        window.example_button,
        window.export_button,
        window.consent_check,
        window.preview_label,
    ):
        assert widget.winfo_ismapped() and widget.winfo_height() > 1
        assert (
            widget.winfo_rooty() + widget.winfo_height()
            <= window.winfo_rooty() + window.winfo_height()
        )
        assert (
            widget.winfo_rootx() + widget.winfo_width()
            <= window.winfo_rootx() + window.winfo_width()
        )


def test_disconnect_retains_recorded_history_but_clears_current_fix(screen):
    root, app, window, dialogs = example(screen)
    app.disconnect()
    window.refresh()
    assert app.session.snapshot().position is None
    assert app.session.trip_summary().point_count == 30
    assert "NOT LIVE" in window.mode.get()
