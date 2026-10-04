import gc

import pytest

from fieldforge.app import FieldForgeApp
from fieldforge.navigation.gpx import (
    capture_export,
    commit_import,
    parse_gpx,
    preview_import,
    render_gpx,
)
from fieldforge.navigation.places import PlaceStore, make_place


def test_full_snapshot_recovers_places_coords_notes_and_legacy_api(tmp_path):
    from fieldforge.core.recovery import create_verified_backup, restore_verified_copy
    app = FieldForgeApp(tmp_path / "app.db")
    store = PlaceStore(app.db.path)
    record = store.save(make_place("Fictional meeting", 0, 1, "meeting point", "Private note\n\n"))
    backup = create_verified_backup(app.db.path, tmp_path / "all.ffbackup")
    assert dict(backup.counts)["Waypoints"] == 1
    target = restore_verified_copy(backup, tmp_path / "restored.db", active_database=app.db.path)
    recovered = PlaceStore(target).snapshot().records
    assert recovered == (record,)
    assert FieldForgeApp(target).waypoints() == [record.point]


def test_gpx_roundtrip_and_sharing_exclude_private_article_and_household_data(tmp_path):
    from fieldforge.core.models import HouseholdMember
    from fieldforge.knowledge import KnowledgeArticle
    from fieldforge.knowledge.assistant import ReferenceAssistant
    from fieldforge.knowledge.binder import capture_binder, render_binder
    from fieldforge.knowledge.packs import export_pack
    app = FieldForgeApp(tmp_path / "app.db")
    app.add_member(HouseholdMember("PRIVATE_HOUSEHOLD"))
    app.knowledge.upsert(KnowledgeArticle("article", "Practice worksheet", "Ordinary article text.", "reference"))
    app.knowledge.annotate("article", bookmarked=True, note="PRIVATE_ARTICLE")
    store = PlaceStore(app.db.path)
    record = store.save(make_place("Waypoint-sentinel-421", 0, 1, notes="PRIVATE_PLACE"))
    raw = render_gpx(capture_export(store, (record.point.id,)))
    assert b"PRIVATE_" not in raw
    other = PlaceStore(FieldForgeApp(tmp_path / "other.db").db.path)
    assert commit_import(other, preview_import(other, parse_gpx(raw)), acknowledged=True) == (1, 0)
    assert other.snapshot().records[0].point.name == record.point.name
    assert not other.snapshot().records[0].point.notes
    pack = export_pack(app.knowledge, tmp_path / "articles.json").read_bytes()
    binder = render_binder(capture_binder(app.db.path, slugs=("article",)))
    assert b"Waypoint-sentinel-421" not in pack+binder
    assert not ReferenceAssistant(app.db.path).ask("Waypoint-sentinel-421").references
    assert app.members()[0].name == "PRIVATE_HOUSEHOLD"


def test_real_desktop_has_places_and_guards_unsaved_editor_before_close_backup(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui import desktop
    from fieldforge.ui.places import PlacesTab
    from fieldforge.ui.recovery import RecoveryTab
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; dedicated CI requires a real display")
    path = tmp_path / "app.db"
    monkeypatch.setenv("FIELDFORGE_DB", str(path))
    monkeypatch.setattr(tk, "Tk", lambda: root)
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *args, **kwargs: None)
    errors, passed, workers = [], [], []
    root.report_callback_exception = lambda *args: errors.append(args)

    def children(widget):
        yield widget
        for child in widget.winfo_children():
            yield from children(child)

    def play():
        root.after_cancel(timer)
        try:
            panel = next(w for w in children(root) if isinstance(w, PlacesTab))
            recovery = next(w for w in children(root) if isinstance(w, RecoveryTab))
            assert panel.master.tab(panel, "text") == "Places"
            root.geometry("1000x700")
            root.update()
            switcher = root.nametowidget(".section_navigation.choice")
            assert switcher.winfo_ismapped()
            switcher.set("Places")
            switcher.event_generate("<<ComboboxSelected>>")
            root.update()
            assert panel.master.select() == str(panel)
            panel.add_button.invoke()
            panel.dialog.fields["name"].set("Fictional place")
            panel.dialog.fields["latitude"].set("0")
            panel.dialog.fields["longitude"].set("1")
            assert not recovery.before_backup()
            root.tk.call(root.protocol("WM_DELETE_WINDOW"))
            assert root.winfo_exists() and panel.dialog is not None
            panel.dialog.save_button.invoke()
            root.update()
            assert panel.dialog is None and recovery.before_backup()
            assert FieldForgeApp(path).waypoints()[0].name == "Fictional place"
            passed.append(True)
        except Exception as exc:
            errors.append(exc)
        finally:
            workers.extend(w._worker for w in children(root) if hasattr(w, "_worker"))
            root.destroy()

    root.after(200, play)
    timer = root.after(7000, root.destroy)
    desktop.run()
    for worker in workers:
        worker.shutdown(wait=True, cancel_futures=True)
    gc.collect()
    assert passed and not errors
