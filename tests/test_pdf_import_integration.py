"""Full-checkout integration, including the real Library button and recovery engine."""

import gc
import time

import pytest
from pdf_fixture import pdf_bytes

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.documents import commit_document
from fieldforge.knowledge.pdf_import import prepare_pdf_article, read_pdf_document


@pytest.fixture
def imported(tmp_path):
    pytest.importorskip("pypdf")
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(pdf_bytes(("Cedarledger tools location", None, "Last page conditions")))
    document = read_pdf_document(pdf)
    article = prepare_pdf_article(document, title="Cedarledger PDF reference", category="tools")
    library = KnowledgeLibrary(tmp_path / "library.db")
    commit_document(library, article, acknowledged=True)
    return library, article


def test_real_ask_library_retrieves_pdf_text_with_source_warning_preserved(imported):
    from fieldforge.knowledge.assistant import ReferenceAssistant

    library, article = imported
    report = ReferenceAssistant(library.database_path).ask("cedarledger")
    assert report.references[0].article == article
    assert "Original PDF SHA-256" in report.references[0].article.body
    assert "NOT A COMPLETE COPY" in report.references[0].article.body
    assert "Cedarledger tools location" in report.references[0].excerpt


def test_json_pack_roundtrip_keeps_pdf_page_markers_and_hash(imported, tmp_path):
    from fieldforge.knowledge.packs import export_pack, import_pack

    library, article = imported
    library.annotate(article.slug, bookmarked=True, note="PRIVATE PDF note")
    pack = export_pack(library, tmp_path / "export.json")
    other = KnowledgeLibrary(tmp_path / "other.db")
    import_pack(other, pack)
    assert other.get(article.slug) == article
    assert "PDF PAGE 2 OF 3" in other.get(article.slug).body
    assert "PRIVATE PDF note" not in pack.read_text(encoding="utf-8")


def test_snapshot_keeps_pdf_text_and_private_annotation(imported, tmp_path):
    from fieldforge.core.recovery import create_verified_backup, restore_verified_copy

    library, article = imported
    library.annotate(article.slug, bookmarked=True, note="Private PDF notes\n\n")
    preview = create_verified_backup(library.database_path, tmp_path / "backup.ffbackup")
    target = restore_verified_copy(preview, tmp_path / "restored.db", active_database=library.database_path)
    other = KnowledgeLibrary(target)
    assert other.get(article.slug) == article
    assert other.annotation(article.slug)["note"] == "Private PDF notes\n\n"


def test_real_library_toolbar_opens_pdf_dialog_and_refreshes_after_import(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.knowledge import KnowledgeTab
    from fieldforge.ui.pdf_import import PDFImportDialog

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; PDF integration CI requires a working display")
    root.geometry("1240x900")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("fieldforge.ui.pdf_import.messagebox.askyesno", lambda *args, **kwargs: True)
    library = KnowledgeLibrary(tmp_path / "app.db")
    library.upsert(KnowledgeArticle("mine", "My article", "Unrelated content", "records"))
    panel = KnowledgeTab(root, library)
    panel.pack(fill="both", expand=True)
    dialog = None
    try:
        root.update()
        panel.results.selection_set("mine")
        root.update()
        panel.note.insert("1.0", "Unsaved private note")
        panel.query.set("hidden-by-filter")
        panel.pdf_import_button.invoke()
        root.update()
        dialog = next(child for child in panel.winfo_children() if isinstance(child, PDFImportDialog))
        assert panel.busy and not panel.save_current()
        assert library.annotation("mine")["note"] == "Unsaved private note"
        source = tmp_path / "sample.pdf"
        source.write_bytes(pdf_bytes(("Cedarledger equipment location", "End conditions")))
        monkeypatch.setattr("fieldforge.ui.pdf_import.filedialog.askopenfilename", lambda **kwargs: str(source))
        dialog.choose_button.invoke()
        deadline = time.monotonic() + 10
        while dialog._busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert not dialog._busy and dialog.document is not None, dialog.status.get()
        slug = dialog.document.suggested_id
        dialog.acknowledged.set(True)
        dialog.import_document()
        while not dialog._disposed and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        root.update()
        assert dialog._disposed and not panel.busy
        assert panel.query.get() == "" and panel.results.exists(slug)
        assert panel.slug == slug and "PDF PAGE 1 OF 2" in panel.body.get("1.0", "end")
        assert library.annotation("mine")["note"] == "Unsaved private note"
        assert not errors
    finally:
        if dialog is not None:
            if not dialog._disposed:
                dialog.destroy()
            dialog._worker.shutdown(wait=True, cancel_futures=True)
        root.destroy()
        panel._worker.shutdown(wait=True, cancel_futures=True)
        gc.collect()
