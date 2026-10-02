"""Source-mode integration; this never substitutes for running the Windows binary."""

import gc
import os
import sqlite3

import pytest

from fieldforge import package_checks
from fieldforge.ui.build_info import description, install_help_menu, show_build_info


@pytest.fixture
def root():
    gc.collect()
    tk = pytest.importorskip("tkinter")
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("A functioning display is required in the graphical CI job")
    errors = []
    window.report_callback_exception = lambda *args: errors.append(args)
    yield window
    window.destroy()
    gc.collect()
    assert not errors


def test_build_info_displays_exact_database_without_reading_or_changing_it(tmp_path):
    path = tmp_path / "private chosen file.db"
    path.write_bytes(b"not a database and must not be opened")
    before = path.read_bytes()
    text = description(path)
    assert str(path.resolve()) in text
    assert "Not recorded in this source build" in text
    assert "not inside the portable application folder" in text
    assert "External map files are not included" in text
    assert path.read_bytes() == before


def test_real_help_menu_opens_readonly_data_location_window(root, tmp_path):
    database = tmp_path / "never-opened.db"
    menu = install_help_menu(root, database)
    help_menu = root.nametowidget(menu.entrycget("Help", "menu"))
    help_menu.invoke(0)
    root.update()
    window = next(w for w in root.winfo_children() if w.winfo_class() == "Toplevel")
    def children(widget):
        for child in widget.winfo_children():
            yield child
            yield from children(child)
    text = next(w for w in children(window) if w.winfo_class() == "Text")
    assert str(database) in text.get("1.0", "end")
    assert text["state"] == "disabled"
    assert not database.exists()


def test_help_window_minimum_dimensions_and_close(root, tmp_path):
    window = show_build_info(root, tmp_path / "selected.db")
    window.geometry("650x480")
    root.update()
    button = next(w for w in window.winfo_children() if w.winfo_class() == "TButton")
    assert button.winfo_rooty() + button.winfo_height() <= window.winfo_rooty() + window.winfo_height()
    button.invoke()
    root.update()
    assert not window.winfo_exists()


def test_source_diagnostics_use_scratch_data_and_real_parser_not_user_database(root, tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    sentinel = tmp_path / "unreadable-user-database.db"
    sentinel.write_bytes(b"user sentinel - not SQL")
    monkeypatch.setenv("FIELDFORGE_DB", str(sentinel))
    before = dict(os.environ)
    closed = []
    original_connect = sqlite3.connect
    class TrackedMapConnection(sqlite3.Connection):
        def close(self):
            super().close()
            closed.append(True)
    def connect(database, *args, **kwargs):
        # Only track the diagnostic fixture writer, not production read-only URIs.
        if str(database).endswith("synthetic.mbtiles"):
            kwargs["factory"] = TrackedMapConnection
        return original_connect(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", connect)
    report = package_checks.verify_installation()
    assert closed == [True]  # A transaction context alone does not close SQLite.
    assert report["status"] == "passed" and not report["packaged"]
    assert "Not attempted" in report["desktop"]
    assert len(report["checks"]) == 5
    assert sentinel.read_bytes() == b"user sentinel - not SQL"
    assert dict(os.environ) == before
