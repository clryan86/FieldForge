"""Synthetic test packs only; generated with Python's independent SQLite writer."""
import binascii
import gzip
import sqlite3
import struct
import sys
import zlib


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result + bytes([value]))


def field(number, value):
    if isinstance(value, int): return varint(number << 3) + varint(value)
    if isinstance(value, str): value = value.encode()
    return varint(number << 3 | 2) + varint(len(value)) + value


def vector_tile():
    # Independent protobuf writer: polygon with a hole, road and named point.
    def feature(kind, words, tags=()):
        return field(2, b''.join(map(varint, tags))) + field(3, kind) + field(4, b''.join(map(varint, words)))
    def layer(name, geometry, keys=(), values=()):
        return field(3, field(15, 2) + field(1, name) + b''.join(field(2, g) for g in geometry) + b''.join(field(3, k) for k in keys) + b''.join(field(4, field(1, v)) for v in values) + field(5, 256))
    polygon = feature(3, [9,32,32,26,448,0,0,448,447,0,15,9,128,319,26,0,192,192,0,0,191,15])
    road = feature(2, [9,0,256,10,512,0], [0,0])
    point = feature(1, [9,256,256], [0,0])
    return layer('water', [polygon]) + layer('transportation', [road], ['class'], ['primary']) + layer('place', [point], ['name'], ['Fixture camp'])


def png(rgb):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xffffffff)
    pixels = (b"\0" + bytes(rgb) * 256) * 256
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


def fixture(mode="valid"):
    db = sqlite3.connect(":memory:")
    db.executescript("CREATE TABLE metadata(name TEXT, value TEXT); CREATE TABLE tiles(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);")
    if mode != "unindexed":
        db.execute('CREATE UNIQUE INDEX "tile index" ON tiles(zoom_level,tile_column,tile_row)')
    meta = [("name", "Synthetic test fixture"), ("format", "pbf" if mode.startswith("vector") else "png"), ("attribution", "<b>Fixture credit</b>"), ("center", "0,0,22")]
    if mode == "xyz": meta.append(("scheme", "xyz"))
    if mode == "duplicate": meta.append(("name", "Duplicate"))
    db.executemany("INSERT INTO metadata VALUES (?,?)", meta)
    if mode == "oversize-metadata": db.execute("INSERT INTO metadata VALUES ('description',?)", ("x" * 16385,))
    db.executemany("INSERT INTO tiles VALUES (?,?,?,?)", [(1, 0, 0, png((255, 0, 0))), (1, 0, 1, png((0, 0, 255))), (2, 1, 1, png((0, 255, 0)))])
    if mode.startswith("vector"):
        vector = vector_tile()
        db.execute("UPDATE tiles SET tile_data=?", (vector,))
        db.execute("UPDATE tiles SET tile_data=? WHERE tile_row=0", (gzip.compress(vector, mtime=0),))
        if mode == "vector-mixed": db.execute("UPDATE tiles SET tile_data=? WHERE tile_row=1", (b'\x1a\xff',))
    if mode == "oversize-tile": db.execute("UPDATE tiles SET tile_data=zeroblob(2097153) WHERE zoom_level=1 AND tile_row=0")
    if mode == "bad-coordinate": db.execute("UPDATE tiles SET tile_column=-1 WHERE zoom_level=1")
    if mode == "view": db.executescript("ALTER TABLE tiles RENAME TO source_tiles; CREATE VIEW tiles AS SELECT * FROM source_tiles;")
    db.commit()
    data = db.serialize()
    db.close()
    if mode == "wal": data = data[:18] + b"\x02\x02" + data[20:]
    return data


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "valid"
    sys.stdout.buffer.write(vector_tile() if mode == "vector-bytes" else fixture(mode))
