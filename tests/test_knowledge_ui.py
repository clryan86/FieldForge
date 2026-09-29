import os
import time

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.packs import export_pack, import_pack


@pytest.fixture
def reader(tmp_path, monkeypatch):
    if os.environ.get("FIELDFORGE_REQUIRE_GUI") == "1":
        import tkinter as tk
    else:
        tk = pytest.importorskip("tkinter")
    from fieldforge.ui.knowledge import KnowledgeTab
    try:
        root = tk.Tk()
    except tk.TclError:
        if os.environ.get("FIELDFORGE_REQUIRE_GUI") == "1":
            raise
        pytest.skip("Tk display unavailable; use xvfb-run for GUI smoke tests")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
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
