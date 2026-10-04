import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.pathways import STATUS_LABELS, PathwayStore


@pytest.fixture
def reader(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.pathways import PathwaysTab

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; use xvfb-run for GUI tests")
    root.geometry("1240x800")
    failures = []
    root.report_callback_exception = lambda *args: failures.append(args)
    errors = []
    monkeypatch.setattr("fieldforge.ui.pathways.messagebox.showerror",
                        lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr("fieldforge.ui.pathways.messagebox.askyesno", lambda *args, **kwargs: False)
    library = KnowledgeLibrary(tmp_path / "ui.db")
    store = PathwayStore(library)
    frame = PathwaysTab(root, store)
    frame.pack(fill="both", expand=True)
    root.update()
    try:
        yield root, frame, store, errors
    finally:
        root.destroy()
    assert not failures


def select(root, frame, slug):
    frame.tree.selection_set(slug)
    frame.tree.focus(slug)
    root.update()
    assert frame.slug == slug


def test_tree_has_goals_not_fake_installed_articles(reader):
    _, frame, store, errors = reader
    assert len(frame.tree.get_children()) == 6
    assert sum(len(frame.tree.get_children(parent)) for parent in frame.tree.get_children()) == 24
    assert "0 linked articles installed" in frame.summary.get()
    assert "0 goals with practice recorded" in frame.summary.get()
    assert store.library.count() == 0
    assert str(frame.note["state"]) == "disabled"
    assert not errors


def test_select_goal_shows_prerequisites_and_missing_content(reader):
    root, frame, _, errors = reader
    select(root, frame, "computing")
    assert frame.title.get() == "Study computing and digital preservation"
    assert "Guide needed" in frame.overview.get("1.0", "end")
    assert len(frame.plan.get_children()) == 12
    assert not frame.reading.get_children()
    assert str(frame.open_button["state"]) == "disabled"
    assert "not an installed lesson" in frame.reading_notice.get()
    assert not errors


def test_navigation_saves_notes_and_status(reader):
    root, frame, store, errors = reader
    select(root, frame, "measurement")
    frame.note.insert("1.0", "Practice with fictional values.\n\n")
    frame.status.set(STATUS_LABELS["practiced"])
    select(root, frame, "inventory")
    assert store.progress("measurement").note.endswith("\n\n")
    assert store.progress("measurement").status == "practiced"
    select(root, frame, "measurement")
    assert frame.note.get("1.0", "end-1c") == "Practice with fictional values.\n\n"
    assert not errors


def test_filter_refresh_saves_notes_and_accurately_reports_no_results(reader):
    root, frame, store, errors = reader
    select(root, frame, "water")
    frame.note.insert("1.0", "Unfinished questions")
    frame.query.set("unmatchedneedle")
    assert frame.refresh()
    assert store.progress("water").note == "Unfinished questions"
    assert "No topics match" in frame.overview.get("1.0", "end")
    assert not frame.tree.get_children()
    frame.clear_filters()
    root.update()
    assert frame.tree.exists("water")
    assert not errors


def test_stale_save_blocks_navigation_and_preserves_visible_edits(reader):
    root, frame, store, errors = reader
    select(root, frame, "water")
    frame.note.insert("1.0", "Unsaved window A")
    store.save("water", status="exploring", note="Saved window B", expected_revision=0)
    frame.tree.selection_set("inventory")
    root.update()
    assert frame.slug == "water"
    assert frame.tree.selection() == ("water",)
    assert frame.note.get("1.0", "end-1c") == "Unsaved window A"
    assert store.progress("water").note == "Saved window B"
    assert len(errors) == 1


def test_reload_is_confirmed_before_discarding_unsaved_edits(reader, monkeypatch):
    root, frame, store, errors = reader
    select(root, frame, "water")
    frame.note.insert("1.0", "Keep until confirmed")
    store.save("water", status="exploring", note="Other saved copy", expected_revision=0)
    frame.reload_progress()
    assert frame.note.get("1.0", "end-1c") == "Keep until confirmed"
    monkeypatch.setattr("fieldforge.ui.pathways.messagebox.askyesno", lambda *args, **kwargs: True)
    frame.reload_progress()
    assert frame.note.get("1.0", "end-1c") == "Other saved copy"
    assert frame._saved.revision == 1
    assert not errors


def test_open_reference_is_real_offline_text_and_does_not_record_practice(reader):
    root, frame, store, errors = reader
    store.library.upsert(KnowledgeArticle("starter-v1-measurement", "Local measurement worksheet",
                                         "Unique offline text, not a remote link.", "math"))
    frame.refresh()
    select(root, frame, "measurement")
    assert frame.reading.get_children() == ("starter-v1-measurement",)
    window = frame.open_article()
    root.update()
    assert window is not None
    # ScrolledText is inside its own Frame along with a scrollbar.
    children = window.winfo_children()[0].winfo_children()
    text = next(child for child in children if child.winfo_class() == "Text")
    assert "Unique offline text" in text.get("1.0", "end")
    assert str(text["state"]) == "disabled"
    assert store.progress("measurement").status == "not_started"
    window.destroy()
    assert not errors


def test_plan_navigation_works_when_prerequisite_is_hidden_by_stage_filter(reader):
    root, frame, _, errors = reader
    frame.stage.set(frame._stage_options[6])
    frame.refresh()
    select(root, frame, "computing")
    assert not frame.tree.exists("measurement")
    frame.plan.selection_set("measurement")
    frame.go_to_step()
    root.update()
    assert frame.slug == "measurement"
    assert frame.stage.get() == "All learning stages"
    assert not errors


def test_save_failure_preserves_note_and_blocks_close_guard(reader, monkeypatch):
    root, frame, _, errors = reader
    select(root, frame, "measurement")
    frame.note.insert("1.0", "Keep this text")

    def fail(*args, **kwargs):
        raise OSError("disk error")

    monkeypatch.setattr(frame.store, "save", fail)
    assert not frame.save_current()
    assert frame.note.get("1.0", "end-1c") == "Keep this text"
    assert len(errors) == 1


def test_refresh_uses_new_imports_and_save_button_updates_counts(reader):
    root, frame, store, errors = reader
    store.library.upsert(KnowledgeArticle("starter-v1-measurement", "Imported later",
                                         "Imported body.", "math"))
    frame.refresh()
    select(root, frame, "measurement")
    frame.status.set(STATUS_LABELS["practiced"])
    frame.save_button.invoke()
    root.update()
    assert "1 linked articles installed" in frame.summary.get()
    assert "1 goals with practice recorded" in frame.summary.get()
    assert store.progress("measurement").status == "practiced"
    assert not errors


def test_desktop_tab_integration_refreshes_articles_and_blocks_failed_saves(reader, monkeypatch):
    root, original, store, errors = reader
    from tkinter import ttk

    from fieldforge.ui.pathways import add_pathways_tab

    original.pack_forget()
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)
    library_tab = ttk.Frame(notebook)
    library_tab.library = store.library
    library_tab.save_current = lambda: True
    notebook.add(library_tab, text="Knowledge Library")
    paths = add_pathways_tab(notebook, library_tab)
    root.update()
    store.library.upsert(KnowledgeArticle("starter-v1-measurement", "Newly imported", "New text", "math"))
    notebook.select(paths)
    root.update()
    assert "1 linked articles installed" in paths.summary.get()
    select(root, paths, "water")
    paths.note.insert("1.0", "Private changes")
    store.save("water", status="exploring", note="Other window", expected_revision=0)
    notebook.select(library_tab)
    root.update()
    assert notebook.select() == str(paths)
    assert paths.note.get("1.0", "end-1c") == "Private changes"
    assert len(errors) == 1


def test_desktop_tab_integration_saves_learning_note_before_leaving(reader):
    root, original, store, errors = reader
    from tkinter import ttk

    from fieldforge.ui.pathways import add_pathways_tab

    original.pack_forget()
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)
    library_tab = ttk.Frame(notebook)
    library_tab.library = store.library
    library_tab.save_current = lambda: True
    notebook.add(library_tab, text="Knowledge Library")
    paths = add_pathways_tab(notebook, library_tab)
    root.update()
    notebook.select(paths)
    root.update()
    select(root, paths, "water")
    paths.note.insert("1.0", "Save on tab navigation")
    notebook.select(library_tab)
    root.update()
    assert store.progress("water").note == "Save on tab navigation"
    assert notebook.select() == str(library_tab)
    assert not errors
