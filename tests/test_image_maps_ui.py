"""Reference image UI and cancellation; real Tk and real encoded raster fixtures."""

import time

import pytest
from test_gps_desktop import root as root
from test_raster_maps import encoded

from fieldforge_gps.image_map_ui import ImageMapFrame


@pytest.fixture
def image_ui(root):
    root.geometry("1080x780")
    frame = ImageMapFrame(root)
    root.update()
    yield root, frame
    frame.close()
    frame.worker._thread.join(2)
    assert not frame.worker._thread.is_alive()


def settled(root, frame):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        root.update()
        if frame._job is None and frame._draw_after is None:
            return
        time.sleep(0.005)
    raise AssertionError("Image viewer did not settle")


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "TIFF", "BMP", "GIF"])
def test_real_image_open_pan_zoom_and_clear(image_ui, tmp_path, fmt):
    root, frame = image_ui
    path = tmp_path / "reference-image"
    path.write_bytes(encoded(fmt, (800, 500)))
    original = path.read_bytes()
    assert not frame.open_path(path) and frame.document is None
    frame.permission.set(True)
    assert frame.open_path(path)
    settled(root, frame)
    assert frame.document.format == fmt and frame.canvas.find_withtag("reference-image")
    assert "Uncalibrated" in frame.status.get() and "First page/frame" in frame.status.get()
    frame.actual_button.invoke()
    frame.pan(30, 20)
    settled(root, frame)
    assert frame.scale == 1 and frame.center == (430, 270)
    frame.plus_button.invoke()
    settled(root, frame)
    assert frame.scale == 1.5
    frame.permission.set(False)
    assert frame.document is None and not frame.canvas.find_withtag("reference-image")
    assert path.read_bytes() == original


def test_replacing_image_clears_old_pixels_even_when_new_file_fails(image_ui, tmp_path):
    root, frame = image_ui
    path = tmp_path / "map.png"
    path.write_bytes(encoded("PNG"))
    frame.permission.set(True)
    frame.open_path(path)
    settled(root, frame)
    assert frame.canvas.find_withtag("reference-image")
    frame.open_path(tmp_path / "missing.png")
    assert frame.document is None and not frame.canvas.find_withtag("reference-image")
    settled(root, frame)
    assert frame.document is None and frame._photo is None


def test_close_while_image_read_is_pending_discards_late_result(image_ui, tmp_path, monkeypatch):
    import threading

    from fieldforge_gps import raster

    root, frame = image_ui
    path = tmp_path / "map.png"
    path.write_bytes(encoded("PNG"))
    document = raster.read_reference(path, consent=True)
    started, release = threading.Event(), threading.Event()

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(2)
        return document

    monkeypatch.setattr(raster, "read_reference", delayed)
    frame.permission.set(True)
    frame.open_path(path)
    assert started.wait(1)
    frame.close()
    release.set()
    frame.worker._thread.join(2)
    root.update()
    assert frame.document is None and frame._photo is None and frame._after is None
    assert frame.worker.poll() is None


def test_map_workspace_owns_image_viewer_and_closes_its_worker(root):
    from fieldforge.ui.gps import GPSWorkspace

    owner = GPSWorkspace(root)
    receiver = owner.open()
    view = receiver.live_map_frame
    image_frame = view.open_image_reference()
    assert view.open_image_reference() is image_frame
    assert receiver.session is None and not view.show_live.get()
    workers = [image_frame.worker, view._map_reader]
    owner.close()
    for worker in workers:
        worker._thread.join(2)
        assert not worker._thread.is_alive()
    assert image_frame._closed
