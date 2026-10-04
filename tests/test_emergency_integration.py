"""Full-checkout checks for existing data, source privacy, backup and actual desktop guards."""

import gc

import pytest

from fieldforge.core.emergency import EmergencyStore


def populated(path):
    from fieldforge.app import FieldForgeApp
    from fieldforge.core.models import HouseholdMember
    app = FieldForgeApp(path)
    app.add_member(HouseholdMember("Fictional exercise participant"))
    app.add_incident("info", "Previous legacy journal record")
    store = EmergencyStore(path)
    record = store.create("Zyxprivateincident27691", "power_outage")
    task = store.detail(record.id).tasks[0]
    store.update_task(task.id, expected_revision=1, status="blocked", note="Zyxprivatetask27691")
    store.add_note(record.id, "Zyxprivatelog27691")
    return app, store, record


def test_existing_household_and_legacy_journal_are_preserved(tmp_path):
    app, store, record = populated(tmp_path / "app.db")
    assert app.members()[0].name == "Fictional exercise participant"
    assert app.incidents()[0]["message"] == "Previous legacy journal record"
    assert len(app.incidents()) == 1
    original = app.scenario("power_outage")
    saved = store.detail(record.id)
    assert {(task.title, task.reason) for task in saved.tasks} == {
        (task["title"], task["reason"]) for task in original["actions"]
    }
    assert not any(task["completed"] for task in original["actions"])


def test_complete_backup_recovers_emergency_progress_and_journal(tmp_path):
    from fieldforge.core.recovery import create_verified_backup, restore_verified_copy
    app, store, record = populated(tmp_path / "source.db")
    before = store.detail(record.id)
    backup = create_verified_backup(app.db.path, tmp_path / "complete.ffbackup")
    path = restore_verified_copy(backup, tmp_path / "restored.db", active_database=app.db.path)
    assert EmergencyStore(path).detail(record.id) == before
    # The recovery screen's existing Incident entries counter is the legacy log only.
    assert dict(backup.counts)["Incident entries"] == 1


def test_private_incidents_not_in_article_exports_or_ask_library(tmp_path):
    from fieldforge.knowledge.assistant import ReferenceAssistant
    from fieldforge.knowledge.packs import export_pack
    app, _, _ = populated(tmp_path / "app.db")
    exported = export_pack(app.knowledge, tmp_path / "public.json")
    encoded = exported.read_text(encoding="utf-8")
    assert "Zyxprivate" not in encoded
    for word in ("Zyxprivateincident27691", "Zyxprivatetask27691", "Zyxprivatelog27691"):
        assert not ReferenceAssistant(app.db.path).ask(word).references


def test_reopening_new_tables_never_resets_legacy_schema_or_scenario_data(tmp_path):
    app, store, record = populated(tmp_path / "app.db")
    before = store.detail(record.id)
    with app.db.connect() as db:
        version = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
    assert version == "2"
    EmergencyStore(app.db.path)
    assert store.detail(record.id) == before
    assert app.knowledge.count() == 0


def test_actual_desktop_incident_editor_guards_close_backup_and_resumes(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui import desktop
    from fieldforge.ui.emergency import EmergencyTab
    from fieldforge.ui.recovery import RecoveryTab
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; dedicated GUI CI requires a display")
    monkeypatch.setenv("FIELDFORGE_DB", str(tmp_path / "desktop.db"))
    monkeypatch.setattr(tk, "Tk", lambda: root)
    monkeypatch.setattr("fieldforge.ui.emergency.messagebox.showinfo", lambda *args, **kwargs: None)
    failures, completed, workers = [], [], []
    root.report_callback_exception = lambda *args: failures.append(args)
    def children(widget):
        yield widget
        for child in widget.winfo_children():
            yield from children(child)
    def exercise():
        root.after_cancel(timer)
        try:
            panel = next(widget for widget in children(root) if isinstance(widget, EmergencyTab))
            recovery = next(widget for widget in children(root) if isinstance(widget, RecoveryTab))
            assert not panel.store.browse()
            panel.new()
            root.tk.call(root.protocol("WM_DELETE_WINDOW"))
            assert root.winfo_exists() and not recovery.before_backup()
            panel.dialog.name.set("Fictional desktop exercise")
            panel.dialog.scenario.set("power_outage")
            panel.dialog.save()
            root.update()
            assert panel.current and panel.current.incident.mode == "exercise"
            assert recovery.before_backup()
            task = panel.current.tasks[0]
            panel.tasks.selection_set(str(task.id))
            root.update()
            panel.edit_task()
            assert not recovery.before_backup()
            panel.dialog.action_status.set("Done (self-reported)")
            panel.dialog.save()
            root.update()
            assert panel.current.done == 1
            assert EmergencyStore(tmp_path / "desktop.db").detail(panel.current.incident.id).done == 1
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
