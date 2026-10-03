"""Main-desktop ownership and unsaved-trip guards for the GPS workspace."""

import gc
import os
import time
from pathlib import Path

import pytest

import fieldforge_gps
from fieldforge.ui.gps import GPSWorkspace, install_gps_menu


@pytest.fixture
def root(monkeypatch):
    import tkinter as tk

    gc.collect()
    try:
        window = tk.Tk()
    except tk.TclError:
        if os.environ.get("FIELDFORGE_REQUIRE_GUI") == "1":
            pytest.fail("Desktop GPS integration requires a functioning display")
        pytest.skip("Graphical integration runs in the dedicated CI jobs")
    errors = []
    window.report_callback_exception = lambda *args: errors.append(args)

    def unexpected_dialog(*args, **kwargs):
        pytest.fail(f"Unexpected desktop error dialog: {args}")

    monkeypatch.setattr("tkinter.messagebox.showerror", unexpected_dialog)
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass  # Some tests exercise the desktop's normal root-close callback.
    gc.collect()
    assert not errors


def join(workers):
    for worker in workers:
        worker._thread.join(2)
        assert not worker._thread.is_alive()


def unsaved_trip(root, receiver):
    path = Path(fieldforge_gps.__file__).parent / "data" / "SYNTHETIC-TRIP.nmea"
    receiver.datum.set(True)
    receiver.trip_consent.set(True)
    assert receiver.load_recording(path, collect_track=True)
    deadline = time.monotonic() + 5
    while receiver.session.snapshot().running and time.monotonic() < deadline:
        root.update()
        time.sleep(.005)
    assert receiver.session.trip_summary().point_count > 0


def test_navigation_menu_reuses_workspace_without_reading_household(root, tmp_path, monkeypatch):
    import tkinter as tk

    sentinel = tmp_path / "household.db"
    sentinel.write_bytes(b"Unrelated data; do not read or initialize")
    monkeypatch.setenv("FIELDFORGE_DB", str(sentinel))
    bar = tk.Menu(root)
    root.configure(menu=bar)
    workspace = install_gps_menu(root, bar)
    assert workspace.receiver is None
    menu = root.nametowidget(bar.entrycget("Navigation", "menu"))
    menu.invoke(0)
    receiver = workspace.receiver
    view = receiver.live_map_frame
    workers = [view._map_reader, view.open_finder().worker]
    root.update()
    menu.invoke(0)
    assert workspace.receiver is receiver and receiver.live_map_frame is view
    assert receiver.session is None and not view.show_live.get()
    assert sentinel.read_bytes() == b"Unrelated data; do not read or initialize"
    assert list(tmp_path.iterdir()) == [sentinel]
    workspace.close()
    join(workers)
    assert root.winfo_exists() and workspace.window is None


def test_receiver_close_cancel_preserves_unsaved_trip_then_can_close(root, monkeypatch):
    workspace = GPSWorkspace(root)
    receiver = workspace.open()
    reader = receiver.live_map_frame._map_reader
    unsaved_trip(root, receiver)
    count = receiver.session.trip_summary().point_count
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *a, **kw: False)
    workspace.request_close()
    assert workspace.receiver is receiver and receiver.session.trip_summary().point_count == count
    assert workspace.window.winfo_exists() and not receiver._closed
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *a, **kw: True)
    workspace.request_close()
    assert workspace.receiver is None and receiver._closed
    join([reader])


def test_direct_parent_destruction_clears_ownership_and_workers(root):
    workspace = GPSWorkspace(root)
    receiver = workspace.open()
    view = receiver.live_map_frame
    workers = [view._map_reader, view.open_finder().worker]
    workspace.window.destroy()
    assert workspace.window is None and workspace.receiver is None
    assert receiver._closed and view._closed
    join(workers)
    replacement = workspace.open()
    assert replacement is not receiver and replacement.session is None
    reader = replacement.live_map_frame._map_reader
    workspace.close()
    join([reader])


def test_map_startup_failure_does_not_leave_receiver_running(root, monkeypatch):
    from fieldforge_gps.__main__ import GPSWindow

    def fail(_self):
        raise RuntimeError("Controlled workspace startup failure")

    monkeypatch.setattr(GPSWindow, "open_live_map", fail)
    workspace = GPSWorkspace(root)
    with pytest.raises(RuntimeError, match="Controlled workspace"):
        workspace.open()
    assert workspace.receiver is None and workspace.window is None
    assert not root.winfo_children()


def test_real_desktop_close_respects_gps_trip_before_destroying_root(root, tmp_path, monkeypatch):
    import tkinter as tk

    from fieldforge.ui import desktop

    monkeypatch.setenv("FIELDFORGE_DB", str(tmp_path / "app.db"))
    monkeypatch.setattr(tk, "Tk", lambda: root)
    workers = []
    confirmations = []

    def exercise():
        menu_bar = root.nametowidget(root.cget("menu"))
        navigation = root.nametowidget(menu_bar.entrycget("Navigation", "menu"))
        navigation.invoke(0)
        receiver = next(
            child for window in root.winfo_children() if window.winfo_class() == "Toplevel"
            for child in window.winfo_children() if isinstance(child, fieldforge_gps.__main__.GPSWindow)
        )
        workers.append(receiver.live_map_frame._map_reader)
        unsaved_trip(root, receiver)

        def reject(*args, **_kwargs):
            confirmations.append(args[0])
            return False

        monkeypatch.setattr("tkinter.messagebox.askyesno", reject)
        root.tk.call(root.protocol("WM_DELETE_WINDOW"))
        assert confirmations == ["Exit GPS workspace?"]
        assert root.winfo_exists() and not receiver._closed
        monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *a, **kw: True)
        root.tk.call(root.protocol("WM_DELETE_WINDOW"))
        assert receiver._closed

    monkeypatch.setattr(root, "mainloop", exercise)
    desktop.run()
    join(workers)
