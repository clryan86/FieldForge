import gc
import threading
import time
from dataclasses import replace

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.binder import BinderDialog

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; GUI CI requires a display")
    root.geometry("1100x850")
    errors, closed = [], []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("fieldforge.ui.binder.messagebox.askyesno", lambda *args, **kwargs: False)
    library = KnowledgeLibrary(tmp_path / "library.db")
    library.upsert(KnowledgeArticle("article", "Workshop measurement", "First complete body.\n\nKeep conditions.", "math"))
    library.annotate("article", bookmarked=True, note="PRIVATE_NOTE_MARKER")
    dialog = BinderDialog(root, library.database_path, "article", on_close=lambda: closed.append(True))
    root.update()
    try:
        yield root, dialog, library, closed
    finally:
        if not dialog._disposed:
            dialog.destroy()
        dialog._worker.shutdown(wait=True, cancel_futures=True)
        root.destroy()
        gc.collect()
    assert not errors


def wait(root, dialog):
    deadline = time.monotonic() + 5
    while dialog.busy and not dialog._disposed and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    root.update()
    assert not dialog.busy or dialog._disposed


def preview(root, dialog):
    dialog.preview_button.invoke()
    wait(root, dialog)
    assert dialog.binder is not None


def test_initial_screen_does_not_export_or_include_private_notes(screen):
    _, dialog, library, closed = screen
    assert dialog.binder is None and dialog.saved is None
    assert not dialog.notes.get() and not dialog.permission.get()
    assert str(dialog.save_button["state"]) == "disabled"
    assert str(dialog.open_button["state"]) == "disabled"
    assert library.count() == 1 and not closed


def test_preview_reads_real_article_and_missing_review_without_writing_file(screen):
    root, dialog, library, _ = screen
    before = library.database_path.read_bytes()
    preview(root, dialog)
    assert dialog.tree.item("0", "values")[1] == "Not supplied"
    assert "First complete body" in dialog.text.get("1.0", "end")
    assert "PRIVATE_NOTE_MARKER" not in dialog.text.get("1.0", "end")
    assert "FULL articles" in dialog.summary.get()
    assert before == library.database_path.read_bytes()
    assert str(dialog.save_button["state"]) == "disabled"


def test_private_notes_need_explicit_confirmation_before_preview(screen, monkeypatch):
    root, dialog, _, _ = screen
    dialog.notes.set(True)
    dialog.build()
    assert not dialog.busy and dialog.binder is None
    assert "not confirmed" in dialog.status.get()
    monkeypatch.setattr("fieldforge.ui.binder.messagebox.askyesno", lambda *args, **kwargs: True)
    preview(root, dialog)
    assert dialog.binder.include_notes
    assert "PRIVATE_NOTE_MARKER" in dialog.text.get("1.0", "end")
    assert "INCLUDED" in dialog.summary.get()


def test_changing_options_invalidates_previous_preview_and_consent(screen):
    root, dialog, _, _ = screen
    preview(root, dialog)
    dialog.permission.set(True)
    dialog._buttons()
    assert str(dialog.save_button["state"]) == "normal"
    dialog.binder_title.set("Different binder")
    assert dialog.binder is None and not dialog.permission.get()
    assert not dialog.tree.get_children()
    assert str(dialog.save_button["state"]) == "disabled"


def test_save_uses_the_captured_version_and_never_opens_automatically(screen, tmp_path, monkeypatch):
    root, dialog, library, _ = screen
    preview(root, dialog)
    original = library.get("article")
    library.upsert(replace(original, body="New body after preview"))
    path = tmp_path / "binder.html"
    monkeypatch.setattr("fieldforge.ui.binder.filedialog.asksaveasfilename", lambda **kwargs: str(path))
    def blocked(*args, **kwargs):
        raise AssertionError("automatic browser launch")
    monkeypatch.setattr("fieldforge.ui.binder.open_saved_binder", blocked)
    dialog.permission.set(True)
    dialog._buttons()
    dialog.save_button.invoke()
    wait(root, dialog)
    assert dialog.saved and path.exists()
    assert "First complete body" in path.read_text(encoding="utf-8")
    assert "New body after preview" not in path.read_text(encoding="utf-8")
    assert "Nothing was printed or opened" in dialog.status.get()


def test_save_cancel_and_existing_file_preserve_prior_data(screen, tmp_path, monkeypatch):
    root, dialog, _, _ = screen
    preview(root, dialog)
    dialog.permission.set(True)
    monkeypatch.setattr("fieldforge.ui.binder.filedialog.asksaveasfilename", lambda **kwargs: "")
    dialog.save()
    assert not dialog.busy and dialog.saved is None
    path = tmp_path / "existing.html"
    path.write_text("Keep this", encoding="utf-8")
    monkeypatch.setattr("fieldforge.ui.binder.filedialog.asksaveasfilename", lambda **kwargs: str(path))
    dialog.save()
    wait(root, dialog)
    assert path.read_text(encoding="utf-8") == "Keep this"
    assert dialog.saved is None and "Operation failed" in dialog.status.get()
    assert dialog.binder is not None


def test_open_saved_binder_requires_separate_confirmation(screen, tmp_path, monkeypatch):
    root, dialog, _, _ = screen
    preview(root, dialog)
    path = tmp_path / "binder.html"
    monkeypatch.setattr("fieldforge.ui.binder.filedialog.asksaveasfilename", lambda **kwargs: str(path))
    dialog.permission.set(True)
    dialog.save()
    wait(root, dialog)
    opened = []
    monkeypatch.setattr("fieldforge.ui.binder.open_saved_binder", lambda saved: opened.append(saved) or True)
    dialog.open_button.invoke()
    assert not opened
    monkeypatch.setattr("fieldforge.ui.binder.messagebox.askyesno", lambda *args, **kwargs: True)
    dialog.open_button.invoke()
    assert opened == [dialog.saved]
    assert "requested" in dialog.status.get()


def test_corrupt_new_preview_disables_stale_success(screen):
    root, dialog, library, _ = screen
    preview(root, dialog)
    with library.connect() as db:
        db.execute("UPDATE knowledge_articles SET checksum='broken'")
    dialog.build()
    wait(root, dialog)
    assert dialog.binder is None and dialog.saved is None
    assert "checksum mismatch" in dialog.status.get()
    assert str(dialog.save_button["state"]) == "disabled"


def test_save_worker_blocks_normal_close_until_result_is_known(screen, tmp_path, monkeypatch):
    root, dialog, _, closed = screen
    from fieldforge.ui import binder
    preview(root, dialog)
    original = binder.save_binder
    started, release = threading.Event(), threading.Event()
    def delayed(*args, **kwargs):
        started.set()
        release.wait(2)
        return original(*args, **kwargs)
    monkeypatch.setattr(binder, "save_binder", delayed)
    monkeypatch.setattr(binder.filedialog, "asksaveasfilename", lambda **kwargs: str(tmp_path / "out.html"))
    dialog.permission.set(True)
    dialog.save()
    assert started.wait(1)
    dialog.close()
    assert not dialog._disposed and not closed
    release.set()
    wait(root, dialog)
    assert dialog.saved is not None
    dialog.close()
    assert dialog._disposed and closed == [True]


def test_preview_cancel_discards_late_read_without_output(screen, monkeypatch):
    root, dialog, _, closed = screen
    from fieldforge.ui import binder
    started, release = threading.Event(), threading.Event()
    original = binder.capture_binder
    def delayed(*args, **kwargs):
        started.set()
        release.wait(2)
        return original(*args, **kwargs)
    monkeypatch.setattr(binder, "capture_binder", delayed)
    dialog.build()
    assert started.wait(1)
    dialog.close()
    release.set()
    dialog._worker.shutdown(wait=True)
    root.update()
    assert dialog._disposed and closed == [True] and dialog.saved is None


def test_worker_does_not_touch_tk_and_ui_uses_main_thread(screen, monkeypatch):
    root, dialog, _, _ = screen
    from fieldforge.ui import binder
    main = threading.get_ident()
    threads = []
    original = binder.capture_binder
    def capture(*args, **kwargs):
        threads.append(threading.get_ident())
        return original(*args, **kwargs)
    monkeypatch.setattr(binder, "capture_binder", capture)
    preview(root, dialog)
    assert threads and main not in threads


def test_bookmark_mode_is_global_and_explicit(screen):
    root, dialog, library, _ = screen
    library.upsert(KnowledgeArticle("another", "Another topic", "Full unrelated body", "different"))
    library.annotate("another", bookmarked=True, note="")
    dialog.mode.set("bookmarks")
    preview(root, dialog)
    assert len(dialog.binder.entries) == 2
    assert [entry.article.slug for entry in dialog.binder.entries] == ["another", "article"]


def test_long_preview_discloses_truncation_without_losing_full_output(screen):
    root, dialog, library, _ = screen
    library.upsert(replace(library.get("article"), body="Long text.\n" * 2500))
    preview(root, dialog)
    assert len(dialog.text.get("1.0", "end-1c")) == 20000
    assert "FULL article" in dialog.text_notice.get()
    assert len(dialog.binder.entries[0].article.body) > 20000


def test_confirmation_and_print_controls_visible_at_minimum_size(screen):
    root, dialog, _, _ = screen
    dialog.geometry("800x700")
    root.update()
    for control in (dialog.save_button, dialog.open_button, dialog.privacy, dialog.footer):
        assert control.winfo_rooty() + control.winfo_height() <= dialog.winfo_rooty() + dialog.winfo_height()
    assert dialog.tabs.winfo_height() > 100
