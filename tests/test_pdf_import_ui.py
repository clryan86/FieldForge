import gc
import hashlib
import threading
import time
from dataclasses import replace

import pytest
from pdf_fixture import pdf_bytes

from fieldforge.knowledge import KnowledgeLibrary
from fieldforge.knowledge.documents import commit_document
from fieldforge.knowledge.pdf_import import PDFCancelled, PDFTextDocument, prepare_pdf_article


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.pdf_import import PDFImportDialog

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; PDF GUI CI requires a display")
    root.geometry("1100x900")
    errors, completed = [], []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("fieldforge.ui.pdf_import.messagebox.askyesno", lambda *args, **kwargs: True)
    library = KnowledgeLibrary(tmp_path / "library.db")
    try:
        dialog = PDFImportDialog(root, library, completed.append)
    except Exception:
        root.destroy()
        raise
    root.update()
    try:
        yield root, dialog, library, completed
    finally:
        if not dialog._disposed:
            dialog.destroy()
        dialog._worker.shutdown(wait=True, cancel_futures=True)
        root.destroy()
        gc.collect()
    assert not errors


def wait(root, dialog):
    deadline = time.monotonic() + 8
    while dialog._busy and not dialog._disposed and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    root.update()
    assert not dialog._busy or dialog._disposed


def load(root, dialog, tmp_path):
    pytest.importorskip("pypdf")
    path = tmp_path / "workshop.pdf"
    path.write_bytes(pdf_bytes(("Cedarledger equipment record", None, "End conditions must remain.")))
    dialog.load_path(str(path))
    wait(root, dialog)
    assert dialog.document is not None, dialog.status.get()
    return path


def test_initial_screen_has_no_import_or_automatic_dependency_install(screen):
    _, dialog, library, completed = screen
    assert dialog.document is None and not dialog.acknowledged.get()
    assert "Optional PDF support" in dialog.status.get()
    assert "No OCR" in dialog.status.get()
    assert str(dialog.import_button["state"]) == "disabled"
    assert "original PDF bytes are NOT stored" in dialog.import_notice["text"]
    assert library.count() == 0 and not completed


def test_actual_file_picker_loads_all_pages_and_marks_missing_text(screen, tmp_path, monkeypatch):
    root, dialog, library, _ = screen
    pytest.importorskip("pypdf")
    path = tmp_path / "sample.pdf"
    path.write_bytes(pdf_bytes(("First text", None, "Last conditions")))
    monkeypatch.setattr("fieldforge.ui.pdf_import.filedialog.askopenfilename", lambda **kwargs: str(path))
    dialog.choose_button.invoke()
    wait(root, dialog)
    assert dialog.document is not None
    assert "3 physical PDF pages" in dialog.info.get()
    assert "Pages with no extracted text: 2" in dialog.info.get()
    assert "PDF TEXT EXTRACTION" in dialog.preview.get("1.0", "end")
    assert dialog.fields["reviewed_on"].get() == dialog.fields["source_publisher"].get() == ""
    assert library.count() == 0
    dialog.page_picker.current(2)
    dialog.show_page()
    assert "may be blank or image-only" in dialog.preview.get("1.0", "end")
    dialog.page_picker.current(3)
    dialog.show_page()
    assert "Last conditions" in dialog.preview.get("1.0", "end")


def test_source_trust_decline_never_reads_or_imports(screen, monkeypatch):
    _, dialog, library, _ = screen
    monkeypatch.setattr("fieldforge.ui.pdf_import.messagebox.askyesno", lambda *args, **kwargs: False)
    monkeypatch.setattr("fieldforge.ui.pdf_import.read_pdf_document", lambda *args, **kwargs: pytest.fail("No read expected"))
    dialog.load_path("declined.pdf")
    assert not dialog._busy and dialog.document is None and library.count() == 0
    assert "not started" in dialog.status.get()


def test_import_confirmation_keeps_all_pages_not_only_viewed_page(screen, tmp_path):
    root, dialog, library, completed = screen
    path = load(root, dialog, tmp_path)
    captured = dialog.document
    dialog.page_picker.current(3)
    dialog.show_page()
    dialog.import_document()
    assert library.count() == 0 and not completed
    dialog.fields["title"].set("My permitted reference")
    dialog.fields["license"].set("User-supplied permission")
    dialog.acknowledged.set(True)
    dialog._update_buttons()
    path.unlink()  # Commit must use the preview, not read the path again.
    dialog.import_button.invoke()
    wait(root, dialog)
    assert dialog._disposed and completed[0].status == "added"
    article = library.get(captured.suggested_id)
    assert article.body == captured.body
    assert "PDF PAGE 1 OF 3" in article.body and "PDF PAGE 2 OF 3" in article.body
    assert article.license == "User-supplied permission"
    assert library.search("Cedarledger")[0].slug == article.slug


def test_no_text_failure_does_not_leave_previous_preview_ready(screen, tmp_path):
    root, dialog, library, _ = screen
    load(root, dialog, tmp_path)
    bad = tmp_path / "blank.pdf"
    bad.write_bytes(pdf_bytes((None,)))
    dialog.load_path(str(bad))
    wait(root, dialog)
    assert dialog.document is None and not dialog.acknowledged.get()
    assert "OCR" in dialog.status.get()
    assert not dialog.page_picker["values"]
    assert str(dialog.import_button["state"]) == "disabled"
    assert library.count() == 0


def test_existing_article_conflict_preserves_original_and_preview(screen, tmp_path):
    root, dialog, library, completed = screen
    load(root, dialog, tmp_path)
    article = prepare_pdf_article(dialog.document, title=dialog.fields["title"].get(), category="PDF references")
    existing = replace(article, title="Edited title")
    commit_document(library, existing, acknowledged=True)
    library.annotate(existing.slug, bookmarked=True, note="Keep private note")
    dialog.acknowledged.set(True)
    dialog.import_document()
    wait(root, dialog)
    assert not dialog._disposed and not completed
    assert "Nothing was replaced" in dialog.status.get()
    assert library.get(existing.slug) == existing
    assert library.annotation(existing.slug)["note"] == "Keep private note"


def test_cancel_signals_parser_and_late_result_does_not_save(screen, monkeypatch):
    root, dialog, library, completed = screen
    started, finished = threading.Event(), threading.Event()
    def delayed(*args, cancel, **kwargs):
        started.set()
        assert cancel.wait(3)
        finished.set()
        raise PDFCancelled("Cancelled")
    monkeypatch.setattr("fieldforge.ui.pdf_import.read_pdf_document", delayed)
    dialog.load_path("slow.pdf")
    assert started.wait(1)
    dialog.close()
    assert finished.wait(1)
    dialog._worker.shutdown(wait=True)
    root.update()
    assert dialog._disposed and completed == [None] and library.count() == 0


def test_long_page_preview_cap_keeps_entire_captured_body(screen):
    root, dialog, _, _ = screen
    document = PDFTextDocument("long.pdf", "a" * 64, 100, ("Data\n" * 5000, "Final page"), "6.19.0")
    dialog._loaded(document)
    dialog.page_picker.current(1)
    dialog.show_page()
    assert len(dialog.preview.get("1.0", "end-1c")) == 20000
    assert "first 20,000" in dialog.preview_notice.get()
    assert len(dialog.document.pages[0]) == 25000
    assert "Final page" in dialog.document.body
    root.update()


def test_dependency_setup_help_does_not_execute_installation(screen, monkeypatch):
    _, dialog, _, _ = screen
    messages = []
    monkeypatch.setattr("fieldforge.ui.pdf_import.messagebox.showinfo", lambda *args, **kwargs: messages.append(args))
    dialog.setup_help()
    assert 'pip install ".[pdf]"' in messages[0][1]
    assert "No installation is performed" in messages[0][1]


def test_invalid_metadata_leaves_extracted_text_for_correction(screen, tmp_path):
    root, dialog, library, _ = screen
    load(root, dialog, tmp_path)
    dialog.fields["source_url"].set("file:///not-allowed")
    dialog.acknowledged.set(True)
    dialog.import_document()
    assert dialog.document is not None and not dialog._busy
    assert "Check article details" in dialog.status.get()
    assert library.count() == 0


def test_existing_text_import_still_uses_original_path_and_validation(screen, tmp_path):
    root, pdf_dialog, library, _ = screen
    from fieldforge.ui.documents import TextImportDialog

    pdf_dialog.close()
    dialog = TextImportDialog(root, library)
    try:
        path = tmp_path / "notes.txt"
        path.write_bytes(b"Exact text\r\n\r\n")
        dialog.load_path(str(path))
        wait(root, dialog)
        assert dialog.document.body == "Exact text\r\n\r\n"
        dialog.acknowledged.set(True)
        dialog.import_document()
        wait(root, dialog)
        assert dialog._disposed and library.count() == 1
        slug = "local-" + hashlib.sha256(b"Exact text\r\n\r\n").hexdigest()
        assert library.get(slug).body == "Exact text\r\n\r\n"
    finally:
        if not dialog._disposed:
            dialog.destroy()
        dialog._worker.shutdown(wait=True)


def test_minimum_size_keeps_limit_privacy_confirmation_visible(screen, tmp_path):
    root, dialog, _, _ = screen
    load(root, dialog, tmp_path)
    dialog.geometry("860x780")
    root.update()
    for widget in (dialog.import_notice, dialog.import_button, dialog.consent, dialog.close_button):
        assert widget.winfo_rooty() + widget.winfo_height() <= dialog.winfo_rooty() + dialog.winfo_height()
    assert dialog.preview.winfo_height() > 80
