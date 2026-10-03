"""Explicit installation diagnostics, always on generated temporary records.

Never reads the user's selected database. This is a smoke test, not full platform
certification. Only on Windows does it launch/close the real recovered desktop
and standalone recovery EXE via the normal runtime command path.
"""

from __future__ import annotations

import json
import os
import platform
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from contextlib import closing
from pathlib import Path

from fieldforge.runtime import build_identity, desktop_command, desktop_environment, packaged


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sample_pdf() -> bytes:
    """An original one-page synthetic PDF with correct byte offsets, not a manual."""
    stream = b"BT /F1 12 Tf 45 700 Td (FieldForge package check: paper worksheet.) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
               b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + value + b"\nendobj\n")
    start = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    return bytes(data)


def sample_png() -> bytes:
    def chunk(name, payload):
        return (struct.pack(">I", len(payload)) + name + payload
                + struct.pack(">I", zlib.crc32(name + payload) & 0xffffffff))
    rows = (b"\0" + bytes((50, 95, 65)) * 256) * 256
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _close_own_windows(process: subprocess.Popen, expected_title: str) -> None:
    """Windows-only diagnostic: close only the child PID we just launched."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                         wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                         ctypes.POINTER(ctypes.c_size_t)]
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    try:
        deadline = time.monotonic() + 25
        found = []
        while time.monotonic() < deadline and process.poll() is None:
            found.clear()
            @callback_type
            def visit(handle, _parameter):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
                if pid.value == process.pid and user32.IsWindowVisible(handle):
                    text = ctypes.create_unicode_buffer(512)
                    user32.GetWindowTextW(handle, text, len(text))
                    if text.value == expected_title:
                        found.append(handle)
                return True
            user32.EnumWindows(visit, 0)
            if found:
                break
            time.sleep(0.05)
        _require(bool(found), "Packaged desktop did not expose its expected visible window")
        # Wait for a responsive event loop, not merely a successful process spawn.
        result = ctypes.c_size_t()
        _require(bool(user32.SendMessageTimeoutW(found[0], 0, 0, 0, 2, 5000, ctypes.byref(result))),
                 "Packaged desktop did not respond to its Windows message loop")
        time.sleep(0.3)
        _require(bool(user32.PostMessageW(found[0], 0x0010, 0, 0)), "Could not request normal desktop close")
        _require(process.wait(timeout=15) == 0, "Packaged desktop failed during normal close")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def verify_gps_workspace(root) -> None:
    """Require the packaged map, catalogue and UI without opening a serial port."""
    import io

    from PIL import Image

    from fieldforge.ui.gps import GPSWorkspace
    from fieldforge_gps.raster import tile_png

    workspace = GPSWorkspace(root)
    workers = []
    try:
        receiver = workspace.open()
        view = receiver.live_map_frame
        workers.append(view._map_reader)
        finder = view.open_finder()
        workers.append(finder.worker)
        view.map_trust.set(True)
        view.example_map()
        finder.permission.set(True)
        finder.wgs84.set(True)
        finder.example()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            root.update()
            if (view.map_pack is not None and finder.catalog is not None
                    and view._map_task is None and view._draw_after is None):
                break
            time.sleep(.005)
        _require(view.map_pack is not None and bool(view.canvas.find_withtag("map-tile")),
                 "Bundled fictional GPS map or PNG rendering is unavailable")
        _require(finder.catalog is not None and len(finder.catalog.places) == 6,
                 "Bundled fictional place catalogue is unavailable")
        _require(receiver.session is None and not view.show_live.get()
                 and not receiver.trip_consent.get(), "GPS workspace connected or recorded automatically")
        image_view = view.open_image_reference()
        workers.append(image_view.worker)
        with tempfile.TemporaryDirectory(prefix="FieldForge image check ") as directory:
            for fmt, label in (("JPEG", "jpg"), ("WEBP", "webp")):
                encoded = io.BytesIO()
                with Image.new("RGB", (256, 256), (80, 120, 160)) as sample:
                    sample.save(encoded, format=fmt)
                with Image.open(io.BytesIO(tile_png(encoded.getvalue(), label))) as decoded:
                    _require(decoded.size == (256, 256), "Raster tile codec is unavailable")
                path = Path(directory) / ("synthetic." + label)
                path.write_bytes(encoded.getvalue())
                image_view.permission.set(True)
                image_view.open_path(path)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    root.update()
                    if image_view._job is None and image_view._draw_after is None:
                        break
                    time.sleep(.005)
                _require(image_view.document is not None
                         and image_view.document.format == fmt
                         and bool(image_view.canvas.find_withtag("reference-image")),
                         "Packaged map-image viewer or raster decoder is unavailable")
        if packaged():
            import serial
            _require(callable(serial.Serial), "Packaged serial adapter is unavailable")
    finally:
        workspace.close()
        for worker in workers:
            worker._thread.join(2)
            _require(not worker._thread.is_alive(), "GPS diagnostic worker did not stop")


def verify_installation() -> dict[str, object]:
    import tkinter as tk

    from fieldforge.app import FieldForgeApp
    from fieldforge.core.recovery import (
        create_verified_backup,
        launch_recovered_copy,
        restore_verified_copy,
    )
    from fieldforge.knowledge import KnowledgeLibrary
    from fieldforge.knowledge.documents import commit_document
    from fieldforge.knowledge.foundations import install_foundations
    from fieldforge.knowledge.originals import CapturedPDF, OriginalStore
    from fieldforge.knowledge.pdf_import import prepare_pdf_article, read_pdf_document
    from fieldforge.knowledge.pocket import capture_pocket, render_pocket
    from fieldforge.knowledge.starter import install_starter
    from fieldforge.navigation.map_view import Viewport
    from fieldforge.navigation.mbtiles import inspect_pack, read_frame

    user_database = os.environ.get("FIELDFORGE_DB")
    checks = []
    with tempfile.TemporaryDirectory(prefix="FieldForge install check ") as directory:
        root_path = Path(directory) / "Space and Unicode résumé"
        root_path.mkdir()
        app = FieldForgeApp(root_path / "scratch.db")
        install_starter(app.knowledge)
        install_foundations(app.knowledge, acknowledged=True)
        _require(app.knowledge.count() == 32, "Bundled lesson corpus missing")
        checks.append("32 bundled starter/foundations articles installed in scratch database")
        pdf = root_path / "paper worksheet.pdf"
        pdf.write_bytes(sample_pdf())
        extracted = read_pdf_document(pdf)
        _require("FieldForge package check" in extracted.pages[0], "Bundled PDF worker failed extraction")
        article = prepare_pdf_article(extracted, title="Diagnostic paper worksheet", category="test")
        commit_document(app.knowledge, article, acknowledged=True)
        checks.append("PDF text extracted by production subprocess helper")
        originals = OriginalStore(app.db.path)
        record = originals.store(CapturedPDF(pdf.name, pdf.read_bytes()), acknowledged=True).record
        backup = create_verified_backup(app.db.path, root_path / "snapshot.ffbackup")
        recovered = restore_verified_copy(backup, root_path / "recovered.db", active_database=app.db.path)
        restored = OriginalStore(recovered)
        _require(restored.read_verified(record) == sample_pdf(), "Restored original bytes differ")
        _require(KnowledgeLibrary(recovered).count() == 33, "Restored articles missing")
        checks.append("Full backup restored articles and exact original PDF bytes")
        pocket = render_pocket(capture_pocket(recovered, slugs=(article.slug,)))
        _require(b"FieldForge package check" in pocket, "Pocket export missing text")
        checks.append("Offline HTML reader rendered from recovered article")
        map_path = root_path / "synthetic.mbtiles"
        with closing(sqlite3.connect(map_path)) as db, db:
            db.execute("CREATE TABLE metadata(name TEXT,value TEXT)")
            db.execute("CREATE TABLE tiles(zoom_level INTEGER,tile_column INTEGER,tile_row INTEGER,tile_data BLOB)")
            db.execute("CREATE UNIQUE INDEX tile_index ON tiles(zoom_level,tile_column,tile_row)")
            db.executemany("INSERT INTO metadata VALUES(?,?)", [("name", "Synthetic installation check — not a map"),
                                                               ("format", "png"), ("center", "0,0,0")])
            db.execute("INSERT INTO tiles VALUES(0,0,0,?)", (sample_png(),))
        frame = read_frame(inspect_pack(map_path), Viewport(0, 0, 0, 256, 256))
        _require(any(tile.data == sample_png() for tile in frame.tiles), "MBTiles reader failed")
        tk_root = tk.Tk()
        try:
            tk_root.withdraw()
            image = tk.PhotoImage(master=tk_root, data=sample_png(), format="png")
            _require(image.width() == image.height() == 256, "Bundled Tk PNG decoder failed")
            tk_root.update()
            tk_version = str(tk_root.tk.call("info", "patchlevel"))
            verify_gps_workspace(tk_root)
        finally:
            tk_root.destroy()
        checks.append("Tk window and PNG decoding; synthetic MBTiles tile read")
        checks.append("GPS workspace with fictional tiles/places and JPEG/WebP image rendering; no receiver or recording")
        desktop_result = "Not attempted on this source/non-Windows diagnostic"
        if packaged() and sys.platform == "win32":
            child = launch_recovered_copy(recovered)
            _close_own_windows(child, "FieldForge — Offline Emergency Operations")
            _require(KnowledgeLibrary(recovered).count() == 33, "Desktop launch altered the scratch article count")
            checks.append("Actual recovered desktop EXE opened, responded and closed normally")
            missing = root_path / "deliberately missing.db"
            child = subprocess.Popen([*desktop_command(), "--recovery"], env=desktop_environment(missing),
                                     cwd=root_path, shell=False)
            _close_own_windows(child, "FieldForge — Backup & Recovery")
            _require(not missing.exists(), "Standalone recovery created the missing active database")
            checks.append("Standalone recovery EXE opened without initializing a missing database")
            desktop_result = "Two real Windows desktop subprocesses verified"
        _require(os.environ.get("FIELDFORGE_DB") == user_database, "Diagnostic changed caller database setting")
    return {"status": "passed", "build": build_identity(), "python": platform.python_version(),
            "platform": sys.platform, "packaged": packaged(), "pypdf": extracted.parser_version,
            "tk": tk_version, "desktop": desktop_result, "checks": checks,
            "scope": "Temporary synthetic records only; no user database inspected or reset"}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pdf-worker", action="store_true", help="Internal PDF bytes-in/JSON-out protocol")
    mode.add_argument("--verify-installation", action="store_true", help="Test this installation using temporary sample data")
    args = parser.parse_args(argv)
    if args.pdf_worker:
        from fieldforge.knowledge.pdf_worker import main as worker
        return worker()
    try:
        result = verify_installation()
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=True))
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
