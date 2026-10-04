import gc
import threading
import time

import pytest

from fieldforge.knowledge import KnowledgeLibrary
from fieldforge.knowledge.documents import TextDocument, prepare_article


@pytest.fixture
def dialog(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.documents import TextImportDialog

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; use xvfb-run for GUI coverage")
    root.geometry("1100x820")
    callback_errors = []
    root.report_callback_exception = lambda *args: callback_errors.append(args)
    library = KnowledgeLibrary(tmp_path / "library.db")
    finished = []
    frame = TextImportDialog(root, library, finished.append)
    root.update()
    try:
        yield root, frame, library, finished
    finally:
        if not frame._disposed:
            frame.destroy()
        frame._worker.shutdown(wait=True, cancel_futures=True)
        root.destroy()
        gc.collect()
    assert not callback_errors


def wait(root, frame):
    deadline = time.monotonic() + 4
    while frame._busy and not frame._disposed and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    root.update()
    assert not frame._busy or frame._disposed


def load(root, frame, tmp_path, name="ledger.md", raw=b"# Equipment ledger\n\nLabel each tool and record its location.\n"):
    path = tmp_path / name
    path.write_bytes(raw)
    frame.load_path(str(path))
    wait(root, frame)
    assert frame.document is not None
    return path


def authorize(frame):
    frame.acknowledged.set(True)
    frame._update_buttons()


def test_initial_dialog_is_readonly_preview_not_an_import(dialog):
    _, frame, library, finished = dialog
    assert library.count() == 0 and frame.document is None
    assert not frame.acknowledged.get()
    assert str(frame.import_button["state"]) == "disabled"
    assert str(frame.preview["state"]) == "disabled"
    assert not finished


def test_file_picker_loads_visible_snapshot_and_defaults_without_writing(dialog, tmp_path, monkeypatch):
    root, frame, library, _ = dialog
    path = tmp_path / "my_ledger.md"
    path.write_text("# Workshop\n\nLabel tools before recording them.\n", encoding="utf-8")
    monkeypatch.setattr("fieldforge.ui.documents.filedialog.askopenfilename", lambda **kwargs: str(path))
    frame.choose_button.invoke()
    wait(root, frame)
    assert "# Workshop" in frame.preview.get("1.0", "end")
    assert frame.fields["title"].get() == "my ledger"
    assert frame.fields["source_url"].get() == frame.fields["reviewed_on"].get() == ""
    assert "Complete captured text" in frame.preview_notice.get()
    assert str(tmp_path) not in frame.info.get()
    assert library.count() == 0


def test_file_picker_cancel_has_no_effect(dialog, monkeypatch):
    _, frame, library, _ = dialog
    monkeypatch.setattr("fieldforge.ui.documents.filedialog.askopenfilename", lambda **kwargs: "")
    frame.choose_button.invoke()
    assert not frame._busy and frame.document is None and library.count() == 0


def test_import_requires_acknowledgment_even_when_called_directly(dialog, tmp_path):
    root, frame, library, _ = dialog
    load(root, frame, tmp_path)
    frame.import_document()
    assert not frame._busy and library.count() == 0
    assert "permission" in frame.status.get()


def test_confirmed_import_stores_metadata_exact_text_and_closes(dialog, tmp_path):
    root, frame, library, finished = dialog
    path = load(root, frame, tmp_path, raw=b"Exact snapshot\r\n\r\n")
    frame.fields["title"].set("My chosen title")
    frame.fields["source_publisher"].set("Owner supplied")
    frame.fields["tags"].set("equipment, ledger")
    frame.fields["license"].set("Owner's supplied terms")
    slug = frame.fields["slug"].get()
    authorize(frame)
    frame.import_button.invoke()
    wait(root, frame)
    assert frame._disposed and len(finished) == 1
    assert finished[0].status == "added"
    article = library.get(slug)
    assert article.body.encode() == path.read_bytes()
    assert article.title == "My chosen title" and article.source_publisher == "Owner supplied"
    assert article.tags == ("equipment", "ledger")


def test_editing_source_after_preview_does_not_change_the_import(dialog, tmp_path):
    root, frame, library, _ = dialog
    path = load(root, frame, tmp_path)
    expected = frame.document.body
    slug = frame.document.suggested_id
    path.write_text("Replacement text", encoding="utf-8")
    authorize(frame)
    frame.import_document()
    wait(root, frame)
    assert library.get(slug).body == expected


def test_failed_second_load_cannot_import_the_previous_file(dialog, tmp_path):
    root, frame, library, _ = dialog
    load(root, frame, tmp_path)
    authorize(frame)
    frame.load_path(str(tmp_path / "unsupported.pdf"))
    wait(root, frame)
    assert frame.document is None and not frame.acknowledged.get()
    assert "No document loaded" in frame.info.get()
    assert frame.preview.get("1.0", "end-1c") == ""
    assert str(frame.import_button["state"]) == "disabled"
    frame.import_document()
    assert library.count() == 0


def test_invalid_metadata_keeps_preview_for_correction(dialog, tmp_path):
    root, frame, library, _ = dialog
    load(root, frame, tmp_path)
    frame.fields["source_url"].set("file:///secret")
    authorize(frame)
    frame.import_document()
    assert not frame._busy and not frame._disposed
    assert library.count() == 0 and frame.document is not None
    assert "Check article details" in frame.status.get()
    assert frame.tabs.index(frame.tabs.select()) == 1


def test_cancel_discards_preview_without_writing(dialog, tmp_path):
    root, frame, library, finished = dialog
    load(root, frame, tmp_path)
    authorize(frame)
    frame.close_button.invoke()
    root.update()
    assert frame._disposed and finished == [None]
    assert library.count() == 0


def test_identical_existing_document_reports_unchanged(dialog, tmp_path):
    root, frame, library, finished = dialog
    load(root, frame, tmp_path)
    existing = prepare_article(frame.document, title=frame.fields["title"].get(), category="local documents")
    library.upsert(existing)
    library.annotate(existing.slug, bookmarked=True, note="Keep this note")
    authorize(frame)
    frame.import_document()
    wait(root, frame)
    assert finished[0].status == "unchanged" and library.count() == 1
    assert library.annotation(existing.slug)["note"] == "Keep this note"


def test_existing_conflict_is_visible_and_never_clobbered(dialog, tmp_path):
    root, frame, library, finished = dialog
    load(root, frame, tmp_path)
    existing = prepare_article(frame.document, title="Previous edit", category="local documents")
    library.upsert(existing)
    authorize(frame)
    frame.import_document()
    wait(root, frame)
    assert not frame._disposed and not finished
    assert "Nothing was replaced" in frame.status.get()
    assert library.get(existing.slug) == existing
    assert str(frame.import_button["state"]) == "normal"


def test_long_preview_is_labeled_but_import_keeps_all_text(dialog, tmp_path):
    root, frame, library, _ = dialog
    raw = b"entry\n" * 4000
    load(root, frame, tmp_path, raw=raw)
    assert "ENTIRE captured text" in frame.preview_notice.get()
    assert len(frame.preview.get("1.0", "end-1c")) == 20000
    slug = frame.document.suggested_id
    authorize(frame)
    frame.import_document()
    wait(root, frame)
    assert library.get(slug).body == raw.decode()


def test_read_and_commit_run_off_ui_thread(dialog, tmp_path, monkeypatch):
    root, frame, _, _ = dialog
    from fieldforge.ui import documents

    main_thread = threading.get_ident()
    read_threads, write_threads = [], []
    original_read, original_write = documents.read_text_document, documents.commit_document

    def read(*args):
        read_threads.append(threading.get_ident())
        return original_read(*args)

    def write(*args, **kwargs):
        write_threads.append(threading.get_ident())
        return original_write(*args, **kwargs)

    monkeypatch.setattr(documents, "read_text_document", read)
    monkeypatch.setattr(documents, "commit_document", write)
    load(root, frame, tmp_path)
    authorize(frame)
    frame.import_document()
    wait(root, frame)
    assert read_threads and write_threads
    assert main_thread not in read_threads + write_threads


def test_close_during_commit_is_blocked_and_result_delivered(dialog, tmp_path, monkeypatch):
    root, frame, library, finished = dialog
    from fieldforge.ui import documents

    load(root, frame, tmp_path)
    original = documents.commit_document
    started, proceed = threading.Event(), threading.Event()

    def delayed(*args, **kwargs):
        started.set()
        proceed.wait(2)
        return original(*args, **kwargs)

    monkeypatch.setattr(documents, "commit_document", delayed)
    authorize(frame)
    frame.import_document()
    assert started.wait(1)
    frame.close()
    assert not frame._disposed and not finished
    assert "Wait" in frame.status.get()
    assert str(frame.choose_button["state"]) == "disabled"
    proceed.set()
    wait(root, frame)
    assert library.count() == 1 and finished[0].status == "added"


def test_cancel_during_read_discards_late_result_without_writing(dialog, monkeypatch):
    root, frame, library, finished = dialog
    started, proceed = threading.Event(), threading.Event()

    def delayed(*args):
        started.set()
        proceed.wait(2)
        return TextDocument("late.txt", b"Not imported")

    monkeypatch.setattr("fieldforge.ui.documents.read_text_document", delayed)
    frame.load_path("late.txt")
    assert started.wait(1)
    frame.close()
    proceed.set()
    frame._worker.shutdown(wait=True)
    root.update()
    assert frame._disposed and finished == [None] and library.count() == 0


def test_write_failure_keeps_preview_and_does_not_claim_success(dialog, tmp_path, monkeypatch):
    root, frame, library, finished = dialog
    load(root, frame, tmp_path)

    def fail(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("fieldforge.ui.documents.commit_document", fail)
    authorize(frame)
    frame.import_document()
    wait(root, frame)
    assert "simulated disk failure" in frame.status.get()
    assert not frame._disposed and frame.document is not None and not finished
    assert library.count() == 0


def test_new_load_resets_source_claims_and_consent(dialog, tmp_path):
    root, frame, _, _ = dialog
    load(root, frame, tmp_path)
    frame.fields["source_publisher"].set("First author")
    frame.fields["reviewed_on"].set("2025-01-01")
    authorize(frame)
    load(root, frame, tmp_path, name="second.md", raw=b"Second document")
    assert frame.fields["source_publisher"].get() == ""
    assert frame.fields["reviewed_on"].get() == ""
    assert not frame.acknowledged.get()


def test_confirmation_and_cancel_remain_visible_at_minimum_size(dialog):
    root, frame, _, _ = dialog
    frame.geometry("780x650")
    root.update()
    for widget in (frame.import_button, frame.consent, frame.close_button):
        bottom = widget.winfo_rooty() - frame.winfo_rooty() + widget.winfo_height()
        assert bottom <= frame.winfo_height()
    assert frame.preview.winfo_height() > 80
