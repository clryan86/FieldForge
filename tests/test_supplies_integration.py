"""Full-checkout tests against the actual app, snapshots and desktop."""

import gc
from dataclasses import replace

import pytest

from fieldforge.core.models import HouseholdMember, InventoryCategory, InventoryItem
from fieldforge.core.supplies import SuppliesService, SupplyConflict


def app_at(path):
    from fieldforge.app import FieldForgeApp

    app = FieldForgeApp(path)
    app.add_member(HouseholdMember("Fictional planner", daily_water_liters=3, daily_calories=2000))
    return app, SuppliesService(app.db.path)


def test_new_edits_feed_existing_calculators_and_backups(tmp_path):
    from fieldforge.core.backup import export_backup, restore_backup
    from fieldforge.db.database import FieldForgeDatabase

    app, service = app_at(tmp_path / "app.db")
    water = service.save(InventoryItem("Bottles", InventoryCategory.WATER, 6, "bottle", liters_per_unit=2))
    service.save(InventoryItem("Rice", InventoryCategory.FOOD, 4, "bag", calories_per_unit=6000))
    assert app.water_status().days_remaining == pytest.approx(3.6)
    assert app.food_status().days_remaining == pytest.approx(10.8)
    water = service.save(replace(water.item, liters_per_unit=3), expected=water.token)
    assert app.water_status().days_remaining == pytest.approx(5.4)
    assert service.dashboard()["water"]["days_remaining"] == pytest.approx(5.4)
    backup = export_backup(app.db, tmp_path / "legacy.json")
    target = FieldForgeDatabase(tmp_path / "target.db")
    restore_backup(target, backup)
    assert any(item.liters_per_unit == 3 for item in target.list_inventory())


def test_full_snapshot_preserves_change_history_and_remaining_stock(tmp_path):
    from fieldforge.core.recovery import create_verified_backup, restore_verified_copy

    app, service = app_at(tmp_path / "app.db")
    record = service.save(InventoryItem("Bottles", InventoryCategory.WATER, 6, "bottle", liters_per_unit=2))
    service.adjust(record, "use", 2, "Fictional test use")
    preview = create_verified_backup(app.db.path, tmp_path / "complete.ffbackup")
    assert dict(preview.counts)["Application events"] == 2
    path = restore_verified_copy(preview, tmp_path / "recovered.db", active_database=app.db.path)
    recovered = SuppliesService(path)
    assert recovered.get(record.item.id).item.quantity == 4
    with recovered.connect() as db:
        assert "Fictional test use" in db.execute("SELECT payload_json FROM app_events ORDER BY id DESC").fetchone()[0]


def test_original_database_quantity_api_changes_trigger_conflict(tmp_path):
    app, service = app_at(tmp_path / "app.db")
    original = service.save(InventoryItem("Supplies", InventoryCategory.OTHER, 6, "each"))
    app.db.update_inventory_quantity(original.item.id, 8)
    with pytest.raises(SupplyConflict):
        service.save(replace(original.item, quantity=9), expected=original.token)
    assert app.inventory()[0].quantity == 8


def test_new_workflow_requires_no_schema_migration(tmp_path):
    app, service = app_at(tmp_path / "app.db")
    with app.db.connect() as db:
        before = list(db.execute("SELECT name,sql FROM sqlite_master ORDER BY name"))
    service.save(InventoryItem("Supplies", InventoryCategory.OTHER, 1, "each"))
    with app.db.connect() as db:
        after = list(db.execute("SELECT name,sql FROM sqlite_master ORDER BY name"))
    assert [tuple(row) for row in before] == [tuple(row) for row in after]


def test_actual_desktop_supply_edit_updates_dashboard_and_guards_close(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from tkinter import ttk

    from fieldforge.ui import desktop
    from fieldforge.ui.supplies import SuppliesTab

    app_at(tmp_path / "desktop.db")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; GUI CI exercises this test")
    monkeypatch.setenv("FIELDFORGE_DB", str(tmp_path / "desktop.db"))
    monkeypatch.setattr(tk, "Tk", lambda: root)
    monkeypatch.setattr("fieldforge.ui.supplies.messagebox.showinfo", lambda *args, **kwargs: None)
    errors, completed, workers = [], [], []
    root.report_callback_exception = lambda *args: errors.append(args)

    def descendants(widget):
        yield widget
        for child in widget.winfo_children():
            yield from descendants(child)

    def metric_values():
        result = []
        for widget in descendants(root):
            if isinstance(widget, ttk.Label) and widget.cget("style") == "Metric.TLabel":
                result.append(root.getvar(widget.cget("textvariable")))
        return result

    def exercise():
        root.after_cancel(timer)
        try:
            panel = next(child for child in descendants(root) if isinstance(child, SuppliesTab))
            panel.add()
            root.tk.call(root.protocol("WM_DELETE_WINDOW"))
            assert root.winfo_exists() and panel.dialog is not None
            for key, value in {"name": "Bottles", "category": "water", "quantity": "6", "unit": "bottle", "liters_per_unit": "2"}.items():
                panel.dialog.fields[key].set(value)
            panel.dialog.save()
            root.update()
            assert "3.6 days" in metric_values()
            panel.tree.selection_set(panel.tree.get_children()[0])
            root.update()
            panel.adjust()
            panel.dialog.quantity.set("3")
            panel.dialog.reason.set("Fictional test consumption")
            panel.dialog.save()
            root.update()
            assert "1.8 days" in metric_values()
            completed.append(True)
        except Exception as exc:
            errors.append(exc)
        finally:
            workers.extend(widget._worker for widget in descendants(root) if hasattr(widget, "_worker"))
            root.destroy()

    root.after(200, exercise)
    timer = root.after(7000, root.destroy)
    desktop.run()
    for worker in workers:
        worker.shutdown(wait=True)
    assert completed and not errors
    gc.collect()
