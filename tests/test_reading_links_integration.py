"""Full-checkout integration: imports, backups, private exports and desktop guards."""

import gc

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.pathways import LearningCatalog, LearningGoal, PathwayStore


def link(store, goal, slug):
    version = store.reading_links.preview(slug).version
    return store.reading_links.link(goal, slug, expected_version=version)


def test_imported_text_and_pdf_derived_articles_can_be_linked_without_rewriting_them(tmp_path):
    from fieldforge.knowledge.documents import TextDocument, commit_document, prepare_article
    from fieldforge.knowledge.pdf_import import PDFTextDocument, prepare_pdf_article

    library = KnowledgeLibrary(tmp_path / "library.db")
    text = prepare_article(TextDocument("practice.md", b"Original exercise\r\n\r\n"), title="Text practice", category="math")
    pdf = prepare_pdf_article(PDFTextDocument("practice.pdf", "a"*64, 100, ("PDF page text", ""), "6.19.0"),
                              title="PDF extraction fixture", category="math")
    store = PathwayStore(library)
    for article in (text, pdf):
        commit_document(library, article, acknowledged=True)
        linked = link(store, "measurement", article.slug)
        assert store.reading_links.open_link(linked.id, expected_revision=1) == article
        assert library.get(article.slug) == article
    assert "NOT A COMPLETE COPY" in pdf.body
    assert store.progress("measurement").status == "not_started"


def test_complete_snapshot_preserves_reading_links_and_independent_notes(tmp_path):
    from fieldforge.core.recovery import create_verified_backup, restore_verified_copy

    library = KnowledgeLibrary(tmp_path / "library.db")
    library.upsert(KnowledgeArticle("practice", "Practice", "Local text.", "math"))
    library.annotate("practice", bookmarked=True, note="Private article note")
    store = PathwayStore(library)
    linked = link(store, "measurement", "practice")
    progress = store.save("measurement", status="exploring", note="Private learning note", expected_revision=0)
    snapshot = create_verified_backup(library.database_path, tmp_path / "all.ffbackup")
    target = restore_verified_copy(snapshot, tmp_path / "restored.db", active_database=library.database_path)
    restored = PathwayStore(KnowledgeLibrary(target))
    assert restored.reading_links.list("measurement") == (linked,)
    assert restored.progress("measurement") == progress
    assert restored.library.annotation("practice")["note"] == "Private article note"
    assert restored.reading_links.open_link(linked.id, expected_revision=1).body == "Local text."


def test_article_packs_and_field_binders_do_not_export_personal_reading_associations(tmp_path):
    from fieldforge.knowledge.binder import capture_binder, render_binder
    from fieldforge.knowledge.packs import export_pack, import_pack

    library = KnowledgeLibrary(tmp_path / "library.db")
    library.upsert(KnowledgeArticle("practice", "Practice", "Local text.", "math"))
    goal = LearningGoal("private-plan-sentinel", "Private goal title", 1, "Test", "Objective", "Exercise", "Requirements")
    store = PathwayStore(library, LearningCatalog((goal,)))
    link(store, goal.slug, "practice")
    pack = export_pack(library, tmp_path / "article-pack.json", include_personal=True)
    assert "private-plan-sentinel" not in pack.read_text(encoding="utf-8")
    assert b"private-plan-sentinel" not in render_binder(capture_binder(library.database_path, slugs=("practice",)))
    other = KnowledgeLibrary(tmp_path / "other.db")
    import_pack(other, pack, restore_personal=True)
    assert not PathwayStore(other, store.catalog).reading_links.list(goal.slug)


def test_actual_desktop_link_manager_preserves_close_and_backup_guards(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.app import FieldForgeApp
    from fieldforge.ui import desktop
    from fieldforge.ui.pathways import PathwaysTab
    from fieldforge.ui.recovery import RecoveryTab

    app = FieldForgeApp(tmp_path / "app.db")
    app.knowledge.upsert(KnowledgeArticle("practice", "Practice", "Fictional measurement exercise.", "math"))
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; graphical CI requires a working display")
    monkeypatch.setenv("FIELDFORGE_DB", str(app.db.path))
    monkeypatch.setattr(tk, "Tk", lambda: root)
    errors, done, workers = [], [], []
    root.report_callback_exception = lambda *args: errors.append(args)

    def children(widget):
        yield widget
        for child in widget.winfo_children():
            yield from children(child)

    def exercise():
        root.after_cancel(timer)
        try:
            panel = next(widget for widget in children(root) if isinstance(widget, PathwaysTab))
            recovery = next(widget for widget in children(root) if isinstance(widget, RecoveryTab))
            panel.tree.selection_set("measurement")
            root.update()
            panel.note.insert("1.0", "Preserve this learning note")
            panel.manage_reading()
            root.update()
            assert panel.reading_dialog is not None and not recovery.before_backup()
            root.tk.call(root.protocol("WM_DELETE_WINDOW"))
            assert root.winfo_exists()
            dialog = panel.reading_dialog
            dialog.candidates.selection_set("practice")
            root.update()
            dialog.link_button.invoke()
            root.update()
            dialog.destroy()
            root.update()
            assert panel.reading.get_children() == ("practice",)
            assert panel.store.progress("measurement").note == "Preserve this learning note"
            assert recovery.before_backup()
            done.append(True)
        except Exception as exc:
            errors.append(exc)
        finally:
            workers.extend(widget._worker for widget in children(root) if hasattr(widget, "_worker"))
            root.destroy()

    root.after(200, exercise)
    timer = root.after(7000, root.destroy)
    desktop.run()
    for worker in workers:
        worker.shutdown(wait=True)
    assert done and not errors
    gc.collect()
