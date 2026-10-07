"""Real encoded images through both MBTiles readers and the reference renderer."""

import hashlib
import io
import os
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from map_fixture import make_map

from fieldforge.navigation.map_view import Viewport
from fieldforge.navigation.mbtiles import inspect_pack, read_frame
from fieldforge_gps import _file_identity, mbtiles, raster

Image = pytest.importorskip("PIL.Image")


def encoded(fmt, size=(256, 256), color=(80, 120, 160), **kwargs):
    with Image.new("RGB", size, color) as image:
        output = io.BytesIO()
        image.save(output, format=fmt, **kwargs)
        return output.getvalue()


@pytest.mark.parametrize("fmt,label", [("JPEG", "jpg"), ("JPEG", "jpeg"), ("WEBP", "webp")])
@pytest.mark.parametrize("pixels", [256, 512])
def test_both_mbtiles_readers_decode_real_raster_bytes_without_writes(tmp_path, fmt, label, pixels):
    path = make_map(tmp_path / "raster.mbtiles", zooms=(0,), metadata={"format": label})
    original = encoded(fmt, (pixels, pixels))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE tiles SET tile_data=?", (original,))
    before = path.read_bytes()
    gps_pack = mbtiles.inspect_pack(path, consent=True)
    gps_tile = mbtiles.read_tiles(gps_pack, ((0, 0, 0),))[0]
    assert gps_tile.state == "ready"
    main_pack = inspect_pack(path)
    main_tile = read_frame(main_pack, Viewport(0, 0, 0, 256, 256)).tiles[0]
    assert not main_tile.issue and main_tile.pixels == pixels
    for data in (gps_tile.data, main_tile.data):
        with Image.open(io.BytesIO(data)) as image:
            assert image.format == "PNG" and image.size == (pixels, pixels)
            assert (
                max(abs(a - b) for a, b in zip(image.getpixel((10, 10))[:3], (80, 120, 160))) <= 3
            )
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "data,declared",
    [
        (b"not a picture", "jpg"),
        (encoded("PNG"), "jpg"),
        (encoded("JPEG", (128, 256)), "jpg"),
        (encoded("JPEG"), "webp"),
    ],
)
def test_corrupt_mismatched_and_nonsquare_tiles_are_rejected(data, declared):
    with pytest.raises(ValueError):
        raster.tile_png(data, declared)


def test_animated_webp_tile_rejected():
    with (
        Image.new("RGB", (256, 256), "red") as first,
        Image.new("RGB", (256, 256), "blue") as second,
    ):
        data = io.BytesIO()
        first.save(data, format="WEBP", save_all=True, append_images=[second], duration=100, loop=0)
    with pytest.raises(ValueError, match="Animated"):
        raster.tile_png(data.getvalue(), "webp")


@pytest.mark.parametrize(
    "fmt", ["PNG", "JPEG", "WEBP", "TIFF", "BMP", "GIF", "ICO", "PPM", "TGA", "JPEG2000", "AVIF"]
)
def test_supported_reference_images_are_decoded_by_content_and_rendered(tmp_path, fmt):
    # File type is detected from bytes, not inferred from an untrusted extension.
    path = tmp_path / "map-with-arbitrary-extension.data"
    path.write_bytes(encoded(fmt, (64, 64)))
    before = path.read_bytes()
    doc = raster.read_reference(path, consent=True)
    assert doc.format == fmt and doc.width == doc.height == 64
    assert doc.sha256 == hashlib.sha256(before).hexdigest()
    png = raster.render_reference(doc, (32, 32), 1, (64, 64))
    with Image.open(io.BytesIO(png)) as result:
        assert result.format == "PNG" and result.size == (64, 64)
        assert not result.info
    assert path.read_bytes() == before


def test_multi_page_tiff_shows_first_page_only(tmp_path):
    path = tmp_path / "pages.tiff"
    with Image.new("RGB", (50, 40), "red") as first, Image.new("RGB", (50, 40), "blue") as second:
        first.save(path, save_all=True, append_images=[second])
    doc = raster.read_reference(path, consent=True)
    assert doc.pixels.getpixel((10, 10)) == (255, 0, 0, 255)


def simulate_stat_clocks(monkeypatch, path, *, changed_api=None):
    """Model Windows' distinct ctime clocks while retaining real file identities."""
    original_lstat, original_fstat = Path.lstat, os.fstat
    clock = path.lstat().st_ctime_ns
    calls = {"path": 0, "descriptor": 0}

    def clocked(info, api):
        calls[api] += 1
        fields = {
            name: getattr(info, name)
            for name in ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        }
        fields["st_ctime_ns"] = clock + (100 if api == "descriptor" else 0)
        if changed_api == api and calls[api] > 1:
            fields["st_ctime_ns"] += 1
        return SimpleNamespace(**fields)

    def lstat(selected, *args, **kwargs):
        info = original_lstat(selected, *args, **kwargs)
        return clocked(info, "path") if selected == path else info

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(os, "fstat", lambda fd: clocked(original_fstat(fd), "descriptor"))


@pytest.mark.parametrize("windows", [True, False], ids=["windows", "posix"])
def test_reference_path_and_descriptor_ctime_semantics(tmp_path, monkeypatch, windows):
    path = tmp_path / "map.png"
    path.write_bytes(encoded("PNG", (20, 20)))
    simulate_stat_clocks(monkeypatch, path)
    monkeypatch.setattr(_file_identity, "_WINDOWS", windows)
    if windows:
        doc = raster.read_reference(path, consent=True)
        assert doc.format == "PNG" and doc.width == doc.height == 20
    else:
        with pytest.raises(ValueError, match="changed before"):
            raster.read_reference(path, consent=True)


@pytest.mark.parametrize("changed_api", ["path", "descriptor"])
def test_windows_reference_rejects_same_api_ctime_changes(tmp_path, monkeypatch, changed_api):
    path = tmp_path / "map.png"
    path.write_bytes(encoded("PNG", (20, 20)))
    simulate_stat_clocks(monkeypatch, path, changed_api=changed_api)
    monkeypatch.setattr(_file_identity, "_WINDOWS", True)
    with pytest.raises(ValueError, match="changed during"):
        raster.read_reference(path, consent=True)


def test_reference_rejects_file_replaced_after_descriptor_read(tmp_path, monkeypatch):
    path = tmp_path / "map.png"
    replacement = tmp_path / "replacement.png"
    raw = encoded("PNG", (20, 20))
    path.write_bytes(raw)
    replacement.write_bytes(raw)
    before = path.lstat()
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    original_lstat = Path.lstat
    calls = 0

    def lstat(selected, *args, **kwargs):
        nonlocal calls
        if selected == path:
            calls += 1
            if calls == 2:
                os.replace(replacement, path)
        return original_lstat(selected, *args, **kwargs)

    monkeypatch.setattr(_file_identity, "_WINDOWS", True)
    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(ValueError, match="changed during"):
        raster.read_reference(path, consent=True)
    assert not replacement.exists()


def test_reference_rejects_real_write_during_descriptor_read(tmp_path, monkeypatch):
    path = tmp_path / "map.png"
    raw = encoded("PNG", (20, 20))
    path.write_bytes(raw)
    before = path.lstat()
    original_fstat = os.fstat
    calls = 0

    def fstat(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        return original_fstat(fd)

    monkeypatch.setattr(_file_identity, "_WINDOWS", True)
    monkeypatch.setattr(os, "fstat", fstat)
    with pytest.raises(ValueError, match="changed during"):
        raster.read_reference(path, consent=True)


def test_reference_permission_cancellation_and_byte_pixel_limits(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="permission"):
        raster.read_reference(tmp_path / "does-not-exist")
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(ValueError, match="cancelled"):
        raster.read_reference(tmp_path / "does-not-exist", consent=True, cancel=cancelled)
    path = tmp_path / "map.png"
    path.write_bytes(encoded("PNG", (20, 20)))
    monkeypatch.setattr(raster, "MAX_IMAGE_PIXELS", 399)
    with pytest.raises(ValueError, match="million pixels"):
        raster.read_reference(path, consent=True)
    monkeypatch.setattr(raster, "MAX_IMAGE_BYTES", 16)
    with pytest.raises(ValueError, match="regular image"):
        raster.read_reference(path, consent=True)


@pytest.mark.parametrize(
    "source", ["https://example.com/map.png", "file:///tmp/map.png", "//server/map.png"]
)
def test_no_url_or_network_share_inputs(source):
    with pytest.raises(ValueError, match="local image"):
        raster.read_reference(source, consent=True)


@pytest.mark.skipif(
    __import__("sys").platform == "win32", reason="Local symlink privileges vary on Windows"
)
def test_reference_symlink_and_fifo_are_not_opened(tmp_path):
    import os

    source = tmp_path / "image.png"
    source.write_bytes(encoded("PNG"))
    link = tmp_path / "alias.png"
    link.symlink_to(source)
    fifo = tmp_path / "pipe.png"
    os.mkfifo(fifo)
    for path in (link, fifo):
        with pytest.raises(ValueError, match="regular image"):
            raster.read_reference(path, consent=True)


def test_reference_render_is_bounded_and_pans_in_pixel_coordinates(tmp_path):
    path = tmp_path / "map.png"
    with Image.new("RGB", (100, 50), "red") as source:
        source.paste("blue", (50, 0, 100, 50))
        source.save(path)
    doc = raster.read_reference(path, consent=True)
    for center, expected in [((25, 25), (255, 0, 0, 255)), ((75, 25), (0, 0, 255, 255))]:
        with Image.open(io.BytesIO(raster.render_reference(doc, center, 1, (20, 20)))) as view:
            assert view.getpixel((10, 10)) == expected
    for center, scale, size in [
        ((25, 25), float("nan"), (20, 20)),
        ((25, 25), 0, (20, 20)),
        ((25, 25), 1, (100_000, 100_000)),
        ((25, float("inf")), 1, (20, 20)),
    ]:
        with pytest.raises(ValueError, match="viewport"):
            raster.render_reference(doc, center, scale, size)
