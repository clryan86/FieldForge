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
    portal = None
    try:
        portal = workspace.open_portal()
        root.update()
        _require(portal.session is None and portal.search_entry.instate(["disabled"]),
                 "Portal must open offline without making requests")
        portal.close()
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
        if portal is not None:
            portal.worker.join(2)
            _require(not portal.worker.is_alive(), "Portal diagnostic worker did not stop")
        for worker in workers:
            worker._thread.join(2)
            _require(not worker._thread.is_alive(), "GPS diagnostic worker did not stop")


def verify_blueprint_workspace(root, directory: Path) -> None:
    """Exercise the shipped form and export without an AI model or user data."""
    from fieldforge.blueprints.parameters import prepare_part_edit
    from fieldforge.blueprints.render import export_blueprint, load_blueprint, save_blueprint
    from fieldforge.content import install_reference_library
    from fieldforge.knowledge import KnowledgeLibrary
    from fieldforge.ui.blueprint_home import BlueprintHome

    library = KnowledgeLibrary(directory / "blueprints.db")
    install_reference_library(library)
    _require(library.count() == 439, "Packaged reference collection is incomplete")
    home = BlueprintHome(root, library)
    try:
        form = home.new_layout()
        form.name.set("Installation test layout")
        form.part_name.set("Measured panel")
        form.material.set("User supplied material")
        for field, value in zip(form.size, ["24 in", "30 cm", "18 mm"]):
            field.set(value)
        form.add()
        form.create_button.invoke()
        root.update()
        _require(home.studio is not None, "Blueprint form did not open drawings")
        maker = home.studio.makers["engineering"]
        _require(maker.blueprint["design"]["parts"][0]["size_mm"] == [609.6, 300, 18],
                 "Blueprint form lost user-entered measurements")
        value = prepare_part_edit(maker.blueprint, "P1", size=["24 in", "35 cm", "18 mm"])["blueprint"]
        maker.show_blueprint(value)
        path = save_blueprint(value, directory / "measured-layout.json")
        reopened = load_blueprint(path)
        _require(reopened["design"]["parts"][0]["size_mm"][1] == 350,
                 "Edited blueprint measurements did not survive reopening")
        export_blueprint(reopened, directory / "blueprint-export")
        for name in ("report.html", "blueprint.json", "top.svg", "front.svg", "side.svg",
                     "isometric.svg", "part-001.svg", "parts.csv", "materials.csv"):
            _require((directory / "blueprint-export" / name).is_file(), "Missing blueprint export: " + name)
        for mode in ("project", "software"):
            studio = home.open_maker(mode)
            _require(str(studio.pages.select()) == str(studio.makers[mode]), "Blueprint maker is unavailable")
    finally:
        home.destroy()


def verify_education_workspace(root, directory: Path) -> None:
    """Check bundled teaching data and a real attempt/save/restore UI workflow."""
    from fieldforge.app import FieldForgeApp
    from fieldforge.core.recovery import create_verified_backup, restore_verified_copy
    from fieldforge.knowledge.education import StudyStore, worksheet
    from fieldforge.ui.education import EducationTab

    app = FieldForgeApp(directory / "education.db")
    tab = EducationTab(root, app.db.path)
    try:
        _require(len(tab.catalog) == 196, "Education catalogue missing from the bundle")
        _require(tab.lesson.id == "number-count", "Number foundations are not the default starting course")
        tab.diagram_next.invoke()
        _require(tab.diagram_index == 1 and len(tab.diagram.find_withtag("one")) == 7,
                 "Counting diagram step is missing from the executable")
        tab.open_lesson("number-add")
        tab.move_question(1)
        tab.response.insert("1.0", "33")
        tab.check_button.invoke()
        _require(tab.work.result == "retry" and "lost the ten" in tab.feedback.get("1.0", "end"),
                 "Regrouping feedback is missing")
        tab.hint_button.invoke()
        tab.response.delete("1.0", "end")
        tab.response.insert("1.0", "43")
        tab.reasoning.insert("1.0", "Thirteen ones make another ten with three ones remaining.")
        tab.check_button.invoke()
        _require(tab.work.result == "correct" and tab.work.hints == 1, "Foundation arithmetic check failed")
        number_lesson, number_question, number_work = tab.lesson, tab.question, tab.work
        tab.open_lesson("number-divide")
        tab.move_question(5)
        tab.response.insert("1.0", "Zero cards can be shared, but zero-card groups cannot account for twelve.")
        tab.reveal_button.invoke()
        tab.review_button.invoke()
        division_lesson, division_question, division_work = tab.lesson, tab.question, tab.work
        tab.open_lesson("fraction-combine")
        tab.diagram_next.invoke()
        _require(len(tab.diagram.find_withtag("filled")) == 6 and tab.diagram_index == 1,
                 "Fraction strips or stepped examples are missing")
        tab.pages.select(tab.fraction_lab)
        lab = tab.fraction_lab
        for variable, value in zip(lab.values, (2, 3, 3, 4)):
            variable.set(str(value))
        lab.inputs[3].event_generate("<<ComboboxSelected>>")
        _require("A = 8/12; B = 9/12" in lab.comparison.get("1.0", "end"), "Fraction lab comparison is unavailable")
        _require(len(lab.canvas.find_withtag("fraction_point")) == 2, "Fraction number lines are missing")
        tab.pages.select(tab.practice_page)
        tab.response.insert("1.0", "2/9")
        tab.check_button.invoke()
        _require(tab.work.result == "retry" and "Adding denominators" in tab.feedback.get("1.0", "end"),
                 "Fraction misconception feedback is missing")
        tab.hint_button.invoke()
        tab.response.delete("1.0", "end")
        tab.response.insert("1.0", "3/6")
        tab.reasoning.insert("1.0", "Two sixths plus one sixth makes three sixths.")
        tab.check_button.invoke()
        _require(tab.work.result == "correct", "Equivalent fraction answer was rejected")
        fraction_lesson, fraction_question, fraction_work = tab.lesson, tab.question, tab.work
        lab.reset_button.invoke()
        _require(tab.work == fraction_work, "Exploring the lab changed saved practice")
        tab.open_lesson("fraction-quantity")
        tab.move_question(5)
        tab.response.insert("1.0", "For 54 cards, five sixths is 45; the remaining nine restores 54.")
        tab.reveal_button.invoke()
        tab.review_button.invoke()
        quantity_lesson, quantity_question, quantity_work = tab.lesson, tab.question, tab.work
        tab.open_lesson("guide-length")
        tab.response.insert("1.0", "11")
        tab.check_button.invoke()
        _require(tab.work.result == "retry" and "end position" in tab.feedback.get("1.0", "end"),
                 "Education misconception feedback is missing")
        tab.hint_button.invoke()
        tab.response.delete("1.0", "end")
        tab.response.insert("1.0", "8")
        tab.reasoning.insert("1.0", "Subtract the 3 cm start from the 11 cm endpoint.")
        tab.check_button.invoke()
        _require(tab.work.result == "correct" and tab.work.hints == 1,
                 "Education numeric check lost its support record")
        tab.next.invoke()
        tab.previous.invoke()
        _require(tab.response.get("1.0", "end-1c") == "8", "Education navigation lost an answer")
        tab.move_question(4)
        tab.response.insert("1.0", "The length is fixed while the counting unit changes.")
        tab.reveal_button.invoke()
        tab.explained_button.invoke()
        _require(tab.work.reflection == "explained it" and tab.work.result == "draft",
                 "Written explanations were incorrectly treated as automatically checked")
        _require(tab.save_current(), "Education work could not be saved")
        lesson, question, expected = tab.lesson, tab.question, tab.work
        tab.track.set("Guided: Read & write")
        tab.refresh()
        _require(tab.lesson.id == "read-notice" and "[N5]" in tab.source_text.get("1.0", "end"),
                 "Literacy course and its practice source are unavailable")
        tab.choice_response.set("A")
        tab.check_button.invoke()
        _require(tab.work.result == "retry" and "older poster" in tab.feedback.get("1.0", "end"),
                 "Literacy choice feedback is unavailable")
        tab.hint_button.invoke()
        tab.choice_response.set("B")
        tab.reasoning.insert("1.0", "N5 replaces the older location.")
        tab.check_button.invoke()
        _require(tab.work.result == "correct" and tab.work.hints == 1,
                 "Literacy choice check lost its hint record")
        literacy_lesson, literacy_question, literacy_work = tab.lesson, tab.question, tab.work
        tab.move_question(3)
        tab.response.insert("1.0", "Use Room 2 on Saturday from 2 to 3 p.m.; N5 replaces the old poster.")
        tab.reveal_button.invoke()
        tab.review_button.invoke()
        _require(tab.work.result == "draft" and tab.work.reflection == "needs practice",
                 "Writing must remain an explicit self-review")
        writing_question, writing_work = tab.question, tab.work
        tab.track.set("Guided: Investigate & reason")
        tab.refresh()
        _require(tab.lesson.id == "evidence-measure" and "[M4]" in tab.source_text.get("1.0", "end"),
                 "Evidence course or data record is missing")
        tab.open_lesson("evidence-sample")
        tab.response.insert("1.0", "8/40")
        tab.check_button.invoke()
        _require(tab.work.result == "retry" and "Forty combines" in tab.feedback.get("1.0", "end"),
                 "Evidence denominator feedback is missing")
        tab.hint_button.invoke()
        tab.response.delete("1.0", "end")
        tab.response.insert("1.0", "0.8")
        tab.reasoning.insert("1.0", "Eight successes belong to the ten large-print attempts.")
        tab.check_button.invoke()
        _require(tab.work.result == "correct" and tab.work.hints == 1,
                 "Evidence exact proportion check failed")
        evidence_lesson, evidence_question, evidence_work = tab.lesson, tab.question, tab.work
        tab.open_lesson("evidence-report")
        tab.move_question(4)
        tab.response.insert("1.0", "The returned sheets favor B, but four sheets have unknown outcomes.")
        tab.reveal_button.invoke()
        tab.review_button.invoke()
        report_lesson, report_question, report_work = tab.lesson, tab.question, tab.work
        learner_a = tab.store.create_learner("Installation learner A")
        learner_b = tab.store.create_learner("Installation learner B")
        tab.reload_learners()
        tab.learner_picker.current(next(i for i, p in enumerate(tab.learner_list) if p.id == learner_a.id))
        tab.learner_picker.event_generate("<<ComboboxSelected>>")
        _require(tab.store.learner_id == learner_a.id and tab.work.revision == 0,
                 "Learner selector did not open a separate practice record")
        tab.open_lesson("fraction-combine")
        tab.hint_button.invoke()
        tab.response.insert("1.0", "1/2")
        tab.reasoning.insert("1.0", "Learner A renamed thirds as sixths.")
        tab.check_button.invoke()
        learner_lesson, learner_question, learner_a_work = tab.lesson, tab.question, tab.work
        _require(learner_a_work.result == "correct" and learner_a_work.hints == 1, "Learner A practice failed")
        tab.learner_picker.current(next(i for i, p in enumerate(tab.learner_list) if p.id == learner_b.id))
        tab.learner_picker.event_generate("<<ComboboxSelected>>")
        _require(tab.store.learner_id == learner_b.id and tab.work.hints == 0 and tab.work.response == "",
                 "Learner B inherited another learner's answer or hint history")
        tab.response.insert("1.0", "2/9")
        tab.check_button.invoke()
        learner_b_work = tab.work
        _require(learner_b_work.result == "retry", "Learner B's independent answer was not checked")
        learner_a = tab.store.rename_learner(learner_a, "Installation learner A renamed")
        tab.reload_learners()
        _require(tab.switch_learner(learner_a.id), "Could not return to learner A")
        tab.resume()
        _require(tab.work == learner_a_work, "Resume mixed two learners' practice records")
    finally:
        tab.destroy()
    backup = create_verified_backup(app.db.path, directory / "education.ffbackup")
    recovered = restore_verified_copy(backup, directory / "education-restored.db", active_database=app.db.path)
    store = StudyStore(recovered)
    _require(dict(backup.counts)["Education learners"] == 3
             and dict(backup.counts)["Additional learner practice records"] == 2,
             "Backup preview omitted learner records")
    _require(learner_a in store.learners() and store.preferred_learner() == learner_a.id,
             "Learner names or remembered selection did not survive backup")
    _require(StudyStore(recovered, learner_a.id).read(learner_lesson.id, learner_question) == learner_a_work
             and StudyStore(recovered, learner_b.id).read(learner_lesson.id, learner_question) == learner_b_work,
             "Learners' independent answers did not survive backup and restore")
    learner_output = worksheet(learner_lesson,
        tuple(StudyStore(recovered, learner_a.id).read(learner_lesson.id, q) for q in learner_lesson.questions),
        learner=learner_a.name)
    _require(learner_a.name in learner_output and learner_a_work.reasoning in learner_output,
             "Worksheet did not identify its learner or include that learner's work")
    (directory / "learner-worksheet.html").write_text(learner_output, encoding="utf-8")
    _require(store.read(fraction_lesson.id, fraction_question) == fraction_work
             and store.read(quantity_lesson.id, quantity_question) == quantity_work,
             "Fraction calculation or writing did not survive backup and restore")
    fraction_output = worksheet(fraction_lesson, tuple(store.read(fraction_lesson.id, q) for q in fraction_lesson.questions))
    _require(fraction_output.count("<svg") == 3 and "[C4]" in fraction_output and fraction_work.reasoning in fraction_output,
             "Fraction worksheet lost a diagram, practice card or saved explanation")
    (directory / "fractions-worksheet.html").write_text(fraction_output, encoding="utf-8")
    _require(store.read(number_lesson.id, number_question) == number_work
             and store.read(division_lesson.id, division_question) == division_work,
             "Number foundations work did not survive backup and restore")
    number_output = worksheet(number_lesson, tuple(store.read(number_lesson.id, q) for q in number_lesson.questions))
    _require(number_output.count("<svg") == 3 and "[A4]" in number_output and number_work.reasoning in number_output,
             "Number worksheet lost a diagram step, source or explanation")
    (directory / "numbers-worksheet.html").write_text(number_output, encoding="utf-8")
    _require(store.read(lesson.id, question) == expected, "Education work did not survive a full backup")
    _require(store.read(literacy_lesson.id, literacy_question) == literacy_work
             and store.read(literacy_lesson.id, writing_question) == writing_work,
             "Literacy choice or writing work did not survive a full backup")
    records = tuple(store.read(lesson.id, q) for q in lesson.questions)
    output = worksheet(lesson, records)
    _require(expected.response in output and "<details>" in output, "Offline worksheet export is incomplete")
    (directory / "education-worksheet.html").write_text(output, encoding="utf-8")
    literacy_output = worksheet(literacy_lesson, tuple(store.read(literacy_lesson.id, q) for q in literacy_lesson.questions))
    _require("[N5]" in literacy_output and writing_work.response in literacy_output,
             "Literacy worksheet lost its source or saved writing")
    (directory / "literacy-worksheet.html").write_text(literacy_output, encoding="utf-8")
    _require(store.read(evidence_lesson.id, evidence_question) == evidence_work
             and store.read(report_lesson.id, report_question) == report_work,
             "Evidence calculation or report did not survive backup")
    evidence_output = worksheet(report_lesson, tuple(store.read(report_lesson.id, q) for q in report_lesson.questions))
    _require("<svg" in evidence_output and "[R2]" in evidence_output and report_work.response in evidence_output,
             "Evidence worksheet lost its chart, records or report")
    (directory / "evidence-worksheet.html").write_text(evidence_output, encoding="utf-8")
    reopened = EducationTab(root, recovered)
    try:
        _require(reopened.current_learner.id == learner_a.id, "Reopened desktop forgot the selected learner")
        reopened.resume()
        _require(reopened.work == learner_a_work, "Reopened learner A work is incorrect")
        _require(reopened.switch_learner(learner_b.id), "Could not reopen learner B")
        reopened.resume()
        _require(reopened.work == learner_b_work, "Reopened learner B work is incorrect")
        _require(reopened.switch_learner("default"), "Could not return to original practice")
        reopened.open_lesson(fraction_lesson.id)
        _require(reopened.work == fraction_work and reopened.response.get("1.0", "end-1c") == "3/6",
                 "Recovered fraction response is not visible")
        reopened.open_lesson(number_lesson.id)
        reopened.move_question(1)
        _require(reopened.response.get("1.0", "end-1c") == "43" and reopened.work.hints == 1,
                 "Restored foundation practice is not visible")
        reopened.open_lesson(lesson.id)
        reopened.move_question(4)
        _require(reopened.response.get("1.0", "end-1c") == expected.response,
                 "Recovered education response is not visible in the UI")
        reopened.open_lesson(literacy_lesson.id)
        _require(reopened.choice_response.get() == "B", "Recovered choice is not visible")
        reopened.open_lesson(evidence_lesson.id)
        _require(reopened.response.get("1.0", "end-1c") == "0.8", "Recovered evidence calculation is not visible")
        reopened.draw_diagram()
        _require(any(reopened.diagram.type(item) == "rectangle" for item in reopened.diagram.find_all()),
                 "Evidence bar chart is unavailable in the packaged desktop")
    finally:
        reopened.destroy()


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
            verify_blueprint_workspace(tk_root, root_path)
            verify_education_workspace(tk_root, root_path)
        finally:
            tk_root.destroy()
        checks.append("Tk window and PNG decoding; synthetic MBTiles tile read")
        checks.append("GPS workspace with fictional tiles/places, JPEG/WebP images and offline-default portal; no receiver or recording")
        checks.append("Blueprint form, mixed-unit dimensions, edit/save/reopen, drawing exports, three makers and 439 packaged references")
        checks.append("Education: 196 lessons; independent learner profiles, remembered selection, isolated answers and hints, rename, resume, all-learner backup/restore, labeled worksheets, fraction lab and every guided course")
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
