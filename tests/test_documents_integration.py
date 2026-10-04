"""Full-checkout checks: actual reader, source retrieval, pack export and recovery."""

import gc
import json
import time

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.documents import TextDocument, commit_document, prepare_article


def specimen():
    return prepare_article(TextDocument("ledger.md", b"# Cedarledger\r\n\r\nRecord tool location and date.\r\n"),
                           title="Cedarledger equipment record", category="tools", source_publisher="Test owner")


def test_import_is_immediately_searchable_by_ask_library(tmp_path):
    from fieldforge.app import FieldForgeApp
    from fieldforge.knowledge.assistant import ReferenceAssistant

    app = FieldForgeApp(tmp_path / "app.db")
    article = specimen()
    commit_document(app.knowledge, article, acknowledged=True)
    result = ReferenceAssistant(app.db.path).ask("cedarledger location")
    assert result.references[0].article == article
    ref = result.references[0]
    assert ref.excerpt == article.body[ref.start:ref.end]
    assert app.knowledge.search("cedarledger")[0].slug == article.slug


def test_article_packs_include_imported_body_but_not_private_notes(tmp_path):
    from fieldforge.knowledge.packs import export_pack, import_pack

    library = KnowledgeLibrary(tmp_path / "library.db")
    article = specimen()
    commit_document(library, article, acknowledged=True)
    library.annotate(article.slug, bookmarked=True, note="PRIVATE_NOTE_SENTINEL")
    pack = export_pack(library, tmp_path / "public-pack.json")
    payload = json.loads(pack.read_text(encoding="utf-8"))
    assert payload["data"]["articles"][0]["body"] == article.body
    assert "PRIVATE_NOTE_SENTINEL" not in pack.read_text(encoding="utf-8")
    target = KnowledgeLibrary(tmp_path / "other.db")
    import_pack(target, pack)
    assert target.get(article.slug) == article


def test_snapshot_restores_imported_text_provenance_and_annotations(tmp_path):
    from fieldforge.core.snapshot import export_snapshot, restore_snapshot

    library = KnowledgeLibrary(tmp_path / "library.db")
    article = specimen()
    commit_document(library, article, acknowledged=True)
    library.annotate(article.slug, bookmarked=True, note="Private record")
    pack = export_snapshot(library.database_path, tmp_path / "backup.ffbackup")
    target_path = tmp_path / "restored.db"
    restore_snapshot(pack, target_path)
    target = KnowledgeLibrary(target_path)
    assert target.get(article.slug) == article
    assert target.annotation(article.slug) == {"bookmarked": True, "note": "Private record"}


@pytest.fixture
def full_reader(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.documents import TextImportDialog
    from fieldforge.ui.knowledge import KnowledgeTab

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; dedicated text-import-gui CI job uses Xvfb")
    root.geometry("1240x840")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("fieldforge.ui.knowledge.messagebox.showerror", lambda *args, **kwargs: errors.append(args))
    library = KnowledgeLibrary(tmp_path / "ui.db")
    frame = KnowledgeTab(root, library)
    frame.pack(fill="both", expand=True)
    root.update()
    windows = []
    try:
        yield root, frame, library, windows
    finally:
        # Keep worker references so they can be joined after normal widget cleanup.
        windows.extend(child for child in frame.winfo_children() if isinstance(child, TextImportDialog))
        for window in windows:
            if not window._disposed:
                window.destroy()
            window._worker.shutdown(wait=True, cancel_futures=True)
        frame._worker.shutdown(wait=True, cancel_futures=True)
        root.destroy()
        gc.collect()
    assert not errors


def wait(root, window):
    deadline = time.monotonic() + 5
    while window._busy and not window._disposed and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    root.update()
    assert not window._busy or window._disposed


def test_actual_library_button_saves_notes_opens_preview_and_refreshes(full_reader, tmp_path, monkeypatch):
    root, frame, library, windows = full_reader
    from fieldforge.ui.documents import TextImportDialog

    library.upsert(KnowledgeArticle("existing", "Existing record", "Previous text.", "records"))
    frame.refresh()
    frame.results.selection_set("existing")
    root.update()
    frame.note.insert("1.0", "Unsaved article note")
    frame.query.set("a-filter-that-hides-new-documents")
    frame.text_import_button.invoke()
    root.update()
    window = next(child for child in frame.winfo_children() if isinstance(child, TextImportDialog))
    windows.append(window)
    assert frame.busy and not frame.save_current()
    assert library.annotation("existing")["note"] == "Unsaved article note"
    path = tmp_path / "new_ledger.txt"
    path.write_text("Cedarledger with tool locations.", encoding="utf-8")
    monkeypatch.setattr("fieldforge.ui.documents.filedialog.askopenfilename", lambda **kwargs: str(path))
    window.choose_button.invoke()
    wait(root, window)
    slug = window.document.suggested_id
    window.acknowledged.set(True)
    window._update_buttons()
    window.import_button.invoke()
    wait(root, window)
    assert not frame.busy and not frame.query.get()
    assert frame.results.exists(slug)
    assert frame.results.selection() == (slug,)
    assert frame.slug == slug
    assert "Cedarledger" in frame.body.get("1.0", "end")
    assert library.annotation("existing")["note"] == "Unsaved article note"


def test_cancel_releases_existing_close_guard_without_mutating_library(full_reader):
    root, frame, library, windows = full_reader
    from fieldforge.ui.documents import open_document_import

    window = open_document_import(frame)
    windows.append(window)
    assert frame.busy and not frame.save_current()
    window.close()
    root.update()
    assert not frame.busy and frame.save_current()
    assert library.count() == 0


def test_busy_or_failed_note_save_never_opens_an_import_dialog(full_reader, monkeypatch):
    _, frame, _, _ = full_reader
    from fieldforge.ui.documents import open_document_import

    frame.busy = True
    assert open_document_import(frame) is None
    frame.busy = False
    monkeypatch.setattr(frame, "save_current", lambda: False)
    assert open_document_import(frame) is None
    assert not frame.busy


def test_existing_library_controls_visible_after_import_toolbar_added(full_reader):
    root, frame, _, _ = full_reader
    root.geometry("1150x820")
    root.update()
    button = frame.text_import_button
    assert button.winfo_rooty() + button.winfo_height() < frame.winfo_rooty() + frame.winfo_height()
    assert frame.previous.winfo_rooty() + frame.previous.winfo_height() <= frame.winfo_rooty() + frame.winfo_height()
