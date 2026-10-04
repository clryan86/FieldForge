import gc

import pytest
from test_emergency import existing_database, incident

from fieldforge.core.emergency import STATUS_LABELS


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.emergency import EmergencyTab
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; GUI CI requires a display")
    root.geometry("1240x800")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("fieldforge.ui.emergency.messagebox.askyesno", lambda *args, **kwargs: False)
    monkeypatch.setattr("fieldforge.ui.emergency.messagebox.showinfo", lambda *args, **kwargs: None)
    store = existing_database(tmp_path / "ui.db")
    panel = EmergencyTab(root, store)
    panel.pack(fill="both", expand=True, padx=16, pady=16)
    root.update()
    try:
        yield root, panel, store
    finally:
        root.destroy()
        gc.collect()
    assert not errors


def choose(root, panel, record):
    panel.refresh()
    panel.sessions.selection_set(str(record.id))
    root.update()
    assert panel.current.incident.id == record.id


def task_editor(root, panel):
    task = panel.current.tasks[0]
    panel.tasks.selection_set(str(task.id))
    root.update()
    panel.edit_button.invoke()
    root.update()
    return panel.dialog


def test_initial_ui_creates_no_incident(screen):
    _, panel, store = screen
    assert not store.browse() and panel.current is None
    assert str(panel.copy_button['state']) == 'disabled'
    assert "Showing 0 records" in panel.status.get()


def test_new_dialog_previews_existing_template_and_creates_only_on_save(screen):
    root, panel, store = screen
    panel.new_button.invoke()
    root.update()
    editor = panel.dialog
    assert editor.exercise.get() and not store.browse()
    assert editor.text.get("1.0", "end-1c")
    assert str(editor.text['state']) == 'disabled'
    editor.name.set("Fictional drill")
    editor.scenario.set("power_outage")
    editor.show_template()
    editor.save_button.invoke()
    root.update()
    assert panel.dialog is None and len(store.browse()) == 1
    assert panel.current.incident.title == "Fictional drill"
    assert panel.current.done == 0 and "EXERCISE" in panel.heading.get()


def test_failed_creation_keeps_form_and_no_partial_incident(screen):
    root, panel, store = screen
    panel.new()
    panel.dialog.save()
    root.update()
    assert panel.dialog and "Not saved" in panel.dialog.status.get()
    assert not store.browse()


def test_cancel_dirty_creation_needs_confirmation(screen, monkeypatch):
    root, panel, store = screen
    panel.new()
    panel.dialog.name.set("Draft only")
    panel.dialog.close()
    assert panel.dialog
    monkeypatch.setattr("fieldforge.ui.emergency.messagebox.askyesno", lambda *args, **kwargs: True)
    panel.dialog.close()
    root.update()
    assert panel.dialog is None and not store.browse()


def test_task_status_note_save_and_resume(screen):
    root, panel, store = screen
    record = incident(store)
    choose(root, panel, record)
    editor = task_editor(root, panel)
    editor.action_status.set(STATUS_LABELS['done'])
    editor.text.insert("1.0", " Private task note\n\n")
    editor.save()
    root.update()
    assert panel.current.done == 1 and "1/5" in panel.summary.get()
    panel.refresh()
    root.update()
    assert panel.current.tasks[0].note == " Private task note\n\n"
    assert store.detail(record.id).done == 1


def test_blocked_status_requires_explanation(screen):
    root, panel, store = screen
    choose(root, panel, incident(store))
    editor = task_editor(root, panel)
    editor.action_status.set(STATUS_LABELS['blocked'])
    editor.save()
    assert "why" in editor.status.get() and panel.dialog
    editor.text.insert("1.0", "Awaiting appropriate help")
    editor.save()
    root.update()
    assert panel.current.tasks[0].status == 'blocked'


def test_stale_task_save_keeps_edits_visible(screen):
    root, panel, store = screen
    choose(root, panel, incident(store))
    editor = task_editor(root, panel)
    original = panel.current.tasks[0]
    editor.text.insert("1.0", "Unsaved window A")
    store.update_task(original.id, expected_revision=1, status='done', note='Saved window B')
    editor.save()
    root.update()
    assert editor.text.get("1.0", "end-1c") == "Unsaved window A"
    assert "another window" in editor.status.get()
    assert store.detail(original.session_id).tasks[0].note == 'Saved window B'


def test_log_note_appended_and_kept_separate_from_other_incidents(screen):
    root, panel, store = screen
    first, second = incident(store), incident(store)
    choose(root, panel, first)
    panel.note_button.invoke()
    panel.dialog.text.insert("1.0", "Private example observation")
    panel.dialog.save()
    root.update()
    assert "Private example observation" in panel.log.get("1.0", "end")
    assert "Latest 2 of 2" in panel.log.get("1.0", "end")
    choose(root, panel, second)
    assert "Private example observation" not in panel.log.get("1.0", "end")


def test_archive_is_confirmed_readonly_and_reopen_retains_records(screen, monkeypatch):
    root, panel, store = screen
    choose(root, panel, incident(store))
    panel.archive()
    assert panel.current.incident.state == 'active'
    monkeypatch.setattr("fieldforge.ui.emergency.messagebox.askyesno", lambda *args, **kwargs: True)
    panel.archive_button.invoke()
    root.update()
    assert panel.current.incident.state == 'archived'
    assert panel.include_archived.get() and str(panel.note_button['state']) == 'disabled'
    panel.tasks.selection_set(str(panel.current.tasks[0].id))
    root.update()
    assert str(panel.edit_button['state']) == 'disabled'
    panel.archive()
    root.update()
    assert panel.current.incident.state == 'active'
    assert "reopened" in panel.log.get("1.0", "end")


def test_archive_race_is_reported_without_losing_another_note(screen, monkeypatch):
    root, panel, store = screen
    record = incident(store)
    choose(root, panel, record)
    store.add_note(record.id, "Other window note")
    monkeypatch.setattr("fieldforge.ui.emergency.messagebox.askyesno", lambda *args, **kwargs: True)
    panel.archive()
    assert "not changed" in panel.status.get()
    assert store.detail(record.id).incident.state == 'active'


def test_copy_is_explicit_uses_latest_status_and_excludes_private_notes(screen):
    root, panel, store = screen
    record = incident(store)
    choose(root, panel, record)
    task = panel.current.tasks[0]
    store.update_task(task.id, expected_revision=1, status='done', note='PRIVATE_TASK')
    store.add_note(record.id, 'PRIVATE_LOG')
    panel.copy_button.invoke()
    text = root.clipboard_get()
    assert "done: 1/5" in text and record.title in text
    assert 'PRIVATE_TASK' not in text and 'PRIVATE_LOG' not in text
    assert 'system clipboard' in panel.status.get()


def test_error_clears_stale_result_and_close_guard_blocks_modal(screen, monkeypatch):
    root, panel, store = screen
    choose(root, panel, incident(store))
    panel.new()
    first = panel.dialog
    panel.new()
    assert panel.dialog is first and not panel.can_close()
    first.close()
    root.update()
    assert panel.can_close()
    def fail(**kwargs):
        raise OSError("simulated read error")
    monkeypatch.setattr(store, 'browse', fail)
    panel.refresh()
    assert panel.current is None and not panel.sessions.get_children()
    assert "Could not refresh" in panel.status.get()


def test_controls_remain_visible_at_minimum_sizes(screen):
    root, panel, _ = screen
    root.geometry("1000x700")
    panel.new()
    editor = panel.dialog
    editor.geometry("720x640")
    root.update()
    for widget in (panel.copy_button, panel.footer):
        assert widget.winfo_rooty() + widget.winfo_height() <= panel.winfo_rooty() + panel.winfo_height()
    for widget in (editor.save_button, editor.cancel_button, editor.footer):
        assert widget.winfo_rooty() + widget.winfo_height() <= editor.winfo_rooty() + editor.winfo_height()
    assert editor.text.winfo_height() > 50
