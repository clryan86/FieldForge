"""Preview-first import of local UTF-8 text. No downloads, rendering, or replacement.

One selected file becomes one article. Original bytes are kept in memory until
import/cancel; only the decoded body and user-approved metadata enter the library.
Imported article bodies are searchable and included in ordinary knowledge packs.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_CHARACTERS = 2_000_000
SUPPORTED_SUFFIXES = frozenset({".txt", ".md", ".markdown"})
IMPORT_NOTICE = (
    "Import only material you have permission to store. Imported article text is searchable "
    "and included in ordinary Export Pack files, even when private notes are excluded. "
    "Do not use this feature for passwords or private household/medical records. "
    "Importing does not verify accuracy, safety, source claims, or redistribution rights."
)


@dataclass(frozen=True)
class TextDocument:
    """Immutable captured bytes. UTF-8 BOM is removed; all other text is preserved."""

    name: str
    raw: bytes = field(repr=False)
    body: str = field(init=False, repr=False)
    file_sha256: str = field(init=False)
    body_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or len(self.name) > 1000:
            raise ValueError("invalid document name")
        if type(self.raw) is not bytes or not 0 < len(self.raw) <= MAX_DOCUMENT_BYTES:
            raise ValueError("text document must contain 1 byte to 2 MiB")
        try:
            body = self.raw.decode("utf-8-sig", errors="strict")
        except UnicodeError as exc:
            raise ValueError("Not valid UTF-8 text. Save a UTF-8 text copy before importing.") from exc
        if not body.strip():
            raise ValueError("document has no readable text")
        if len(body) > MAX_DOCUMENT_CHARACTERS:
            raise ValueError("document exceeds 2,000,000 characters; split it into smaller files")
        if any((ord(char) < 32 and char not in "\t\r\n") or ord(char) == 127 for char in body):
            raise ValueError("document contains binary/control characters; import a plain text copy")
        object.__setattr__(self, "body", body)
        object.__setattr__(self, "file_sha256", hashlib.sha256(self.raw).hexdigest())
        object.__setattr__(self, "body_sha256", hashlib.sha256(body.encode("utf-8")).hexdigest())

    @property
    def suggested_id(self) -> str:
        # Independent of the filename; renaming a file alone does not change its ID.
        return "local-" + self.body_sha256

    @property
    def suggested_title(self) -> str:
        return Path(self.name).stem.replace("_", " ").replace("-", " ")[:500]


def read_text_document(source: str | Path) -> TextDocument:
    """Read a bounded regular file once. No directory scanning or URL fetching."""
    path = Path(source).expanduser()
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("Choose a .txt, .md, or .markdown file. PDF/Word/scans are not supported here.")
    # O_NONBLOCK prevents accidentally waiting for a FIFO writer on POSIX. It has
    # no effect on regular files. Windows binary mode avoids newline translation.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("choose a regular text file, not a device or pipe")
        if info.st_size > MAX_DOCUMENT_BYTES:
            raise ValueError("document exceeds 2 MiB; split it into smaller text files")
        # closefd=False leaves exactly one owner for cleanup even after exceptions.
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_DOCUMENT_BYTES + 1)
    finally:
        os.close(fd)
    return TextDocument(path.name, raw)


def prepare_article(document: TextDocument, *, title: str, category: str,
                    slug: str | None = None, tags: tuple[str, ...] = (),
                    source_title: str = "", source_publisher: str = "",
                    source_url: str = "", license: str = "",
                    reviewed_on: str = "", safety_level: str = "caution") -> KnowledgeArticle:
    """Use the captured body, never read the path again after preview."""
    if not isinstance(document, TextDocument):
        raise ValueError("preview a text document first")
    identifier = document.suggested_id if slug is None else slug
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", identifier):
        raise ValueError("article ID must be 1–100 lowercase letters, digits, or hyphens")
    return KnowledgeArticle(
        slug=identifier, title=title, body=document.body, category=category, tags=tags,
        source_title=source_title, source_publisher=source_publisher, source_url=source_url,
        license=license, reviewed_on=reviewed_on, safety_level=safety_level,
    )


@dataclass(frozen=True)
class DocumentImportResult:
    status: str
    slug: str
    title: str


class DocumentConflict(ValueError):
    """The selected ID already exists with different text or metadata."""


def commit_document(library: KnowledgeLibrary, article: KnowledgeArticle, *,
                    acknowledged: bool = False) -> DocumentImportResult:
    """Atomically add or recognize an identical article. NEVER replace old data.

    Check and insert share the same write transaction. Two import windows cannot
    silently overwrite each other, and annotations are never touched.
    """
    if acknowledged is not True:
        raise ValueError("confirm storage permission and the article-export privacy notice first")
    if not isinstance(article, KnowledgeArticle):
        raise ValueError("expected a validated article preview")
    with library.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT * FROM knowledge_articles WHERE slug=?", (article.slug,)).fetchone()
        if existing is not None:
            same = library._article(existing) == article and existing["checksum"] == article.checksum
            if not same:
                raise DocumentConflict(
                    "This article ID already has different text or metadata. Nothing was replaced. "
                    "Keep the existing article, or choose a different ID to deliberately add another copy."
                )
            return DocumentImportResult("unchanged", article.slug, article.title)
        library._write(db, article)
    return DocumentImportResult("added", article.slug, article.title)
