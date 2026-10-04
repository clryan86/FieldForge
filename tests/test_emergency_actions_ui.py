import gc
import sqlite3
from contextlib import closing

import pytest

from fieldforge.core.emergency import STATUS_LABELS
from fieldforge.core.emergency_actions import ActionStore


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.emergency_actions import ActionWorkspace
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; graphical CI requires a working display")
    root.geometry("1240x840")
    path = tmp_path / "test.db"
    with closing(sqlite3.connect(path)):
        pass
    store = ActionStore(path)
    failures = []
    root.report_callback_exception = lambda *args: failures.append(args)
    monkeypatch.setattr("fieldforge.ui.emergency_actions.messagebox.askyesno", lambda *args, **kwargs: False)
    monkeypatch.setattr("fieldforge.ui.emergency_actions.messagebox.showinfo", lambda *args, **kwargs: None)
    panel = ActionWorkspace(root, store)
    panel.pack(fill="both", expand=True, padx=12, pady=12)
    root.update()
    try:
        yield root, panel, store
    finally:
        root.destroy()
        gc.collect()
    assert not failures


def select_session(root, panel, store):
    session = store.create("Fictional exercise", "power_outage")
    panel.refresh()
    panel.sessions.selection_set(str(session.id))
    root.update()
    assert panel.current.incident.id == session.id
    return session


def select_task(root, panel, task_id):
    panel.tasks.selection_set(str(task_id))
    root.update()
    assert panel.selected_task().id == task_id


def fill_custom(editor):
    editor.task_title.set("Count labelled containers")
    editor.reason.insert("1.0", "Put the exercise count in the record sheet.\n\n")
    editor.responsible.set("Cedar team")
    editor.priority.set("high")


def test_empty_workspace_has_no_fake_incident_or_assignment(screen):
    _, panel, store = screen
    assert not store.browse() and panel.current is None
    assert str(panel.add_action_button["state"]) == "disabled"
    assert "do not send notifications" in panel.notice["text"]


def test_new_incident_flow_still_creates_original_exercise(screen):
    root, panel, store = screen
    panel.new_button.invoke()
    panel.dialog.name.set("Separate drill")
    panel.dialog.save()
    root.update()
    assert panel.current.incident.mode == "exercise"
    assert all(task.origin == "template" for task in panel.current.tasks)
    assert all(not task.responsible for task in panel.current.tasks)
    assert len(store.browse()) == 1


def test_custom_task_creation_is_explicit_visible_and_pending(screen):
    root, panel, store = screen
    session = select_session(root, panel, store)
    panel.add_action_button.invoke()
    fill_custom(panel.dialog)
    assert len(store.detail(session.id).tasks) == 5
    assert str(panel.dialog.status_picker["state"]) == "disabled"
    panel.dialog.save_button.invoke()
    root.update()
    task = panel.current.tasks[-1]
    assert task.origin == "custom" and task.status == "pending" and task.responsible == "Cedar team"
    assert "User-added" in panel.tasks.item(str(task.id), "text")
    assert panel.tasks.set(str(task.id), "responsible") == "Cedar team"
    assert panel.dialog is None and len(store.detail(session.id).tasks) == 6


def test_template_editor_locks_wording_but_can_assign_and_record_progress(screen):
    root, panel, store = screen
    session = select_session(root, panel, store)
    task = panel.current.tasks[0]
    select_task(root, panel, task.id)
    panel.edit_button.invoke()
    editor = panel.dialog
    assert str(editor.title_entry["state"]) == "readonly"
    assert str(editor.reason["state"]) == "disabled"
    assert str(editor.priority_picker["state"]) == "disabled"
    editor.responsible.set("Maple alias")
    editor.action_status.set(STATUS_LABELS["in_progress"])
    editor.text.insert("1.0", "Private update\n\n")
    editor.save()
    root.update()
    changed = store.get_task(task.id)
    assert changed.responsible == "Maple alias" and changed.note == "Private update\n\n"
    assert changed.title == task.title and changed.reason == task.reason
    assert store.detail(session.id).incident.template_sha256 == session.template_sha256


def test_template_service_rejects_even_programmatic_edit_from_dialog(screen):
    root, panel, store = screen
    select_session(root, panel, store)
    task = panel.current.tasks[0]
    select_task(root, panel, task.id)
    panel.edit_task()
    panel.dialog.task_title.set("Attempted rewrite")
    panel.dialog.save()
    assert "frozen" in panel.dialog.status.get()
    assert store.get_task(task.id) == task


def test_custom_task_details_can_be_corrected_without_relabelling_as_template(screen):
    root, panel, store = screen
    session = select_session(root, panel, store)
    task = store.add_custom(session.id, expected_revision=session.revision, title="First title", reason="First context")
    panel.refresh()
    select_task(root, panel, task.id)
    panel.edit_task()
    assert str(panel.dialog.title_entry["state"]) == "normal"
    panel.dialog.task_title.set("Corrected title")
    panel.dialog.reason.delete("1.0", "end")
    panel.dialog.reason.insert("1.0", "Corrected context")
    panel.dialog.save()
    root.update()
    assert store.get_task(task.id).title == "Corrected title"
    assert store.get_task(task.id).origin == "custom"


def test_stale_assignment_preserves_unsaved_alias_and_newer_record(screen):
    root, panel, store = screen
    select_session(root, panel, store)
    task = panel.current.tasks[0]
    select_task(root, panel, task.id)
    panel.edit_task()
    panel.dialog.responsible.set("Unsaved alias A")
    newer = store.update_task(task.id, expected_revision=task.revision, status=task.status,
                              note=task.note, responsible="Saved alias B")
    panel.dialog.save()
    assert panel.dialog.responsible.get() == "Unsaved alias A"
    assert "another window" in panel.dialog.status.get()
    assert store.get_task(task.id) == newer


def test_stale_incident_add_keeps_entered_task_text(screen):
    root, panel, store = screen
    session = select_session(root, panel, store)
    panel.add_action()
    fill_custom(panel.dialog)
    store.add_note(session.id, "Another window updated this incident")
    panel.dialog.save()
    assert "incident changed" in panel.dialog.status.get()
    assert panel.dialog.task_title.get() == "Count labelled containers"
    assert len(store.detail(session.id).tasks) == 5


def test_cancel_requires_confirmation_and_parent_close_is_guarded(screen, monkeypatch):
    root, panel, store = screen
    select_session(root, panel, store)
    panel.add_action()
    original = panel.dialog
    fill_custom(original)
    panel.add_action()
    assert panel.dialog is original and not panel.can_close()
    original.close()
    assert panel.dialog is original
    monkeypatch.setattr("fieldforge.ui.emergency_actions.messagebox.askyesno", lambda *args, **kwargs: True)
    original.close()
    root.update()
    assert panel.dialog is None and panel.can_close()
    assert len(panel.current.tasks) == 5


def test_archived_records_disable_custom_changes_but_reopen_retains_alias(screen, monkeypatch):
    root, panel, store = screen
    select_session(root, panel, store)
    task = panel.current.tasks[0]
    store.update_task(task.id, expected_revision=task.revision, status=task.status, note="", responsible="Keep this alias")
    panel.refresh()
    monkeypatch.setattr("fieldforge.ui.emergency_actions.messagebox.askyesno", lambda *args, **kwargs: True)
    panel.archive()
    root.update()
    assert panel.current.incident.state == "archived"
    assert str(panel.add_action_button["state"]) == "disabled"
    select_task(root, panel, task.id)
    assert str(panel.edit_button["state"]) == "disabled"
    panel.add_action()
    assert panel.dialog is None
    panel.archive()
    root.update()
    assert panel.current.incident.state == "active"
    assert store.get_task(task.id).responsible == "Keep this alias"


def test_clipboard_copy_labels_user_content_and_excludes_private_fields(screen):
    root, panel, store = screen
    session = select_session(root, panel, store)
    task = store.add_custom(session.id, expected_revision=session.revision, title="Visible task", reason="Visible description",
                             responsible="SECRET_RESPONSIBLE")
    store.update_task(task.id, expected_revision=task.revision, status="blocked", note="SECRET_TASK_NOTE")
    store.add_note(session.id, "SECRET_JOURNAL")
    panel.refresh()
    panel.copy_button.invoke()
    text = root.clipboard_get()
    assert "[User-added] Visible task" in text and "Visible description" in text
    assert "SECRET_" not in text
    assert "titles" in panel.status.get().lower()


def test_save_failure_keeps_editor_no_false_success(screen, monkeypatch):
    root, panel, store = screen
    select_session(root, panel, store)
    panel.add_action()
    fill_custom(panel.dialog)
    def fail(*args, **kwargs):
        raise OSError("Storage error")
    monkeypatch.setattr(store, "add_custom", fail)
    panel.dialog.save()
    assert panel.dialog is not None and "Storage error" in panel.dialog.status.get()
    assert len(panel.current.tasks) == 5


def test_blocked_requires_reason_and_does_not_send_anything(screen):
    root, panel, store = screen
    select_session(root, panel, store)
    task = panel.current.tasks[0]
    select_task(root, panel, task.id)
    panel.edit_task()
    panel.dialog.action_status.set(STATUS_LABELS["blocked"])
    panel.dialog.save()
    assert "why the action is blocked" in panel.dialog.status.get()
    assert store.get_task(task.id).status == "pending"


def test_action_buttons_and_editor_controls_visible_at_minimum_size(screen):
    root, panel, store = screen
    root.geometry("1000x700")
    select_session(root, panel, store)
    root.update()
    for widget in (panel.add_action_button, panel.edit_button, panel.copy_button):
        assert widget.winfo_rooty() + widget.winfo_height() <= panel.winfo_rooty() + panel.winfo_height()
    assert panel.add_action_button.winfo_x() >= panel.edit_button.winfo_x() + panel.edit_button.winfo_width()
    panel.add_action()
    panel.dialog.geometry("740x650")
    root.update()
    for widget in (panel.dialog.notice, panel.dialog.save_button, panel.dialog.footer):
        assert widget.winfo_rooty() + widget.winfo_height() <= panel.dialog.winfo_rooty() + panel.dialog.winfo_height()
    assert panel.dialog.reason.winfo_height() > 60


def test_editing_completed_custom_task_requires_review_status(screen):
    root, panel, store = screen
    session = select_session(root, panel, store)
    task = store.add_custom(session.id, expected_revision=session.revision, title="Original task", reason="Original context")
    task = store.update_task(task.id, expected_revision=task.revision, status="done", note="")
    panel.refresh()
    select_task(root, panel, task.id)
    panel.edit_task()
    panel.dialog.task_title.set("Changed task")
    panel.dialog.save()
    assert "Task details changed" in panel.dialog.status.get()
    panel.dialog.action_status.set(STATUS_LABELS["pending"])
    panel.dialog.save()
    root.update()
    assert store.get_task(task.id).status == "pending"
