import gc
import threading
import time

import pytest
from map_fixture import make_map

from fieldforge.app import FieldForgeApp
from fieldforge.navigation.map_view import Viewport
from fieldforge.navigation.mbtiles import inspect_pack, read_frame, read_markers
from fieldforge.navigation.places import PlaceStore, make_place


def test_external_maps_are_not_copied_into_app_backups_or_content_exports(tmp_path):
    from fieldforge.core.recovery import create_verified_backup, restore_verified_copy
    from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
    from fieldforge.knowledge.packs import export_pack

    app = FieldForgeApp(tmp_path/'app.db')
    app.knowledge.upsert(KnowledgeArticle('lesson', 'Practice lesson', 'Original test text', 'reference'))
    saved = PlaceStore(app.db.path).save(make_place('Private location example', 0, 1, notes='Private place note'))
    path = make_map(tmp_path/'external-map.mbtiles', metadata={'name': 'MAP_STORAGE_SENTINEL_43'})
    before = app.db.path.read_bytes()
    assert read_frame(inspect_pack(path), Viewport(0, 0, 2, 512, 512)).tiles
    assert read_markers(app.db.path)[0].id == saved.point.id
    assert app.db.path.read_bytes() == before
    exported = export_pack(app.knowledge, tmp_path/'content.json').read_bytes()
    assert b'MAP_STORAGE_SENTINEL_43' not in exported and b'Private location example' not in exported
    backup = create_verified_backup(app.db.path, tmp_path/'backup.ffbackup')
    restored = restore_verified_copy(backup, tmp_path/'recovered.db', active_database=app.db.path)
    assert b'MAP_STORAGE_SENTINEL_43' not in restored.read_bytes()
    assert KnowledgeLibrary(restored).get('lesson') == app.knowledge.get('lesson')
    assert PlaceStore(restored).snapshot().records == (saved,)
    path.unlink()
    # An app backup preserved the place record, not the external imagery file.
    assert read_markers(restored) and not path.exists()


def test_real_desktop_maps_section_opens_file_and_normal_close_cancels_reader(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip('tkinter')
    from fieldforge.ui import desktop, maps
    from fieldforge.ui.maps import MapsTab

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip('Tk display unavailable; dedicated graphical CI requires Tk')
    root.geometry('1240x800')
    app_path = tmp_path/'app.db'
    path = make_map(tmp_path/'external.mbtiles')
    monkeypatch.setenv('FIELDFORGE_DB', str(app_path))
    monkeypatch.setattr(tk, 'Tk', lambda: root)
    monkeypatch.setattr('tkinter.messagebox.askyesno', lambda *args, **kwargs: True)
    monkeypatch.setattr('fieldforge.ui.maps.filedialog.askopenfilename', lambda **kwargs: str(path))
    errors, workers, passed = [], [], []
    root.report_callback_exception = lambda *args: errors.append(args)
    cancelled = threading.Event()

    def children(widget):
        yield widget
        for child in widget.winfo_children():
            yield from children(child)

    def exercise():
        root.after_cancel(timer)
        try:
            panel = next(w for w in children(root) if isinstance(w, MapsTab))
            root.geometry('1000x700')
            root.update()
            selector = root.nametowidget('.section_navigation.choice')
            assert 'Maps' in selector['values'] and selector.winfo_ismapped()
            selector.set('Maps')
            selector.event_generate('<<ComboboxSelected>>')
            root.update()
            assert panel.master.select() == str(panel)
            panel.open_button.invoke()
            deadline = time.monotonic()+8
            while (panel.busy or panel.frame is None) and time.monotonic() < deadline:
                root.update()
                time.sleep(.005)
            assert panel.frame is not None and panel._images
            assert not panel.overlay.get() and not panel.markers
            started = threading.Event()
            def delayed(*args, cancel):
                started.set()
                assert cancel.wait(3)
                cancelled.set()
                raise ValueError('Cancelled during desktop close')
            monkeypatch.setattr(maps, '_read_view', delayed)
            panel.request_view()
            assert started.wait(1)
            workers.extend(w._worker for w in children(root) if hasattr(w, '_worker'))
            root.tk.call(root.protocol('WM_DELETE_WINDOW'))
            assert cancelled.wait(1)
            passed.append(True)
        except Exception as exc:
            errors.append(exc)
            try:
                workers.extend(w._worker for w in children(root) if hasattr(w, '_worker'))
                root.destroy()
            except tk.TclError:
                pass

    root.after(200, exercise)
    timer = root.after(12000, root.destroy)
    desktop.run()
    for worker in workers:
        worker.shutdown(wait=True, cancel_futures=True)
    gc.collect()
    assert passed and cancelled.is_set() and not errors
    assert FieldForgeApp(app_path).waypoints() == []
