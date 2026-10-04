"""Real PDF files, actual app/snapshot behavior, export privacy and desktop guards."""

import gc
import time
from io import BytesIO

import pytest
from pdf_fixture import pdf_bytes

from fieldforge.app import FieldForgeApp
from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.originals import CapturedPDF, OriginalStore, capture_pdf


def source_pdf(*, encrypted=False, active=False):
    pytest.importorskip("pypdf")
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject

    writer = PdfWriter(clone_from=PdfReader(BytesIO(pdf_bytes(("Fixture text", None, "Last conditions")))))
    vector = DecodedStreamObject()
    vector.set_data(b"q 0.1 0.3 0.6 rg 70 220 230 160 re f 0 0 0 RG 3 w 60 210 250 180 re S Q")
    writer.pages[1][NameObject("/Contents")] = writer._add_object(vector)
    writer.add_metadata({"/Title": "Original diagram fixture"})
    writer.add_attachment("fixture.txt", b"Quillvaultsentinel4921")
    if active:
        writer.add_js("app.alert('Fictional preservation test only');")
    if encrypted:
        writer.encrypt("test-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def saved(tmp_path):
    app = FieldForgeApp(tmp_path / "app.db")
    app.knowledge.upsert(KnowledgeArticle("drawing", "Drawing text", "Use the separately stored original PDF.", "reference"))
    store = OriginalStore(app.db.path)
    raw = source_pdf()
    original = store.store(CapturedPDF("diagram.pdf", raw), article=store.anchor("drawing"), acknowledged=True).record
    return app, store, original, raw


def test_snapshot_restores_exact_original_including_graphics_metadata_attachments(saved, tmp_path):
    from pypdf import PdfReader

    from fieldforge.core.recovery import create_verified_backup, restore_verified_copy

    app, store, record, raw = saved
    app.knowledge.annotate("drawing", bookmarked=True, note="Private article note\n\n")
    backup = create_verified_backup(app.db.path, tmp_path / "complete.ffbackup")
    assert dict(backup.counts)["Stored original PDF files"] == 1
    assert dict(backup.counts)["Original PDF references"] == 1
    store.remove(record)
    restored = restore_verified_copy(backup, tmp_path / "restored.db", active_database=app.db.path)
    recovered = OriginalStore(restored)
    assert recovered.read_verified(record) == raw
    exported = recovered.export(record, tmp_path / "Recovered-diagram.pdf", acknowledged=True)
    assert exported.path.read_bytes() == raw
    reader = PdfReader(exported.path)
    assert len(reader.pages) == 3 and "230 160 re" in reader.pages[1].get_contents().get_data().decode()
    assert reader.metadata.title == "Original diagram fixture"
    assert reader.attachments["fixture.txt"] == [b"Quillvaultsentinel4921"]
    assert KnowledgeLibrary(restored).annotation("drawing")["note"] == "Private article note\n\n"


@pytest.mark.parametrize("mode", ["scan", "encrypted", "active"])
def test_byte_storage_does_not_parse_decrypt_extract_or_open_pdf(tmp_path, monkeypatch, mode):
    pytest.importorskip("pypdf")
    import pypdf

    library = KnowledgeLibrary(tmp_path / "app.db")
    store = OriginalStore(library.database_path)
    raw = pdf_bytes((None, None)) if mode == "scan" else source_pdf(encrypted=mode == "encrypted", active=mode == "active")
    path = tmp_path / "original.pdf"
    path.write_bytes(raw)
    def forbidden(*args, **kwargs):
        raise AssertionError("preservation must not parse the PDF")
    monkeypatch.setattr(pypdf, "PdfReader", forbidden)
    record = store.store(capture_pdf(path), acknowledged=True).record
    assert store.export(record, tmp_path / "copy.pdf", acknowledged=True).path.read_bytes() == raw
    assert library.count() == 0


def test_text_extraction_and_storing_original_remain_separate_operations(tmp_path):
    from fieldforge.knowledge.documents import commit_document
    from fieldforge.knowledge.pdf_import import prepare_pdf_article, read_pdf_document

    raw = source_pdf()
    path = tmp_path / "original.pdf"
    path.write_bytes(raw)
    library = KnowledgeLibrary(tmp_path / "library.db")
    text = read_pdf_document(path)
    article = prepare_pdf_article(text, title="Extracted sample", category="reference")
    commit_document(library, article, acknowledged=True)
    store = OriginalStore(library.database_path)
    assert store.browse().references == 0
    record = store.store(capture_pdf(path), article=store.anchor(article.slug), acknowledged=True).record
    assert library.get(article.slug) == article
    assert "NOT A COMPLETE COPY" in article.body
    assert text.empty_pages == (2,)
    assert record.file_sha256 == text.file_sha256
    assert store.read_verified(record) == raw


def test_shared_content_exports_and_ask_library_do_not_read_original_tables(saved, tmp_path, monkeypatch):
    import sqlite3

    from fieldforge.knowledge.assistant import ReferenceAssistant
    from fieldforge.knowledge.binder import capture_binder, render_binder
    from fieldforge.knowledge.packs import export_pack
    from fieldforge.knowledge.pocket import capture_pocket, render_pocket

    app, store, record, _ = saved
    real = sqlite3.connect
    def connect(*args, **kwargs):
        db = real(*args, **kwargs)
        def authorize(action, table, *_):
            if table in {"knowledge_original_blobs", "knowledge_original_refs"}:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        return db
    monkeypatch.setattr(sqlite3, "connect", connect)
    pack = export_pack(app.knowledge, tmp_path / "shared.json", include_personal=True).read_bytes()
    binder = render_binder(capture_binder(app.db.path, slugs=("drawing",)))
    pocket = render_pocket(capture_pocket(app.db.path, slugs=("drawing",)))
    for data in (pack, binder, pocket):
        assert record.filename.encode() not in data
        assert record.file_sha256.encode() not in data
        assert b"Quillvaultsentinel4921" not in data
    assert not ReferenceAssistant(app.db.path).ask("Quillvaultsentinel4921").references


def test_recovery_reports_optional_originals_but_does_not_silently_validate_each_pdf_hash(saved, tmp_path):
    from fieldforge.core.recovery import create_verified_backup, inspect_backup

    app, store, record, raw = saved
    with store.connect() as db:
        # Corruption that leaves valid SQLite structure, to distinguish the two checks.
        db.execute("UPDATE knowledge_original_blobs SET payload=?", (b"%PDF-" + b"x"*(len(raw)-5),))
    backup = create_verified_backup(app.db.path, tmp_path / "structurally-valid.ffbackup")
    assert dict(inspect_backup(backup.source).counts)["Stored original PDF files"] == 1
    assert any("original-PDF hashes" in warning for warning in backup.warnings)
    with pytest.raises(ValueError, match="checksum failed"):
        store.read_verified(record)


def test_real_desktop_originals_dialog_blocks_close_and_backup_until_dismissed(tmp_path, monkeypatch):
    gc.collect()
    tk = pytest.importorskip("tkinter")
    from fieldforge.ui import desktop
    from fieldforge.ui.knowledge import KnowledgeTab
    from fieldforge.ui.originals import OriginalsDialog
    from fieldforge.ui.recovery import RecoveryTab

    app = FieldForgeApp(tmp_path / "desktop.db")
    app.knowledge.upsert(KnowledgeArticle("sample", "Sample reference", "Harmless test text.", "reference"))
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable; graphical CI requires one")
    monkeypatch.setenv("FIELDFORGE_DB", str(app.db.path))
    monkeypatch.setattr(tk, "Tk", lambda: root)
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *args, **kwargs: None)
    failures, passed, workers = [], [], []
    root.report_callback_exception = lambda *args: failures.append(args)

    def children(widget):
        yield widget
        for child in widget.winfo_children():
            yield from children(child)

    def exercise():
        root.after_cancel(timer)
        dialog = None
        try:
            library = next(w for w in children(root) if isinstance(w, KnowledgeTab))
            recovery = next(w for w in children(root) if isinstance(w, RecoveryTab))
            library.results.selection_set("sample")
            root.update()
            library.originals_button.invoke()
            dialog = next(w for w in children(root) if isinstance(w, OriginalsDialog))
            deadline = time.monotonic()+5
            while dialog.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(0.005)
            assert dialog.store is not None
            assert library.busy and not recovery.before_backup()
            root.tk.call(root.protocol("WM_DELETE_WINDOW"))
            assert root.winfo_exists()
            dialog.close()
            root.update()
            assert not library.busy and recovery.before_backup()
            passed.append(True)
        except Exception as exc:
            failures.append(exc)
        finally:
            if dialog:
                dialog._worker.shutdown(wait=True, cancel_futures=True)
            workers.extend(w._worker for w in children(root) if hasattr(w, "_worker"))
            root.destroy()

    root.after(200, exercise)
    timer = root.after(10000, root.destroy)
    desktop.run()
    for worker in workers:
        worker.shutdown(wait=True, cancel_futures=True)
    gc.collect()
    assert passed and not failures
