import gc
import threading
import time
from dataclasses import replace

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.originals import CapturedPDF


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.knowledge import KnowledgeTab

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; graphical CI requires a working display")
    root.geometry("1240x850")
    failures = []
    root.report_callback_exception = lambda *args: failures.append(args)
    monkeypatch.setattr("fieldforge.ui.originals.messagebox.askyesno", lambda *args, **kwargs: False)
    library = KnowledgeLibrary(tmp_path / "app.db")
    library.upsert(KnowledgeArticle("guide", "Workshop drawing reference", "Keep the original for drawings.", "reference"))
    panel = KnowledgeTab(root, library)
    panel.pack(fill="both", expand=True)
    root.update()
    dialogs = []
    yield root, panel, library, dialogs
    for dialog in dialogs:
        if not dialog._disposed:
            dialog.destroy()
        dialog._worker.shutdown(wait=True, cancel_futures=True)
    root.destroy()
    panel._worker.shutdown(wait=True, cancel_futures=True)
    gc.collect()
    assert not failures


def wait(root, dialog):
    deadline = time.monotonic() + 6
    while dialog.busy and not dialog._disposed and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    root.update()
    assert not dialog.busy or dialog._disposed


def opened(root, panel, dialogs, *, article=True):
    from fieldforge.ui.originals import OriginalsDialog
    if article:
        panel.results.selection_set("guide")
        root.update()
    panel.originals_button.invoke()
    root.update()
    dialog = next(child for child in panel.winfo_children() if isinstance(child, OriginalsDialog))
    dialogs.append(dialog)
    wait(root, dialog)
    return dialog


def capture(root, dialog, path, *, associate=False):
    path.write_bytes(b"%PDF-1.7\nTest bytes, not a valid PDF\x00\xff")
    dialog.associate.set(associate)
    dialog.load_path(str(path))
    wait(root, dialog)
    assert dialog.captured is not None, dialog.status.get()


def test_empty_library_can_store_without_article_and_has_no_automatic_files(screen):
    root, panel, _, dialogs = screen
    dialog = opened(root, panel, dialogs, article=False)
    assert dialog.current_slug is None and not dialog.store.browse().records
    assert not dialog.associate.get() and not dialog.permission.get()
    assert str(dialog.association_box["state"]) == "disabled"
    assert "metadata preview only" in dialog.file_label.master["text"]
    assert panel.busy and not panel.save_current()
    dialog.close()
    assert not panel.busy


def test_pending_article_note_saved_but_not_copied_and_capture_requires_consent(screen, tmp_path):
    root, panel, library, dialogs = screen
    panel.results.selection_set("guide")
    root.update()
    panel.note.insert("1.0", "PRIVATE_PENDING_NOTE")
    dialog = opened(root, panel, dialogs)
    assert library.annotation("guide")["note"] == "PRIVATE_PENDING_NOTE"
    capture(root, dialog, tmp_path / "drawing.pdf", associate=True)
    assert "not stored" in dialog.file_info.get()
    dialog.save()
    assert dialog.store.browse().references == 0
    dialog.permission.set(True)
    dialog._buttons()
    dialog.store_button.invoke()
    wait(root, dialog)
    assert dialog.store.browse().references == 1
    assert dialog.selected().article_slug == "guide"
    assert dialog.captured is None
    assert "PRIVATE_PENDING_NOTE" not in dialog.details.get()
    assert library.annotation("guide")["note"] == "PRIVATE_PENDING_NOTE"


def test_association_choice_change_discards_prior_capture_and_consent(screen, tmp_path):
    root, panel, _, dialogs = screen
    dialog = opened(root, panel, dialogs)
    capture(root, dialog, tmp_path / "source.pdf")
    dialog.permission.set(True)
    dialog.associate.set(True)
    assert dialog.captured is None and not dialog.permission.get()
    assert str(dialog.store_button["state"]) == "disabled"


def test_failed_second_capture_does_not_leave_old_pdf_ready(screen, tmp_path):
    root, panel, _, dialogs = screen
    dialog = opened(root, panel, dialogs)
    capture(root, dialog, tmp_path / "source.pdf")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a PDF header")
    dialog.load_path(str(bad))
    wait(root, dialog)
    assert dialog.captured is None and "PDF header" in dialog.status.get()
    assert dialog.store.browse().references == 0


def test_article_changes_during_preview_are_not_silently_accepted(screen, tmp_path):
    root, panel, library, dialogs = screen
    dialog = opened(root, panel, dialogs)
    capture(root, dialog, tmp_path / "source.pdf", associate=True)
    library.upsert(replace(library.get("guide"), body="Changed in another window"))
    dialog.permission.set(True)
    dialog.save()
    wait(root, dialog)
    assert "changed since capture" in dialog.status.get()
    assert dialog.captured is not None and dialog.store.browse().references == 0


def test_actual_export_button_needs_confirmation_and_preserves_all_bytes(screen, tmp_path, monkeypatch):
    root, panel, _, dialogs = screen
    dialog = opened(root, panel, dialogs)
    path = tmp_path / "original.pdf"
    capture(root, dialog, path)
    raw = path.read_bytes()
    path.unlink()  # Store uses captured bytes, not the path.
    dialog.permission.set(True)
    dialog.save()
    wait(root, dialog)
    record = dialog.selected()
    output = tmp_path / "restored.pdf"
    monkeypatch.setattr("fieldforge.ui.originals.filedialog.asksaveasfilename", lambda **kwargs: str(output))
    dialog.export_button.invoke()
    assert not output.exists()
    monkeypatch.setattr("fieldforge.ui.originals.messagebox.askyesno", lambda *args, **kwargs: True)
    dialog.export_button.invoke()
    wait(root, dialog)
    assert output.read_bytes() == raw
    assert "Nothing opened automatically" in dialog.status.get()
    assert dialog.store.read_verified(record) == raw


def test_verification_and_corruption_error_do_not_show_false_success(screen, tmp_path):
    root, panel, _, dialogs = screen
    dialog = opened(root, panel, dialogs)
    capture(root, dialog, tmp_path / "source.pdf")
    dialog.permission.set(True)
    dialog.save()
    wait(root, dialog)
    dialog.verify_button.invoke()
    wait(root, dialog)
    assert "Verified" in dialog.status.get() and "does not validate" in dialog.status.get()
    with dialog.store.connect() as db:
        db.execute("UPDATE knowledge_original_blobs SET payload=CAST(replace(CAST(payload AS TEXT),'Test','Fake') AS BLOB)")
    dialog.verify_button.invoke()
    wait(root, dialog)
    assert "checksum failed" in dialog.status.get() and "Verified" not in dialog.status.get()


def test_remove_confirmation_only_affects_selected_stored_reference(screen, tmp_path, monkeypatch):
    root, panel, library, dialogs = screen
    dialog = opened(root, panel, dialogs)
    original = tmp_path / "source.pdf"
    capture(root, dialog, original)
    dialog.permission.set(True)
    dialog.save()
    wait(root, dialog)
    dialog.remove_button.invoke()
    assert dialog.store.browse().references == 1
    monkeypatch.setattr("fieldforge.ui.originals.messagebox.askyesno", lambda *args, **kwargs: True)
    dialog.remove_button.invoke()
    wait(root, dialog)
    assert dialog.store.browse().unique_files == 0
    assert original.exists() and library.get("guide")


def test_background_save_blocks_close_and_duplicate_submit(screen, tmp_path, monkeypatch):
    root, panel, _, dialogs = screen
    dialog = opened(root, panel, dialogs)
    capture(root, dialog, tmp_path / "source.pdf")
    real = dialog.store.store
    started, release = threading.Event(), threading.Event()
    calls = []
    def delayed(*args, **kwargs):
        calls.append(threading.get_ident())
        started.set()
        release.wait(3)
        return real(*args, **kwargs)
    monkeypatch.setattr(dialog.store, "store", delayed)
    dialog.permission.set(True)
    dialog.save()
    assert started.wait(1)
    dialog.save()
    dialog.close()
    assert not dialog._disposed and panel.busy
    release.set()
    wait(root, dialog)
    assert len(calls) == 1 and calls[0] != threading.get_ident()
    assert dialog.store.browse().references == 1


def test_cancelling_read_discards_captured_bytes_without_storage(screen, tmp_path, monkeypatch):
    root, panel, _, dialogs = screen
    dialog = opened(root, panel, dialogs)
    started, release = threading.Event(), threading.Event()
    def delayed(*args):
        started.set()
        release.wait(3)
        return CapturedPDF("source.pdf", b"%PDF-example"), None
    monkeypatch.setattr("fieldforge.ui.originals._capture", delayed)
    dialog.load_path(str(tmp_path / "source.pdf"))
    assert started.wait(1)
    dialog.close()
    release.set()
    dialog._worker.shutdown(wait=True)
    root.update()
    assert dialog._disposed and not panel.busy and dialog.store.browse().references == 0


def test_paging_search_and_current_article_filter(screen):
    root, panel, _, dialogs = screen
    dialog = opened(root, panel, dialogs)
    for i in range(27):
        dialog.store.store(CapturedPDF(f"record{i:02}.pdf", f"%PDF-{i}".encode()), acknowledged=True)
    dialog.store.store(CapturedPDF("linked.pdf", b"%PDF-linked"), article=dialog.store.anchor("guide"), acknowledged=True)
    dialog.refresh()
    wait(root, dialog)
    assert len(dialog.tree.get_children()) == 25
    dialog.next.invoke()
    wait(root, dialog)
    assert len(dialog.tree.get_children()) == 3
    dialog.current_only.set(True)
    dialog.refresh()
    wait(root, dialog)
    assert len(dialog.tree.get_children()) == 1
    dialog.query.set("no-match")
    dialog.refresh()
    wait(root, dialog)
    assert not dialog.tree.get_children()
    assert str(dialog.export_button["state"]) == "disabled"


def test_failed_list_clears_stale_counts_and_actions(screen, monkeypatch):
    root, panel, _, dialogs = screen
    dialog = opened(root, panel, dialogs)
    def fail(*args, **kwargs):
        raise OSError("Read error")
    monkeypatch.setattr(dialog.store, "browse", fail)
    dialog.refresh()
    wait(root, dialog)
    assert "no stale counts" in dialog.summary.get()
    assert "Read error" in dialog.status.get()
    assert not dialog.tree.get_children()


def test_busy_library_failed_note_and_failed_constructor_guards(screen, monkeypatch):
    _, panel, _, _ = screen
    from fieldforge.ui import originals
    panel.busy = True
    assert originals.open_originals(panel) is None
    panel.busy = False
    original = panel.save_current
    monkeypatch.setattr(panel, "save_current", lambda: False)
    assert originals.open_originals(panel) is None
    monkeypatch.setattr(panel, "save_current", original)
    def fail(*args, **kwargs):
        raise ValueError("Cannot build window")
    monkeypatch.setattr(originals, "OriginalsDialog", fail)
    with pytest.raises(ValueError):
        originals.open_originals(panel)
    assert not panel.busy


def test_minimum_size_keeps_permission_and_actions_visible(screen, tmp_path):
    root, panel, _, dialogs = screen
    root.geometry("1000x700")
    root.update()
    assert panel.originals_button.winfo_rootx()+panel.originals_button.winfo_width() <= panel.winfo_rootx()+panel.winfo_width()
    dialog = opened(root, panel, dialogs)
    capture(root, dialog, tmp_path / "diagram.pdf", associate=True)
    dialog.geometry("980x760")
    root.update()
    for widget in (dialog.store_button, dialog.consent, dialog.export_button, dialog.close_button, dialog.footer):
        assert widget.winfo_rootx()+widget.winfo_width() <= dialog.winfo_rootx()+dialog.winfo_width()
        assert widget.winfo_rooty()+widget.winfo_height() <= dialog.winfo_rooty()+dialog.winfo_height()
    assert dialog.tree.winfo_height() > 80
