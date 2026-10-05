import gc
import os
import sqlite3
import threading
import time
from concurrent.futures import Future
from dataclasses import replace
from types import SimpleNamespace

import pytest
from map_fixture import make_map, png

from fieldforge.app import FieldForgeApp
from fieldforge.navigation.mbtiles import inspect_pack
from fieldforge.navigation.places import PlaceStore, make_place


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip('tkinter')
    from fieldforge.ui.maps import MapsTab
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip('Tk display unavailable; graphical CI explicitly requires Tk')
    root.geometry('1120x820')
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr('tkinter.messagebox.askyesno', lambda *args, **kwargs: False)
    app = FieldForgeApp(tmp_path/'app.db')
    panel = MapsTab(root, app.db.path)
    panel.pack(fill='both', expand=True)
    root.update()
    path = make_map(tmp_path/'training.mbtiles')
    try:
        yield root, panel, app, path
    finally:
        root.destroy()
        panel._worker.shutdown(wait=True, cancel_futures=True)
        gc.collect()
    assert not errors


def wait(root, panel):
    deadline = time.monotonic() + 6
    idle_since = None
    while time.monotonic() < deadline:
        root.update()
        if not panel.busy and panel._resize_id is None:
            idle_since = idle_since or time.monotonic()
            if time.monotonic() - idle_since > .18:
                return
        else:
            idle_since = None
        time.sleep(.005)
    assert False, (panel.busy, panel.status.get(), panel._generation)


def opened(root, panel, path):
    panel.open_path(path)
    wait(root, panel)
    assert panel.frame is not None, panel.status.get()


def test_initial_screen_never_opens_map_or_reads_private_places(screen, monkeypatch):
    root, panel, app, path = screen
    assert panel.pack_info is None and panel.frame is None
    assert not panel.overlay.get() and not panel.markers
    assert not app.waypoints()
    assert str(panel.go_button['state']) == 'disabled'
    assert 'No GPS' in panel.notice['text']
    called = []
    monkeypatch.setattr('fieldforge.ui.maps.read_markers', lambda *_: called.append(True))
    opened(root, panel, path)
    assert not called and not panel.canvas.find_withtag('private-marker')


def test_prepared_regional_map_window_reuses_single_open_instance(screen, monkeypatch):
    _, panel, _, _ = screen
    from fieldforge.ui import regional_index

    opened = []

    class Window:
        def __init__(self, parent):
            self.parent = parent
            self._disposed = False
            self.lifted = 0
            opened.append(self)

        def lift(self):
            self.lifted += 1

    monkeypatch.setattr(regional_index, 'RegionalIndexWindow', Window)
    panel.regional_button.invoke()
    first = panel._regional_window
    panel.regional_button.invoke()
    assert first.parent is panel
    assert panel._regional_window is first and first.lifted == 1 and len(opened) == 1

    first._disposed = True
    panel.regional_button.invoke()
    assert panel._regional_window is not first and len(opened) == 2


def test_file_picker_requires_trust_confirmation_before_opening(screen, monkeypatch):
    root, panel, _, path = screen
    monkeypatch.setattr('fieldforge.ui.maps.filedialog.askopenfilename', lambda **kwargs: str(path))
    panel.open_button.invoke()
    assert panel.pack_info is None and not panel.busy
    monkeypatch.setattr('tkinter.messagebox.askyesno', lambda *args, **kwargs: True)
    panel.open_button.invoke()
    wait(root, panel)
    assert panel.frame is not None and panel._images
    assert 'Original FieldForge test grid' in panel.attribution.get()
    assert '0 unreadable' in panel.status.get()


def test_actual_png_rendering_and_half_resolution_retina(screen, tmp_path):
    root, panel, _, _ = screen
    path = make_map(tmp_path/'retina.mbtiles', zooms=(0,), size=512)
    opened(root, panel, path)
    assert all(image.width() == image.height() == 256 for image in panel._images)
    assert panel._images[0].get(1, 1) == (70, 115, 90)
    assert 'outside projection' in panel.status.get()


def test_pan_zoom_buttons_keyboard_and_home(screen):
    root, panel, _, path = screen
    opened(root, panel, path)
    assert panel.view.zoom == 2
    panel.minus.invoke()
    wait(root, panel)
    assert panel.view.zoom == 1
    panel.key(SimpleNamespace(keysym='Right'))
    wait(root, panel)
    assert panel.view.longitude == pytest.approx(90)
    panel.plus.invoke()
    wait(root, panel)
    assert panel.view.zoom == 2 and panel.view.longitude == pytest.approx(90)
    panel.home_button.invoke()
    wait(root, panel)
    assert panel.view.latitude == panel.view.longitude == 0
    panel.wheel(SimpleNamespace(delta=-120))
    wait(root, panel)
    assert panel.view.zoom == 1


def test_drag_and_pointer_use_rendered_coordinates_not_gps(screen):
    root, panel, _, path = screen
    opened(root, panel, path)
    old = panel.view
    panel.motion(SimpleNamespace(x=old.width/2, y=old.height/2))
    assert 'latitude 0.0000000' in panel.pointer.get() and 'NOT GPS' in panel.pointer.get()
    panel.drag_start(SimpleNamespace(x=100, y=100))
    panel.drag_move(SimpleNamespace(x=164, y=100))
    assert 'Panning preview' in panel.pointer.get()
    panel.drag_end(SimpleNamespace(x=164, y=100))
    wait(root, panel)
    assert panel.view.longitude == pytest.approx(-22.5)


def test_coordinate_center_and_invalid_polar_value_not_clamped(screen):
    root, panel, _, path = screen
    opened(root, panel, path)
    panel.latitude.set('45')
    panel.longitude.set('-90')
    panel.go_button.invoke()
    wait(root, panel)
    assert panel.view.latitude == 45 and panel.view.longitude == -90
    old = panel.view
    panel.latitude.set('90')
    panel.go()
    assert panel.view == old and 'polar coordinates' in panel.status.get()
    panel.latitude.set('not latitude')
    panel.go()
    assert panel.view == old and 'Center not changed' in panel.status.get()


def test_missing_and_broken_png_cells_labeled_without_old_images(screen, tmp_path):
    root, panel, _, path = screen
    opened(root, panel, path)
    hole = make_map(tmp_path/'hole.mbtiles', zooms=(0,), missing=((0, 0, 0),))
    # Retain a zoom while leaving the visible center tile missing at z2.
    hole2 = make_map(tmp_path/'hole2.mbtiles', missing=((2, 1, 1), (2, 2, 1), (2, 1, 2), (2, 2, 2)))
    opened(root, panel, hole2)
    labels = [panel.canvas.itemcget(item, 'text') for item in panel.canvas.find_all() if panel.canvas.type(item) == 'text']
    assert any('Tile not installed' in value for value in labels)
    panel.open_path(hole)
    wait(root, panel)
    assert panel.frame is None and not panel._images and 'could not be opened' in panel.source.get()
    bad = make_map(tmp_path/'bad-png.mbtiles', zooms=(0,))
    with sqlite3.connect(bad) as db:
        db.execute('UPDATE tiles SET tile_data=?', (png()[:33]+b'broken',))
    opened(root, panel, bad)
    assert 'unreadable' in panel.status.get() and not panel._images
    labels = [panel.canvas.itemcget(i, 'text') for i in panel.canvas.find_all() if panel.canvas.type(i) == 'text']
    assert any('PNG could not be decoded' in value for value in labels)


def test_place_overlay_optin_does_not_show_notes_or_move_database(screen):
    root, panel, app, path = screen
    store = PlaceStore(app.db.path)
    a = store.save(make_place('Training marker', 0, 1, notes='PRIVATE_NOTE_NOT_SHOWN'))
    store.save(make_place('Polar marker', 90, 0))
    before = app.db.path.read_bytes()
    opened(root, panel, path)
    assert panel.markers == ()
    panel.overlay_box.invoke()
    wait(root, panel)
    assert len(panel.markers) == 2 and panel.canvas.find_withtag('private-marker')
    assert '1 outside projection' in panel.status.get()
    assert 'PRIVATE_NOTE_NOT_SHOWN' not in panel.status.get() + str(panel.markers)
    panel.place_choice.set(f'{a.point.id} — Training marker')
    panel.center_button.invoke()
    wait(root, panel)
    assert panel.view.longitude == 1
    panel.place_choice.set('2 — Polar marker')
    panel.center_place()
    assert panel.view.longitude == 1 and 'outside the Web Mercator' in panel.status.get()
    panel.overlay_box.invoke()
    wait(root, panel)
    assert panel.markers == () and not panel.canvas.find_withtag('private-marker')
    assert app.db.path.read_bytes() == before


def test_overlay_refreshed_after_saved_place_changes_and_error_clears_it(screen, monkeypatch):
    root, panel, app, path = screen
    store = PlaceStore(app.db.path)
    record = store.save(make_place('First marker', 0, 1))
    opened(root, panel, path)
    panel.overlay_box.invoke()
    wait(root, panel)
    assert panel.markers[0].name == 'First marker'
    store.save(replace(record.point, name='Edited marker'), expected=record)
    panel.reload_button.invoke()
    wait(root, panel)
    assert panel.markers[0].name == 'Edited marker'
    def fail(*args):
        raise ValueError('Marker source unavailable')
    monkeypatch.setattr('fieldforge.ui.maps.read_markers', fail)
    panel.request_view()
    wait(root, panel)
    assert not panel.markers and not panel.canvas.find_withtag('private-marker')
    assert panel.frame is not None and 'Saved places unavailable' in panel.status.get()


def test_map_changed_on_disk_clears_frame_and_cannot_show_cached_success(screen):
    root, panel, _, path = screen
    opened(root, panel, path)
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns+100000))
    panel.reload_button.invoke()
    wait(root, panel)
    assert panel.frame is None and not panel._images
    assert 'changed since opening' in panel.status.get()


def test_cancel_and_late_open_result_cannot_replace_new_map(screen, tmp_path, monkeypatch):
    root, panel, _, path = screen
    from fieldforge.ui import maps
    first = inspect_pack(path)
    second_path = make_map(tmp_path/'second.mbtiles', metadata={'name': 'Second training map'})
    started, release = threading.Event(), threading.Event()
    real = maps.inspect_pack
    def delayed(source, *, cancel):
        if source == path:
            started.set()
            release.wait(3)
            return first  # Deliberately ignore cancellation to test UI generation tokens.
        return real(source, cancel=cancel)
    monkeypatch.setattr(maps, 'inspect_pack', delayed)
    panel.open_path(path)
    assert started.wait(1)
    panel.open_path(second_path)
    release.set()
    wait(root, panel)
    assert panel.pack_info.name == 'Second training map'
    old = Future()
    old.set_result(first)
    panel._poll(old, 'open', panel._generation-1)
    assert panel.pack_info.name == 'Second training map'


def test_close_map_cancels_late_frame_and_erases_session_overlay(screen, monkeypatch):
    root, panel, _, path = screen
    from fieldforge.ui import maps
    opened(root, panel, path)
    started, release = threading.Event(), threading.Event()
    original = maps._read_view
    def delayed(*args, cancel):
        started.set()
        release.wait(3)
        return original(*args, cancel=cancel)
    monkeypatch.setattr(maps, '_read_view', delayed)
    panel.request_view()
    assert started.wait(1)
    panel.close_button.invoke()
    release.set()
    panel._worker.shutdown(wait=True)
    root.update()
    assert panel.pack_info is None and panel.frame is None and not panel.markers
    assert not panel.overlay.get() and not panel._images


def test_reads_run_on_worker_and_tk_decode_on_main_thread(screen, monkeypatch):
    root, panel, _, path = screen
    from fieldforge.ui import maps
    main = threading.get_ident()
    reads, decodes = [], []
    original, draw = maps.read_frame, panel._draw
    def read(*args, **kwargs):
        reads.append(threading.get_ident())
        return original(*args, **kwargs)
    def paint(*args):
        decodes.append(threading.get_ident())
        return draw(*args)
    monkeypatch.setattr(maps, 'read_frame', read)
    monkeypatch.setattr(panel, '_draw', paint)
    opened(root, panel, path)
    assert reads and all(t != main for t in reads)
    assert decodes and set(decodes) == {main}


def test_full_source_metadata_shown_as_text_never_fetched(screen, tmp_path):
    root, panel, _, _ = screen
    content = '<script>do_not_execute()</script> https://example.invalid/map'
    path = make_map(tmp_path/'metadata.mbtiles', metadata={'attribution': content*30, 'license': 'Unknown; not inferred'})
    opened(root, panel, path)
    window = panel.details()
    root.update()
    def text_widgets(widget):
        if widget.winfo_class() == 'Text':
            yield widget
        for child in widget.winfo_children():
            yield from text_widgets(child)
    text = next(text_widgets(window)).get('1.0', 'end')
    assert content*30 in text and 'not copied into FieldForge' in text
    assert 'full text in Map details' in panel.attribution.get()
    window.destroy()


def test_minimum_geometry_and_cursor_updates_do_not_cause_resize_reload_loop(screen):
    root, panel, _, path = screen
    root.geometry('1000x700')
    root.update()
    opened(root, panel, path)
    assert panel.canvas.winfo_height() >= 200
    for widget in (panel.open_button, panel.reload_button, panel.center_button, panel.footer):
        assert widget.winfo_rootx()+widget.winfo_width() <= panel.winfo_rootx()+panel.winfo_width()
        assert widget.winfo_rooty()+widget.winfo_height() <= panel.winfo_rooty()+panel.winfo_height()
    generation = panel._generation
    panel.motion(SimpleNamespace(x=panel.view.width/2, y=panel.view.height/2))
    wait(root, panel)
    assert panel._generation == generation
    root.geometry('1200x820')
    wait(root, panel)
    assert panel.frame.view.width == panel.canvas.winfo_width()
    stable = panel._generation
    wait(root, panel)
    assert stable == panel._generation


def test_destroy_signals_worker_cancellation_without_writes(screen, monkeypatch):
    root, panel, app, path = screen
    started, finished = threading.Event(), threading.Event()
    def read(_source, *, cancel):
        started.set()
        assert cancel.wait(3)
        finished.set()
        raise ValueError('Cancelled test')
    monkeypatch.setattr('fieldforge.ui.maps.inspect_pack', read)
    before = app.db.path.read_bytes()
    panel.open_path(path)
    assert started.wait(1)
    panel.destroy()
    assert finished.wait(1)
    panel._worker.shutdown(wait=True)
    root.update()
    assert app.db.path.read_bytes() == before
