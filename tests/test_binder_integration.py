"""Full-checkout integration with existing article import and notebook save guards."""

import gc
import time
from dataclasses import replace

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.binder import capture_binder, render_binder


def test_real_starter_articles_keep_full_bodies_and_source_metadata(tmp_path):
    from fieldforge.app import FieldForgeApp
    from fieldforge.knowledge.starter import install_starter

    app = FieldForgeApp(tmp_path / "app.db")
    install_starter(app.knowledge)
    slugs = ("starter-v1-inventory", "starter-v1-measurement", "starter-v1-teaching")
    binder = capture_binder(app.db.path, slugs=slugs)
    for entry, slug in zip(binder.entries, slugs):
        assert entry.article == app.knowledge.get(slug)
        assert entry.article.reviewed_on == ""
        assert entry.article.license
    assert len(binder.entries) == 3 and app.knowledge.count() == 12
    assert b"not independently" in render_binder(binder)


def test_document_import_and_private_notes_keep_separate_export_consent(tmp_path):
    from fieldforge.knowledge.documents import TextDocument, commit_document, prepare_article

    library = KnowledgeLibrary(tmp_path / "app.db")
    article = prepare_article(TextDocument("local.md", b"Full document\r\n\r\nEnd conditions\n"),
                              title="Local reference", category="reference")
    commit_document(library, article, acknowledged=True)
    library.annotate(article.slug, bookmarked=True, note="PRIVATE_NOTE")
    captured = capture_binder(library.database_path, bookmarks=True)
    assert captured.entries[0].article == article
    assert b"PRIVATE_NOTE" not in render_binder(captured)
    assert b"PRIVATE_NOTE" in render_binder(capture_binder(library.database_path, bookmarks=True, include_notes=True))


@pytest.fixture
def reader(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.knowledge import KnowledgeTab

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; dedicated GUI CI supplies a display")
    root.geometry("1150x820")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("fieldforge.ui.binder.messagebox.askyesno", lambda *args, **kwargs: True)
    library = KnowledgeLibrary(tmp_path / "library.db")
    library.upsert(KnowledgeArticle("article", "Complete local source", "Do not omit this text.", "tools"))
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


def wait(root, dialog):
    deadline = time.monotonic() + 5
    while dialog.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    root.update()
    assert not dialog.busy


def test_actual_library_button_saves_note_and_holds_existing_close_guard(reader, tmp_path, monkeypatch):
    root, panel, library, dialogs = reader
    from fieldforge.ui.binder import BinderDialog

    panel.results.selection_set("article")
    root.update()
    panel.note.insert("1.0", "Previously unsaved note")
    panel.bookmark.set(True)
    panel.personal.set(True)  # Pack setting must NOT silently opt a binder into private notes.
    panel.binder_button.invoke()
    root.update()
    dialog = next(child for child in panel.winfo_children() if isinstance(child, BinderDialog))
    dialogs.append(dialog)
    assert panel.busy and not panel.save_current()
    assert library.annotation("article")["note"] == "Previously unsaved note"
    assert not dialog.notes.get()
    dialog.build()
    wait(root, dialog)
    assert dialog.binder.entries[0].article == library.get("article")
    target = tmp_path / "packet.html"
    monkeypatch.setattr("fieldforge.ui.binder.filedialog.asksaveasfilename", lambda **kwargs: str(target))
    dialog.permission.set(True)
    dialog.save()
    wait(root, dialog)
    assert "Previously unsaved note" not in target.read_text(encoding="utf-8")
    dialog.close()
    root.update()
    assert not panel.busy and panel.save_current()
    assert library.annotation("article")["note"] == "Previously unsaved note"


def test_failed_note_save_or_busy_import_prevents_binder_open(reader, monkeypatch):
    _, panel, _, _ = reader
    from fieldforge.ui.binder import open_binder

    panel.busy = True
    assert open_binder(panel) is None
    panel.busy = False
    monkeypatch.setattr(panel, "save_current", lambda: False)
    assert open_binder(panel) is None and not panel.busy


def test_open_without_selected_article_defaults_to_bookmarks(reader):
    root, panel, library, dialogs = reader
    from fieldforge.ui.binder import open_binder

    library.annotate("article", bookmarked=True, note="")
    dialog = open_binder(panel)
    dialogs.append(dialog)
    assert dialog.mode.get() == "bookmarks"
    dialog.build()
    wait(root, dialog)
    assert len(dialog.binder.entries) == 1
    old = dialog.binder.entries[0].article
    library.upsert(replace(old, body="Changed later"))
    assert dialog.binder.entries[0].article == old


def test_new_button_visible_in_existing_library_layout(reader):
    root, panel, _, _ = reader
    root.update()
    button = panel.binder_button
    assert button.winfo_width() > 1
    assert button.winfo_rooty() + button.winfo_height() <= panel.winfo_rooty() + panel.winfo_height()
