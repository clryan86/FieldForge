import math
import os
import socket
import sqlite3
import struct
from threading import Event

import pytest
from map_fixture import make_map, png, tile_color

from fieldforge.app import FieldForgeApp
from fieldforge.navigation import mbtiles
from fieldforge.navigation.map_view import MAX_LATITUDE, Viewport, project, unproject
from fieldforge.navigation.mbtiles import (
    MapCancelled,
    inspect_pack,
    read_frame,
    read_markers,
)
from fieldforge.navigation.places import PlaceStore, make_place


@pytest.fixture
def pack_path(tmp_path):
    return make_map(tmp_path / 'map #fixture.mbtiles')


@pytest.mark.parametrize('latitude,longitude,z', [(0, 0, 0), (0, 0, 22), (30, 40, 4), (-50, -120, 9),
    (MAX_LATITUDE, 179.99, 3), (-MAX_LATITUDE, -180, 0), (0, 180, 1)])
def test_projection_roundtrip_and_date_line(latitude, longitude, z):
    x, y = project(latitude, longitude, z)
    lat, lon = unproject(x, y, z)
    assert lat == pytest.approx(latitude, abs=1e-10)
    assert lon == pytest.approx(-180 if longitude == 180 else longitude, abs=1e-10)
    assert 0 <= x < 256 * 2**z and 0 <= y <= 256 * 2**z


def test_projection_independent_known_coordinates_and_north_direction():
    assert project(0, 0, 0) == (128, 128)
    assert project(0, -90, 2) == (256, 512)
    # Mercator's asinh(tan(lat)) = pi/2 at this latitude -> y = quarter world.
    latitude = math.degrees(math.atan(math.sinh(math.pi / 2)))
    assert project(latitude, 0, 2) == pytest.approx((512, 256))
    assert project(45, 0, 3)[1] < project(0, 0, 3)[1]


@pytest.mark.parametrize('args', [(90, 0, 1), (-90, 0, 1), (0, 181, 1), (True, 0, 1), (0, 0, True),
    (0, 0, -1), (0, 0, 23), (float('nan'), 0, 1), (0, float('inf'), 1), ('0', 0, 1)])
def test_invalid_projection_not_silently_guessed_or_clamped(args):
    with pytest.raises(ValueError):
        project(*args)


def test_viewport_tile_placement_and_wrapping():
    view = Viewport(0, 0, 1, 512, 512)
    slots = view.slots()
    assert [(s.column, s.row, s.left, s.top) for s in slots] == [(0, 0, 0, 0), (1, 0, 256, 0),
                                                               (0, 1, 0, 256), (1, 1, 256, 256)]
    date_line = Viewport(0, 179, 2, 512, 256)
    assert {s.column for s in date_line.slots()} == {0, 2, 3}
    assert date_line.locations(0, -179)  # Opposite longitude spelling is nearby, not off screen.
    assert len(Viewport(0, 0, 0, 1000, 256).locations(0, 0)) > 1


def test_pan_center_pointer_and_polar_limits():
    view = Viewport(0, 0, 2, 512, 512)
    assert view.at_pixel(256, 256) == pytest.approx((0, 0))
    assert view.pan(256, 0).longitude == pytest.approx(90)
    assert view.pan(0, -100000).latitude == pytest.approx(MAX_LATITUDE)
    assert view.pan(0, 100000).latitude == pytest.approx(-MAX_LATITUDE)
    assert not view.locations(80, 0)
    with pytest.raises(ValueError, match='outside'):
        Viewport(MAX_LATITUDE, 0, 1, 256, 256).at_pixel(128, 0)
    with pytest.raises(ValueError):
        Viewport(0, 0, 1, 10000, 500)
    with pytest.raises(ValueError):
        view.pan(float('inf'), 0)


def test_pack_is_readonly_and_uses_observed_zoom_levels(pack_path):
    before, info = pack_path.read_bytes(), pack_path.stat()
    pack = inspect_pack(pack_path)
    assert pack.zooms == (1, 2) and pack.zoom == 2
    assert pack.latitude == pack.longitude == 0
    assert 'Fictional' in pack.name
    frame = read_frame(pack, Viewport(0, 0, 1, 512, 512))
    assert all(tile.data is not None and not tile.issue for tile in frame.tiles)
    assert frame.tiles[0].data == png(256, tile_color(1, 0, 0), grid=True)
    assert frame.tiles[2].data == png(256, tile_color(1, 0, 1), grid=True)
    assert pack_path.read_bytes() == before and pack_path.stat().st_mtime_ns == info.st_mtime_ns
    assert not os.path.exists(str(pack_path) + '-journal')


def test_missing_tiles_are_reported_not_invented_and_no_upsampling(tmp_path):
    path = make_map(tmp_path/'holes.mbtiles', zooms=(1, 3), missing=((1, 1, 0),))
    pack = inspect_pack(path)
    frame = read_frame(pack, Viewport(0, 0, 1, 512, 512))
    assert [t.issue for t in frame.tiles] == ['', 'Tile not installed', '', '']
    assert frame.tiles[1].data is None
    with pytest.raises(ValueError, match='available zoom'):
        read_frame(pack, Viewport(0, 0, 2, 512, 512))


def test_retina_dimensions_and_outside_projection_cells(tmp_path):
    path = make_map(tmp_path/'retina.mbtiles', zooms=(0,), size=512)
    frame = read_frame(inspect_pack(path), Viewport(0, 0, 0, 768, 768))
    good = [tile for tile in frame.tiles if tile.data]
    assert len(good) == 3 and all(t.pixels == 512 for t in good)
    assert all(t.issue == 'Outside projection' for t in frame.tiles if not t.data)
    assert good[0].data is good[1].data  # Repeated world copies share cached bytes.


@pytest.mark.parametrize('metadata', [{'format': 'pbf'}, {'scheme': 'xyz'},
    {'name': ''}, {'name': 'bad\x00name'}, {'description': 'x'*16385}])
def test_unsupported_map_metadata_rejected(tmp_path, metadata):
    path = make_map(tmp_path/'bad.mbtiles', metadata=metadata)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        inspect_pack(path)
    assert path.read_bytes() == before


def test_duplicate_metadata_and_unindexed_or_view_schema_rejected(tmp_path):
    path = make_map(tmp_path/'unindexed.mbtiles', index=False)
    with pytest.raises(ValueError, match='unique'):
        inspect_pack(path)
    db = sqlite3.connect(path)
    db.execute('CREATE UNIQUE INDEX tile_index ON tiles(zoom_level,tile_column,tile_row)')
    db.execute("INSERT INTO metadata VALUES('name','Second name')")
    db.commit()
    db.close()
    with pytest.raises(ValueError, match='duplicate'):
        inspect_pack(path)
    path2 = make_map(tmp_path/'normalized.mbtiles')
    db = sqlite3.connect(path2)
    db.execute('ALTER TABLE tiles RENAME TO original_tiles')
    db.execute('CREATE VIEW tiles AS SELECT * FROM original_tiles')
    db.commit()
    db.close()
    with pytest.raises(ValueError, match='view-based'):
        inspect_pack(path2)


def test_readonly_bad_file_and_missing_file_not_created(tmp_path):
    missing = tmp_path/'missing.mbtiles'
    with pytest.raises(OSError):
        inspect_pack(missing)
    assert not missing.exists()
    missing.write_bytes(b'not sqlite' * 20)
    with pytest.raises(sqlite3.DatabaseError):
        inspect_pack(missing)
    with pytest.raises(ValueError):
        inspect_pack(tmp_path/'wrong.pdf')


def test_suspicious_index_names_are_quoted_not_executed(pack_path):
    db = sqlite3.connect(pack_path)
    db.execute('DROP INDEX tile_index')
    db.execute('CREATE UNIQUE INDEX "odd""; DELETE FROM tiles; --" ON tiles(zoom_level,tile_column,tile_row)')
    db.commit()
    db.close()
    pack = inspect_pack(pack_path)
    assert 'DELETE' in pack.index_name
    assert all(t.data for t in read_frame(pack, Viewport(0, 0, 1, 512, 512)).tiles)


@pytest.mark.parametrize('center', ['invalid', '0,90,2', '181,0,2', '0,0,8', 'nan,0,2', '0,0,1.5'])
def test_bad_declared_center_has_explicit_fallback_not_fake_location(tmp_path, center):
    path = make_map(tmp_path/'bad-center.mbtiles', metadata={'center': center, 'minzoom': '9'})
    pack = inspect_pack(path)
    assert pack.zoom == 1 and any('center ignored' in w for w in pack.warnings)
    assert any('minzoom differs' in w for w in pack.warnings)
    assert read_frame(pack, Viewport(pack.latitude, pack.longitude, pack.zoom, 1, 1)).tiles[0].data


def test_empty_or_invalid_zoom_coordinates_rejected(pack_path):
    db = sqlite3.connect(pack_path)
    db.execute('UPDATE tiles SET zoom_level=50 WHERE zoom_level=2')
    db.commit()
    db.close()
    with pytest.raises(ValueError, match='zoom levels'):
        inspect_pack(pack_path)
    db = sqlite3.connect(pack_path)
    db.execute('DELETE FROM tiles')
    db.commit()
    db.close()
    with pytest.raises(ValueError):
        inspect_pack(pack_path)


@pytest.mark.parametrize('bad', [b'not png', b'\x89PNG\r\n\x1a\n'+b'x'*40,
    b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\rIHDR'+struct.pack('>II', 200000, 200000)+b'x'*10])
def test_bad_tile_is_explicit_and_does_not_return_oversized_pixels(pack_path, bad):
    db = sqlite3.connect(pack_path)
    db.execute('UPDATE tiles SET tile_data=? WHERE zoom_level=1 AND tile_column=0 AND tile_row=1', (bad,))
    db.commit()
    db.close()
    frame = read_frame(inspect_pack(pack_path), Viewport(0, 0, 1, 512, 512))
    assert frame.tiles[0].data is None and frame.tiles[0].issue
    assert all(t.data for t in frame.tiles[1:])


def test_visible_byte_budget_and_tile_limit_enforced(pack_path, monkeypatch):
    pack = inspect_pack(pack_path)
    monkeypatch.setattr(mbtiles, 'MAX_FRAME_BYTES', 100)
    with pytest.raises(ValueError, match='frame budget'):
        read_frame(pack, Viewport(0, 0, 1, 512, 512))
    monkeypatch.setattr(mbtiles, 'MAX_TILE_BYTES', 40)
    frame = read_frame(pack, Viewport(0, 0, 1, 512, 512))
    assert all(t.data is None and t.issue == 'Invalid/oversized tile' for t in frame.tiles)


def test_changed_map_discarded_and_active_wal_not_used(pack_path):
    pack = inspect_pack(pack_path)
    info = pack_path.stat()
    os.utime(pack_path, ns=(info.st_atime_ns, info.st_mtime_ns+100000))
    with pytest.raises(ValueError, match='changed since'):
        read_frame(pack, Viewport(0, 0, 1, 256, 256))
    wal = str(pack_path)+'-wal'
    with open(wal, 'wb') as stream:
        stream.write(b'active')
    with pytest.raises(ValueError, match='WAL'):
        inspect_pack(pack_path)


def test_change_during_read_discards_frame_and_cancelled_reads_are_safe(pack_path, monkeypatch):
    pack = inspect_pack(pack_path)
    real = mbtiles._png_size
    changed = []
    def modify(data):
        if not changed:
            info = pack_path.stat()
            os.utime(pack_path, ns=(info.st_atime_ns, info.st_mtime_ns+100000))
            changed.append(True)
        return real(data)
    monkeypatch.setattr(mbtiles, '_png_size', modify)
    with pytest.raises(ValueError, match='changed while'):
        read_frame(pack, Viewport(0, 0, 1, 256, 256))
    cancel = Event()
    cancel.set()
    with pytest.raises(MapCancelled):
        inspect_pack(pack_path, cancel=cancel)


def test_sql_work_deadline_is_checked_not_claimed_as_filesystem_timeout(pack_path, monkeypatch):
    monkeypatch.setattr(mbtiles, 'QUERY_SECONDS', -1)
    with pytest.raises(TimeoutError):
        with mbtiles._read_database(pack_path, mbtiles._signature(pack_path)) as db:
            db.execute('WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<100000) SELECT sum(x) FROM n').fetchone()


def test_marker_optin_reader_never_reads_private_note_columns(tmp_path, monkeypatch):
    app = FieldForgeApp(tmp_path/'app.db')
    saved = PlaceStore(app.db.path).save(make_place('Private alias', 0, 1, notes='DO_NOT_READ'))
    real = sqlite3.connect
    def connect(*args, **kwargs):
        db = real(*args, **kwargs)
        def authorize(action, table, column, *_):
            if table == 'waypoints' and column == 'notes':
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        return db
    monkeypatch.setattr(sqlite3, 'connect', connect)
    markers = read_markers(app.db.path)
    assert len(markers) == 1 and markers[0].id == saved.point.id
    assert 'DO_NOT_READ' not in str(markers)


def test_no_network_or_database_modification_to_read_a_map(pack_path, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError('No network expected')
    for name in ('socket', 'create_connection', 'getaddrinfo'):
        monkeypatch.setattr(socket, name, fail)
    before = pack_path.read_bytes()
    frame = read_frame(inspect_pack(pack_path), Viewport(0, 0, 2, 768, 512))
    assert all(t.data for t in frame.tiles)
    assert pack_path.read_bytes() == before
    app = FieldForgeApp(tmp_path/'app.db')
    assert read_markers(app.db.path) == ()
    with sqlite3.connect(app.db.path) as db:
        db.execute("INSERT INTO waypoints(name,latitude,longitude,kind,notes) VALUES('Bad',100,0,'waypoint','')")
    with pytest.raises(ValueError, match='Invalid saved place'):
        read_markers(app.db.path)


@pytest.mark.parametrize('rows,attribution', [(65, 'a' * 8193), (128, 'a' * 16384),
                                             (128, 'é' * 8192)])
def test_public_gps_metadata_budget_opens_in_both_offline_viewers(tmp_path, rows, attribution):
    from fieldforge_gps.mbtiles import inspect_pack as inspect_gps
    from fieldforge_gps.mbtiles import read_tiles

    # The fixture supplies seven standard entries. These bounds were already
    # accepted by the GPS portal downloader and must survive a main Maps handoff.
    metadata = {f'field_{index}': f'Original fixture field {index}' for index in range(rows - 7)}
    metadata['attribution'] = attribution
    path = make_map(tmp_path / 'published-raster.mbtiles', metadata=metadata)
    before = path.read_bytes()
    gps = inspect_gps(path, consent=True)
    pack = inspect_pack(path)
    assert len(pack.metadata) == rows
    assert dict(pack.metadata)['attribution'] == attribution
    assert dict(gps.metadata)['attribution'] == attribution
    assert read_tiles(gps, ((2, 1, 1),))[0].state == 'ready'
    assert all(tile.data for tile in read_frame(pack, Viewport(0, 0, 2, 512, 512)).tiles)
    assert path.read_bytes() == before
    assert not any((tmp_path / (path.name + suffix)).exists() for suffix in ('-wal', '-journal', '-shm'))


@pytest.mark.parametrize('metadata', [
    {f'field_{index}': 'Original fixture field' for index in range(122)},
    {'attribution': 'a' * 16385},
    {'attribution': 'é' * 8193},
    {'k' * 129: 'Original fixture field'},
])
def test_shared_metadata_bounds_reject_extra_rows_and_oversized_utf8_bytes(tmp_path, metadata):
    from fieldforge_gps.mbtiles import inspect_pack as inspect_gps

    path = make_map(tmp_path / 'oversized-metadata.mbtiles', metadata=metadata)
    before = path.read_bytes()
    with pytest.raises(ValueError, match='metadata'):
        inspect_pack(path)
    with pytest.raises(ValueError, match='metadata'):
        inspect_gps(path, consent=True)
    assert path.read_bytes() == before


@pytest.mark.parametrize('mutation', [
    'ALTER TABLE metadata ADD COLUMN extra TEXT',
    'ALTER TABLE tiles ADD COLUMN extra TEXT',
    '''ALTER TABLE metadata RENAME TO previous_metadata;
       CREATE TABLE metadata(name VARCHAR(128),value TEXT);
       INSERT INTO metadata SELECT name,value FROM previous_metadata;''',
    '''ALTER TABLE tiles RENAME TO previous_tiles;
       CREATE TABLE tiles(zoom_level INT,tile_column INTEGER,tile_row INTEGER,tile_data BLOB);
       INSERT INTO tiles SELECT * FROM previous_tiles;
       CREATE UNIQUE INDEX new_tile_index ON tiles(zoom_level,tile_column,tile_row);''',
])
def test_shared_flat_typed_schema_rejects_extensions_and_alternate_declared_types(pack_path, mutation):
    from fieldforge_gps.mbtiles import inspect_pack as inspect_gps

    with sqlite3.connect(pack_path) as db:
        db.executescript(mutation)
    before = pack_path.read_bytes()
    with pytest.raises(ValueError, match='structure|layout'):
        inspect_pack(pack_path)
    with pytest.raises(ValueError, match='layout'):
        inspect_gps(pack_path, consent=True)
    assert pack_path.read_bytes() == before


@pytest.mark.parametrize('index_sql', [
    'CREATE UNIQUE INDEX replacement ON tiles(zoom_level COLLATE NOCASE,tile_column,tile_row)',
    'CREATE UNIQUE INDEX replacement ON tiles(zoom_level,tile_column,tile_row) WHERE zoom_level=1',
    'CREATE UNIQUE INDEX replacement ON tiles(tile_column,zoom_level,tile_row)',
])
def test_shared_tile_index_requires_binary_full_unique_coordinate_key(pack_path, index_sql):
    from fieldforge_gps.mbtiles import inspect_pack as inspect_gps

    with sqlite3.connect(pack_path) as db:
        db.execute('DROP INDEX tile_index')
        db.execute(index_sql)
    before = pack_path.read_bytes()
    with pytest.raises(ValueError, match='unique'):
        inspect_pack(pack_path)
    with pytest.raises(ValueError, match='unique'):
        inspect_gps(pack_path, consent=True)
    assert pack_path.read_bytes() == before


def test_active_shared_memory_sidecar_is_refused_without_changes(pack_path):
    from fieldforge_gps.mbtiles import inspect_pack as inspect_gps

    sidecar = pack_path.with_name(pack_path.name + '-shm')
    sidecar.write_bytes(b'active shared-memory fixture')
    before = pack_path.read_bytes()
    with pytest.raises(ValueError, match='sidecar'):
        inspect_pack(pack_path)
    with pytest.raises(ValueError, match='sidecar'):
        inspect_gps(pack_path, consent=True)
    assert pack_path.read_bytes() == before
    assert sidecar.read_bytes() == b'active shared-memory fixture'


def test_wal_header_without_sidecars_is_rejected_before_sqlite_creates_auxiliary_files(pack_path):
    from fieldforge_gps.mbtiles import inspect_pack as inspect_gps

    db = sqlite3.connect(pack_path)
    try:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:
        db.close()
    before = pack_path.read_bytes()
    assert before[18:20] == b'\x02\x02'
    assert not any(pack_path.with_name(pack_path.name + suffix).exists() for suffix in ('-wal', '-shm'))
    with pytest.raises(ValueError, match='rollback-mode'):
        inspect_pack(pack_path)
    with pytest.raises(ValueError, match='rollback-mode'):
        inspect_gps(pack_path, consent=True)
    assert pack_path.read_bytes() == before
    assert not any(pack_path.with_name(pack_path.name + suffix).exists() for suffix in ('-wal', '-journal', '-shm'))
