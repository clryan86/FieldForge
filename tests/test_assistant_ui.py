import gc
import threading
import time
from concurrent.futures import Future
from dataclasses import replace

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.assistant import SearchCancelled


@pytest.fixture
def reader(tmp_path, monkeypatch):
    # Collect disposed Tcl interpreters on the UI thread before starting workers.
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.assistant import AskLibraryTab

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; run under xvfb-run for graphical coverage")
    root.geometry("1240x840")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("fieldforge.ui.assistant.messagebox.showerror", lambda *args, **kwargs: errors.append(args))
    library = KnowledgeLibrary(tmp_path / "ui.db")
    frame = AskLibraryTab(root, library)
    frame.pack(fill="both", expand=True)
    root.update()
    try:
        yield root, frame, library
    finally:
        def panels(widget):
            found = [widget] if isinstance(widget, AskLibraryTab) else []
            for child in widget.winfo_children():
                found.extend(panels(child))
            return found

        active = panels(root)
        if root.winfo_exists():
            root.destroy()
        # Production close is non-blocking. Tests also join disposed workers
        # before creating the next independent Tcl interpreter.
        for panel in [frame, *active]:
            panel._worker.shutdown(wait=True, cancel_futures=True)
        gc.collect()
    assert not errors


def seed(library):
    source = KnowledgeArticle("water", "Water storage worksheet",
                              "KEEP THE CONTEXT\n\nRecord the water storage date.\n\n"
                              "Never assume a label establishes safety.", "water",
                              source_publisher="Test fixture", safety_level="caution")
    library.upsert(source)
    return source


def wait(root, frame):
    deadline = time.monotonic() + 4
    while frame.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    assert not frame.busy
    root.update()


def texts(widget):
    found = []
    if widget.winfo_class() == "Text":
        found.append(widget)
    for child in widget.winfo_children():
        found.extend(texts(child))
    return found


def test_initial_view_is_honest_and_does_not_insert_articles(reader):
    _, frame, library = reader
    assert "not a generated answer" in frame.excerpt.get("1.0", "end")
    assert library.count() == 0
    assert str(frame.open_button["state"]) == "disabled"
    assert not frame.busy and frame.report is None


def test_question_populates_exact_passages_and_source_metadata(reader):
    root, frame, library = reader
    seed(library)
    frame.question.set("How do I store water?")
    frame.ask_button.invoke()
    wait(root, frame)
    assert frame.sources.get_children() == ("S1",)
    assert frame.report.question == "How do I store water?"
    assert "EXACT EXCERPT" in frame.excerpt.get("1.0", "end")
    assert "Never assume" in frame.excerpt.get("1.0", "end")
    assert "CAUTION" in frame.metadata.get() and "Not supplied" in frame.metadata.get()
    assert "not a verified answer" in frame.summary.get()
    assert str(frame.ask_button["state"]) == "normal"


def test_empty_library_guidance_and_no_match_are_different(reader):
    root, frame, library = reader
    frame.question.set("water")
    frame.ask()
    wait(root, frame)
    assert "No articles installed" in frame.summary.get()
    assert "starter library" in frame.excerpt.get("1.0", "end")
    seed(library)
    frame.question.set("orbital resonator")
    frame.ask()
    wait(root, frame)
    assert "not proof" in frame.summary.get()
    assert frame.report.library_count == 1


def test_invalid_input_does_not_start_worker(reader):
    _, frame, _ = reader
    frame.question.set("How can you help me?")
    frame.ask()
    assert not frame.busy and frame.report is None
    assert "add a topic" in frame.status.get()


def test_example_button_path_uses_real_local_question(reader):
    root, frame, library = reader
    seed(library)
    frame.example("How do I store water?")
    wait(root, frame)
    assert frame.report.references and frame.category.get() == "All categories"


def test_category_refresh_and_filter(reader):
    root, frame, library = reader
    seed(library)
    frame.refresh_categories()
    assert "water" in frame.categories["values"]
    frame.category.set("not installed category")
    frame.question.set("water")
    frame.ask()
    wait(root, frame)
    assert not frame.report.references and frame.report.category == "not installed category"
    frame.category.set("water")
    frame.ask()
    wait(root, frame)
    assert frame.report.references


def test_full_source_opens_captured_version_and_highlights_quote(reader):
    root, frame, library = reader
    original = seed(library)
    frame.question.set("water")
    frame.ask()
    wait(root, frame)
    library.upsert(replace(original, body="Changed article after the search."))
    window = frame.open_source()
    root.update()
    body = texts(window)[0]
    assert body.get("1.0", "end-1c") == original.body
    assert body.tag_ranges("passage")
    assert str(body["state"]) == "disabled"
    window.destroy()


def test_clipboard_copy_is_explicit_and_contains_provenance(reader):
    root, frame, library = reader
    seed(library)
    frame.question.set("water")
    frame.ask()
    wait(root, frame)
    frame.copy_button.invoke()
    copied = root.clipboard_get()
    assert "Question: water" in copied
    assert "[S1]" in copied and "Body SHA-256" in copied
    assert "not an AI-generated answer" in copied
    assert "system clipboard" in frame.status.get()


def test_clear_removes_displayed_question_and_disables_stale_source_actions(reader):
    root, frame, library = reader
    seed(library)
    frame.question.set("water")
    frame.ask()
    wait(root, frame)
    frame.clear()
    assert frame.report is None and not frame.question.get()
    assert not frame.sources.get_children()
    assert str(frame.open_button["state"]) == "disabled"
    assert str(frame.copy_button["state"]) == "disabled"
    assert "does not clear" in frame.status.get()


def test_cancel_and_late_result_never_repopulate_cleared_view(reader, monkeypatch):
    root, frame, library = reader
    seed(library)
    real_ask = frame.assistant.ask
    started, released, finished = threading.Event(), threading.Event(), threading.Event()

    def delayed(*args, **kwargs):
        started.set()
        released.wait(2)
        try:
            return real_ask(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(frame.assistant, "ask", delayed)
    frame.question.set("water")
    frame.ask()
    assert started.wait(1)
    frame.clear()
    released.set()
    assert finished.wait(1)
    root.update()
    assert frame.report is None and not frame.sources.get_children()
    assert not frame.busy


def test_stale_poll_generation_does_not_display_previous_question(reader):
    _, frame, library = reader
    seed(library)
    old = Future()
    old.set_result(frame.assistant.ask("water"))
    frame._generation = 5
    frame._poll(old, 4)
    assert frame.report is None


def test_worker_failure_shown_without_fake_answer_or_tk_callback_error(reader, monkeypatch):
    root, frame, _ = reader

    def fail(*args, **kwargs):
        raise OSError("simulated locked file")

    monkeypatch.setattr(frame.assistant, "ask", fail)
    frame.question.set("water")
    frame.ask()
    wait(root, frame)
    assert "did not complete" in frame.summary.get()
    assert "simulated locked file" in frame.status.get()
    assert frame.report is None


def test_worker_uses_separate_thread_and_ui_results_use_main_thread(reader, monkeypatch):
    root, frame, library = reader
    seed(library)
    main_thread = threading.get_ident()
    worker_threads = []
    ui_threads = []
    ask = frame.assistant.ask
    show = frame._show_report

    def observe_ask(*args, **kwargs):
        worker_threads.append(threading.get_ident())
        return ask(*args, **kwargs)

    def observe_show(report):
        ui_threads.append(threading.get_ident())
        return show(report)

    monkeypatch.setattr(frame.assistant, "ask", observe_ask)
    monkeypatch.setattr(frame, "_show_report", observe_show)
    frame.question.set("water")
    frame.ask()
    wait(root, frame)
    assert worker_threads and worker_threads[0] != main_thread
    assert ui_threads == [main_thread]


def test_destroy_cancels_worker_without_tk_access_from_worker(reader, monkeypatch):
    root, frame, _ = reader
    started, stopped = threading.Event(), threading.Event()

    def search(*args, cancel, **kwargs):
        started.set()
        cancel.wait(2)
        stopped.set()
        raise SearchCancelled()

    monkeypatch.setattr(frame.assistant, "ask", search)
    frame.question.set("water")
    frame.ask()
    assert started.wait(1)
    frame.destroy()
    assert stopped.wait(1)
    root.update()
    assert frame._destroyed


def test_editing_input_does_not_relabel_an_existing_search_snapshot(reader):
    root, frame, library = reader
    seed(library)
    frame.question.set("water")
    frame.ask()
    wait(root, frame)
    frame.question.set("different unsent question")
    assert frame.report.question == "water"
    assert "Question: water" in frame.summary.get()


def test_notebook_integration_installs_a_functional_tab(reader):
    root, original, library = reader
    from tkinter import ttk

    from fieldforge.ui.assistant import add_ask_library_tab

    original.pack_forget()
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)
    frame = add_ask_library_tab(notebook, library)
    root.update()
    assert notebook.tab(frame, "text") == "Ask Library"
    seed(library)
    frame.question.set("water")
    frame.ask()
    wait(root, frame)
    assert frame.report.references


def test_stale_poll_does_not_lose_newer_callback_identifier(reader):
    _, frame, library = reader
    seed(library)
    future = Future()
    future.set_result(frame.assistant.ask("water"))
    frame._generation = 2
    identifier = frame.after(2000, lambda: None)
    frame._poll_id = identifier
    frame._poll(future, 1)
    assert frame._poll_id == identifier
    frame.after_cancel(identifier)
    frame._poll_id = None


def test_warning_footer_and_source_button_remain_visible_at_minimum_size(reader):
    root, frame, library = reader
    root.geometry("1000x700")
    seed(library)
    frame.question.set("water")
    frame.ask()
    wait(root, frame)
    assert frame.footer.winfo_y() + frame.footer.winfo_height() <= frame.winfo_height()
    button = frame.open_button
    assert button.winfo_y() + button.winfo_height() <= button.master.winfo_height()
    assert frame.excerpt.winfo_height() > 60
