"""Full-checkout checks, including real saved notes and the application's close guard."""

import gc
import time

import pytest


def populated(path):
    from fieldforge.app import FieldForgeApp
    from fieldforge.core.models import HouseholdMember, InventoryCategory, InventoryItem
    from fieldforge.knowledge.pathways import PathwayStore
    from fieldforge.knowledge.starter import install_starter
    from fieldforge.navigation.geo import Waypoint

    app = FieldForgeApp(path)
    app.add_member(HouseholdMember("Fictional recovery test"))
    app.add_item(InventoryItem("Sample item", InventoryCategory.OTHER, 3, "each"))
    app.add_waypoint(Waypoint("Sample waypoint", 0, 0))
    app.add_incident("info", "Test only")
    app.db.log_event("recovery-test", {"fictional": True})
    install_starter(app.knowledge)
    app.knowledge.annotate("starter-v1-water-storage", bookmarked=True, note="Exact article note\n\n")
    PathwayStore(app.knowledge).save("water", status="exploring", note="Exact learning note", expected_revision=0)
    return app


def test_full_application_backup_counts_and_recovery(tmp_path):
    from fieldforge.app import FieldForgeApp
    from fieldforge.core.recovery import create_verified_backup, restore_verified_copy
    from fieldforge.knowledge.pathways import PathwayStore

    app = populated(tmp_path / "app.db")
    preview = create_verified_backup(app.db.path, tmp_path / "all.ffbackup")
    assert dict(preview.counts) == {
        "Household members": 1, "Inventory items": 1, "Waypoints": 1,
        "Incident entries": 1, "Application events": 1, "Knowledge articles": 12,
        "Article annotation records": 1, "Learning-progress records": 1,
    }
    restored = restore_verified_copy(preview, tmp_path / "recovered.db", active_database=app.db.path)
    recovered = FieldForgeApp(restored)
    assert recovered.members()[0].name == "Fictional recovery test"
    assert recovered.knowledge.search("water")
    assert recovered.knowledge.annotation("starter-v1-water-storage")["note"] == "Exact article note\n\n"
    assert PathwayStore(recovered.knowledge).progress("water").note == "Exact learning note"
    assert app.db.path != restored


def test_legacy_snapshot_archive_can_be_inspected_without_format_migration(tmp_path):
    from fieldforge.core.recovery import inspect_backup
    from fieldforge.core.snapshot import export_snapshot

    app = populated(tmp_path / "source.db")
    archive = export_snapshot(app.db.path, tmp_path / "old-command.ffbackup")
    assert dict(inspect_backup(archive).counts)["Knowledge articles"] == 12


def test_household_json_is_not_accepted_as_a_complete_snapshot(tmp_path):
    from fieldforge.core.backup import export_backup
    from fieldforge.core.recovery import inspect_backup

    app = populated(tmp_path / "source.db")
    archive = export_backup(app.db, tmp_path / "legacy.json")
    with pytest.raises(ValueError):
        inspect_backup(archive)


def make_root():
    gc.collect()
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; recovery GUI CI requires it")
    return root


def test_real_editors_are_saved_before_gui_backup(tmp_path, monkeypatch):
    from tkinter import ttk

    from fieldforge.core.recovery import restore_verified_copy
    from fieldforge.knowledge import KnowledgeLibrary
    from fieldforge.knowledge.pathways import PathwayStore
    from fieldforge.ui.knowledge import KnowledgeTab
    from fieldforge.ui.pathways import add_pathways_tab
    from fieldforge.ui.recovery import add_recovery_tab

    root = make_root()
    app = populated(tmp_path / "source.db")
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)
    library_tab = KnowledgeTab(notebook, app.knowledge)
    notebook.add(library_tab, text="Library")
    pathways = add_pathways_tab(notebook, library_tab)
    recovery = add_recovery_tab(notebook, app.db.path, library_tab, pathways)
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("fieldforge.ui.recovery.messagebox.askyesno", lambda *args, **kwargs: True)
    monkeypatch.setattr("fieldforge.ui.recovery.filedialog.asksaveasfilename",
                        lambda **kwargs: str(tmp_path / "saved-edits.ffbackup"))
    try:
        root.update()
        library_tab.results.selection_set("starter-v1-water-storage")
        root.update()
        library_tab.note.delete("1.0", "end")
        library_tab.note.insert("1.0", "Previously unsaved article edit")
        pathways.tree.selection_set("water")
        root.update()
        pathways.note.delete("1.0", "end")
        pathways.note.insert("1.0", "Previously unsaved learning edit")
        recovery.create()
        deadline = time.monotonic() + 8
        while recovery.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert not recovery.busy and recovery.preview is not None
        target = restore_verified_copy(recovery.preview, tmp_path / "recovered.db", active_database=app.db.path)
        recovered = KnowledgeLibrary(target)
        assert recovered.annotation("starter-v1-water-storage")["note"] == "Previously unsaved article edit"
        assert PathwayStore(recovered).progress("water").note == "Previously unsaved learning edit"
    finally:
        root.destroy()
        recovery._worker.shutdown(wait=True)
        library_tab._worker.shutdown(wait=True)
        gc.collect()
    assert not errors


def test_actual_desktop_installs_recovery_tab_and_blocks_busy_close(tmp_path, monkeypatch):
    import tkinter as tk
    from tkinter import ttk

    from fieldforge.ui import desktop
    from fieldforge.ui.recovery import RecoveryTab

    root = make_root()
    monkeypatch.setenv("FIELDFORGE_DB", str(tmp_path / "desktop.db"))
    monkeypatch.setattr(tk, "Tk", lambda: root)
    monkeypatch.setattr("fieldforge.ui.recovery.messagebox.showinfo", lambda *args, **kwargs: None)
    outcomes = []
    failures = []
    workers = []
    root.report_callback_exception = lambda *args: failures.append(args)

    def exercise():
        root.after_cancel(timer)
        try:
            notebook = next(item for item in root.winfo_children() if isinstance(item, ttk.Notebook))
            frame = next(item for item in notebook.winfo_children() if isinstance(item, RecoveryTab))
            assert notebook.tab(frame, "text") == "Backup & Recovery"
            frame.busy = True
            root.tk.call(root.protocol("WM_DELETE_WINDOW"))
            assert root.winfo_exists()
            frame.busy = False
            workers.extend(item._worker for item in notebook.winfo_children() if hasattr(item, "_worker"))
            outcomes.append("present-and-guarded")
            root.tk.call(root.protocol("WM_DELETE_WINDOW"))
        except Exception as exc:
            failures.append(exc)
            root.destroy()

    root.after(150, exercise)
    timer = root.after(5000, root.destroy)
    desktop.run()
    for worker in workers:
        worker.shutdown(wait=True)
    assert not failures
    assert outcomes == ["present-and-guarded"]
    gc.collect()
