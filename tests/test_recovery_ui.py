import gc
import threading
import time

import pytest

from fieldforge.core.recovery import create_verified_backup
from test_recovery import seed


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.recovery import RecoveryTab

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; GUI CI requires a working display")
    root.geometry("1080x800")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    notices = []
    monkeypatch.setattr("fieldforge.ui.recovery.messagebox.askyesno", lambda *args, **kwargs: True)
    monkeypatch.setattr("fieldforge.ui.recovery.messagebox.showinfo", lambda *args, **kwargs: notices.append(args))
    database = seed(tmp_path / "active.db")
    frame = RecoveryTab(root, database)
    frame.pack(fill="both", expand=True)
    root.update()
    try:
        yield root, frame, database, notices
    finally:
        if not frame._disposed:
            frame.destroy()
        frame._worker.shutdown(wait=True, cancel_futures=True)
        root.destroy()
        gc.collect()
    assert not errors


def wait(root, frame):
    deadline = time.monotonic() + 5
    while frame.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    root.update()
    assert not frame.busy


def backup(root, frame, tmp_path, monkeypatch):
    target = tmp_path / "test-copy.ffbackup"
    monkeypatch.setattr("fieldforge.ui.recovery.filedialog.asksaveasfilename", lambda **kwargs: str(target))
    frame.save_button.invoke()
    wait(root, frame)
    assert frame.preview is not None
    return target


def test_initial_state_and_path_are_honest(screen):
    _, frame, database, _ = screen
    assert frame.location.get() == str(database.resolve())
    assert frame.preview is None and frame.recovered is None
    assert "No backup operation" in frame.status.get()
    assert str(frame.restore_button["state"]) == "disabled"
    assert "unsaved edits are not included" in frame.save_help["text"]


def test_create_saves_notes_before_capture_then_displays_real_counts(screen, tmp_path, monkeypatch):
    root, frame, database, _ = screen
    import sqlite3
    from contextlib import closing

    called = []

    def save_pending():
        called.append(True)
        with closing(sqlite3.connect(database)) as db:
            db.execute("INSERT INTO household_members VALUES(2,'Pending fictional change',1)")
            db.commit()
        return True

    frame.before_backup = save_pending
    target = backup(root, frame, tmp_path, monkeypatch)
    assert called == [True]
    assert target.exists() and dict(frame.preview.counts)["Household members"] == 2
    assert "read-back checked" in frame.result_title.get()
    assert "PRIVATE_SENTINEL" not in frame.report.get("1.0", "end")
    assert str(frame.restore_button["state"]) == "normal"


def test_declining_private_backup_consent_makes_no_file(screen, tmp_path, monkeypatch):
    _, frame, _, _ = screen
    calls = []
    monkeypatch.setattr("fieldforge.ui.recovery.messagebox.askyesno", lambda *args, **kwargs: False)
    monkeypatch.setattr("fieldforge.ui.recovery.filedialog.asksaveasfilename", lambda **kwargs: calls.append(True))
    frame.save_button.invoke()
    assert not calls and not frame.busy and frame.preview is None


def test_cancelling_file_picker_does_not_save_or_start_worker(screen, monkeypatch):
    _, frame, _, _ = screen
    calls = []
    frame.before_backup = lambda: calls.append(True)
    monkeypatch.setattr("fieldforge.ui.recovery.filedialog.asksaveasfilename", lambda **kwargs: "")
    frame.save_button.invoke()
    assert not calls and not frame.busy


def test_pending_note_failure_blocks_backup(screen, tmp_path, monkeypatch):
    _, frame, _, _ = screen
    target = tmp_path / "not-created.ffbackup"
    frame.before_backup = lambda: False
    monkeypatch.setattr("fieldforge.ui.recovery.filedialog.asksaveasfilename", lambda **kwargs: str(target))
    frame.save_button.invoke()
    assert not frame.busy and not target.exists()
    assert "Backup not started" in frame.status.get()


def test_inspect_archive_works_when_current_database_is_missing(screen, tmp_path, monkeypatch):
    root, frame, database, _ = screen
    preview = create_verified_backup(database, tmp_path / "valid.ffbackup")
    database.unlink()
    monkeypatch.setattr("fieldforge.ui.recovery.filedialog.askopenfilename", lambda **kwargs: str(preview.source))
    frame.inspect_button.invoke()
    wait(root, frame)
    assert not database.exists()
    assert frame.preview.database_sha256 == preview.database_sha256
    assert "inspection passed" in frame.result_title.get()


def test_invalid_new_inspection_disables_previous_recovery(screen, tmp_path, monkeypatch):
    root, frame, _, _ = screen
    backup(root, frame, tmp_path, monkeypatch)
    invalid = tmp_path / "bad.ffbackup"
    invalid.write_text("Not a backup")
    monkeypatch.setattr("fieldforge.ui.recovery.filedialog.askopenfilename", lambda **kwargs: str(invalid))
    frame.inspect_button.invoke()
    wait(root, frame)
    assert frame.preview is None
    assert str(frame.restore_button["state"]) == "disabled"
    assert "Operation failed" in frame.result_title.get()


def test_restore_confirmation_and_recovered_path_leave_active_unchanged(screen, tmp_path, monkeypatch):
    root, frame, database, _ = screen
    archive = backup(root, frame, tmp_path, monkeypatch)
    before = database.read_bytes()
    recovered = tmp_path / "separate.db"
    monkeypatch.setattr("fieldforge.ui.recovery.filedialog.asksaveasfilename", lambda **kwargs: str(recovered))
    frame.restore_button.invoke()
    wait(root, frame)
    assert archive.exists() and recovered.exists()
    assert frame.recovered == recovered.resolve()
    assert database.read_bytes() == before
    assert frame.database == database.resolve()
    assert "current database unchanged" in frame.result_title.get()
    assert str(frame.open_button["state"]) == "normal"


def test_declining_restore_does_not_write_destination(screen, tmp_path, monkeypatch):
    root, frame, _, _ = screen
    backup(root, frame, tmp_path, monkeypatch)
    target = tmp_path / "no-restore.db"
    monkeypatch.setattr("fieldforge.ui.recovery.filedialog.asksaveasfilename", lambda **kwargs: str(target))
    monkeypatch.setattr("fieldforge.ui.recovery.messagebox.askyesno", lambda *args, **kwargs: False)
    frame.restore_button.invoke()
    assert not frame.busy and not target.exists() and frame.recovered is None


def test_changed_backup_is_rejected_after_gui_preview(screen, tmp_path, monkeypatch):
    root, frame, database, _ = screen
    archive = backup(root, frame, tmp_path, monkeypatch)
    from fieldforge.core.snapshot import export_snapshot

    different = seed(tmp_path / "different.db", "DIFFERENT_DATA")
    export_snapshot(different, archive)
    target = tmp_path / "should-not-restore.db"
    monkeypatch.setattr("fieldforge.ui.recovery.filedialog.asksaveasfilename", lambda **kwargs: str(target))
    frame.restore_button.invoke()
    wait(root, frame)
    assert not target.exists() and frame.preview is None
    assert "changed since preview" in frame.status.get()
    assert database.exists()


def test_opening_restored_copy_is_explicit_and_reported_as_request(screen, tmp_path, monkeypatch):
    _, frame, database, _ = screen
    requested = []
    frame.recovered = database
    frame._controls()
    monkeypatch.setattr("fieldforge.ui.recovery.launch_recovered_copy", lambda path: requested.append(path))
    monkeypatch.setattr("fieldforge.ui.recovery.messagebox.askyesno", lambda *args, **kwargs: False)
    frame.open_button.invoke()
    assert not requested
    monkeypatch.setattr("fieldforge.ui.recovery.messagebox.askyesno", lambda *args, **kwargs: True)
    frame.open_button.invoke()
    assert requested == [database]
    assert "launch requested" in frame.status.get()


def test_close_and_double_click_guard_during_work(screen, tmp_path, monkeypatch):
    root, frame, _, notices = screen
    from fieldforge.ui import recovery

    original = recovery.create_verified_backup
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow(*args):
        calls.append(True)
        started.set()
        release.wait(2)
        return original(*args)

    monkeypatch.setattr(recovery, "create_verified_backup", slow)
    monkeypatch.setattr(recovery.filedialog, "asksaveasfilename", lambda **kwargs: str(tmp_path / "slow.ffbackup"))
    frame.create()
    assert started.wait(1)
    assert not frame.can_close() and notices
    frame.create()
    assert calls == [True]
    assert str(frame.save_button["state"]) == "disabled"
    release.set()
    wait(root, frame)
    assert frame.can_close()


def test_file_work_is_off_main_thread_and_callbacks_stay_on_it(screen, tmp_path, monkeypatch):
    root, frame, _, _ = screen
    from fieldforge.ui import recovery

    main = threading.get_ident()
    workers, ui = [], []
    original, original_text = recovery.create_verified_backup, frame._text

    def capture(*args):
        workers.append(threading.get_ident())
        return original(*args)

    def text(value):
        ui.append(threading.get_ident())
        original_text(value)

    monkeypatch.setattr(recovery, "create_verified_backup", capture)
    monkeypatch.setattr(frame, "_text", text)
    backup(root, frame, tmp_path, monkeypatch)
    assert workers and main not in workers
    assert ui and set(ui) == {main}


def test_clipboard_path_copy_is_explicit(screen):
    root, frame, database, _ = screen
    frame.copy_active_path()
    assert root.clipboard_get() == str(database.resolve())
    assert "local username" in frame.status.get()


def test_minimum_size_keeps_controls_and_warning_visible(screen):
    root, frame, _, _ = screen
    root.geometry("850x700")
    root.update()
    for widget in (frame.notice, frame.footer, frame.restore_button, frame.open_button):
        assert widget.winfo_rooty() + widget.winfo_height() <= frame.winfo_rooty() + frame.winfo_height()
    assert frame.report.winfo_height() > 70


def test_tab_integration_saves_both_existing_note_editors(screen):
    root, standalone, database, _ = screen
    from tkinter import ttk
    from types import SimpleNamespace

    from fieldforge.ui.recovery import add_recovery_tab

    calls = []
    standalone.pack_forget()
    book = ttk.Notebook(root)
    book.pack(fill="both", expand=True)
    knowledge = SimpleNamespace(busy=False, save_current=lambda: calls.append("article") or True)
    pathways = SimpleNamespace(save_current=lambda: calls.append("learning") or True)
    frame = add_recovery_tab(book, database, knowledge, pathways)
    root.update()
    try:
        assert book.tab(frame, "text") == "Backup & Recovery"
        assert frame.before_backup() and calls == ["article", "learning"]
        knowledge.busy = True
        assert not frame.before_backup()
        assert calls == ["article", "learning"]
    finally:
        frame.destroy()
        frame._worker.shutdown(wait=True)
