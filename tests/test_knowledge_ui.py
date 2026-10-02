import gc
import os
import time
import weakref

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.packs import export_pack, import_pack


@pytest.fixture(scope="module")
def tk_root():
    # Match the application's single Tcl interpreter. Repeated Tk() creation
    # can fail to reload Tcl scripts on Windows even after root.destroy().
    gc.collect()
    if os.environ.get("FIELDFORGE_REQUIRE_GUI") == "1":
        import tkinter as tk
    else:
        tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        if os.environ.get("FIELDFORGE_REQUIRE_GUI") == "1":
            raise
        pytest.skip("Tk display unavailable; use xvfb-run for GUI smoke tests")
    root.withdraw()
    yield root
    root.destroy()
    gc.collect()


@pytest.fixture
def reader(tk_root, tmp_path, monkeypatch):
    import tkinter as tk

    from fieldforge.ui.knowledge import KnowledgeTab

    gc.collect()
    root = tk.Toplevel(tk_root)
    errors = []
    tk_root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("fieldforge.ui.knowledge.messagebox.showerror",
                        lambda title, text, **kwargs: errors.append((title, text)))
    library = KnowledgeLibrary(tmp_path / "ui.db")
    library.upsert(KnowledgeArticle("a", "Article A", "First reference.", "records"))
    library.upsert(KnowledgeArticle("b", "Article B", "Second reference.", "records"))
    frame = KnowledgeTab(root, library)
    frame.pack(fill="both", expand=True)
    root.update()
    yield root, frame, library, errors
    root.destroy()
    assert not errors


def select(root, frame, slug):
    frame.results.selection_set(slug)
    root.update()
    frame._select()


def test_select_search_and_autosave(reader):
    root, frame, library, _errors = reader
    assert len(frame.results.get_children()) == 2
    select(root, frame, "a")
    frame.note.insert("1.0", "My private note")
    frame.bookmark.set(True)
    select(root, frame, "b")
    assert library.annotation("a") == {"bookmarked": True, "note": "My private note"}
    frame.favorites.set(True)
    frame.refresh()
    assert frame.results.get_children() == ("a",)
    frame.query.set("unmatched")
    frame.refresh()
    assert not frame.results.get_children()
    assert frame.slug is None


def test_import_worker_preserves_restored_note(reader, tmp_path):
    root, frame, library, _errors = reader
    other = KnowledgeLibrary(tmp_path / "other.db")
    other.upsert(library.get("a"))
    other.annotate("a", bookmarked=True, note="Restored note")
    pack = export_pack(other, tmp_path / "private.json", include_personal=True)
    select(root, frame, "a")
    frame._start(import_pack, library, pack, restore_personal=True, replace=True)
    deadline = time.monotonic() + 5
    while frame.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert not frame.busy
    assert library.annotation("a")["note"] == "Restored note"
    select(root, frame, "a")
    assert frame.note.get("1.0", "end-1c") == "Restored note"


def test_navigation_preserves_note_whitespace(reader):
    root, frame, library, _errors = reader
    select(root, frame, "a")
    frame.note.insert("1.0", "  note\n\n")
    frame.refresh()
    select(root, frame, "a")
    assert frame.note.get("1.0", "end-1c") == "  note\n\n"
    assert library.annotation("a")["note"] == "  note\n\n"


def wait_for_search(root, window):
    deadline = time.monotonic() + 5
    while window.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    root.update()
    assert not window.busy


def test_evidence_search_opens_full_source_and_saves_note(reader):
    root, frame, library, _errors = reader
    select(root, frame, "b")
    frame.note.insert("1.0", "Unsaved private note")
    frame._evidence()
    window = frame.evidence_window
    window.query.set("How do I find the first reference?")
    window.search()
    wait_for_search(root, window)
    assert window.evidence[0].slug == "a"
    assert "First reference." in window.passage.get("1.0", "end-1c")
    assert "Body SHA-256" in window.passage.get("1.0", "end-1c")
    window.open_selected()
    root.update()
    assert not window.winfo_exists()
    assert frame.evidence_window is None
    assert frame.slug == "a"
    assert library.annotation("b")["note"] == "Unsaved private note"
    highlight = frame.body.tag_ranges("evidence")
    assert frame.body.get(*highlight) == "First reference."


def test_evidence_no_matches_and_validation_failure(reader):
    root, frame, _library, _errors = reader
    frame._evidence()
    window = frame.evidence_window
    window.query.set("unmatchedword")
    window.search()
    wait_for_search(root, window)
    assert not window.results.get_children()
    assert "No matching passages" in window.status.get()
    assert window.open_button.instate(["disabled"])
    window.query.set("x" * 513)
    window.search()
    wait_for_search(root, window)
    assert "Search failed" in window.status.get()
    assert window.search_button.instate(["!disabled"])
    assert window.entry.instate(["!disabled"])
    window.destroy()


def test_evidence_rejects_source_changed_after_search(reader):
    root, frame, library, errors = reader
    frame._evidence()
    window = frame.evidence_window
    window.query.set("first")
    window.search()
    wait_for_search(root, window)
    library.upsert(KnowledgeArticle("a", "Article A", "Updated first reference.", "records"))
    window.open_selected()
    assert window.winfo_exists()
    assert "changed after the search" in errors.pop()[1]
    window.destroy()


def test_close_evidence_window_during_search(reader, monkeypatch):
    import threading

    root, frame, _library, _errors = reader
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def slow_retrieval(*args, **kwargs):
        started.set()
        release.wait(5)
        finished.set()
        return []

    monkeypatch.setattr("fieldforge.ui.evidence.retrieve_evidence", slow_retrieval)
    frame._evidence()
    window = frame.evidence_window
    window.query.set("first")
    window.search()
    assert started.wait(2)
    window.destroy()
    release.set()
    assert finished.wait(2)
    root.update()
    assert window._poll_id is None


def test_destroyed_search_window_releases_tk_objects_on_ui_thread(reader):
    root, frame, _library, _errors = reader
    frame._evidence()
    window = frame.evidence_window
    root.update()
    reference = weakref.ref(window)
    window.destroy()
    assert frame.evidence_window is None
    assert window.query is None
    assert window.status is None
    del window
    assert reference() is None


def test_local_ai_model_selection_draft_and_source_navigation(reader, monkeypatch):
    from fieldforge.knowledge import retrieve_evidence
    from fieldforge.knowledge.assistant import AssistantResult

    root, frame, library, _errors = reader
    received = []
    monkeypatch.setattr("fieldforge.ui.evidence.OllamaClient.list_models",
                        lambda *_args, **_kwargs: ["test:small"])

    def draft(_library, question, model, client, *, cancel):
        received.append((question, model, client.port))
        return AssistantResult(question, model, "First reference. [S1]",
                               tuple(retrieve_evidence(library, question)),
                               ("S1",), ("AI draft: check its sources.",))

    monkeypatch.setattr("fieldforge.ui.evidence.draft_answer", draft)
    frame._evidence()
    window = frame.evidence_window
    window.query.set("first")
    window.draft()
    assert "Load models" in window.status.get()
    window.load_models()
    wait_for_search(root, window)
    assert window.model.get() == "test:small"
    window.draft()
    wait_for_search(root, window)
    assert received == [("first", "test:small", 11434)]
    assert "AI draft: check its sources." in window.answer.get("1.0", "end-1c")
    assert window.pages.select() == str(window.answer_page)
    assert window.results.item("0", "values")[0] == "[S1] Article A"
    window.geometry("660x600")
    window.pages.select(window.sources_page)
    root.update()
    assert window.open_button.winfo_ismapped()
    assert (window.open_button.winfo_rooty() + window.open_button.winfo_height()
            <= window.sources_page.winfo_rooty() + window.sources_page.winfo_height())
    window.open_selected()
    assert frame.slug == "a"
    assert frame.evidence_window is window
    assert window.state() == "withdrawn"
    frame._evidence()
    root.update()
    assert window.state() == "normal"
    assert "First reference. [S1]" in window.answer.get("1.0", "end-1c")


def test_local_ai_errors_leave_search_available_and_clear_old_draft(reader, monkeypatch):
    from fieldforge.knowledge.assistant import LocalModelError

    root, frame, _library, _errors = reader
    frame._evidence()
    window = frame.evidence_window
    window.port.set("bad")
    window.load_models()
    assert "port" in window.status.get()
    window.port.set("11434")

    def unavailable(*_args, **_kwargs):
        raise LocalModelError("Start local Ollama")

    monkeypatch.setattr("fieldforge.ui.evidence.draft_answer", unavailable)
    window.model.set("test")
    window.query.set("first")
    window._answer_text("Old draft must not linger")
    window.draft()
    wait_for_search(root, window)
    assert "Start local Ollama" in window.status.get()
    assert window.answer.get("1.0", "end-1c") == ""
    assert window.draft_button.instate(["!disabled"])
    window.search()
    wait_for_search(root, window)
    assert window.evidence[0].slug == "a"
    assert window.pages.select() == str(window.sources_page)


@pytest.mark.parametrize("close", [False, True])
def test_local_ai_cancel_or_close_signals_worker(reader, monkeypatch, close):
    import threading

    from fieldforge.knowledge.assistant import GenerationCancelled

    root, frame, _library, _errors = reader
    started, finished = threading.Event(), threading.Event()

    def wait_for_cancel(*_args, cancel, **_kwargs):
        started.set()
        assert cancel.wait(3)
        finished.set()
        raise GenerationCancelled("Cancelled. No draft was saved.")

    monkeypatch.setattr("fieldforge.ui.evidence.draft_answer", wait_for_cancel)
    frame._evidence()
    window = frame.evidence_window
    window.model.set("test")
    window.query.set("first")
    window.draft()
    assert started.wait(2)
    if close:
        window.destroy()
        assert frame.evidence_window is None
        assert window._poll_id is None
        assert window.answer is None
    else:
        window.cancel()
        wait_for_search(root, window)
        assert "Cancelled" in window.status.get()
        assert window.cancel_button.instate(["disabled"])
        assert window.draft_button.instate(["!disabled"])
    assert finished.wait(2)
    root.update()


def test_notebook_teardown_can_finish_pending_save_callbacks(reader):
    from tkinter import ttk

    from fieldforge.ui.knowledge import KnowledgeTab

    root, _frame, library, _errors = reader
    notebook = ttk.Notebook(root)
    pane = KnowledgeTab(notebook, library)
    notebook.add(pane, text="Library")
    notebook.bind("<<NotebookTabChanged>>", lambda _event: pane.save_current())
    notebook.pack()
    root.update()
    notebook.destroy()
    root.update()
    assert pane._closed
    assert pane.save_current()


def test_desktop_backup_verify_and_restore_copy(reader, tmp_path, monkeypatch):
    from fieldforge.core.snapshot import inspect_snapshot
    from fieldforge.db.database import FieldForgeDatabase
    from fieldforge.ui.backups import BackupsTab

    root, frame, library, _errors = reader
    FieldForgeDatabase(library.database_path)
    select(root, frame, "a")
    frame.note.insert("1.0", "Saved before backup")
    panel = BackupsTab(root, library.database_path, frame.save_current)
    panel.pack()
    archive = tmp_path / "full.zip"
    monkeypatch.setattr("fieldforge.ui.backups.filedialog.asksaveasfilename",
                        lambda **kwargs: str(archive))
    panel.backup_button.invoke()
    wait_for_search(root, panel)
    assert "Full backup created" in panel.status.get()
    assert library.annotation("a")["note"] == "Saved before backup"
    assert inspect_snapshot(archive)["records"]["knowledge_articles"] == 2
    monkeypatch.setattr("fieldforge.ui.backups.filedialog.askopenfilename",
                        lambda **kwargs: str(archive))
    panel.verify_button.invoke()
    wait_for_search(root, panel)
    assert "Backup verified" in panel.status.get()
    assert "Knowledge articles: 2" in panel.details.get("1.0", "end-1c")
    recovered = tmp_path / "recovered.db"
    monkeypatch.setattr("fieldforge.ui.backups.filedialog.asksaveasfilename",
                        lambda **kwargs: str(recovered))
    panel.restore_button.invoke()
    wait_for_search(root, panel)
    assert "Recovered copy created" in panel.status.get()
    assert KnowledgeLibrary(recovered).annotation("a")["note"] == "Saved before backup"
    assert frame.slug == "a"
    panel.destroy()


def test_empty_desktop_library_installs_offline_references(tk_root, tmp_path):
    import tkinter as tk

    from fieldforge.ui.knowledge import KnowledgeTab

    window = tk.Toplevel(tk_root)
    library = KnowledgeLibrary(tmp_path / "empty.db")
    frame = KnowledgeTab(window, library)
    frame.pack()
    try:
        wait_for_search(window, frame)
        assert library.count() >= 250
        assert len(frame.results.get_children()) == 50
        assert "water-sanitation" in frame.categories["values"]
    finally:
        window.destroy()


@pytest.mark.parametrize("mode", ["engineering", "project", "software"])
def test_blueprint_studios_preview_edit_save_and_open(reader, monkeypatch, tmp_path, mode):
    import json

    from blueprint_fixtures import document

    from fieldforge.blueprints.render import load_blueprint
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    assert set(studio.makers) == {"engineering", "project", "software"}
    maker = studio.makers[mode]
    studio.pages.select(maker)
    try:
        maker.generate()
        assert "Load models" in maker.status.get()
        monkeypatch.setattr("fieldforge.ui.blueprints.OllamaClient.list_models",
                            lambda *args, **kwargs: ["fixture:local"])
        monkeypatch.setattr("fieldforge.ui.blueprints.generate_blueprint",
                            lambda *args, **kwargs: document(mode))
        maker.load_models()
        wait_for_search(root, maker)
        maker.generate()
        wait_for_search(root, maker)
        maker.pages.select(maker.preview)
        root.update()
        assert maker.preview.canvas.find_all()
        assert "SOURCE EVIDENCE" in maker.result.get("1.0", "end-1c")
        value = maker.blueprint["design"]
        value = {**value, "title": "Manually revised design"}
        maker.editor.delete("1.0", "end")
        maker.editor.insert("1.0", json.dumps(value))
        maker.save()
        assert "Apply your design edits" in maker.status.get()
        maker.apply_edits()
        assert maker.blueprint["review"] is None
        assert maker.blueprint["status"] == "needs_revision"
        target = tmp_path / (mode + ".json")
        monkeypatch.setattr("fieldforge.ui.blueprints.filedialog.asksaveasfilename",
                            lambda **kwargs: str(target))
        maker.save()
        assert load_blueprint(target)["design"]["title"] == "Manually revised design"
        assert not maker.has_unsaved_changes()
        monkeypatch.setattr("fieldforge.ui.blueprints.filedialog.askopenfilename",
                            lambda **kwargs: str(target))
        maker.open_saved()
        assert maker.brief.get("1.0", "end-1c") == maker.blueprint["request"]["brief"]
        assert not maker.has_unsaved_changes()
        maker.editor.insert("end", " ")
        monkeypatch.setattr("fieldforge.ui.blueprints.messagebox.askyesno", lambda *a, **kw: False)
        studio.close()
        assert studio.winfo_exists()
    finally:
        studio.destroy()


def test_blueprint_studio_cancel_and_destroy_release_workers(reader, monkeypatch):
    import threading

    from fieldforge.knowledge.assistant import GenerationCancelled
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    started, finished = threading.Event(), threading.Event()

    def blocked(*args, cancel, **kwargs):
        started.set()
        assert cancel.wait(3)
        finished.set()
        raise GenerationCancelled("Blueprint cancelled")

    monkeypatch.setattr("fieldforge.ui.blueprints.generate_blueprint", blocked)
    studio = BlueprintStudio(root, library)
    maker = studio.makers["engineering"]
    maker.model.set("fixture:local")
    maker.generate()
    assert started.wait(2)
    maker._cancel.set()
    wait_for_search(root, maker)
    assert "cancelled" in maker.status.get()
    assert finished.wait(2)
    assert maker.generate_button.instate(["!disabled"])
    started.clear()
    finished.clear()
    maker.generate()
    assert started.wait(2)
    studio.destroy()
    assert finished.wait(2)
    root.update()
    assert maker._poll_id is None
    assert maker.status is None


def test_blueprint_studio_failure_preserves_previous_draft(reader, monkeypatch):
    from blueprint_fixtures import document

    from fieldforge.knowledge.assistant import LocalModelError
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers["project"]
    maker.show_blueprint(document("project"), dirty=False)
    maker.model.set("fixture:local")

    def fail(*args, **kwargs):
        raise LocalModelError("Local model unavailable")

    monkeypatch.setattr("fieldforge.ui.blueprints.generate_blueprint", fail)
    maker.generate()
    wait_for_search(root, maker)
    assert "unavailable" in maker.status.get()
    assert maker.blueprint["design"]["title"] == "Example design"
    studio.destroy()


def test_desktop_backup_failures_restore_controls_and_preserve_data(reader, tmp_path, monkeypatch):
    from fieldforge.core.snapshot import export_snapshot
    from fieldforge.db.database import FieldForgeDatabase
    from fieldforge.ui.backups import BackupsTab

    root, frame, library, _errors = reader
    FieldForgeDatabase(library.database_path)
    archive = export_snapshot(library.database_path, tmp_path / "full.zip")
    panel = BackupsTab(root, library.database_path, frame.save_current)
    panel.pack()
    monkeypatch.setattr("fieldforge.ui.backups.filedialog.askopenfilename",
                        lambda **kwargs: str(archive))
    monkeypatch.setattr("fieldforge.ui.backups.filedialog.asksaveasfilename",
                        lambda **kwargs: str(library.database_path))
    panel.restore_button.invoke()
    wait_for_search(root, panel)
    assert "Operation failed" in panel.status.get()
    assert "live database" in panel.details.get("1.0", "end-1c")
    assert panel.restore_button.instate(["!disabled"])
    assert library.count() == 2
    panel.prepare = lambda: False
    panel.backup_button.invoke()
    assert not panel.busy
    assert "save your note" in panel.status.get()
    panel.destroy()
