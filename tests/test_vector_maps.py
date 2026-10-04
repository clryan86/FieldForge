"""Synthetic MVT bytes exercise actual offline vector decoding and rendering."""

import gzip
import io
import sqlite3
from contextlib import closing

import pytest
from map_fixture import make_map
from PIL import Image

from fieldforge.navigation.map_view import Viewport
from fieldforge.navigation.mbtiles import inspect_pack, read_frame
from fieldforge.navigation.vector_tiles import render_vector_tile
from fieldforge.online.catalog import CatalogError, inspect_raster
from fieldforge_gps.mbtiles import inspect_pack as inspect_gps_pack
from fieldforge_gps.mbtiles import read_tiles


def _varint(value):
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def _uint(field, value):
    return _varint(field << 3) + _varint(value)


def _bytes(field, value):
    return _varint((field << 3) | 2) + _varint(len(value)) + value


def _text(field, value):
    return _bytes(field, value.encode("utf-8"))


def _packed(field, values):
    return _bytes(field, b"".join(_varint(value) for value in values))


def _zigzag(value):
    return (value << 1) ^ (value >> 63)


def _layer(name, geom_type, commands, *, road_class=None):
    feature = b""
    if road_class is not None:
        feature += _packed(2, [0, 0])
    feature += _uint(3, geom_type) + _packed(4, commands)
    layer = _text(1, name) + _bytes(2, feature)
    if road_class is not None:
        layer += _text(3, "class") + _bytes(4, _text(1, road_class))
    return layer + _uint(5, 4096) + _uint(15, 2)


def vector_tile():
    # Full-tile water polygon and a major road, encoded as real MVT protobuf.
    polygon = [9, 0, 0, 26, _zigzag(4096), 0, 0, _zigzag(4096),
               _zigzag(-4096), 0, 15]
    line = [9, _zigzag(500), _zigzag(2048), 10, _zigzag(3000), 0]
    return _bytes(3, _layer("water", 3, polygon)) + _bytes(
        3, _layer("transportation", 2, line, road_class="primary")
    )


def _image(data):
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGBA")


def test_vector_tile_renders_polygon_and_styled_major_road():
    rendered = render_vector_tile(gzip.compress(vector_tile()))
    with _image(rendered) as image:
        assert image.size == (256, 256)
        assert image.getpixel((20, 20))[:3] == (168, 207, 224)
        assert image.getpixel((128, 128))[:3] != image.getpixel((128, 120))[:3]
        assert image.getpixel((128, 120))[:3] == (168, 207, 224)


@pytest.mark.parametrize("bad", [b"", b"bad", b"\x1f\x8bcorrupt", b"\x1a\x05abc"])
def test_invalid_or_empty_vector_tiles_are_rejected(bad):
    with pytest.raises(ValueError):
        render_vector_tile(bad)


def test_pbf_mbtiles_open_in_both_offline_readers_without_changing_source(tmp_path):
    path = make_map(tmp_path / "roads.mbtiles", zooms=(0,), metadata={"format": "pbf"})
    source = gzip.compress(vector_tile())
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE tiles SET tile_data=?", (source,))
    original = path.read_bytes()

    main_pack = inspect_pack(path)
    main_frame = read_frame(main_pack, Viewport(0, 0, 0, 256, 256))
    assert main_frame.tiles[0].pixels == 256 and main_frame.tiles[0].data.startswith(b"\x89PNG")

    gps_pack = inspect_gps_pack(path, consent=True)
    gps_tile, = read_tiles(gps_pack, ((0, 0, 0),))
    assert gps_tile.state == "ready" and gps_tile.data.startswith(b"\x89PNG")
    with _image(gps_tile.data) as image:
        assert image.getpixel((20, 20))[:3] == (168, 207, 224)
    assert path.read_bytes() == original


def test_portal_preflight_accepts_real_vector_mbtiles_and_rejects_raster_mislabeled_as_pbf(tmp_path):
    path = make_map(tmp_path / "publishable.mbtiles", zooms=(0,), metadata={"format": "pbf"})
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE tiles SET tile_data=?", (gzip.compress(vector_tile()),))
    inspect_raster(path, "mbtiles")

    bad = make_map(tmp_path / "mislabeled.mbtiles", zooms=(0,), metadata={"format": "pbf"})
    with pytest.raises(CatalogError, match="PBF tile sample"):
        inspect_raster(bad, "mbtiles")
