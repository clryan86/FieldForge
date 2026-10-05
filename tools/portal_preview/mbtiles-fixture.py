"""Synthetic test packs only; generated with Python's independent SQLite writer."""
import binascii
import sqlite3
import struct
import sys
import zlib


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
    meta = [("name", "Synthetic test fixture"), ("format", "pbf" if mode == "vector" else "png"), ("attribution", "<b>Fixture credit</b>"), ("center", "0,0,22")]
    if mode == "xyz": meta.append(("scheme", "xyz"))
    if mode == "duplicate": meta.append(("name", "Duplicate"))
    db.executemany("INSERT INTO metadata VALUES (?,?)", meta)
    if mode == "oversize-metadata": db.execute("INSERT INTO metadata VALUES ('description',?)", ("x" * 16385,))
    db.executemany("INSERT INTO tiles VALUES (?,?,?,?)", [(1, 0, 0, png((255, 0, 0))), (1, 0, 1, png((0, 0, 255))), (2, 1, 1, png((0, 255, 0)))])
    if mode == "oversize-tile": db.execute("UPDATE tiles SET tile_data=zeroblob(2097153) WHERE zoom_level=1 AND tile_row=0")
    if mode == "bad-coordinate": db.execute("UPDATE tiles SET tile_column=-1 WHERE zoom_level=1")
    if mode == "view": db.executescript("ALTER TABLE tiles RENAME TO source_tiles; CREATE VIEW tiles AS SELECT * FROM source_tiles;")
    db.commit()
    data = db.serialize()
    db.close()
    if mode == "wal": data = data[:18] + b"\x02\x02" + data[20:]
    return data


if __name__ == "__main__":
    sys.stdout.buffer.write(fixture(sys.argv[1] if len(sys.argv) > 1 else "valid"))
