import gc
from dataclasses import replace

import pytest
from test_supplies import seed_database, water


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.supplies import SuppliesTab

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    root.geometry("1150x750")
    errors, changed = [], []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("fieldforge.ui.supplies.messagebox.askyesno", lambda *args, **kwargs: False)
    monkeypatch.setattr("fieldforge.ui.supplies.messagebox.showinfo", lambda *args, **kwargs: None)
    service = seed_database(tmp_path / "ui.db")
    panel = SuppliesTab(root, service, on_change=lambda: changed.append(True))
    panel.pack(fill="both", expand=True, padx=16, pady=16)
    root.update()
    try:
        yield root, panel, service, changed
    finally:
        root.destroy()
        gc.collect()
    assert not errors


def select(root, panel, record):
    panel.refresh()
    panel.tree.selection_set(str(record.item.id))
    root.update()


def fill(dialog):
    for key, value in {"name": "Water bottles", "category": "water", "quantity": "6", "unit": "bottle",
                       "liters_per_unit": "2", "location": "Storage shelf"}.items():
        dialog.fields[key].set(value)


def test_empty_state_and_add_workflow_shows_arithmetic(screen):
    root, panel, service, changed = screen
    assert not service.browse()
    panel.add_button.invoke()
    root.update()
    dialog = panel.dialog
    fill(dialog)
    root.update()
    assert "6 × 2 liters/bottle = 12 liters" in dialog.totals.get()
    assert not service.browse()  # preview has no data side effects
    dialog.save_button.invoke()
    root.update()
    assert panel.dialog is None and len(service.browse()) == 1
    assert changed == [True]
    assert "Water bottles" in panel.tree.item(panel.tree.get_children()[0], "values")


def test_editor_populates_and_updates_every_field(screen):
    root, panel, service, changed = screen
    record = service.save(water(notes="Keep notes\n\n"))
    select(root, panel, record)
    panel.edit_button.invoke()
    root.update()
    dialog = panel.dialog
    assert dialog.note.get("1.0", "end-1c") == "Keep notes\n\n"
    dialog.fields["name"].set("Edited bottles")
    dialog.fields["liters_per_unit"].set("3")
    dialog.fields["expires_on"].set("2027-12-01")
    dialog.fields["minimum_quantity"].set("4")
    dialog.save()
    root.update()
    updated = service.get(record.item.id).item
    assert updated.name == "Edited bottles" and updated.liters_per_unit == 3
    assert updated.minimum_quantity == 4 and str(updated.expires_on) == "2027-12-01"
    assert changed == [True]


def test_invalid_numbers_keep_unsaved_editor_open(screen):
    root, panel, service, changed = screen
    panel.add()
    fill(panel.dialog)
    panel.dialog.fields["quantity"].set("NaN")
    panel.dialog.save()
    root.update()
    assert panel.dialog is not None and "Not saved" in panel.dialog.status.get()
    assert not service.browse() and not changed


def test_conflict_keeps_user_edits_and_newer_record(screen):
    root, panel, service, _ = screen
    old = service.save(water())
    select(root, panel, old)
    panel.edit()
    panel.dialog.fields["name"].set("My unsaved edit")
    newer = service.save(replace(old.item, location="Other window"), expected=old.token)
    panel.dialog.save()
    root.update()
    assert panel.dialog.fields["name"].get() == "My unsaved edit"
    assert "another window" in panel.dialog.status.get()
    assert service.get(old.item.id) == newer


def test_cancel_requires_confirmation_for_dirty_form(screen, monkeypatch):
    root, panel, service, _ = screen
    panel.add()
    fill(panel.dialog)
    panel.dialog.close()
    assert panel.dialog is not None
    monkeypatch.setattr("fieldforge.ui.supplies.messagebox.askyesno", lambda *args, **kwargs: True)
    panel.dialog.close()
    root.update()
    assert panel.dialog is None and not service.browse()


def test_stock_use_and_receive_update_inventory(screen):
    root, panel, service, changed = screen
    old = service.save(water())
    select(root, panel, old)
    panel.adjust_button.invoke()
    dialog = panel.dialog
    dialog.quantity.set("2")
    dialog.reason.set("Practice consumption")
    dialog.save_button.invoke()
    root.update()
    assert service.get(old.item.id).item.quantity == 4
    select(root, panel, service.get(old.item.id))
    panel.adjust()
    panel.dialog.change.set("receive")
    panel.dialog.quantity.set("5")
    panel.dialog.reason.set("Delivery")
    panel.dialog.save()
    root.update()
    assert service.get(old.item.id).item.quantity == 9 and len(changed) == 2


def test_stock_overdraw_is_rejected_without_closing(screen):
    root, panel, service, _ = screen
    old = service.save(water(quantity=1))
    select(root, panel, old)
    panel.adjust()
    panel.dialog.quantity.set("2")
    panel.dialog.reason.set("Too much")
    panel.dialog.save()
    assert "more stock" in panel.dialog.status.get()
    assert service.get(old.item.id) == old


def test_removal_confirmed_and_logged_not_confused_with_consumption(screen, monkeypatch):
    root, panel, service, changed = screen
    record = service.save(water())
    select(root, panel, record)
    panel.remove()
    assert service.get(record.item.id) == record
    prompts = []
    monkeypatch.setattr("fieldforge.ui.supplies.messagebox.askyesno", lambda *args, **kwargs: prompts.append(args) or True)
    panel.remove_button.invoke()
    root.update()
    assert not service.browse() and changed == [True]
    assert "not recording consumption" in prompts[0][1]
    assert "private change history" in panel.status.get()


def test_paging_filters_and_selection_controls(screen):
    root, panel, service, _ = screen
    for i in range(52):
        service.save(water(name=f"Supply {i:03}"))
    panel.refresh()
    root.update()
    assert len(panel.tree.get_children()) == 50
    panel.next.invoke()
    assert len(panel.tree.get_children()) == 2
    panel.query.set("Supply 051")
    panel.refresh()
    assert len(panel.tree.get_children()) == 1 and panel.offset == 0
    panel.category.set("food")
    panel.refresh()
    assert not panel.tree.get_children()
    assert str(panel.edit_button["state"]) == "disabled"


def test_parent_close_guard_and_single_editor(screen):
    root, panel, _, _ = screen
    panel.add()
    original = panel.dialog
    panel.add()
    assert panel.dialog is original and not panel.can_close()
    original.close()
    root.update()
    assert panel.can_close()


def test_read_error_not_reported_as_success(screen, monkeypatch):
    _, panel, _, _ = screen
    def fail(*args, **kwargs):
        raise OSError("simulated lock")
    monkeypatch.setattr(panel.service, "browse", fail)
    panel.refresh()
    assert "Could not refresh" in panel.status.get()


def test_dialog_controls_visible_at_minimum_size(screen):
    root, panel, _, _ = screen
    panel.add()
    dialog = panel.dialog
    dialog.geometry("700x610")
    root.update()
    for control in (dialog.save_button, dialog.footer):
        assert control.winfo_rooty() + control.winfo_height() <= dialog.winfo_rooty() + dialog.winfo_height()
    assert dialog.preview_label.winfo_height() > 20
