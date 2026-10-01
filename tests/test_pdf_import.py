import hashlib
import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest
from pdf_fixture import pdf_bytes

from fieldforge.knowledge import KnowledgeLibrary
from fieldforge.knowledge import pdf_import as module
from fieldforge.knowledge.documents import DocumentConflict, commit_document
from fieldforge.knowledge.pdf_import import (
    EMPTY_PAGE,
    EXTRACTION_NOTICE,
    PDFCancelled,
    PDFTextDocument,
    prepare_pdf_article,
    read_pdf_document,
)


@pytest.fixture
def pdf(tmp_path):
    pytest.importorskip("pypdf")
    path = tmp_path / "private_source.pdf"
    path.write_bytes(pdf_bytes(("Cedarledger equipment record", None, "End conditions must remain.")))
    return path


def sample(**changes):
    return PDFTextDocument(**{"name": "sample.pdf", "file_sha256": "a" * 64, "file_bytes": 100,
                               "pages": ("Sample text", "", "Last page"), "parser_version": "6.19.0", **changes})


def test_real_pdf_subprocess_preserves_page_order_missing_page_and_hash(pdf):
    before = pdf.read_bytes()
    result = read_pdf_document(pdf)
    assert result.pages == ("Cedarledger equipment record", "", "End conditions must remain.")
    assert result.empty_pages == (2,)
    assert result.file_sha256 == hashlib.sha256(before).hexdigest()
    assert result.file_bytes == len(before)
    assert result.body.startswith(EXTRACTION_NOTICE)
    assert "--- PDF PAGE 2 OF 3 ---" in result.body and EMPTY_PAGE in result.body
    assert pdf.read_bytes() == before
    assert type(result.memory_limited) is bool


def test_pdf_metadata_does_not_become_authority_or_review(pdf):
    document = read_pdf_document(pdf)
    article = prepare_pdf_article(document, title="My chosen title", category="Reference")
    assert article.body == document.body and article.category == "reference"
    assert article.source_title == article.source_publisher == article.reviewed_on == article.license == ""
    assert "Unverified PDF metadata" not in article.body
    assert "Do not auto-endorse" not in article.body
    assert str(pdf) not in article.body and pdf.name not in article.body
    assert article.safety_level == "caution"


def test_all_empty_pages_not_fabricated_as_complete_import(tmp_path):
    pytest.importorskip("pypdf")
    path = tmp_path / "blank.pdf"
    path.write_bytes(pdf_bytes((None, None)))
    with pytest.raises(ValueError, match="No readable text layer.*OCR"):
        read_pdf_document(path)


def test_encrypted_pdf_rejected_without_decrypting(tmp_path):
    pytest.importorskip("pypdf")
    path = tmp_path / "encrypted.pdf"
    path.write_bytes(pdf_bytes(encrypted=True))
    with pytest.raises(ValueError, match="Encrypted PDFs"):
        read_pdf_document(path)


def test_unparseable_pdf_returns_clear_failure(tmp_path):
    pytest.importorskip("pypdf")
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-1.7\nnot a real PDF")
    with pytest.raises(ValueError):
        read_pdf_document(path)


@pytest.mark.parametrize("extension,data", [(".txt", b"%PDF-1.7"), (".pdf", b""), (".pdf", b"not a PDF")])
def test_wrong_format_never_starts_parser(tmp_path, monkeypatch, extension, data):
    path = tmp_path / ("wrong" + extension)
    path.write_bytes(data)
    monkeypatch.setattr(module, "_run_parser", lambda *_: pytest.fail("Parser should not start"))
    with pytest.raises(ValueError):
        read_pdf_document(path)


def test_source_size_limit_checked_before_parser(pdf, monkeypatch):
    monkeypatch.setattr(module, "MAX_PDF_BYTES", 20)
    monkeypatch.setattr(module, "_run_parser", lambda *_: pytest.fail("Parser should not start"))
    with pytest.raises(ValueError, match="16 MiB"):
        read_pdf_document(pdf)


def test_missing_dependency_has_install_instruction(pdf, monkeypatch):
    monkeypatch.setattr(module.importlib.util, "find_spec", lambda _: None)
    with pytest.raises(ValueError, match=r'optional dependency.*\.\[pdf\]'):
        read_pdf_document(pdf)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO check")
def test_named_pipe_rejected_without_waiting_for_writer(tmp_path):
    path = tmp_path / "pipe.pdf"
    os.mkfifo(path)
    with pytest.raises(ValueError, match="regular"):
        read_pdf_document(path)


@pytest.mark.parametrize("changes", [
    {"pages": ()}, {"pages": ["text"]}, {"pages": ("\x00bad",)}, {"pages": (" ",)},
    {"pages": ("x",) * 201}, {"file_sha256": "bad"}, {"file_bytes": True},
    {"parser_version": "bad\nversion"}, {"memory_limited": 1}, {"name": ""},
])
def test_invalid_snapshot_rejected(changes):
    with pytest.raises(ValueError):
        sample(**changes)


def test_unicode_page_text_and_disclaimers_are_not_normalized():
    document = sample(pages=(" Café — 草稿\r\n\r\n", "Second page\n"))
    assert document.pages[0] in document.body
    assert "physical pages: 2" in document.body
    assert "not printed page labels" in document.body
    assert "None detected (this does not prove completeness)" in document.body


def test_parser_limits_no_silent_partial_pages(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    from fieldforge.knowledge import pdf_worker

    raw = pdf_bytes(("First", "Second"))
    monkeypatch.setattr(pdf_worker, "MAX_PAGES", 1)
    with pytest.raises(ValueError, match="physical pages"):
        pdf_worker.extract(raw)
    monkeypatch.setattr(pdf_worker, "MAX_PAGES", 200)
    monkeypatch.setattr(pdf_worker, "MAX_TEXT_CHARACTERS", 3)
    with pytest.raises(ValueError, match="characters"):
        pdf_worker.extract(raw)
    monkeypatch.setattr(pdf_worker, "MAX_TEXT_CHARACTERS", 1_500_000)
    monkeypatch.setattr(pdf_worker, "MAX_STREAM_BYTES", 3)
    with pytest.raises(ValueError, match="content exceeds"):
        pdf_worker.extract(raw)


def test_cancel_before_read_never_opens_file(tmp_path):
    cancelled = Event()
    cancelled.set()
    with pytest.raises(PDFCancelled):
        read_pdf_document(tmp_path / "missing.pdf", cancel=cancelled)


def test_timeout_kills_and_reaps_real_child(pdf, monkeypatch):
    original = module.subprocess.Popen
    processes = []
    def start(*args, **kwargs):
        processes.append(original(*args, **kwargs))
        return processes[-1]
    monkeypatch.setattr(module.subprocess, "Popen", start)
    with pytest.raises(TimeoutError):
        read_pdf_document(pdf, timeout=0.000001)
    assert len(processes) == 1 and processes[0].poll() is not None


def test_cancel_during_parser_reaps_process_and_never_returns_preview(pdf, monkeypatch):
    original = module.subprocess.Popen
    started, cancelled = Event(), Event()
    processes = []
    def slow(command, **kwargs):
        assert command[-1] == "fieldforge.knowledge.pdf_worker" and kwargs["shell"] is False
        processes.append(original([sys.executable, "-c", "import time; time.sleep(20)"], **kwargs))
        started.set()
        return processes[-1]
    monkeypatch.setattr(module.subprocess, "Popen", slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(read_pdf_document, pdf, cancel=cancelled)
        assert started.wait(2)
        cancelled.set()
        with pytest.raises(PDFCancelled):
            future.result(timeout=2)
    assert processes[0].poll() is not None


@pytest.mark.parametrize("output", ["not-json", "[]", '{"pages": []}', ""])
def test_bad_worker_responses_are_not_treated_as_articles(pdf, monkeypatch, output):
    original = subprocess.Popen
    def bad(command, **kwargs):
        return original([sys.executable, "-c", f"import sys; sys.stdout.write({output!r})"], **kwargs)
    monkeypatch.setattr(module.subprocess, "Popen", bad)
    with pytest.raises(ValueError):
        read_pdf_document(pdf)


def test_output_budget_enforced(pdf, monkeypatch):
    original = subprocess.Popen
    def noisy(command, **kwargs):
        return original([sys.executable, "-c", "print('x'*1000)"], **kwargs)
    monkeypatch.setattr(module, "MAX_RESPONSE_BYTES", 100)
    monkeypatch.setattr(module.subprocess, "Popen", noisy)
    with pytest.raises(ValueError, match="output limit"):
        read_pdf_document(pdf)


def test_source_changes_after_capture_do_not_replace_previewed_bytes(pdf, monkeypatch):
    original = module._run_parser
    before = pdf.read_bytes()
    def replace_file(raw, cancel, timeout):
        pdf.write_bytes(b"Changed on disk")
        return original(raw, cancel, timeout)
    monkeypatch.setattr(module, "_run_parser", replace_file)
    document = read_pdf_document(pdf)
    assert document.file_sha256 == hashlib.sha256(before).hexdigest()
    assert document.pages[0] == "Cedarledger equipment record"


def test_idempotence_and_conflicts_preserve_user_edits_and_notes(pdf, tmp_path):
    document = read_pdf_document(pdf)
    article = prepare_pdf_article(document, title="Fixture", category="reference")
    library = KnowledgeLibrary(tmp_path / "library.db")
    assert commit_document(library, article, acknowledged=True).status == "added"
    library.annotate(article.slug, bookmarked=True, note="Private note")
    assert commit_document(library, article, acknowledged=True).status == "unchanged"
    changed = replace(article, body="My edited article")
    library.upsert(changed)
    with pytest.raises(DocumentConflict):
        commit_document(library, article, acknowledged=True)
    assert library.get(article.slug) == changed
    assert library.annotation(article.slug) == {"bookmarked": True, "note": "Private note"}


def test_selected_source_metadata_and_search_work(tmp_path):
    document = sample()
    article = prepare_pdf_article(document, title="Sample", category="workshop", source_title="Original reference",
                                  source_publisher="User supplied", license="Unknown, not assumed free")
    library = KnowledgeLibrary(tmp_path / "library.db")
    commit_document(library, article, acknowledged=True)
    assert library.search("Last page")[0].slug == document.suggested_id
    assert library.get(article.slug).source_publisher == "User supplied"
    assert library.get(article.slug).reviewed_on == ""


def test_worker_extraction_does_not_fetch_links_or_run_pdf_actions(monkeypatch, tmp_path):
    pytest.importorskip("pypdf")
    from io import BytesIO

    from pypdf import PdfReader, PdfWriter

    from fieldforge.knowledge.pdf_worker import extract

    writer = PdfWriter(clone_from=PdfReader(BytesIO(pdf_bytes(("https://example.invalid/secret",)))))
    writer.add_js("app.launchURL('https://example.invalid/secret');")
    output = BytesIO()
    writer.write(output)
    def forbidden(*args, **kwargs):
        raise AssertionError("network attempted")
    for name in ("socket", "getaddrinfo", "create_connection"):
        monkeypatch.setattr(socket, name, forbidden)
    assert extract(output.getvalue())["pages"] == ["https://example.invalid/secret"]


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), 61])
def test_invalid_timeouts_rejected(tmp_path, timeout):
    with pytest.raises(ValueError):
        read_pdf_document(tmp_path / "missing.pdf", timeout=timeout)
