import time

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.starter import starter_articles


@pytest.fixture
def reader(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.knowledge import KnowledgeTab

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; run with xvfb-run")
    errors = []
    monkeypatch.setattr("fieldforge.ui.knowledge.messagebox.showerror",
                        lambda *args, **kwargs: errors.append(args))
    library = KnowledgeLibrary(tmp_path / "ui.db")
    frame = KnowledgeTab(root, library)
    frame.pack(fill="both", expand=True)
    root.update()
    try:
        yield root, frame, library, errors
    finally:
        root.destroy()
    assert not errors


def wait(root, frame):
    deadline = time.monotonic() + 5
    while frame.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert not frame.busy
    root.update()


def test_empty_library_explains_next_action_without_silent_data_writes(reader):
    _, frame, library, _ = reader
    assert library.count() == 0
    assert "No articles installed" in frame.metadata.get()
    assert "Load Starter Library" in frame.body.get("1.0", "end")
    assert str(frame.starter_button["text"]) == "Load Starter Library"


def test_button_loads_readable_articles_and_clears_hiding_filters(reader):
    root, frame, library, _ = reader
    frame.query.set("nonexistent")
    frame.favorites.set(True)
    frame.starter_button.invoke()
    assert str(frame.starter_button["state"]) == "disabled"
    wait(root, frame)
    assert library.count() == 12
    assert len(frame.results.get_children()) == 12
    assert not frame.query.get() and not frame.favorites.get()
    slug = starter_articles()[0].slug
    frame.results.selection_set(slug)
    root.update()
    assert "CHOOSE A TASK" in frame.body.get("1.0", "end")
    assert "Review date: Not provided" in frame.metadata.get()


def test_button_saves_current_note_and_never_overwrites_existing_work(reader):
    root, frame, library, _ = reader
    library.upsert(KnowledgeArticle("mine", "My Article", "My text.", "my records"))
    frame.refresh()
    frame.results.selection_set("mine")
    root.update()
    frame.note.insert("1.0", "My unsaved note")
    frame.bookmark.set(True)
    frame.starter_button.invoke()
    wait(root, frame)
    assert library.annotation("mine") == {"bookmarked": True, "note": "My unsaved note"}
    assert library.count() == 13
    frame.starter_button.invoke()
    wait(root, frame)
    assert library.count() == 13


def test_empty_filtered_view_is_not_reported_as_empty_database(reader):
    root, frame, library, _ = reader
    frame.starter_button.invoke()
    wait(root, frame)
    frame.query.set("unmatchedneedle")
    frame.refresh()
    assert "No articles match" in frame.metadata.get()
    assert "still present" in frame.body.get("1.0", "end")
    assert library.count() == 12
