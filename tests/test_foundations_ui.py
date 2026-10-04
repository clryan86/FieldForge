import gc
import threading
import time
from dataclasses import replace

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.foundations import foundation_articles
from fieldforge.knowledge.pathways import PathwayStore


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip('tkinter')
    from fieldforge.ui.knowledge import KnowledgeTab
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip('Tk display unavailable; dedicated GUI CI requires a display')
    root.geometry('1240x850')
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    library = KnowledgeLibrary(tmp_path/'library.db')
    panel = KnowledgeTab(root, library)
    panel.pack(fill='both', expand=True)
    root.update()
    dialogs = []
    try:
        yield root, panel, library, dialogs
    finally:
        for dialog in dialogs:
            if not dialog._disposed:
                dialog.destroy()
            dialog._worker.shutdown(wait=True, cancel_futures=True)
        root.destroy()
        panel._worker.shutdown(wait=True, cancel_futures=True)
        gc.collect()
    assert not errors


def wait(root, dialog):
    deadline = time.monotonic()+6
    while dialog.busy and not dialog._disposed and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    root.update()
    assert not dialog.busy or dialog._disposed


def open_pack(root, panel, dialogs):
    from fieldforge.ui.foundations import FoundationsDialog
    panel.foundations_button.invoke()
    root.update()
    dialog = next(child for child in panel.winfo_children() if isinstance(child, FoundationsDialog))
    dialogs.append(dialog)
    wait(root, dialog)
    return dialog


def test_open_preview_is_not_installation_and_lists_actual_lessons(screen):
    root, panel, library, dialogs = screen
    dialog = open_pack(root, panel, dialogs)
    assert len(dialog.tree.get_children()) == 20
    assert 'WORKED EXAMPLE' in dialog.body.get('1.0', 'end')
    assert '20 not installed' in dialog.status.get()
    assert library.count() == 0 and panel.busy and not panel.save_current()
    assert str(dialog.install_button['state']) == 'disabled'
    dialog.close()
    assert not panel.busy and library.count() == 0


def test_practice_checks_exact_numbers_and_shows_steps_without_records(screen):
    root, panel, library, dialogs = screen
    store = PathwayStore(library)
    before = library.database_path.read_bytes()
    dialog = open_pack(root, panel, dialogs)
    dialog.tabs.select(1)
    dialog.response.set('67')
    dialog.check_button.invoke()
    assert 'Matches this exercise' in dialog.feedback.get()
    assert '5 × 12 + 7' in dialog.feedback_text.get('1.0', 'end')
    dialog.response.set('68')
    assert 'Answer changed' in dialog.feedback.get()
    dialog.check()
    assert 'Not yet' in dialog.feedback.get()
    dialog.response.set('1/0')
    dialog.check()
    assert 'nonzero denominator' in dialog.feedback.get()
    dialog.answer_button.invoke()
    assert 'Worked answer: 67 cards' in dialog.feedback.get()
    assert library.count() == 0
    assert store.progress('measurement').revision == 0
    assert library.database_path.read_bytes() == before


def test_lesson_and_exercise_navigation_clear_previous_answer(screen):
    root, panel, _, dialogs = screen
    dialog = open_pack(root, panel, dialogs)
    dialog.response.set('67')
    dialog.check()
    dialog.exercise_picker.current(1)
    dialog.choose_exercise()
    assert dialog.response.get() == '' and '84 cards' in dialog.question.get()
    dialog.next.invoke()
    root.update()
    assert dialog.selected == 1 and 'Arithmetic' in dialog.lesson_title.get()
    assert '18 + 6' in dialog.question.get()
    dialog.previous.invoke()
    root.update()
    assert dialog.selected == 0
    assert str(dialog.previous['state']) == 'disabled'


def test_install_requires_acknowledgment_refreshes_actual_library_and_preserves_note(screen):
    root, panel, library, dialogs = screen
    library.upsert(KnowledgeArticle('mine', 'My article', 'Local user text', 'records'))
    panel.refresh()
    panel.results.selection_set('mine')
    root.update()
    panel.note.insert('1.0', 'PRIVATE_PENDING_NOTE')
    dialog = open_pack(root, panel, dialogs)
    assert library.annotation('mine')['note'] == 'PRIVATE_PENDING_NOTE'
    dialog.install()
    assert library.count() == 1
    dialog.acknowledged.set(True)
    dialog._buttons()
    dialog.install_button.invoke()
    wait(root, dialog)
    assert len(dialog.result.added) == 20 and library.count() == 21
    dialog.close()
    root.update()
    assert not panel.busy
    assert panel.query.get() == 'foundations' and len(panel.results.get_children()) == 20
    assert library.annotation('mine')['note'] == 'PRIVATE_PENDING_NOTE'


def test_existing_edited_copy_is_not_the_bundled_preview_and_is_preserved(screen):
    root, panel, library, dialogs = screen
    article = replace(foundation_articles()[0], body='My edited installed edition')
    library.upsert(article)
    dialog = open_pack(root, panel, dialogs)
    assert 'preserved' in dialog.lesson_info.get()
    assert 'My edited installed edition' not in dialog.body.get('1.0', 'end')
    assert 'BUNDLED EDITION PREVIEW' in dialog.lesson_info.get()
    dialog.acknowledged.set(True)
    dialog.install()
    wait(root, dialog)
    assert dialog.result.preserved == (article.slug,)
    assert library.get(article.slug) == article


def test_failed_install_leaves_preview_and_does_not_claim_success(screen, monkeypatch):
    root, panel, library, dialogs = screen
    dialog = open_pack(root, panel, dialogs)
    def fail(*args, **kwargs):
        raise OSError('Simulated disk error')
    monkeypatch.setattr('fieldforge.ui.foundations.install_foundations', fail)
    dialog.acknowledged.set(True)
    dialog.install()
    wait(root, dialog)
    assert 'Operation failed' in dialog.status.get() and dialog.result is None
    assert 'WORKED EXAMPLE' in dialog.body.get('1.0', 'end')
    assert library.count() == 0


def test_close_and_duplicate_install_guard_while_worker_runs(screen, monkeypatch):
    root, panel, _, dialogs = screen
    from fieldforge.ui import foundations
    dialog = open_pack(root, panel, dialogs)
    original = foundations.install_foundations
    started, release = threading.Event(), threading.Event()
    calls = []
    def delayed(*args, **kwargs):
        calls.append(True)
        started.set()
        release.wait(3)
        return original(*args, **kwargs)
    monkeypatch.setattr(foundations, 'install_foundations', delayed)
    dialog.acknowledged.set(True)
    dialog.install()
    assert started.wait(1)
    dialog.install()
    dialog.close()
    assert not dialog._disposed and panel.busy and calls == [True]
    release.set()
    wait(root, dialog)
    dialog.close()
    assert not panel.busy


def test_construction_failure_and_busy_library_release_or_preserve_guard(screen, monkeypatch):
    _, panel, _, _ = screen
    from fieldforge.ui import foundations
    panel.busy = True
    assert foundations.open_foundations(panel) is None
    panel.busy = False
    def fail(*args, **kwargs):
        raise ValueError('Construction failed')
    monkeypatch.setattr(foundations, 'FoundationsDialog', fail)
    with pytest.raises(ValueError):
        foundations.open_foundations(panel)
    assert not panel.busy


def test_failed_current_note_save_prevents_pack_dialog(screen, monkeypatch):
    _, panel, _, _ = screen
    from fieldforge.ui.foundations import open_foundations
    monkeypatch.setattr(panel, 'save_current', lambda: False)
    assert open_foundations(panel) is None and not panel.busy


def test_installation_runs_off_main_thread_and_callbacks_stay_on_it(screen, monkeypatch):
    root, panel, _, dialogs = screen
    from fieldforge.ui import foundations
    dialog = open_pack(root, panel, dialogs)
    main = threading.get_ident()
    observed = []
    original = foundations.install_foundations
    def install(*args, **kwargs):
        observed.append(threading.get_ident())
        return original(*args, **kwargs)
    monkeypatch.setattr(foundations, 'install_foundations', install)
    dialog.acknowledged.set(True)
    dialog.install()
    wait(root, dialog)
    assert observed and main not in observed
    assert dialog.result is not None


def test_read_inspection_can_close_without_mutation_or_late_widget_access(screen, monkeypatch):
    root, panel, library, dialogs = screen
    from fieldforge.ui import foundations
    started, release = threading.Event(), threading.Event()
    original = foundations.inspect_foundations
    def delayed(*args, **kwargs):
        started.set()
        release.wait(3)
        return original(*args, **kwargs)
    monkeypatch.setattr(foundations, 'inspect_foundations', delayed)
    panel.foundations_button.invoke()
    dialog = next(child for child in panel.winfo_children() if isinstance(child, foundations.FoundationsDialog))
    dialogs.append(dialog)
    assert started.wait(1)
    dialog.close()
    release.set()
    dialog._worker.shutdown(wait=True)
    root.update()
    assert not panel.busy and library.count() == 0 and dialog.result is None


def test_minimum_size_shows_reading_practice_and_install_controls(screen):
    root, panel, _, dialogs = screen
    root.geometry('1000x700')
    root.update()
    assert panel.foundations_button.winfo_rootx()+panel.foundations_button.winfo_width() <= panel.winfo_rootx()+panel.winfo_width()
    dialog = open_pack(root, panel, dialogs)
    dialog.geometry('980x720')
    dialog.tabs.select(1)
    root.update()
    for widget in (dialog.consent, dialog.install_button, dialog.close_button, dialog.check_button, dialog.footer):
        assert widget.winfo_rooty()+widget.winfo_height() <= dialog.winfo_rooty()+dialog.winfo_height()
        assert widget.winfo_rootx()+widget.winfo_width() <= dialog.winfo_rootx()+dialog.winfo_width()
    assert dialog.feedback_text.winfo_height() > 50
    assert dialog.tree.winfo_width() >= 280
    assert dialog.panes.sashpos(0) >= 300
