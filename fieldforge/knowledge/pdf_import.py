"""Preview-first extraction of existing PDF text layers, not full-document preservation.

Parser work runs in a disposable process with deadline/cancel checks. No OCR,
network calls, rendering, embedded-code execution, automatic imports or overwrites.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

from fieldforge.knowledge import KnowledgeArticle

MAX_PDF_BYTES = 16 * 1024 * 1024
MAX_PAGES = 200
MAX_TEXT_CHARACTERS = 1_500_000
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
EXTRA_HELP = 'PDF support needs the optional dependency. From the updated source folder run: py -m pip install ".[pdf]"'
EXTRACTION_NOTICE = (
    "PDF TEXT EXTRACTION — NOT A COMPLETE COPY OF THE ORIGINAL. "
    "Images, diagrams, annotations and attachments are not imported. Tables, columns, "
    "symbols and reading order may be wrong or incomplete. No OCR or visual verification "
    "was performed. Keep and compare the original PDF before relying on this text, "
    "especially for medical, food, equipment or engineering guidance."
)
EMPTY_PAGE = "[No text extracted on this page. It may be blank or image-only; inspect the original PDF.]"


class PDFCancelled(ValueError):
    """The extraction was cancelled; discard it without any database write."""


@dataclass(frozen=True)
class PDFTextDocument:
    name: str
    file_sha256: str
    file_bytes: int
    pages: tuple[str, ...] = field(repr=False)
    parser_version: str
    memory_limited: bool = False
    body: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or len(self.name) > 1000:
            raise ValueError("invalid PDF filename")
        if not isinstance(self.file_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.file_sha256):
            raise ValueError("invalid original PDF checksum")
        if type(self.file_bytes) is not int or not 1 <= self.file_bytes <= MAX_PDF_BYTES:
            raise ValueError("PDF exceeds the 16 MiB file limit")
        if not isinstance(self.pages, tuple) or not 1 <= len(self.pages) <= MAX_PAGES:
            raise ValueError("PDF must contain 1–200 physical pages")
        if any(not isinstance(page, str) or "\x00" in page for page in self.pages):
            raise ValueError("extracted PDF text contains invalid characters")
        if sum(map(len, self.pages)) > MAX_TEXT_CHARACTERS:
            raise ValueError("PDF text exceeds the 1,500,000-character limit; use a smaller document")
        if not any(page.strip() for page in self.pages):
            raise ValueError("No readable text layer found. This may be a scan. OCR is not included; nothing was imported.")
        if not isinstance(self.parser_version, str) or not re.fullmatch(r"[a-zA-Z0-9.+-]{1,80}", self.parser_version):
            raise ValueError("invalid PDF parser version")
        if type(self.memory_limited) is not bool:
            raise ValueError("invalid parser memory-limit flag")
        missing = ", ".join(map(str, self.empty_pages)) or "None detected (this does not prove completeness)"
        sections = [EXTRACTION_NOTICE, f"Original PDF SHA-256: {self.file_sha256}",
                    f"Extraction: pypdf {self.parser_version}; physical pages: {len(self.pages)}.",
                    "Page numbers below are positions in the PDF, not printed page labels.",
                    "Pages with no extracted text: " + missing]
        for number, page in enumerate(self.pages, 1):
            sections.append(f"--- PDF PAGE {number} OF {len(self.pages)} ---\n{page if page.strip() else EMPTY_PAGE}")
        object.__setattr__(self, "body", "\n\n".join(sections))

    @property
    def empty_pages(self) -> tuple[int, ...]:
        return tuple(i for i, page in enumerate(self.pages, 1) if not page.strip())

    @property
    def suggested_id(self) -> str:
        return "pdf-" + self.file_sha256

    @property
    def suggested_title(self) -> str:
        return Path(self.name).stem.replace("_", " ").replace("-", " ")[:500]


def _capture_file(source: str | Path) -> tuple[str, bytes]:
    path = Path(source).expanduser()
    if path.suffix.lower() != ".pdf":
        raise ValueError("Choose a local .pdf file. Use Import Text Document for plain text.")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("choose a regular PDF file, not a device or pipe")
        if info.st_size > MAX_PDF_BYTES:
            raise ValueError("PDF exceeds the 16 MiB file limit")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_PDF_BYTES + 1)
    finally:
        os.close(fd)
    if not 1 <= len(raw) <= MAX_PDF_BYTES or not raw.startswith(b"%PDF-"):
        raise ValueError("Not a supported PDF header or file size. Choose a valid, trusted PDF.")
    return path.name, raw


def _run_parser(raw: bytes, cancel: Event, timeout: float) -> dict[str, object]:
    """No pipe deadlocks: input/output are temporary handles, not user-selected paths."""
    if importlib.util.find_spec("pypdf") is None:
        raise ValueError(EXTRA_HELP)
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryFile() as incoming, tempfile.TemporaryFile() as outgoing:
        incoming.write(raw)
        incoming.seek(0)
        command = [sys.executable, "-m", "fieldforge.knowledge.pdf_worker"]
        process = subprocess.Popen(command, stdin=incoming, stdout=outgoing, stderr=subprocess.DEVNULL,
                                   cwd=Path(__file__).resolve().parents[2], shell=False,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            while True:
                if cancel.is_set():
                    raise PDFCancelled("PDF extraction cancelled; nothing imported")
                if time.monotonic() > deadline:
                    raise TimeoutError("PDF extraction timed out; choose a smaller trusted document")
                if os.fstat(outgoing.fileno()).st_size > MAX_RESPONSE_BYTES:
                    raise ValueError("PDF extraction exceeded its output limit")
                if process.poll() is not None:
                    break
                cancel.wait(0.04)
            outgoing.seek(0)
            payload = outgoing.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise ValueError("PDF extraction exceeded its output limit")
            if not payload:
                raise ValueError("PDF parser stopped without a result (unsupported data or resource limit). Nothing imported.")
            try:
                result = json.loads(payload.decode("utf-8"))
            except (UnicodeError, ValueError) as exc:
                raise ValueError("PDF parser returned an invalid result; nothing imported") from exc
            if not isinstance(result, dict):
                raise ValueError("PDF parser returned an invalid result")
            if set(result) == {"error"} and isinstance(result["error"], str):
                raise ValueError(result["error"][:500])
            if process.returncode != 0 or set(result) != {"pages", "version", "memory_limited"}:
                raise ValueError("PDF parser failed; nothing imported")
            return result
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()  # Reap the child and close temp handles even after cancellation.


def read_pdf_document(source: str | Path, *, cancel: Event | None = None,
                      timeout: float = 20.0) -> PDFTextDocument:
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError("PDF timeout must be greater than zero and at most 60 seconds")
    cancelled = cancel if cancel is not None else Event()
    if cancelled.is_set():
        raise PDFCancelled("PDF extraction cancelled; nothing imported")
    name, raw = _capture_file(source)
    result = _run_parser(raw, cancelled, timeout)
    if cancelled.is_set():
        raise PDFCancelled("PDF extraction cancelled; nothing imported")
    pages = result["pages"]
    if not isinstance(pages, list):
        raise ValueError("invalid PDF page results")
    return PDFTextDocument(name, hashlib.sha256(raw).hexdigest(), len(raw), tuple(pages),
                           result["version"], result["memory_limited"])


def prepare_pdf_article(document: PDFTextDocument, *, title: str, category: str,
                        slug: str | None = None, tags: tuple[str, ...] = (),
                        source_title: str = "", source_publisher: str = "",
                        source_url: str = "", license: str = "", reviewed_on: str = "",
                        safety_level: str = "caution") -> KnowledgeArticle:
    if not isinstance(document, PDFTextDocument):
        raise ValueError("preview PDF text first")
    identifier = document.suggested_id if slug is None else slug
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", identifier):
        raise ValueError("article ID must be 1–100 lowercase letters, digits, or hyphens")
    return KnowledgeArticle(identifier, title, document.body, category, tags, source_title,
                            source_url, source_publisher, reviewed_on, safety_level, license)
