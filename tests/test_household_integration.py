"""Full-checkout regressions for the actual app, backups and desktop integration."""

import gc
from dataclasses import replace

import pytest

from fieldforge.core.household import HouseholdService
from fieldforge.core.models import HouseholdMember, InventoryCategory, InventoryItem


def app_at(path):
    from fieldforge.app import FieldForgeApp
    app = FieldForgeApp(path)
    app.add_item(InventoryItem("Bottles", InventoryCategory.WATER, 6, "bottle", liters_per_unit=2))
    return app, HouseholdService(path)


def test_existing_member_edits_drive_legacy_and_graphical_calculators(tmp_path):
    from fieldforge.core.supplies import SuppliesService
    app, service = app_at(tmp_path / "app.db")
    member = app.add_member(HouseholdMember("Fictional planner", 3, 2000))
    record = service.get(member.id)
    assert app.water_status().days_remaining == pytest.approx(3.6)
    record = service.save(replace(record.member, daily_water_liters=6), expected=record.token)
    assert app.water_status().days_remaining == pytest.approx(1.8)
    assert SuppliesService(app.db.path).dashboard()["water"]["days_remaining"] == pytest.approx(1.8)
    stock = app.inventory()
    service.remove(record)
    assert app.inventory() == stock
    assert SuppliesService(app.db.path).dashboard()["water"]["label"] == "Set household"


def test_household_changes_and_private_notes_survive_both_backup_formats(tmp_path):
    from fieldforge.core.backup import export_backup, restore_backup
    from fieldforge.core.recovery import create_verified_backup, restore_verified_copy
    from fieldforge.db.database import FieldForgeDatabase
    app, service = app_at(tmp_path / "app.db")
    member = service.save(HouseholdMember("Fictional animal", 1, 500, "Private notes\n\n", is_pet=True))
    snapshot = create_verified_backup(app.db.path, tmp_path / "all.ffbackup")
    path = restore_verified_copy(snapshot, tmp_path / "restored.db", active_database=app.db.path)
    assert HouseholdService(path).get(member.member.id) == member
    household_json = export_backup(app.db, tmp_path / "household.json")
    target = FieldForgeDatabase(tmp_path / "legacy.db")
    restore_backup(target, household_json)
    assert target.list_members()[0].notes == member.member.notes
    assert target.list_members()[0].is_pet


def test_household_notes_not_in_ordinary_article_packs_or_reference_search(tmp_path):
    from fieldforge.knowledge.assistant import ReferenceAssistant
    from fieldforge.knowledge.packs import export_pack
    app, service = app_at(tmp_path / "app.db")
    service.save(HouseholdMember("HiddenAlias73912", 3, 2000, "PrivateMarker98231"))
    report = ReferenceAssistant(app.db.path).ask("PrivateMarker98231")
    assert not report.references
    pack = export_pack(app.knowledge, tmp_path / "public.json")
    encoded = pack.read_text(encoding="utf-8")
    assert "HiddenAlias73912" not in encoded and "PrivateMarker98231" not in encoded
    assert "PrivateMarker98231" not in str(app.db.list_events())


def test_existing_household_rows_and_schema_not_reset_on_editor_open(tmp_path):
    app, service = app_at(tmp_path / "app.db")
    member = app.add_member(HouseholdMember("Fictional existing child", 2, 1500, is_child=True))
    with app.db.connect() as db:
        before = [tuple(row) for row in db.execute("SELECT name,sql FROM sqlite_master ORDER BY name")]
    assert service.browse()[0].member == member
    assert service.summary().children == 1
    with app.db.connect() as db:
        assert [tuple(row) for row in db.execute("SELECT name,sql FROM sqlite_master ORDER BY name")] == before


def test_real_desktop_household_edit_updates_dashboard_and_guards_close_backup(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from tkinter import ttk

    from fieldforge.ui import desktop
    from fieldforge.ui.household import HouseholdTab
    from fieldforge.ui.recovery import RecoveryTab

    app, _ = app_at(tmp_path / "desktop.db")
    member = app.add_member(HouseholdMember("Fictional planner", 3, 2000))
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; dedicated GUI CI requires a display")
    monkeypatch.setenv("FIELDFORGE_DB", str(app.db.path))
    monkeypatch.setattr(tk, "Tk", lambda: root)
    monkeypatch.setattr("fieldforge.ui.household.messagebox.showinfo", lambda *args, **kwargs: None)
    failures, completed, workers = [], [], []
    root.report_callback_exception = lambda *args: failures.append(args)

    def children(widget):
        yield widget
        for child in widget.winfo_children():
            yield from children(child)

    def metric_values():
        return [root.getvar(widget.cget("textvariable")) for widget in children(root)
                if isinstance(widget, ttk.Label) and widget.cget("style") == "Metric.TLabel"]

    def exercise():
        root.after_cancel(timer)
        try:
            panel = next(widget for widget in children(root) if isinstance(widget, HouseholdTab))
            recovery = next(widget for widget in children(root) if isinstance(widget, RecoveryTab))
            panel.tree.selection_set(str(member.id))
            root.update()
            panel.edit()
            root.tk.call(root.protocol("WM_DELETE_WINDOW"))
            assert root.winfo_exists() and panel.dialog
            assert not recovery.before_backup()
            panel.dialog.fields["water"].set("6")
            panel.dialog.save()
            root.update()
            assert "1.8 days" in metric_values()
            assert recovery.before_backup()
            completed.append(True)
        except Exception as exc:
            failures.append(exc)
        finally:
            workers.extend(widget._worker for widget in children(root) if hasattr(widget, "_worker"))
            root.destroy()

    root.after(200, exercise)
    timer = root.after(7000, root.destroy)
    desktop.run()
    for worker in workers:
        worker.shutdown(wait=True)
    assert completed and not failures
    gc.collect()
