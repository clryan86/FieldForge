import gc
from dataclasses import replace

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.pathways import PathwayStore


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.pathways import PathwaysTab
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; GUI CI requires a working display")
    root.geometry("1240x840")
    errors, messages = [], []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("fieldforge.ui.reading_links.messagebox.askyesno", lambda *args, **kwargs: False)
    monkeypatch.setattr("fieldforge.ui.pathways.messagebox.showerror", lambda *args, **kwargs: messages.append(args))
    library = KnowledgeLibrary(tmp_path / "library.db")
    library.upsert(KnowledgeArticle("my-guide", "Personal measurement worksheet", "Original practice text.\n\n", "math"))
    store = PathwayStore(library)
    panel = PathwaysTab(root, store)
    panel.pack(fill="both", expand=True)
    root.update()
    try:
        yield root, panel, store, messages
    finally:
        root.destroy()
        gc.collect()
    assert not errors


def manage(root, panel, slug="measurement"):
    panel.tree.selection_set(slug)
    root.update()
    panel.manage_reading_button.invoke()
    root.update()
    assert panel.reading_dialog is not None
    return panel.reading_dialog


def choose(root, dialog, slug="my-guide"):
    dialog.candidates.selection_set(slug)
    root.update()
    assert dialog.candidate is not None


def test_no_automatic_links_and_explicit_preview_then_link(screen):
    root, panel, store, _ = screen
    dialog = manage(root, panel)
    assert not store.reading_links.list("measurement")
    choose(root, dialog)
    assert "Original practice text" in dialog.preview.get("1.0", "end")
    assert not store.reading_links.list("measurement")
    dialog.link_button.invoke()
    root.update()
    assert len(store.reading_links.list("measurement")) == 1
    assert store.progress("measurement").status == "not_started"
    dialog.destroy()
    root.update()
    assert panel.reading.get_children() == ("my-guide",)
    assert "[Your link]" in panel.reading.item("my-guide", "text")
    assert panel.reading_dialog is None


def test_manage_saves_progress_note_and_blocks_normal_navigation_guard(screen):
    root, panel, store, _ = screen
    panel.tree.selection_set("measurement")
    root.update()
    panel.note.insert("1.0", "Pending private learning note\n\n")
    panel.manage_reading()
    root.update()
    assert store.progress("measurement").note == "Pending private learning note\n\n"
    assert not panel.save_current()
    panel.reading_dialog.destroy()
    root.update()
    assert panel.save_current()


def test_failed_learning_note_save_prevents_manager_open(screen):
    root, panel, store, messages = screen
    panel.tree.selection_set("measurement")
    root.update()
    panel.note.insert("1.0", "Unsaved A")
    store.save("measurement", status="exploring", note="Saved B", expected_revision=0)
    panel.manage_reading()
    assert panel.reading_dialog is None and messages
    assert panel.note.get("1.0", "end-1c") == "Unsaved A"


def test_builtin_mapping_cannot_be_duplicated_from_search(screen):
    root, panel, store, _ = screen
    store.library.upsert(replace(store.library.get("my-guide"), slug="starter-v1-measurement"))
    dialog = manage(root, panel)
    choose(root, dialog, "starter-v1-measurement")
    assert str(dialog.link_button["state"]) == "disabled"
    assert "built-in" in dialog.status.get()


def test_changed_source_requires_preview_and_confirmation_to_update(screen, monkeypatch):
    root, panel, store, _ = screen
    links = store.reading_links
    linked = links.link("measurement", "my-guide", expected_version=links.preview("my-guide").version)
    store.library.upsert(replace(store.library.get("my-guide"), body="New edition of worksheet"))
    dialog = manage(root, panel)
    dialog.tabs.select(1)
    dialog.saved.selection_set(str(linked.id))
    root.update()
    assert "New edition" in dialog.preview.get("1.0", "end")
    assert "changed since" in dialog.status.get()
    dialog.update_button.invoke()
    assert links.list("measurement")[0].state == "changed"
    monkeypatch.setattr("fieldforge.ui.reading_links.messagebox.askyesno", lambda *args, **kwargs: True)
    dialog.update_button.invoke()
    root.update()
    assert links.list("measurement")[0].state == "current"
    assert links.list("measurement")[0].revision == 2
    assert store.progress("measurement").status == "not_started"


def test_linking_changed_preview_fails_without_replacing_work(screen):
    root, panel, store, _ = screen
    dialog = manage(root, panel)
    choose(root, dialog)
    store.library.upsert(replace(store.library.get("my-guide"), body="Changed after selection"))
    dialog.link_button.invoke()
    assert "changed since preview" in dialog.status.get()
    assert not store.reading_links.list("measurement")
    assert "Original practice" in dialog.preview.get("1.0", "end")


def test_removing_missing_source_only_removes_association(screen, monkeypatch):
    root, panel, store, _ = screen
    links = store.reading_links
    linked = links.link("measurement", "my-guide", expected_version=links.preview("my-guide").version)
    with store.library.connect() as db:
        db.execute("DELETE FROM knowledge_articles WHERE slug='my-guide'")
    dialog = manage(root, panel)
    dialog.saved.selection_set(str(linked.id))
    root.update()
    assert "no longer installed" in dialog.status.get()
    assert str(dialog.update_button["state"]) == "disabled"
    dialog.remove_button.invoke()
    assert len(links.list("measurement")) == 1
    monkeypatch.setattr("fieldforge.ui.reading_links.messagebox.askyesno", lambda *args, **kwargs: True)
    dialog.remove_button.invoke()
    root.update()
    assert not links.list("measurement")


def test_remove_link_keeps_article_and_private_note(screen, monkeypatch):
    root, panel, store, _ = screen
    links = store.reading_links
    linked = links.link("measurement", "my-guide", expected_version=links.preview("my-guide").version)
    store.library.annotate("my-guide", bookmarked=True, note="Private annotation")
    dialog = manage(root, panel)
    dialog.saved.selection_set(str(linked.id))
    root.update()
    monkeypatch.setattr("fieldforge.ui.reading_links.messagebox.askyesno", lambda *args, **kwargs: True)
    dialog.remove_button.invoke()
    assert store.library.get("my-guide")
    assert store.library.annotation("my-guide")["note"] == "Private annotation"


def test_large_preview_explains_limit_and_full_view_opens_captured_source(screen):
    root, panel, store, _ = screen
    old = replace(store.library.get("my-guide"), body="Long practice text.\n" * 2000)
    store.library.upsert(old)
    dialog = manage(root, panel)
    choose(root, dialog)
    assert len(dialog.preview.get("1.0", "end-1c")) == 20000
    assert "20,000" in dialog.preview_notice.get()
    store.library.upsert(replace(old, body="Changed later"))
    window = dialog.open_full()
    root.update()
    def texts(widget):
        if widget.winfo_class() == "Text":
            yield widget
        for child in widget.winfo_children():
            yield from texts(child)
    content = next(texts(window)).get("1.0", "end")
    assert old.body in content and "Changed later" not in content
    window.destroy()


def test_map_does_not_silently_open_updated_version(screen):
    root, panel, store, messages = screen
    links = store.reading_links
    links.link("measurement", "my-guide", expected_version=links.preview("my-guide").version)
    panel.refresh()
    panel.tree.selection_set("measurement")
    root.update()
    store.library.upsert(replace(store.library.get("my-guide"), body="New content"))
    assert panel.open_article() is None
    assert "source changed" in str(messages)
    panel.refresh()
    assert "Check reading links" in panel.tree.item("measurement", "values")
    assert not panel.reading.get_children()


def test_pagination_filters_and_failed_search_clear_stale_preview(screen):
    root, panel, store, _ = screen
    for i in range(26):
        store.library.upsert(replace(store.library.get("my-guide"), slug=f"article-{i}", title=f"Reference {i:02}", category="tools"))
    dialog = manage(root, panel)
    assert len(dialog.candidates.get_children()) == 25
    dialog.next.invoke()
    assert len(dialog.candidates.get_children()) == 2
    dialog.category.set("math")
    dialog.search()
    assert dialog.candidates.get_children() == ("my-guide",)
    choose(root, dialog)
    dialog.query.set("x"*513)
    dialog.search()
    assert dialog.candidate is None and not dialog.candidates.get_children()
    assert "Could not search" in dialog.status.get()


def test_empty_library_and_minimum_size_action_controls(screen):
    root, panel, store, _ = screen
    with store.library.connect() as db:
        db.execute("DELETE FROM knowledge_articles")
    dialog = manage(root, panel)
    dialog.geometry("950x730")
    root.update()
    assert not dialog.candidates.get_children()
    assert "Import documents" in dialog.status.get()
    for control in (dialog.link_button, dialog.remove_button, dialog.footer):
        assert control.winfo_rooty() + control.winfo_height() <= dialog.winfo_rooty() + dialog.winfo_height()
