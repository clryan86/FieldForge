"""Real Tk integration. Binder lifecycle regressions are also run separately."""

import gc
import time

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.knowledge import KnowledgeTab
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    root.geometry("1150x820")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    library = KnowledgeLibrary(tmp_path / "app.db")
    library.upsert(KnowledgeArticle("article", "Practice record", "Full local article.\r\n", "tools"))
    panel = KnowledgeTab(root, library)
    panel.pack(fill="both", expand=True)
    root.update()
    dialogs = []
    try:
        yield root, panel, library, dialogs
    finally:
        for dialog in dialogs:
            if not dialog._disposed:
                dialog.destroy()
            dialog._worker.shutdown(wait=True, cancel_futures=True)
        root.destroy()
        panel._worker.shutdown(wait=True, cancel_futures=True)
        gc.collect()
    assert not errors


def open_reader(root, panel, dialogs):
    from fieldforge.ui.pocket import PocketDialog
    panel.results.selection_set("article")
    root.update()
    panel.pocket_button.invoke()
    root.update()
    dialog = next(child for child in panel.winfo_children() if isinstance(child, PocketDialog))
    dialogs.append(dialog)
    return dialog


def wait(root, dialog):
    deadline = time.monotonic() + 5
    while dialog.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    root.update()
    assert not dialog.busy


def test_actual_button_saves_pending_note_but_does_not_export_it(screen, tmp_path, monkeypatch):
    root, panel, library, dialogs = screen
    panel.results.selection_set("article")
    root.update()
    panel.note.insert("1.0", "PRIVATE_PENDING_NOTE")
    panel.personal.set(True)
    dialog = open_reader(root, panel, dialogs)
    assert library.annotation("article")["note"] == "PRIVATE_PENDING_NOTE"
    assert panel.busy and not panel.save_current()
    assert not dialog.notes.get() and not dialog.note_box.winfo_ismapped()
    dialog.build()
    wait(root, dialog)
    assert dialog.binder is not None and dialog.binder.include_notes is False
    path = tmp_path / "Pocket.html"
    monkeypatch.setattr("fieldforge.ui.binder.filedialog.asksaveasfilename", lambda **kwargs: str(path))
    dialog.save()
    assert not path.exists()
    dialog.permission.set(True)
    dialog._buttons()
    dialog.save_button.invoke()
    wait(root, dialog)
    assert 'id="tools"' in path.read_text(encoding="utf-8")
    assert "PRIVATE_PENDING_NOTE" not in path.read_text(encoding="utf-8")
    assert "<script>" in path.read_text(encoding="utf-8")
    assert dialog.saved is not None
    dialog.close()
    root.update()
    assert not panel.busy and panel.save_current()


def test_notes_are_rejected_even_for_programmatically_changed_hidden_option(screen):
    root, panel, _, dialogs = screen
    dialog = open_reader(root, panel, dialogs)
    with pytest.raises(ValueError, match="never exports"):
        dialog.capture_snapshot(dialog.database, slugs=("article",), include_notes=True)


def test_busy_library_or_failed_note_save_prevents_reader(screen, monkeypatch):
    _, panel, _, _ = screen
    from fieldforge.ui.pocket import open_pocket
    panel.busy = True
    assert open_pocket(panel) is None
    panel.busy = False
    monkeypatch.setattr(panel, "save_current", lambda: False)
    assert open_pocket(panel) is None


def test_close_preview_without_saving_releases_busy_guard(screen):
    root, panel, _, dialogs = screen
    dialog = open_reader(root, panel, dialogs)
    dialog.build()
    wait(root, dialog)
    dialog.close()
    root.update()
    assert not panel.busy and dialog.saved is None


def test_constructor_failure_releases_library_guard(screen, monkeypatch):
    _, panel, _, _ = screen
    from fieldforge.ui import pocket
    def fail(*args, **kwargs):
        raise ValueError("cannot create dialog")
    monkeypatch.setattr(pocket, "PocketDialog", fail)
    with pytest.raises(ValueError):
        pocket.open_pocket(panel)
    assert not panel.busy


def test_reader_labels_and_toolbar_visible_at_supported_window_size(screen):
    root, panel, _, dialogs = screen
    assert panel.pocket_button.winfo_width() > 1
    for button in (panel.binder_button, panel.pocket_button):
        assert button.winfo_rootx() + button.winfo_width() <= panel.winfo_rootx() + panel.winfo_width()
    dialog = open_reader(root, panel, dialogs)
    dialog.geometry("800x700")
    root.update()
    for control in (dialog.save_button, dialog.open_button, dialog.footer):
        assert control.winfo_rooty() + control.winfo_height() <= dialog.winfo_rooty() + dialog.winfo_height()
    assert "compatible browser" in dialog.notice["text"]
