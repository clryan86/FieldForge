"""Full-checkout regression: actual app, recovery, article privacy and desktop."""

import gc

import pytest

from fieldforge.core.emergency import EmergencyStore
from fieldforge.core.emergency_actions import ActionStore


def populated(path):
    from fieldforge.app import FieldForgeApp
    app = FieldForgeApp(path)
    original = EmergencyStore(path)
    session = original.create("Fictional handoff drill", "power_outage")
    store = ActionStore(path)
    task = store.add_custom(session.id, expected_revision=session.revision,
                             title="Record the practice count", reason="Write the count on the exercise sheet.",
                             responsible="PRIVATE_ALIAS_73912")
    task = store.update_task(task.id, expected_revision=task.revision, status="blocked", note="PRIVATE_NOTE_73912")
    return app, store, session.id, task


def test_full_snapshot_retains_custom_origin_assignment_status_and_exact_note(tmp_path):
    from fieldforge.core.recovery import create_verified_backup, restore_verified_copy
    app, store, session_id, task = populated(tmp_path / "app.db")
    before = store.detail(session_id)
    snapshot = create_verified_backup(app.db.path, tmp_path / "complete.ffbackup")
    target = restore_verified_copy(snapshot, tmp_path / "restored.db", active_database=app.db.path)
    restored = ActionStore(target)
    assert restored.detail(session_id) == before
    assert restored.get_task(task.id).origin == "custom"
    assert restored.get_task(task.id).responsible == task.responsible


def test_private_incident_metadata_is_not_article_content_or_reference_evidence(tmp_path):
    from fieldforge.knowledge.assistant import ReferenceAssistant
    from fieldforge.knowledge.packs import export_pack
    app, store, session_id, _ = populated(tmp_path / "app.db")
    store.add_note(session_id, "PRIVATE_JOURNAL_73912")
    pack = export_pack(app.knowledge, tmp_path / "article-pack.json", include_personal=True)
    assert "PRIVATE_" not in pack.read_text(encoding="utf-8")
    for marker in ("PRIVATE_ALIAS_73912", "PRIVATE_NOTE_73912", "PRIVATE_JOURNAL_73912"):
        assert not ReferenceAssistant(app.db.path).ask(marker).references


def test_adding_actions_does_not_change_household_inventory_or_old_general_journal(tmp_path):
    from fieldforge.app import FieldForgeApp
    from fieldforge.core.models import HouseholdMember, InventoryCategory, InventoryItem
    app = FieldForgeApp(tmp_path / "app.db")
    app.add_member(HouseholdMember("Fictional profile"))
    app.add_item(InventoryItem("Fictional stock", InventoryCategory.OTHER, 3, "each"))
    app.add_incident("info", "Old general journal entry")
    before = app.members(), app.inventory(), app.incidents()
    store = ActionStore(app.db.path)
    session = store.create("Local drill", "evacuation")
    store.add_custom(session.id, expected_revision=session.revision, title="Check record location", reason="Practice only")
    assert (app.members(), app.inventory(), app.incidents()) == before


def test_actual_desktop_uses_new_actions_and_guards_close_and_backup(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.app import FieldForgeApp
    from fieldforge.ui import desktop
    from fieldforge.ui.emergency import EmergencyTab
    from fieldforge.ui.emergency_actions import ActionWorkspace
    from fieldforge.ui.recovery import RecoveryTab

    path = tmp_path / "desktop.db"
    FieldForgeApp(path)
    session = EmergencyStore(path).create("Existing exercise", "power_outage")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; graphical CI requires one")
    monkeypatch.setenv("FIELDFORGE_DB", str(path))
    monkeypatch.setattr(tk, "Tk", lambda: root)
    monkeypatch.setattr("fieldforge.ui.emergency.messagebox.showinfo", lambda *args, **kwargs: None)
    errors, passed, workers = [], [], []
    root.report_callback_exception = lambda *args: errors.append(args)

    def children(widget):
        yield widget
        for child in widget.winfo_children():
            yield from children(child)

    def exercise():
        root.after_cancel(timer)
        try:
            panel = next(widget for widget in children(root) if isinstance(widget, ActionWorkspace))
            assert isinstance(panel, EmergencyTab)  # Existing integration remains compatible.
            recovery = next(widget for widget in children(root) if isinstance(widget, RecoveryTab))
            panel.sessions.selection_set(str(session.id))
            root.update()
            panel.add_action()
            assert not recovery.before_backup()
            root.tk.call(root.protocol("WM_DELETE_WINDOW"))
            assert root.winfo_exists() and panel.dialog is not None
            panel.dialog.task_title.set("Count practice sheets")
            panel.dialog.reason.insert("1.0", "Fictional exercise only")
            panel.dialog.responsible.set("Practice team")
            panel.dialog.save()
            root.update()
            assert panel.current.tasks[-1].responsible == "Practice team"
            assert panel.current.tasks[-1].origin == "custom"
            assert recovery.before_backup()
            passed.append(True)
        except Exception as exc:
            errors.append(exc)
        finally:
            workers.extend(widget._worker for widget in children(root) if hasattr(widget, "_worker"))
            root.destroy()

    root.after(200, exercise)
    timer = root.after(7000, root.destroy)
    desktop.run()
    for worker in workers:
        worker.shutdown(wait=True)
    assert passed and not errors
    gc.collect()
