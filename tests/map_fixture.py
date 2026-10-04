"""Synthetic, original PNG grids. No real geographic data or downloaded assets."""

import sqlite3
import struct
import zlib


def png(size=256, color=(80, 130, 100), *, grid=False):
    def chunk(kind, value):
        return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value) & 0xffffffff)
    if grid:
        rows = b''.join(b'\0' + b''.join(bytes((205, 220, 210) if x % 64 == 0 or y % 64 == 0 else color)
                                        for x in range(size)) for y in range(size))
    else:
        rows = (b'\0' + bytes(color) * size) * size
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def tile_color(z, x, y):
    return (70 + (x * 35) % 110, 115 + (y * 25) % 80, 90 + (z * 20) % 90)


def make_map(path, *, zooms=(1, 2), size=256, metadata=None, missing=(), index=True):
    """Build a standard flat PNG MBTiles fixture using TMS row storage."""
    values = {'name': 'Fictional training grid — NOT a geographic map', 'format': 'png',
              'description': 'Original software exercise. No roads, boundaries, terrain or real map features.',
              'attribution': 'Original FieldForge test grid. Not for navigation.',
              'center': f'0,0,{zooms[-1]}', 'minzoom': str(zooms[0]), 'maxzoom': str(zooms[-1])}
    if metadata:
        values.update(metadata)
    db = sqlite3.connect(path)
    try:
        db.execute('CREATE TABLE metadata(name TEXT,value TEXT)')
        db.execute('CREATE TABLE tiles(zoom_level INTEGER,tile_column INTEGER,tile_row INTEGER,tile_data BLOB)')
        if index:
            db.execute('CREATE UNIQUE INDEX tile_index ON tiles(zoom_level,tile_column,tile_row)')
        db.executemany('INSERT INTO metadata VALUES(?,?)', values.items())
        for z in zooms:
            for y in range(1 << z):
                for x in range(1 << z):
                    if (z, x, y) not in missing:
                        db.execute('INSERT INTO tiles VALUES(?,?,?,?)',
                                   (z, x, (1 << z) - 1 - y, png(size, tile_color(z, x, y), grid=True)))
        db.commit()
    finally:
        db.close()
    return path
