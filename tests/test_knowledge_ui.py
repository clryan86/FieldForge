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
    from fieldforge.knowledge.local_model import AssistantResult

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
    from fieldforge.knowledge.local_model import LocalModelError

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

    from fieldforge.knowledge.local_model import GenerationCancelled

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
    from fieldforge.core.database_archive import inspect_snapshot
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
    frame = KnowledgeTab(window, library, install_bundled=True)
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


def test_engineering_preview_detail_sheets_zoom_pan_and_colour(reader):
    from blueprint_fixtures import document

    from fieldforge.ui.blueprint_preview import DrawingPreview

    root, frame, _library, _errors = reader
    frame.pack_forget()
    root.geometry("760x650")
    preview = DrawingPreview(root)
    preview.pack(fill="both", expand=True)
    root.update()
    try:
        preview.show(document("engineering"))
        assert "part-001.svg" in preview.choices.cget("values")
        for name in preview.images:
            preview.selection.set(name)
            preview.redraw()
            assert preview.canvas.find_all()
        preview.selection.set("isometric.svg")
        preview.redraw()
        assert sum(preview.canvas.type(item) == "polygon" for item in preview.canvas.find_all()) == 6
        preview.selection.set("part-001.svg")
        preview.zoom.set("200%")
        preview.redraw()
        root.update()
        assert tuple(map(float, preview.canvas.cget("scrollregion").split())) == (0, 0, 2200, 1560)
        labels = [item for item in preview.canvas.find_all() if preview.canvas.type(item) == "text"]
        dimension = next(item for item in labels if preview.canvas.itemcget(item, "text") == "X: 1000 mm")
        assert preview.canvas.itemcget(dimension, "anchor") == "s"
        assert preview.canvas.cget("background") == "#ffffff"
        preview.canvas.xview_moveto(0.5)
        preview.canvas.yview_moveto(0.5)
        assert preview.canvas.xview()[0] > 0 and preview.canvas.yview()[0] > 0
        preview.reset_view()
        assert preview.canvas.xview()[0] == 0 and preview.canvas.yview()[0] == 0
        preview.zoom.set("Fit width")
        preview.redraw()
        assert float(preview.canvas.cget("scrollregion").split()[2]) <= preview.canvas.winfo_width()
        preview.show(document("software"))
        assert preview.canvas.cget("background") == "#102239"
    finally:
        preview.destroy()


def test_geometry_inspector_filters_highlights_and_recomputes_after_edit(reader):
    import copy

    from test_blueprint_geometry import pair

    from fieldforge.blueprints.engine import digest
    from fieldforge.ui.blueprint_preview import DrawingPreview

    root, frame, _library, _errors = reader
    frame.pack_forget()
    root.geometry("760x650")
    preview = DrawingPreview(root)
    preview.pack(fill="both", expand=True)
    root.update()
    value = pair()
    before = copy.deepcopy(value)
    try:
        preview.show(value)
        preview.pages.select(preview.inspector)
        root.update()
        inspector = preview.inspector
        assert inspector.analysis["summary"]["overlap_pairs"] == 1
        assert len(inspector.rows.get_children()) == 1
        inspector.filter.set("separated")
        inspector.refresh()
        assert not inspector.rows.get_children()
        inspector.filter.set("overlap")
        inspector.refresh()
        inspector.rows.selection_set("0")
        inspector.selected()
        assert "Overlap XYZ (mm): 5 / 5 / 5" in inspector.details.get("1.0", "end")
        assert inspector.show_button.instate(["!disabled"])
        inspector.highlight()
        root.update()
        assert preview.pages.select() == str(preview.sheet)
        assert preview.selection.get() == "isometric.svg"
        assert preview.highlighted == {"P1", "P2"}
        polygons = [item for item in preview.canvas.find_all() if preview.canvas.type(item) == "polygon"]
        assert len(polygons) == 12
        assert all(preview.canvas.itemcget(item, "outline") == "#b04400" for item in polygons)
        assert value == before
        value["design"]["parts"][1]["position_mm"] = [15, 0, 0]
        value["design_sha256"] = digest(value["design"])
        preview.show(value)
        assert not preview.highlighted
        assert inspector.analysis["summary"]["connected_groups"] == 2
        inspector.rows.selection_set("0")
        inspector.selected()
        assert "Gap XYZ (mm): 5 / 0 / 0" in inspector.details.get("1.0", "end")
        value["design"]["parts"][1]["size_mm"] = [0, 1, 1]
        preview.show(value)
        assert "unresolved" in inspector.summary.get()
        assert not inspector.rows.get_children()
        assert inspector.show_button.instate(["disabled"])
    finally:
        preview.destroy()


def test_clearance_limit_from_inspector_requires_user_value_and_survives_apply(reader):
    import copy

    from test_blueprint_geometry import pair

    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    studio.geometry("760x650")
    maker = studio.makers["engineering"]
    studio.pages.select(maker)
    try:
        maker.show_blueprint(pair((13, 14, 0)), dirty=False)
        before = copy.deepcopy(maker.blueprint)
        maker.pages.select(maker.preview)
        inspector = maker.preview.inspector
        maker.preview.pages.select(inspector)
        inspector.rows.selection_set("0")
        inspector.selected()
        assert "Shortest clearance (mm): 5" in inspector.details.get("1.0", "end")
        inspector.prepare_limit()
        root.update()
        form = maker.acceptance
        assert maker.requirement_pages.select() == str(form)
        assert form.target.get() == "P1" and form.second_target.get() == "P2"
        assert form.metric.get() == "Pair clearance" and form.operator.get() == ">="
        assert form.value.get() == "" and not form.rules
        assert not maker.has_unsaved_changes() and maker.blueprint == before
        assert set(form.second_entry.cget("values")) == {"P1", "P2"}
        assert form.second_entry.winfo_ismapped()
        assert form.details.winfo_rooty() + form.details.winfo_height() <= maker.winfo_rooty() + maker.winfo_height()
        form.add()
        assert not form.rules and "not added" in maker.status.get()
        form.value.set("6")
        form.add()
        assert form.rules[0]["target"] == "P1/P2" and form.rules[0]["value"] == 6
        assert maker.has_unsaved_changes()
        maker.apply_limits()
        assert maker.blueprint["validation"]["acceptance"][0]["status"] == "failed"
        assert maker.blueprint["validation"]["acceptance"][0]["actual"] == "5"
        form.metric.set("Pair relation")
        form._metric_changed()
        assert form.value_entry.instate(["readonly"]) and form.operator.get() == "="
        form.value.set("separated")
        form.add()
        maker.apply_limits()
        assert maker.blueprint["request"]["acceptance_rules"][1]["value"] == "separated"
        assert maker.blueprint["validation"]["acceptance"][1]["status"] == "passed"
        maker._input_state("disabled")
        assert form.target_entry.instate(["disabled"]) and form.second_entry.instate(["disabled"])
        assert form.value_entry.instate(["disabled"])
        maker._input_state("normal")
        assert form.value_entry.instate(["readonly"])
        form.metric.set("Overall X span")
        form._metric_changed()
        root.update()
        assert not form.second_entry.winfo_ismapped() and form.second_target.get() == ""
    finally:
        studio.destroy()


def test_blueprint_studio_cancel_and_destroy_release_workers(reader, monkeypatch):
    import threading

    from fieldforge.knowledge.local_model import GenerationCancelled
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

    from fieldforge.knowledge.local_model import LocalModelError
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


@pytest.mark.parametrize("mode", ["engineering", "project", "software"])
def test_blueprint_project_refine_compare_edit_restore_and_reopen(reader, monkeypatch, tmp_path, mode):
    import copy
    import json

    from blueprint_fixtures import document

    from fieldforge.blueprints.engine import digest
    from fieldforge.blueprints.projects import load_project
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers[mode]
    studio.pages.select(maker)
    path = tmp_path / (mode + ".ffproject.json")
    monkeypatch.setattr("fieldforge.ui.blueprint_history.filedialog.asksaveasfilename",
                        lambda **kwargs: str(path))
    monkeypatch.setattr("fieldforge.ui.blueprint_history.filedialog.askopenfilename",
                        lambda **kwargs: str(path))
    calls = []

    def refine(_library, request, model, client, **kwargs):
        from blueprint_fixtures import revision

        calls.append((request, kwargs))
        value = revision(kwargs["previous"], request, kwargs["instructions"])
        value["design"]["title"] = "Refined design"
        value["design_sha256"] = digest(value["design"])
        return value

    monkeypatch.setattr("fieldforge.ui.blueprints.generate_blueprint", refine)
    try:
        maker.show_blueprint(document(mode))
        maker.load_request(maker.blueprint)
        maker.history.create()
        assert len(load_project(path)["revisions"]) == 1
        maker.model.set("fixture:local")
        maker.instructions.insert("1.0", "Revise the title and preserve the requirements.")
        maker.refine()
        wait_for_search(root, maker)
        assert calls[0][1]["previous"]["design"]["title"] == "Example design"
        assert len(load_project(path)["revisions"]) == 1
        assert maker.blueprint["design"]["title"] == "Example design"
        review = maker.revision_review
        assert "Refined design" in review.changes.get("1.0", "end-1c")
        review.geometry("760x650")
        root.update()
        assert review.changes.winfo_height() > 200
        assert review.apply_button.winfo_rootx() + review.apply_button.winfo_width() < review.winfo_rootx() + review.winfo_width()
        review.pages.select(review.preview)
        root.update()
        assert review.preview.canvas.find_all() and review.original.images
        assert "SOURCE EVIDENCE" in review.details.get("1.0", "end-1c")
        review.apply()
        assert maker.revision_review is None
        assert len(load_project(path)["revisions"]) == 2
        assert "Refined design" in maker.history.changes.get("1.0", "end-1c")
        assert not maker.has_unsaved_changes()
        value = copy.deepcopy(maker.blueprint["design"])
        value["title"] = "Manual revision"
        maker.editor.delete("1.0", "end")
        maker.editor.insert("1.0", json.dumps(value))
        maker.apply_edits()
        assert len(load_project(path)["revisions"]) == 3
        assert maker.blueprint["review"] is None
        maker.history.rows.selection_set("1")
        maker.history.restore()
        assert maker.blueprint["design"]["title"] == "Example design"
        assert len(load_project(path)["revisions"]) == 4
        maker.history.open()
        assert len(maker.history.rows.get_children()) == 4
        maker.pages.select(maker.history)
        studio.geometry("760x650")
        root.update()
        assert maker.history.changes.winfo_ismapped()
        maker.history.rows.selection_set("2")
        maker.history.compare_selected()
        assert "Refined design" in maker.history.changes.get("1.0", "end-1c")
        assert not maker.has_unsaved_changes()
    finally:
        studio.destroy()


def test_part_editor_previews_units_and_regressions_then_records_one_draft_revision(reader, tmp_path):
    import copy

    from test_blueprint_clearance import limit
    from test_blueprint_geometry import pair

    from fieldforge.blueprints.projects import create_project, load_project
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers["engineering"]
    value = pair((15, 0, 0))
    value["request"]["acceptance_rules"] = [limit()]
    path = tmp_path / "parts.ffproject.json"
    project = create_project(path, "Part edits", value)
    disk_before = path.read_bytes()
    try:
        maker.show_blueprint(value, dirty=False)
        maker.load_request(maker.blueprint)
        maker.history.project, maker.history.path = project, path
        baseline = copy.deepcopy(maker.blueprint)
        maker.edit_part()
        editor = maker.part_editor
        assert editor is not None
        editor.geometry("760x650")
        editor.part.set("P2")
        editor._select_part()
        editor.positions[0].set("1.2 cm")
        editor.sizes[2].set(".5 in")
        editor.preview_changes()
        root.update()
        assert "regressed" in editor.changes.get("1.0", "end")
        assert editor.preview.highlighted == {"P2"}
        assert editor.candidate["blueprint"]["design"]["parts"][1]["size_mm"][2] == 12.7
        assert editor.apply_button.winfo_ismapped() and editor.changes.winfo_height() > 100
        assert editor.apply_button.winfo_rootx() + editor.apply_button.winfo_width() <= editor.winfo_rootx() + editor.winfo_width()
        assert maker.blueprint == baseline and path.read_bytes() == disk_before and not maker.has_unsaved_changes()
        # Choosing a new part cannot silently discard the unapplied candidate.
        editor.part.set("P1")
        editor._select_part()
        assert editor.part.get() == "P2" and editor.candidate is not None
        editor.apply()
        root.update()
        assert maker.part_editor is None and not maker.has_unsaved_changes()
        assert maker.blueprint["request"]["acceptance_rules"] == [limit()]
        assert maker.blueprint["design"]["parts"][1]["position_mm"] == [12, 0, 0]
        assert maker.blueprint["review"] is None and maker.blueprint["status"] == "needs_revision"
        saved = load_project(path)
        assert len(saved["revisions"]) == 2 and saved["revisions"][1]["kind"] == "edited"
        assert saved["revisions"][0] == project["revisions"][0]
        maker.history.undo()
        assert maker.blueprint["design"]["parts"][1]["position_mm"] == [15, 0, 0]
        assert len(load_project(path)["revisions"]) == 3
    finally:
        studio.destroy()


def test_part_editor_blocks_busy_pending_stale_and_unpreviewed_edits_and_can_cancel(reader, monkeypatch):
    import copy

    from test_blueprint_geometry import pair

    from fieldforge.blueprints.engine import digest
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers["engineering"]
    value = pair()
    try:
        maker.show_blueprint(value, dirty=False)
        maker.busy = True
        maker.edit_part()
        maker.busy = False
        assert maker.part_editor is None
        maker.editor.insert("end", "pending")
        maker.edit_part()
        assert maker.part_editor is None
        maker.show_blueprint(value, dirty=False)
        original = copy.deepcopy(maker.blueprint)
        maker.edit_part()
        editor = maker.part_editor
        editor.sizes[0].set("1 ft")
        editor.preview_changes()
        assert editor.candidate is not None
        editor.sizes[0].set("2 ft")
        assert editor.candidate is None and str(editor.apply_button["state"]) == "disabled"
        editor.apply()
        assert maker.blueprint == original and "Preview" in editor.status.get()
        editor.preview_changes()
        maker.editor.insert("end", "pending")
        editor.apply()
        assert maker.blueprint == original
        maker.show_blueprint(value, dirty=False)
        # Even an externally applied change to another part invalidates the captured baseline.
        changed = copy.deepcopy(value)
        changed["design"]["parts"][1]["position_mm"][0] = 20
        changed["design_sha256"] = digest(changed["design"])
        maker.show_blueprint(changed)
        editor.apply()
        assert "Close and reopen" in editor.status.get()
        assert maker.blueprint["design"] == changed["design"]
        monkeypatch.setattr("fieldforge.ui.blueprint_parameters.messagebox.askyesno", lambda *_a, **_k: False)
        editor.close()
        assert maker.part_editor is editor
        monkeypatch.setattr("fieldforge.ui.blueprint_parameters.messagebox.askyesno", lambda *_a, **_k: True)
        editor.close()
        root.update()
        assert maker.part_editor is None and maker.blueprint["design"] == changed["design"]
    finally:
        studio.destroy()


@pytest.mark.parametrize("failure", ["concurrent_writer", "disk_failure"])
def test_part_editor_preserves_project_and_draft_on_save_conflict(reader, tmp_path, monkeypatch, failure):
    import copy
    from pathlib import Path

    from test_blueprint_geometry import pair

    from fieldforge.blueprints.engine import digest
    from fieldforge.blueprints.projects import append_revision, create_project, head, load_project
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers["engineering"]
    value = pair()
    path = tmp_path / "parts.ffproject.json"
    project = create_project(path, "Part edits", value)
    try:
        maker.show_blueprint(value, dirty=False)
        maker.history.project, maker.history.path = project, path
        original = copy.deepcopy(maker.blueprint)
        maker.edit_part()
        editor = maker.part_editor
        editor.sizes[0].set("20")
        editor.preview_changes()
        candidate = copy.deepcopy(editor.candidate["blueprint"])
        if failure == "concurrent_writer":
            external = copy.deepcopy(value)
            external["design"]["title"] = "External update"
            external["design_sha256"] = digest(external["design"])
            append_revision(path, external, expected_head=head(project))
        else:
            def fail(*_a, **_kw):
                raise OSError("Simulated disk failure")
            monkeypatch.setattr(Path, "replace", fail)
        disk_before = path.read_bytes()
        editor.apply()
        assert path.read_bytes() == disk_before
        if failure == "concurrent_writer":
            assert maker.blueprint == original and maker.part_editor is editor
            assert editor.candidate["blueprint"] == candidate
            assert "changed on disk" in editor.status.get()
            assert len(load_project(path)["revisions"]) == 2
        else:
            assert maker.blueprint == candidate and maker.has_unsaved_changes()
            assert maker.part_editor is None and "Draft kept in memory" in maker.status.get()
            assert len(load_project(path)["revisions"]) == 1
    finally:
        studio.destroy()


def test_measured_failures_prepare_user_reviewed_revision_without_changing_design(reader, monkeypatch):
    import copy

    from test_blueprint_clearance import limit
    from test_blueprint_geometry import pair

    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers["engineering"]
    value = pair((12, 0, 0))
    value["request"]["acceptance_rules"] = [limit()]
    monkeypatch.setattr("fieldforge.ui.blueprints.generate_blueprint",
                        lambda *_a, **_kw: pytest.fail("Preparing instructions must not call a model"))
    try:
        maker.show_blueprint(value, dirty=False)
        maker.load_request(maker.blueprint)
        original = copy.deepcopy(maker.blueprint)
        maker.instructions.insert("1.0", "Keep the original material.")
        studio.pages.select(maker)
        maker.pages.select(4)
        maker.refinement_pages.select(maker.diagnostics)
        studio.geometry("760x650")
        root.update()
        panel = maker.diagnostics
        assert panel.prepare_button.winfo_ismapped() and panel.details.winfo_ismapped()
        assert panel.prepare_button.winfo_rootx() + panel.prepare_button.winfo_width() <= (
            studio.winfo_rootx() + studio.winfo_width())
        assert panel.rows.selection() == ("C1",)
        assert "failed" in panel.details.get("1.0", "end")
        maker.busy = True
        panel.prepare()
        maker.busy = False
        assert maker.instructions.get("1.0", "end-1c") == "Keep the original material."
        maker.editor.insert("end", "pending")
        panel.prepare()
        assert maker.instructions.get("1.0", "end-1c") == "Keep the original material."
        maker.show_blueprint(value, dirty=False)
        panel.prepare()
        instruction = maker.instructions.get("1.0", "end-1c")
        assert instruction.startswith("Keep the original material.") and "C1" in instruction
        assert "including passing rules" in instruction
        assert maker.refinement_pages.select() == str(maker.revision_input)
        assert maker.blueprint == original and not maker.has_unsaved_changes() and not maker.busy
        # Revalidate a formerly failing selection instead of using stale cached diagnostics.
        maker.blueprint = pair((15, 0, 0))
        maker.blueprint["request"]["acceptance_rules"] = [limit()]
        maker.editor.delete("1.0", "end")
        import json
        maker.editor.insert("1.0", json.dumps(maker.blueprint["design"], ensure_ascii=False, indent=2))
        panel.prepare()
        assert "passing or unknown" in maker.status.get()
        assert maker.instructions.get("1.0", "end-1c") == instruction
    finally:
        studio.destroy()


def test_conflicting_limits_can_be_inspected_but_never_start_model_or_save_revision(reader, monkeypatch, tmp_path):
    from test_blueprint_clearance import limit
    from test_blueprint_geometry import pair

    from fieldforge.blueprints.projects import create_project
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers["engineering"]
    value = pair((12, 0, 0))
    value["request"]["acceptance_rules"] = [limit(), limit(value=1, operator="<=", id="C2")]
    path = tmp_path / "conflict.ffproject.json"
    project = create_project(path, "Conflicting request", value)
    original = path.read_bytes()
    monkeypatch.setattr("fieldforge.ui.blueprints.generate_blueprint",
                        lambda *_a, **_kw: pytest.fail("A contradictory request must not call a model"))
    try:
        maker.acceptance.set_rules(value["request"]["acceptance_rules"])
        maker.acceptance.check_limits()  # Works even before there is a blueprint.
        assert "conflicting rule groups" in maker.acceptance.note.get()
        maker.show_blueprint(value, dirty=False)
        maker.load_request(maker.blueprint)
        maker.history.project, maker.history.path = project, path
        maker.diagnostics.prepare()
        assert "limits conflict" in maker.status.get() and maker.instructions.get("1.0", "end-1c") == ""
        maker.instructions.insert("1.0", "Fix these dimensions.")
        maker.model.set("fixture")
        maker.refine()
        assert "Conflicting acceptance limits" in maker.status.get() and not maker.busy
        assert path.read_bytes() == original and not maker.has_unsaved_changes()
    finally:
        studio.destroy()


def test_history_comparison_export_uses_selected_revision_and_current_applied_draft(reader, monkeypatch, tmp_path):
    import copy
    import json

    from test_blueprint_clearance import limit
    from test_blueprint_geometry import pair

    from fieldforge.blueprints.engine import digest
    from fieldforge.blueprints.projects import create_project
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers["engineering"]
    before, after = pair((15, 0, 0)), pair((12, 0, 0))
    before["request"]["acceptance_rules"] = [limit()]
    after["request"]["acceptance_rules"] = [limit(value=2)]
    path = tmp_path / "design.ffproject.json"
    project = create_project(path, "Comparison", before)
    original = path.read_bytes()
    destinations = []

    def choose_folder(**_kwargs):
        destinations.append(tmp_path)
        return str(tmp_path)

    monkeypatch.setattr("fieldforge.ui.blueprint_history.filedialog.askdirectory", choose_folder)
    try:
        maker.show_blueprint(after)
        maker.load_request(maker.blueprint)
        maker.history.project, maker.history.path = project, path
        maker.history.refresh()
        maker.history.rows.selection_set("1")
        maker.history.compare_selected()
        assert "regressed" in maker.history.changes.get("1.0", "end")
        # Recompute at export time instead of exporting the cached regression above.
        current = copy.deepcopy(after)
        current["design"]["parts"][1]["position_mm"] = [20, 0, 0]
        current["design_sha256"] = digest(current["design"])
        maker.show_blueprint(current)
        maker.load_request(maker.blueprint)
        maker.busy = True
        maker.history.export_selected()
        assert not destinations
        maker.busy = False
        maker.editor.insert("end", "unapplied edit")
        maker.history.export_selected()
        assert not destinations
        maker.show_blueprint(current)
        studio.pages.select(maker)
        maker.pages.select(maker.history)
        studio.geometry("760x650")
        root.update()
        assert maker.history.export_button.winfo_ismapped()
        assert maker.history.export_button.winfo_rootx() + maker.history.export_button.winfo_width() <= (
            studio.winfo_rootx() + studio.winfo_width())
        maker.history.export_selected()
        result = json.loads((tmp_path / "comparison-revision-1-to-draft" / "comparison.json").read_text(encoding="utf-8"))
        assert result["acceptance"]["outcomes"] == {"still_passed": 1}
        assert result["geometry"]["pairs"][0]["after"]["clearance_mm"] == "10"
        assert path.read_bytes() == original
        assert "still passed" in maker.history.changes.get("1.0", "end")
        maker.history.export_selected()
        assert path.read_bytes() == original  # Existing comparison never overwrites history.
    finally:
        studio.destroy()


def test_project_save_conflict_keeps_unapplied_candidate_original_and_external_revision(reader, monkeypatch, tmp_path):
    from blueprint_fixtures import document, revision

    from fieldforge.blueprints.engine import digest
    from fieldforge.blueprints.projects import append_revision, checkout, head, load_project
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers["project"]
    path = tmp_path / "conflict.ffproject.json"
    monkeypatch.setattr("fieldforge.ui.blueprint_history.filedialog.asksaveasfilename",
                        lambda **kwargs: str(path))
    maker.show_blueprint(document("project"))
    maker.history.create()
    expected = head(maker.history.project)

    def raced(_library, request, *_args, **kwargs):
        external = document("project")
        external["design"]["title"] = "Another window's revision"
        external["design_sha256"] = digest(external["design"])
        append_revision(path, external, expected_head=expected)
        candidate = revision(kwargs["previous"], request, kwargs["instructions"])
        candidate["design"]["title"] = "New model draft"
        candidate["design_sha256"] = digest(candidate["design"])
        return candidate

    monkeypatch.setattr("fieldforge.ui.blueprints.generate_blueprint", raced)
    maker.model.set("fixture:local")
    maker.instructions.insert("1.0", "Update the schedule.")
    maker.refine()
    wait_for_search(root, maker)
    review = maker.revision_review
    review.apply()
    assert "project was not saved" in review.status.get()
    assert maker.blueprint["design"]["title"] == "Example design"
    assert review.proposal["candidate"]["design"]["title"] == "New model draft"
    assert maker.has_unsaved_changes()
    assert checkout(load_project(path))["design"]["title"] == "Another window's revision"
    studio.destroy()


def test_cancel_after_worker_finishes_does_not_replace_or_save_draft(reader):
    from concurrent.futures import Future

    from blueprint_fixtures import document

    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers["project"]
    original = document("project")
    maker.show_blueprint(original, dirty=False)
    ready = Future()
    ready.set_result(document("project"))
    maker.busy = True
    maker._cancel.set()
    maker._poll(ready, "Refining design")
    assert maker.blueprint == original
    assert not maker.dirty
    assert "No generated revision was saved" in maker.status.get()
    assert not maker.busy
    studio.destroy()


@pytest.mark.parametrize("mode,metric,target,limit_value", [
    ("engineering", "Overall X span", "", "600"),
    ("project", "Dependency schedule duration", "", "4"),
    ("software", "Component trust zone", "DB", "offline"),
])
def test_acceptance_limits_block_save_until_applied_and_survive_history(
        reader, monkeypatch, tmp_path, mode, metric, target, limit_value):
    from blueprint_fixtures import document

    from fieldforge.blueprints.projects import load_project
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers[mode]
    studio.pages.select(maker)
    project = tmp_path / (mode + ".ffproject.json")
    monkeypatch.setattr("fieldforge.ui.blueprint_history.filedialog.asksaveasfilename", lambda **kwargs: str(project))
    try:
        maker.show_blueprint(document(mode), dirty=False)
        maker.history.create()
        limits = maker.acceptance
        maker.pages.select(0)
        studio.geometry("760x650")
        root.update()
        assert maker.query_entry.winfo_ismapped()
        assert maker.query_entry.winfo_rooty() + maker.query_entry.winfo_height() <= maker.winfo_rooty() + maker.winfo_height()
        maker.requirement_pages.select(limits)
        root.update()
        assert limits.rows.winfo_ismapped()
        assert limits.details.winfo_rooty() + limits.details.winfo_height() <= maker.winfo_rooty() + maker.winfo_height()
        limits.metric.set(metric)
        limits._metric_changed()
        limits.target.set(target)
        limits.value.set(limit_value)
        limits.add()
        assert len(limits.rules) == 1
        assert maker.has_unsaved_changes()
        maker.save()
        assert "Apply your acceptance limits" in maker.status.get()
        maker.apply_limits()
        assert maker.blueprint["validation"]["acceptance"][0]["status"] == "failed"
        assert maker.blueprint["review"] is None
        assert len(load_project(project)["revisions"]) == 2
        calls = []

        def refine(_library, request, _model, _client, **kwargs):
            from blueprint_fixtures import revision

            calls.append(request)
            return revision(kwargs["previous"], request, kwargs["instructions"])

        monkeypatch.setattr("fieldforge.ui.blueprints.generate_blueprint", refine)
        maker.model.set("fixture:local")
        maker.instructions.insert("1.0", "Respect the acceptance limits.")
        maker.refine()
        wait_for_search(root, maker)
        assert calls[0].acceptance_rules == limits.rules
        assert maker.revision_review.proposal["candidate"]["validation"]["acceptance"][0]["status"] == "failed"
        maker.revision_review.apply()
        assert maker.blueprint["validation"]["acceptance"][0]["status"] == "failed"
        maker._input_state("disabled")
        assert limits.measurements.instate(["disabled"])
        maker._input_state("normal")
        assert limits.measurements.instate(["!disabled"])
        limits.rows.selection_set("L1")
        limits.remove()
        maker.apply_limits()
        assert maker.blueprint["request"]["acceptance_rules"] == []
        maker.history.rows.selection_set("2")
        maker.history.restore()
        assert maker.acceptance.rules[0]["value"] == (limit_value if mode == "software" else float(limit_value))
        assert "acceptance_rules" in maker.history.changes.get("1.0", "end-1c")
    finally:
        studio.destroy()


def test_first_generation_keeps_limits_without_discard_prompt(reader, monkeypatch):
    import copy

    from blueprint_fixtures import document

    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers["engineering"]

    def generate(_library, request, *_args, **_kwargs):
        value = document("engineering")
        value["request"] = copy.deepcopy(request.__dict__)
        return value

    monkeypatch.setattr("fieldforge.ui.blueprints.generate_blueprint", generate)
    monkeypatch.setattr("fieldforge.ui.blueprints.messagebox.askyesno", lambda *a, **kw: pytest.fail("No draft is replaced"))
    try:
        maker.acceptance.value.set("600")
        maker.acceptance.add()
        maker.model.set("fixture:local")
        maker.generate()
        wait_for_search(root, maker)
        assert maker.blueprint["request"]["acceptance_rules"][0]["value"] == 600
        assert maker.blueprint["status"] == "needs_revision"
    finally:
        studio.destroy()


@pytest.mark.parametrize("mode", ["engineering", "project", "software"])
def test_blueprint_evidence_preview_needs_no_model_and_preserves_draft(reader, mode):
    import copy

    from blueprint_fixtures import document

    from fieldforge.knowledge import KnowledgeArticle
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    library.upsert(KnowledgeArticle("preview-reference", "Workshop", "Workshop inventory records are local.", "reference"))
    studio = BlueprintStudio(root, library)
    maker = studio.makers[mode]
    studio.pages.select(maker)
    try:
        maker.show_blueprint(document(mode), dirty=False)
        maker.load_request(maker.blueprint)
        original = copy.deepcopy(maker.blueprint)
        maker.brief.delete("1.0", "end")
        maker.brief.insert("1.0", "Workshop inventory records.")
        maker.preview_evidence()
        wait_for_search(root, maker)
        assert not maker.model.get()
        assert maker.evidence.sources
        assert "Workshop inventory records" in maker.evidence.details.get("1.0", "end-1c")
        assert maker.blueprint == original and not maker.dirty
        assert maker.history.project is None
        studio.geometry("760x650")
        root.update()
        assert maker.evidence.details.winfo_ismapped()
        maker.evidence.show_saved(maker.blueprint)
        assert "Original excerpts" in maker.evidence.details.get("1.0", "end-1c")
        assert maker.evidence.sources == original["sources"]
    finally:
        studio.destroy()


def test_cancelled_evidence_preview_does_not_replace_existing_sources(reader):
    from concurrent.futures import Future

    from blueprint_fixtures import document

    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers["engineering"]
    try:
        maker.show_blueprint(document("engineering"), dirty=False)
        original = list(maker.evidence.sources)
        future = Future()
        future.set_result({"sources": []})
        maker.busy = True
        maker._cancel.set()
        maker._poll(future, "Previewing evidence")
        assert maker.evidence.sources == original and not maker.dirty
        assert "cancelled" in maker.status.get()
        assert maker.evidence.preview_button.instate(["!disabled"])
    finally:
        studio.destroy()


def _propose_revision(maker):
    import copy
    from concurrent.futures import Future

    from blueprint_fixtures import revision

    from fieldforge.blueprints.engine import digest
    from fieldforge.ui.blueprint_revision import project_identity

    request = maker._request()
    instructions = "Revise the recorded title."
    maker._refinement_context = {"before": copy.deepcopy(maker.blueprint), "request": copy.deepcopy(request.__dict__),
                                 "instructions": instructions, "project": project_identity(maker.history)}
    value = revision(maker.blueprint, request, instructions)
    value["design"]["title"] = "Candidate design"
    value["design_sha256"] = digest(value["design"])
    future = Future()
    future.set_result(value)
    maker._poll(future, "Refining design")
    assert maker._refinement_context is None
    assert maker.revision_review is not None, maker.status.get()
    return maker.revision_review


@pytest.mark.parametrize("mode", ["engineering", "project", "software"])
def test_revision_review_export_discard_and_pending_guards_preserve_unsaved_draft_and_history(
        reader, monkeypatch, tmp_path, mode):
    import copy

    from blueprint_fixtures import document

    from fieldforge.blueprints.engine import digest
    from fieldforge.blueprints.projects import create_project
    from fieldforge.blueprints.render import load_blueprint
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers[mode]
    try:
        original = document(mode)
        path = tmp_path / "original.ffproject.json"
        project = create_project(path, "Original", original)
        maker.history.project, maker.history.path = project, path
        original["design"]["title"] = "Unsaved changes before the AI request"
        original["design_sha256"] = digest(original["design"])
        maker.show_blueprint(original)
        maker.load_request(original)
        saved = path.read_bytes()
        previous_undo = document(mode)
        maker.history.previous = copy.deepcopy(previous_undo)
        review = _propose_revision(maker)
        assert maker.dirty and maker.has_unsaved_changes()
        assert maker.blueprint == original and path.read_bytes() == saved
        assert maker.history.previous == previous_undo
        monkeypatch.setattr("fieldforge.ui.blueprints.generate_blueprint", lambda *_a, **_kw: pytest.fail("New model call"))
        maker.generate()
        maker.refine()
        assert not maker.busy and "pending AI candidate" in maker.status.get()
        monkeypatch.setattr("fieldforge.ui.blueprint_revision.filedialog.askdirectory", lambda **_kw: str(tmp_path))
        monkeypatch.setattr("fieldforge.ui.blueprint_revision.simpledialog.askstring", lambda *_a, **_kw: "proposal")
        review.export()
        assert load_blueprint(tmp_path / "proposal" / "blueprint.json")["design"]["title"] == "Candidate design"
        assert (tmp_path / "proposal" / "comparison" / "report.html").is_file()
        review.export()  # Existing directory reports failure and leaves candidate/draft intact.
        assert maker.revision_review is review and maker.blueprint == original and path.read_bytes() == saved
        monkeypatch.setattr("fieldforge.ui.blueprint_revision.messagebox.askyesno", lambda *_a, **_kw: False)
        review.discard()
        studio.close()
        assert review.winfo_exists() and studio.winfo_exists()
        monkeypatch.setattr("fieldforge.ui.blueprint_revision.messagebox.askyesno", lambda *_a, **_kw: True)
        review.discard()
        assert maker.revision_review is None and maker.blueprint == original and maker.dirty
        assert maker.history.previous == previous_undo and path.read_bytes() == saved
        assert "discarded" in maker.status.get()
    finally:
        studio.destroy()


def test_revision_review_guards_busy_unapplied_changed_requirements_baseline_and_project(reader, tmp_path):
    import copy

    from blueprint_fixtures import document

    from fieldforge.blueprints.projects import create_project
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers["project"]
    try:
        maker.show_blueprint(document("project"), dirty=False)
        maker.load_request(maker.blueprint)
        original = copy.deepcopy(maker.blueprint)
        review = _propose_revision(maker)
        maker.busy = True
        review.apply()
        assert "busy" in review.status.get()
        maker.busy = False
        maker.editor.insert("end", " ")
        review.apply()
        assert "Apply your design edits" in review.status.get()
        maker.show_blueprint(original, dirty=False)
        maker.resources.insert("end", "Changed resource availability")
        review.apply()
        assert "requirements changed" in review.status.get()
        maker.load_request(original)
        changed = copy.deepcopy(original)
        changed["review_error"] = "New review status"
        maker.show_blueprint(changed)
        review.apply()
        assert "working draft changed" in review.status.get()
        maker.show_blueprint(original, dirty=False)
        path = tmp_path / "other.ffproject.json"
        maker.history.project, maker.history.path = create_project(path, "Another project", original), path
        review.apply()
        assert "open project changed" in review.status.get()
        maker.history.detach()
        review.apply()
        assert maker.revision_review is None and maker.blueprint["design"]["title"] == "Candidate design"
        assert maker.dirty
        maker.history.undo()
        assert maker.blueprint == original
    finally:
        studio.destroy()


def test_revision_apply_write_failure_retains_candidate_as_unsaved_draft(reader, tmp_path, monkeypatch):
    from pathlib import Path

    from blueprint_fixtures import document

    from fieldforge.blueprints.projects import create_project
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers["software"]
    try:
        maker.show_blueprint(document("software"), dirty=False)
        maker.load_request(maker.blueprint)
        path = tmp_path / "write-failure.ffproject.json"
        maker.history.project, maker.history.path = create_project(path, "Original", maker.blueprint), path
        original = path.read_bytes()
        review = _propose_revision(maker)

        def fail(*_a, **_kw):
            raise OSError("Simulated disk write failure")

        # Python 3.10 caches os.replace in pathlib's accessor; patch the actual
        # file-replacement boundary consistently across supported runtimes.
        monkeypatch.setattr(Path, "replace", fail)
        review.apply()
        assert maker.revision_review is None
        assert maker.blueprint["design"]["title"] == "Candidate design" and maker.dirty
        assert "project was not saved" in maker.status.get() and path.read_bytes() == original
    finally:
        studio.destroy()


@pytest.mark.parametrize("outcome", ["cancelled", "error", "wrong_request"])
def test_refinement_without_acceptance_does_not_save_dirty_draft_or_change_undo(
        reader, monkeypatch, tmp_path, outcome):
    import copy

    from blueprint_fixtures import document, revision

    from fieldforge.blueprints.engine import digest
    from fieldforge.blueprints.projects import create_project
    from fieldforge.knowledge.local_model import GenerationCancelled, LocalModelError
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    studio = BlueprintStudio(root, library)
    maker = studio.makers["engineering"]
    try:
        original = document("engineering")
        path = tmp_path / "no-writes.ffproject.json"
        maker.history.project, maker.history.path = create_project(path, "Original", original), path
        original["design"]["title"] = "Unsaved baseline"
        original["design_sha256"] = digest(original["design"])
        maker.show_blueprint(original)
        maker.load_request(original)
        saved = path.read_bytes()
        maker.history.previous = copy.deepcopy(original)

        def worker(_library, request, *_a, **kwargs):
            if outcome == "cancelled":
                kwargs["cancel"].set()
                raise GenerationCancelled("Cancelled")
            if outcome == "error":
                raise LocalModelError("Unavailable model")
            value = revision(kwargs["previous"], request, kwargs["instructions"])
            value["request"]["resources"] = "Unexpected request change"
            return value

        monkeypatch.setattr("fieldforge.ui.blueprints.generate_blueprint", worker)
        maker.model.set("fixture:local")
        maker.instructions.insert("1.0", "Revise the recorded design.")
        maker.refine()
        wait_for_search(root, maker)
        assert maker.revision_review is None and maker._refinement_context is None
        assert maker.blueprint == original and maker.dirty and maker.history.previous == original
        assert path.read_bytes() == saved and maker.instructions.get("1.0", "end-1c")
        if outcome == "wrong_request":
            assert "submitted revision request" in maker.status.get()
    finally:
        studio.destroy()


@pytest.mark.parametrize("mode", ["engineering", "project", "software"])
def test_saved_review_resumes_in_empty_maker_without_model_then_applies_and_undoes(reader, monkeypatch, tmp_path, mode):
    import copy

    from blueprint_fixtures import document

    from fieldforge.blueprints.review_files import load_review
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    first = BlueprintStudio(root, library)
    maker = first.makers[mode]
    maker.show_blueprint(document(mode), dirty=False)
    maker.load_request(maker.blueprint)
    original = copy.deepcopy(maker.blueprint)
    maker.resources.insert("end", "Submitted resource update")
    review = _propose_revision(maker)
    candidate = copy.deepcopy(review.proposal["candidate"])
    path = tmp_path / "saved.ffreview.json"
    monkeypatch.setattr("fieldforge.ui.blueprint_revision.filedialog.asksaveasfilename", lambda **_kw: str(path))
    review.save()
    raw = path.read_bytes()
    assert load_review(path)["candidate"] == candidate
    assert maker.blueprint == original and not maker.dirty
    assert "remains unapplied" in review.status.get()
    review.save()
    assert "already exists" in review.status.get() and path.read_bytes() == raw
    first.destroy()
    second = BlueprintStudio(root, library)
    maker = second.makers[mode]
    monkeypatch.setattr("fieldforge.ui.blueprints.filedialog.askopenfilename", lambda **_kw: str(path))
    monkeypatch.setattr("fieldforge.ui.blueprints.generate_blueprint", lambda *_a, **_kw: pytest.fail("Model called"))
    try:
        maker.resume_review()
        review = maker.revision_review
        assert review is not None and not maker.model.get()
        assert maker.blueprint == original and maker.dirty and maker.history.project is None
        assert maker.resources.get("1.0", "end-1c") == "Submitted resource update"
        assert "Submitted resource update" in review.details.get("1.0", "end-1c")
        review.geometry("760x650")
        root.update()
        assert review.changes.winfo_height() > 200
        assert review.save_button.winfo_rootx() + review.save_button.winfo_width() < review.winfo_rootx() + review.winfo_width()
        review.apply()
        assert maker.revision_review is None and maker.blueprint == candidate and maker.dirty
        maker.history.undo()
        assert maker.blueprint == original and path.read_bytes() == raw
    finally:
        second.destroy()


def test_saved_review_with_existing_project_preserves_forms_and_only_records_when_applied(reader, monkeypatch, tmp_path):
    import copy

    from blueprint_fixtures import document, revision

    from fieldforge.blueprints.engine import digest
    from fieldforge.blueprints.projects import create_project, load_project
    from fieldforge.blueprints.review_files import create_review, save_review
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    before = document("project")
    candidate = revision(before)
    candidate["request"]["resources"] = "Resources from the submitted request"
    candidate["design"]["title"] = "Reopened candidate"
    candidate["design_sha256"] = digest(candidate["design"])
    path = save_review(create_review(before, candidate), tmp_path / "review.ffreview.json")
    studio = BlueprintStudio(root, library)
    maker = studio.makers["project"]
    project_path = tmp_path / "project.ffproject.json"
    try:
        maker.show_blueprint(before, dirty=False)
        maker.load_request(before)
        maker.resources.insert("end", "Current UI resource notes")
        maker.history.project, maker.history.path = create_project(project_path, "Existing", before), project_path
        saved = project_path.read_bytes()
        original = copy.deepcopy(maker.blueprint)
        monkeypatch.setattr("fieldforge.ui.blueprints.filedialog.askopenfilename", lambda **_kw: str(path))
        maker.resume_review()
        assert maker.blueprint == original and project_path.read_bytes() == saved and not maker.dirty
        assert maker.resources.get("1.0", "end-1c") == "Current UI resource notes"
        maker.revision_review.apply()
        assert len(load_project(project_path)["revisions"]) == 2
        assert maker.blueprint["design"]["title"] == "Reopened candidate" and not maker.dirty
        assert maker.resources.get("1.0", "end-1c") == "Resources from the submitted request"
    finally:
        studio.destroy()


def test_saved_review_stale_baseline_blocks_apply_but_can_export_without_changing_current_draft(reader, monkeypatch, tmp_path):
    import copy

    from blueprint_fixtures import document, revision

    from fieldforge.blueprints.engine import digest
    from fieldforge.blueprints.review_files import create_review, save_review
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    before = document("software")
    path = save_review(create_review(before, revision(before)), tmp_path / "review.ffreview.json")
    studio = BlueprintStudio(root, library)
    maker = studio.makers["software"]
    try:
        current = copy.deepcopy(before)
        current["design"]["title"] = "Different current draft"
        current["design_sha256"] = digest(current["design"])
        maker.show_blueprint(current)
        maker.load_request(current)
        monkeypatch.setattr("fieldforge.ui.blueprints.filedialog.askopenfilename", lambda **_kw: str(path))
        maker.resume_review()
        review = maker.revision_review
        assert "working draft changed" in review.status.get()
        review.apply()
        assert maker.blueprint == current and maker.dirty and maker.revision_review is review
        monkeypatch.setattr("fieldforge.ui.blueprint_revision.filedialog.askdirectory", lambda **_kw: str(tmp_path))
        monkeypatch.setattr("fieldforge.ui.blueprint_revision.simpledialog.askstring", lambda *_a, **_kw: "export")
        review.export()
        assert (tmp_path / "export" / "review.ffreview.json").is_file()
        assert maker.blueprint == current
    finally:
        studio.destroy()


def test_saved_review_wrong_mode_bad_checksum_busy_and_pending_edits_preserve_current_state(reader, monkeypatch, tmp_path):
    from blueprint_fixtures import document, revision

    from fieldforge.blueprints.review_files import create_review, save_review
    from fieldforge.ui.blueprints import BlueprintStudio

    root, _frame, library, _errors = reader
    value = document("project")
    path = save_review(create_review(value, revision(value)), tmp_path / "review.ffreview.json")
    studio = BlueprintStudio(root, library)
    maker = studio.makers["engineering"]
    try:
        monkeypatch.setattr("fieldforge.ui.blueprints.filedialog.askopenfilename", lambda **_kw: str(path))
        maker.resume_review()
        assert "matching blueprint maker" in maker.status.get() and maker.blueprint is None
        path.write_text(path.read_text(encoding="utf-8").replace("Example design", "Changed design"), encoding="utf-8")
        maker.resume_review()
        assert "checksum" in maker.status.get() and maker.blueprint is None
        monkeypatch.setattr("fieldforge.ui.blueprints.filedialog.askopenfilename", lambda **_kw: pytest.fail("Picker called"))
        maker.busy = True
        maker.resume_review()
        maker.busy = False
        maker.show_blueprint(document("engineering"), dirty=False)
        maker.editor.insert("end", " ")
        maker.resume_review()
        assert "Apply your design edits" in maker.status.get()
        assert maker.revision_review is None
    finally:
        studio.destroy()


def test_desktop_backup_failures_restore_controls_and_preserve_data(reader, tmp_path, monkeypatch):
    from fieldforge.core.database_archive import export_snapshot
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
