import gc
from dataclasses import replace

import pytest
from test_household import database, profile


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.household import HouseholdTab

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; GUI CI runs with a required display")
    root.geometry("1120x760")
    errors, changes = [], []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("fieldforge.ui.household.messagebox.askyesno", lambda *args, **kwargs: False)
    monkeypatch.setattr("fieldforge.ui.household.messagebox.showinfo", lambda *args, **kwargs: None)
    service = database(tmp_path / "ui.db")
    panel = HouseholdTab(root, service, on_change=lambda: changes.append(True))
    panel.pack(fill="both", expand=True)
    root.update()
    try:
        yield root, panel, service, changes
    finally:
        root.destroy()
        gc.collect()
    assert not errors


def fill(dialog, *, kind="Adult", water="3", calories="2000"):
    for key, value in {"name": "Fictional planner", "kind": kind, "water": water, "calories": calories}.items():
        dialog.fields[key].set(value)


def select(root, panel, record):
    panel.refresh()
    panel.tree.selection_set(str(record.member.id))
    root.update()


def test_add_is_explicit_and_does_not_seed_real_or_default_records(screen):
    root, panel, service, changes = screen
    assert not service.browse()
    panel.add_button.invoke()
    root.update()
    dialog = panel.dialog
    assert dialog.fields["water"].get() == dialog.fields["calories"].get() == ""
    dialog.fields["kind"].set("Pet")
    assert dialog.fields["water"].get() == dialog.fields["calories"].get() == ""
    fill(dialog)
    dialog.note.insert("1.0", "Local planning note\n\n")
    dialog.save_button.invoke()
    root.update()
    assert panel.dialog is None and len(service.browse()) == 1
    assert service.browse()[0].member.notes == "Local planning note\n\n"
    assert changes == [True]


def test_edit_preserves_existing_allowances_until_explicitly_changed(screen):
    root, panel, service, changes = screen
    record = service.save(profile(is_child=True))
    select(root, panel, record)
    panel.edit_button.invoke()
    root.update()
    dialog = panel.dialog
    assert dialog.fields["kind"].get() == "Child"
    assert dialog.fields["water"].get() == "3.0"
    dialog.fields["kind"].set("Adult")
    assert dialog.fields["water"].get() == "3.0"
    assert dialog.note.get("1.0", "end-1c") == record.member.notes
    dialog.fields["water"].set("4")
    dialog.fields["name"].set("Changed alias")
    dialog.save()
    root.update()
    updated = service.get(record.member.id).member
    assert updated.name == "Changed alias" and updated.daily_water_liters == 4 and not updated.is_child
    assert changes == [True] and "4 liters/day" in panel.summary.get()


def test_invalid_allowances_leave_dirty_form_open(screen):
    root, panel, service, changes = screen
    panel.add()
    fill(panel.dialog, water="NaN")
    panel.dialog.save()
    root.update()
    assert panel.dialog and "Not saved" in panel.dialog.status.get()
    assert not service.browse() and not changes


def test_zero_calories_need_separate_confirmation(screen, monkeypatch):
    root, panel, service, _ = screen
    panel.add()
    fill(panel.dialog, calories="0")
    panel.dialog.save()
    assert panel.dialog and not service.browse()
    prompts = []
    monkeypatch.setattr("fieldforge.ui.household.messagebox.askyesno", lambda *args, **kwargs: prompts.append(args) or True)
    panel.dialog.save()
    root.update()
    assert "planning exclusion" in prompts[0][1]
    assert service.summary().zero_calorie_profiles == 1


def test_cancel_requires_discard_confirmation(screen, monkeypatch):
    root, panel, service, _ = screen
    panel.add()
    fill(panel.dialog)
    panel.dialog.close()
    assert panel.dialog is not None
    monkeypatch.setattr("fieldforge.ui.household.messagebox.askyesno", lambda *args, **kwargs: True)
    panel.dialog.close()
    root.update()
    assert panel.dialog is None and not service.browse()


def test_conflict_does_not_close_editor_or_overwrite_newer_notes(screen):
    root, panel, service, _ = screen
    old = service.save(profile())
    select(root, panel, old)
    panel.edit()
    panel.dialog.fields["name"].set("Unsaved window A")
    newer = service.save(replace(old.member, notes="Saved window B"), expected=old.token)
    panel.dialog.save()
    root.update()
    assert panel.dialog.fields["name"].get() == "Unsaved window A"
    assert "another window" in panel.dialog.status.get()
    assert service.get(old.member.id) == newer


def test_remove_confirmed_recalculates_and_does_not_copy_notes_to_log(screen, monkeypatch):
    root, panel, service, changes = screen
    record = service.save(profile())
    select(root, panel, record)
    panel.remove()
    assert service.get(record.member.id) == record
    prompts = []
    monkeypatch.setattr("fieldforge.ui.household.messagebox.askyesno", lambda *args, **kwargs: prompts.append(args) or True)
    panel.remove_button.invoke()
    root.update()
    assert not service.browse() and changes == [True]
    assert "does not change inventory" in prompts[0][1]
    assert "People: 0" in panel.summary.get()


def test_stale_removal_shows_error_keeps_new_record(screen, monkeypatch):
    root, panel, service, changes = screen
    old = service.save(profile())
    select(root, panel, old)
    newer = service.save(replace(old.member, daily_water_liters=6), expected=old.token)
    monkeypatch.setattr("fieldforge.ui.household.messagebox.askyesno", lambda *args, **kwargs: True)
    panel.remove()
    assert "Not removed" in panel.status.get() and not changes
    assert service.get(old.member.id) == newer


def test_search_filters_and_pagination_do_not_change_summary(screen):
    root, panel, service, _ = screen
    for i in range(52):
        service.save(profile(name=f"Fictional {i:02}"))
    service.save(profile(name="Animal", is_pet=True))
    panel.refresh()
    root.update()
    assert len(panel.tree.get_children()) == 50
    panel.next.invoke()
    assert len(panel.tree.get_children()) == 3
    panel.kind.set("Pets")
    panel.refresh()
    assert len(panel.tree.get_children()) == 1 and "People: 52" in panel.summary.get()
    panel.query.set("No match")
    panel.refresh()
    assert not panel.tree.get_children() and "Pets: 1" in panel.summary.get()
    assert str(panel.edit_button["state"]) == "disabled"


def test_only_one_editor_and_close_guard(screen):
    root, panel, _, _ = screen
    panel.add()
    first = panel.dialog
    panel.add()
    assert panel.dialog is first and not panel.can_close()
    first.close()
    root.update()
    assert panel.can_close()


def test_storage_failure_retains_edited_text(screen, monkeypatch):
    _, panel, service, changes = screen
    panel.add()
    fill(panel.dialog)
    def fail(*args, **kwargs):
        raise OSError("Simulated disk error")
    monkeypatch.setattr(service, "save", fail)
    panel.dialog.save()
    assert panel.dialog.fields["name"].get() == "Fictional planner"
    assert "Simulated disk error" in panel.dialog.status.get() and not changes


def test_refresh_error_clears_stale_totals_and_actions(screen, monkeypatch):
    root, panel, service, _ = screen
    record = service.save(profile())
    select(root, panel, record)
    def fail(*args, **kwargs):
        raise OSError("Simulated lock")
    monkeypatch.setattr(service, "browse", fail)
    panel.refresh()
    assert "no stale totals" in panel.summary.get()
    assert not panel.tree.get_children() and str(panel.edit_button["state"]) == "disabled"


def test_successful_save_distinct_from_dashboard_error(screen, monkeypatch):
    root, panel, service, _ = screen
    def fail():
        raise OSError("Dashboard unavailable")
    panel.on_change = fail
    panel.add()
    fill(panel.dialog)
    panel.dialog.save()
    root.update()
    assert service.browse() and panel.dialog is None
    assert "change saved, but" in panel.status.get()


def test_notes_not_visible_in_household_table(screen):
    root, panel, service, _ = screen
    record = service.save(profile(notes="PRIVATE_NOTE_MARKER"))
    select(root, panel, record)
    assert "PRIVATE_NOTE_MARKER" not in str(panel.tree.item(str(record.member.id)))
    assert "PRIVATE_NOTE_MARKER" not in panel.details.get()


def test_minimum_size_keeps_notice_and_actions_visible(screen):
    root, panel, _, _ = screen
    root.geometry("1000x700")
    panel.add()
    dialog = panel.dialog
    dialog.geometry("720x630")
    root.update()
    for item in (dialog.save_button, dialog.cancel_button, dialog.footer, dialog.privacy):
        assert item.winfo_rooty() + item.winfo_height() <= dialog.winfo_rooty() + dialog.winfo_height()
    assert dialog.note.winfo_height() > 50
