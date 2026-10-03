import hashlib
import sqlite3
import struct
import threading
import zlib
from contextlib import closing
from pathlib import Path

import pytest

from fieldforge_gps import mbtiles as m


def png(size=256, color=(50, 90, 70)):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    raw = (b"\0" + bytes(color) * size) * size
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def pack_file(tmp_path, *, name="map.mbtiles", metadata=None, rows=None, index=True):
    path = tmp_path / name
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE metadata(name TEXT,value TEXT)")
        db.execute(
            "CREATE TABLE tiles(zoom_level INTEGER,tile_column INTEGER,tile_row INTEGER,tile_data BLOB)"
        )
        if index:
            db.execute("CREATE UNIQUE INDEX tile_index ON tiles(zoom_level,tile_column,tile_row)")
        db.executemany(
            "INSERT INTO metadata VALUES (?,?)",
            metadata if metadata is not None else [("name", "Test map"), ("format", "png")],
        )
        db.executemany(
            "INSERT INTO tiles VALUES(?,?,?,?)",
            rows if rows is not None else [(0, 0, 0, png()), (2, 1, 2, png())],
        )
    return path


def test_ordinary_pack_zoom_is_observed_not_claimed(tmp_path):
    path = pack_file(
        tmp_path,
        metadata=[("name", "Test"), ("format", "png"), ("minzoom", "17"), ("maxzoom", "22")],
    )
    p = m.inspect_pack(path, consent=True)
    assert p.levels == (0, 2)
    assert p.start == (0, 0, 0)


@pytest.mark.parametrize("consent", [False, None, 1, "yes"])
def test_consent_required_before_even_checking_path(consent):
    with pytest.raises(ValueError, match="Confirm"):
        m.inspect_pack("/nonexistent/map.mbtiles", consent=consent)


@pytest.mark.parametrize(
    "value",
    [
        "https://example.test/a.mbtiles",
        "file:///tmp/a.mbtiles",
        "//server/share/a.mbtiles",
        r"\\server\share\a.mbtiles",
    ],
)
def test_urls_and_unc_rejected(value):
    with pytest.raises(ValueError, match="local file"):
        m.inspect_pack(value, consent=True)


def test_readonly_tms_reversal_and_no_fallback(tmp_path):
    path = pack_file(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    files = set(tmp_path.iterdir())
    path.chmod(0o444)
    pack = m.inspect_pack(path, consent=True)
    tiles = m.read_tiles(pack, ((2, 1, 1), (2, 1, 2), (1, 0, 0)))
    assert [t.state for t in tiles] == ["ready", "missing", "missing"]
    assert tiles[0].data == png()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert set(tmp_path.iterdir()) == files


def test_official_mbtiles_coordinate_example(tmp_path):
    p = m.inspect_pack(pack_file(tmp_path, rows=[(11, 327, 1256, png())]), consent=True)
    assert m.read_tiles(p, ((11, 327, 791),))[0].state == "ready"
    assert m.read_tiles(p, ((11, 327, 1256),))[0].state == "missing"


@pytest.mark.parametrize("name", ["space # ? café.mbtiles", "UPPER.MBTILES"])
def test_uri_quoting_and_unicode(tmp_path, name):
    p = m.inspect_pack(pack_file(tmp_path, name=name), consent=True)
    assert m.read_tiles(p, ((0, 0, 0),))[0].state == "ready"


@pytest.mark.parametrize("suffix", ["-wal", "-journal", "-shm"])
def test_active_sidecar_rejected(tmp_path, suffix):
    path = pack_file(tmp_path)
    Path(str(path) + suffix).write_bytes(b"active")
    with pytest.raises(ValueError, match="sidecar"):
        m.inspect_pack(path, consent=True)


def test_wal_header_without_sidecar_rejected(tmp_path):
    path = pack_file(tmp_path)
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    with pytest.raises(ValueError, match="WAL-mode"):
        m.inspect_pack(path, consent=True)


def test_view_layout_rejected_not_called_corrupt(tmp_path):
    path = pack_file(tmp_path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("ALTER TABLE tiles RENAME TO storage")
        db.execute("CREATE VIEW tiles AS SELECT * FROM storage")
    with pytest.raises(ValueError, match="ordinary"):
        m.inspect_pack(path, consent=True)


@pytest.mark.parametrize(
    "index_sql",
    [
        None,
        "CREATE INDEX nope ON tiles(zoom_level,tile_column,tile_row)",
        "CREATE UNIQUE INDEX nope ON tiles(tile_column,zoom_level,tile_row)",
        "CREATE UNIQUE INDEX nope ON tiles(zoom_level,tile_column,tile_row) WHERE zoom_level=0",
        "CREATE UNIQUE INDEX nope ON tiles(zoom_level COLLATE NOCASE,tile_column,tile_row)",
    ],
)
def test_unsupported_index_never_repaired(tmp_path, index_sql):
    path = pack_file(tmp_path, index=False)
    if index_sql:
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(index_sql)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="unique"):
        m.inspect_pack(path, consent=True)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [("name", "No format")],
        [("format", "png")],
        [("name", ""), ("format", "png")],
        [("name", "A"), ("format", "pbf")],
        [("name", "A"), ("format", "png"), ("name", "B")],
        [("name", "A"), ("format", "png"), ("scheme", "xyz")],
        [("name", "x" * 16385), ("format", "png")],
        [("name", b"not text"), ("format", "png")],
        [("name", "A"), ("format", "png")] + [(str(i), "v") for i in range(127)],
        [("name", "A"), ("format", "png"), ("k" * 129, "v")],
        [("name", "é" * 8200), ("format", "png")],
    ],
)
def test_bad_metadata(tmp_path, rows):
    with pytest.raises(ValueError):
        m.inspect_pack(pack_file(tmp_path, metadata=rows), consent=True)


@pytest.mark.parametrize("center", ["-90,45,2", "180,0,0", "0,0,0"])
def test_valid_declared_center(tmp_path, center):
    p = m.inspect_pack(
        pack_file(tmp_path, metadata=[("name", "A"), ("format", "png"), ("center", center)]),
        consent=True,
    )
    assert p.start[2] == int(center.split(",")[2])
    assert "pack-declared" in p.start_notice
    assert -180 <= p.start[0] < 180


@pytest.mark.parametrize(
    "center", ["1,2", "nan,0,0", "0,90,0", "181,0,0", "0,0,1", "0,0,.5", "<script>"]
)
def test_invalid_center_falls_back_to_observed_tile(tmp_path, center):
    p = m.inspect_pack(
        pack_file(tmp_path, metadata=[("name", "A"), ("format", "png"), ("center", center)]),
        consent=True,
    )
    assert p.start == (0, 0, 0) and "Invalid declared center" in p.start_notice


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [(-1, 0, 0, png())],
        [(23, 0, 0, png())],
        [(0, -1, 0, png())],
        [(0, 0, 1, png())],
        [(1.5, 0, 0, png())],
    ],
)
def test_invalid_or_empty_coordinates(tmp_path, rows):
    with pytest.raises(ValueError):
        m.inspect_pack(pack_file(tmp_path, rows=rows), consent=True)


@pytest.mark.parametrize(
    "data", [b"", b"junk" * 30, b"x" * (m.MAX_TILE_BYTES + 1), None, "not bytes", png(32)]
)
def test_bad_tiles_marked_without_invalidating_other_cells(tmp_path, data):
    p = m.inspect_pack(pack_file(tmp_path, rows=[(0, 0, 0, data), (2, 1, 2, png())]), consent=True)
    assert [t.state for t in m.read_tiles(p, ((0, 0, 0), (2, 1, 1)))] == ["bad", "ready"]


@pytest.mark.parametrize("size", [256, 512])
def test_supported_png_sizes(size):
    assert m.png_preflight(png(size)) == size


def test_bad_png_crc_rejected():
    data = bytearray(png())
    data[29] ^= 1
    with pytest.raises(ValueError, match="checksum"):
        m.png_preflight(bytes(data))


@pytest.mark.parametrize("offset,value", [(24, 7), (25, 9), (26, 1), (27, 1), (28, 2)])
def test_invalid_png_encoding(offset, value):
    data = bytearray(png())
    data[offset] = value
    data[29:33] = struct.pack(">I", zlib.crc32(data[12:29]))
    with pytest.raises(ValueError, match="encoding"):
        m.png_preflight(bytes(data))


@pytest.mark.parametrize(
    "keys",
    [
        [(True, 0, 0)],
        [(0, 1, 0)],
        [(0, 0, -1)],
        [(23, 0, 0)],
        [(0, 0)],
        [(0, "0", 0)],
        [(0, 0, 0)] * 97,
    ],
)
def test_bad_requests(tmp_path, keys):
    p = m.inspect_pack(pack_file(tmp_path), consent=True)
    with pytest.raises(ValueError):
        m.read_tiles(p, keys)


def test_duplicate_cells_count_bytes_once(tmp_path, monkeypatch):
    p = m.inspect_pack(pack_file(tmp_path), consent=True)
    monkeypatch.setattr(m, "MAX_FRAME_BYTES", len(png()))
    assert len(m.read_tiles(p, ((0, 0, 0),) * 50)) == 50
    with pytest.raises(ValueError, match="32 MiB"):
        m.read_tiles(p, ((0, 0, 0), (2, 1, 1)))


def test_changed_source_is_rejected_even_if_new_tile_is_valid(tmp_path):
    path = pack_file(tmp_path)
    p = m.inspect_pack(path, consent=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE metadata SET value='Changed' WHERE name='name'")
    with pytest.raises(ValueError, match="changed"):
        m.read_tiles(p, ((0, 0, 0),))


def test_cancel_before_open_or_frame(tmp_path):
    path = pack_file(tmp_path)
    p = m.inspect_pack(path, consent=True)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(m.MapReadCancelled):
        m.inspect_pack(path, consent=True, cancel=cancel)
    with pytest.raises(m.MapReadCancelled):
        m.read_tiles(p, ((0, 0, 0),), cancel=cancel)


def test_database_connection_is_query_only(tmp_path):
    p = m.inspect_pack(pack_file(tmp_path), consent=True)
    with m._database(p.path, p.identity, None) as db:
        assert db.execute("PRAGMA query_only").fetchone() == (1,)
        assert db.execute("PRAGMA trusted_schema").fetchone() == (0,)
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM tiles")


def test_sql_progress_deadline(tmp_path, monkeypatch):
    p = m.inspect_pack(pack_file(tmp_path), consent=True)
    monkeypatch.setattr(m, "SQL_SECONDS", -1)
    with pytest.raises(ValueError, match="limit"):
        with m._database(p.path, p.identity, None) as db:
            db.execute(
                "WITH RECURSIVE a(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM a WHERE x<100000) SELECT sum(x) FROM a"
            ).fetchone()


def test_markup_inert_and_controls_removed(tmp_path):
    p = m.inspect_pack(
        pack_file(
            tmp_path,
            metadata=[
                ("name", "A\u202e\x01"),
                ("format", "png"),
                ("attribution", '<a href="https://example.test">source</a>'),
            ],
        ),
        consent=True,
    )
    assert p.name == "A" and "<a href=" in dict(p.metadata)["attribution"]


def test_source_change_during_frame_rejected(tmp_path, monkeypatch):
    p = m.inspect_pack(pack_file(tmp_path), consent=True)
    original = m._identity
    count = 0

    def changed(path):
        nonlocal count
        count += 1
        result = original(path)
        return result if count == 1 else (*result[:-1], result[-1] + 1)

    monkeypatch.setattr(m, "_identity", changed)
    with pytest.raises(ValueError, match="changed during"):
        m.read_tiles(p, ((0, 0, 0),))
