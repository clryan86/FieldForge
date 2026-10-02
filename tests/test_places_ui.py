import gc
import threading
import time
from dataclasses import replace

import pytest

from fieldforge.app import FieldForgeApp
from fieldforge.navigation.gpx import NS, parse_gpx
from fieldforge.navigation.places import make_place


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui.places import PlacesTab
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; dedicated graphical CI requires it")
    root.geometry("1150x790")
    errors, workers = [], []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *args, **kwargs: False)
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *args, **kwargs: None)
    app = FieldForgeApp(tmp_path / "app.db")
    panel = PlacesTab(root, app.db.path)
    panel.pack(fill="both", expand=True)
    root.update()
    try:
        yield root, panel, app, workers
    finally:
        if panel.dialog is not None and hasattr(panel.dialog, "_worker"):
            workers.append(panel.dialog._worker)
        root.destroy()
        for worker in workers:
            worker.shutdown(wait=True, cancel_futures=True)
        gc.collect()
    assert not errors


def points(root, panel):
    a = panel.store.save(make_place("Fictional start", 0, 0, notes="PRIVATE A"))
    b = panel.store.save(make_place("Fictional end", 0, 1, notes="PRIVATE B"))
    panel.refresh()
    root.update()
    return a, b


def select(root, panel, number):
    panel.tree.selection_set(str(number))
    root.update()
    assert panel.selected().point.id == number


def wait(root, dialog):
    deadline = time.monotonic() + 6
    while dialog.busy and not dialog._disposed and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    root.update()
    assert not dialog.busy or dialog._disposed


def gpx_file(path, name="Imported", lon="1", extra=""):
    path.write_text(f'<gpx xmlns="{NS}" version="1.1" creator="test">{extra}'
                    f'<wpt lat="0" lon="{lon}"><name>{name}</name><desc>Incoming private note</desc></wpt></gpx>', encoding="utf-8")
    return path


def test_empty_workspace_no_fake_gps_or_seeded_locations(screen):
    _, panel, app, _ = screen
    assert app.waypoints() == [] and not panel.tree.get_children()
    assert "No live GPS" in panel.notice["text"]
    assert str(panel.edit_button["state"]) == "disabled"
    assert str(panel.export_button["state"]) == "disabled"


def test_new_place_editor_requires_coordinates_and_saves_notes(screen):
    root, panel, app, _ = screen
    panel.add_button.invoke()
    editor = panel.dialog
    assert not editor.fields["latitude"].get() and not editor.fields["longitude"].get()
    editor.fields["name"].set("Fictional meeting")
    editor.save_button.invoke()
    assert "Not saved" in editor.status.get() and app.waypoints() == []
    editor.fields["latitude"].set("0")
    editor.fields["longitude"].set("1.25")
    editor.note.insert("1.0", "Private notes\n\n")
    editor.save_button.invoke()
    root.update()
    assert panel.dialog is None
    assert app.waypoints()[0].notes == "Private notes\n\n"
    assert app.waypoints()[0].longitude == 1.25


def test_existing_place_edit_stale_save_keeps_entered_values(screen):
    root, panel, _, _ = screen
    a, _ = points(root, panel)
    select(root, panel, a.point.id)
    panel.edit_button.invoke()
    editor = panel.dialog
    editor.fields["name"].set("Unsaved name")
    panel.store.save(replace(a.point, name="Newer saved name"), expected=a)
    editor.save()
    assert "another window" in editor.status.get()
    assert editor.fields["name"].get() == "Unsaved name"
    assert panel.store.snapshot((a.point.id,)).records[0].point.name == "Newer saved name"


def test_cancel_requires_discard_and_close_backup_guard(screen, monkeypatch):
    root, panel, app, _ = screen
    panel.add()
    editor = panel.dialog
    editor.fields["name"].set("Unsaved")
    assert not panel.can_close()
    panel.add()
    assert panel.dialog is editor
    editor.close()
    assert not editor._disposed
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *args, **kwargs: True)
    editor.close()
    root.update()
    assert panel.dialog is None and panel.can_close() and not app.waypoints()


def test_tiny_coordinate_can_be_reedited_without_exponent_error(screen):
    root, panel, _, _ = screen
    record = panel.store.save(make_place("Tiny coordinate", ".00000001", "-.00000001"))
    panel.refresh()
    select(root, panel, record.point.id)
    panel.edit()
    assert panel.dialog.fields["latitude"].get() == "0.00000001"
    panel.dialog.note.insert("1.0", "New note")
    panel.dialog.save()
    assert panel.store.snapshot().records[0].point.latitude == 1e-8


def test_selected_endpoints_calculate_current_data_and_clear_stale_error(screen):
    root, panel, _, _ = screen
    a, b = points(root, panel)
    select(root, panel, a.point.id)
    panel.start_button.invoke()
    select(root, panel, b.point.id)
    panel.end_button.invoke()
    panel.calculate_button.invoke()
    content = panel.result.get("1.0", "end")
    assert "90.0° TRUE" in content and "111.195 km" in content
    assert "PRIVATE" not in content
    panel.store.remove(b)
    panel.calculate()
    content = panel.result.get("1.0", "end")
    assert "No estimate available" in content and "111.195" not in content


def test_same_point_bearing_not_invented_and_refresh_invalidates_result(screen):
    root, panel, _, _ = screen
    a, _ = points(root, panel)
    select(root, panel, a.point.id)
    panel.endpoint(True)
    panel.endpoint(False)
    panel.calculate()
    assert "Unavailable" in panel.result.get("1.0", "end")
    panel.refresh()
    assert "Recalculate" in panel.result.get("1.0", "end")


def test_remove_confirmation_and_stale_record_do_not_delete_new_data(screen, monkeypatch):
    root, panel, app, _ = screen
    a, _ = points(root, panel)
    select(root, panel, a.point.id)
    panel.remove_button.invoke()
    assert len(app.waypoints()) == 2
    panel.store.save(replace(a.point, notes="Updated"), expected=a)
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *args, **kwargs: True)
    panel.remove_button.invoke()
    assert "Not removed" in panel.status.get() and len(app.waypoints()) == 2
    panel.refresh()
    select(root, panel, a.point.id)
    panel.remove_button.invoke()
    assert len(app.waypoints()) == 1


def test_name_search_pagination_and_failed_refresh_no_stale_list(screen):
    root, panel, _, _ = screen
    for i in range(53):
        panel.store.save(make_place(f"Place {i:02}", 0, i))
    panel.refresh()
    assert len(panel.tree.get_children()) == 50
    panel.next.invoke()
    assert len(panel.tree.get_children()) == 3
    panel.query.set("place 01")
    panel.refresh()
    assert len(panel.tree.get_children()) == 1
    panel.query.set("x"*201)
    panel.refresh()
    root.update()
    assert not panel.tree.get_children() and "Could not refresh" in panel.status.get()
    assert str(panel.edit_button["state"]) == "disabled"


def test_import_preview_fields_conflicts_and_confirmed_commit(screen, tmp_path):
    root, panel, app, workers = screen
    panel.import_button.invoke()
    dialog = panel.dialog
    workers.append(dialog._worker)
    path = gpx_file(tmp_path / "input.gpx", extra="<metadata><name>Discarded metadata</name></metadata>")
    dialog.load_path(path)
    wait(root, dialog)
    assert "metadata: 1" in dialog.summary.get()
    assert dialog.preview.added == 1 and app.waypoints() == []
    assert "Incoming private note" in dialog.details.get("1.0", "end")
    dialog.act()
    assert not app.waypoints()
    dialog.permission.set(True)
    dialog._buttons()
    dialog.action_button.invoke()
    wait(root, dialog)
    assert len(app.waypoints()) == 1 and "Imported 1" in dialog.status.get()
    dialog.close()
    root.update()
    assert panel.dialog is None and len(panel.tree.get_children()) == 1


def test_import_conflict_disabled_and_recheck_after_database_change(screen, tmp_path):
    root, panel, app, workers = screen
    panel.import_gpx()
    dialog = panel.dialog
    workers.append(dialog._worker)
    path = gpx_file(tmp_path / "input.gpx")
    dialog.load_path(path)
    wait(root, dialog)
    other = panel.store.save(make_place("Other record", 2, 3))
    dialog.permission.set(True)
    dialog.act()
    wait(root, dialog)
    assert "changed since preview" in dialog.status.get()
    assert len(app.waypoints()) == 1 and dialog.preview is not None
    dialog.recheck_button.invoke()
    wait(root, dialog)
    assert dialog.preview.conflicts == 0 and not dialog.permission.get()
    panel.store.save(make_place("Imported", 0, 9))
    dialog.recheck()
    wait(root, dialog)
    assert dialog.preview.conflicts == 1
    dialog.permission.set(True)
    dialog._buttons()
    assert str(dialog.action_button["state"]) == "disabled"
    assert panel.store.snapshot((other.point.id,)).records


def test_export_only_selected_snapshot_excludes_notes_then_optin(screen, tmp_path, monkeypatch):
    root, panel, _, workers = screen
    a, b = points(root, panel)
    select(root, panel, a.point.id)
    panel.export_button.invoke()
    dialog = panel.dialog
    workers.append(dialog._worker)
    wait(root, dialog)
    assert len(dialog.preview.points) == 1 and not dialog.preview.points[0].notes
    path = tmp_path / "public.gpx"
    monkeypatch.setattr("fieldforge.ui.place_exchange.filedialog.asksaveasfilename", lambda **kwargs: str(path))
    dialog.permission.set(True)
    dialog.act()
    wait(root, dialog)
    assert b"PRIVATE A" not in path.read_bytes()
    dialog.notes_box.invoke()
    assert dialog.preview is None and not dialog.permission.get()
    dialog.choose_button.invoke()
    wait(root, dialog)
    assert dialog.preview.include_notes and dialog.preview.points[0].notes == "PRIVATE A"
    private = tmp_path / "private.gpx"
    monkeypatch.setattr("fieldforge.ui.place_exchange.filedialog.asksaveasfilename", lambda **kwargs: str(private))
    panel.store.remove(a)
    dialog.permission.set(True)
    dialog.act()
    wait(root, dialog)
    assert parse_gpx(private.read_bytes()).points[0].notes == "PRIVATE A"
    assert len(parse_gpx(private.read_bytes()).points) == 1
    assert panel.store.snapshot().records == (b,)


def test_import_write_blocks_close_and_stays_off_tk_thread(screen, tmp_path, monkeypatch):
    root, panel, _, workers = screen
    from fieldforge.ui import place_exchange
    panel.import_gpx()
    dialog = panel.dialog
    workers.append(dialog._worker)
    dialog.load_path(gpx_file(tmp_path / "input.gpx"))
    wait(root, dialog)
    started, release = threading.Event(), threading.Event()
    threads = []
    original = place_exchange.commit_import
    def delayed(*args, **kwargs):
        threads.append(threading.get_ident())
        started.set()
        release.wait(3)
        return original(*args, **kwargs)
    monkeypatch.setattr(place_exchange, "commit_import", delayed)
    dialog.permission.set(True)
    dialog.act()
    assert started.wait(1)
    dialog.close()
    assert not dialog._disposed and not panel.can_close()
    release.set()
    wait(root, dialog)
    assert threads and threading.get_ident() not in threads
    dialog.close()
    root.update()
    assert panel.can_close()


def test_failed_second_import_preview_clears_previous_file(screen, tmp_path):
    root, panel, _, workers = screen
    panel.import_gpx()
    dialog = panel.dialog
    workers.append(dialog._worker)
    path = gpx_file(tmp_path / "valid.gpx")
    dialog.load_path(path)
    wait(root, dialog)
    dialog.permission.set(True)
    broken = tmp_path / "bad.gpx"
    broken.write_bytes(b"broken")
    dialog.load_path(broken)
    wait(root, dialog)
    assert dialog.preview is None and not dialog.permission.get()
    assert not dialog.tree.get_children()


def test_minimum_supported_geometry_keeps_buttons_in_window(screen, tmp_path):
    root, panel, _, workers = screen
    root.geometry("1000x700")
    points(root, panel)
    root.update()
    for widget in (panel.import_button, panel.export_button, panel.tree, panel.footer):
        assert widget.winfo_rootx()+widget.winfo_width() <= panel.winfo_rootx()+panel.winfo_width()
        assert widget.winfo_rooty()+widget.winfo_height() <= panel.winfo_rooty()+panel.winfo_height()
    panel.add()
    editor = panel.dialog
    editor.geometry("720x610")
    root.update()
    assert editor.save_button.winfo_rooty()+editor.save_button.winfo_height() <= editor.winfo_rooty()+editor.winfo_height()
    editor.close()
    panel.import_gpx()
    dialog = panel.dialog
    workers.append(dialog._worker)
    dialog.load_path(gpx_file(tmp_path / "input.gpx"))
    wait(root, dialog)
    dialog.geometry("880x680")
    root.update()
    for widget in (dialog.action_button, dialog.consent, dialog.footer):
        assert widget.winfo_rootx()+widget.winfo_width() <= dialog.winfo_rootx()+dialog.winfo_width()
        assert widget.winfo_rooty()+widget.winfo_height() <= dialog.winfo_rooty()+dialog.winfo_height()


def test_closing_gpx_read_discards_late_result_without_import(screen, tmp_path, monkeypatch):
    root, panel, app, workers = screen
    from fieldforge.ui import place_exchange
    panel.import_gpx()
    dialog = panel.dialog
    workers.append(dialog._worker)
    started, release = threading.Event(), threading.Event()
    original = place_exchange._read
    def delayed(*args):
        started.set()
        release.wait(3)
        return original(*args)
    monkeypatch.setattr(place_exchange, "_read", delayed)
    dialog.load_path(gpx_file(tmp_path / "input.gpx"))
    assert started.wait(1)
    dialog.close()
    release.set()
    dialog._worker.shutdown(wait=True)
    root.update()
    assert not app.waypoints() and panel.dialog is None
