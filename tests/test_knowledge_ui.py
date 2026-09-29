import time

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.packs import export_pack, import_pack


@pytest.fixture
def reader(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.knowledge import KnowledgeTab
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; use xvfb-run for GUI smoke tests")
    errors = []
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
