"""Preserve exact original PDF bytes independently of text extraction.

No PDF parser/viewer is invoked. Header and hash checks do not establish PDF
validity, safety, copying rights or fidelity of a linked article's extraction.
Only full SQLite snapshots include originals; ordinary article exports do not.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from fieldforge.knowledge import KnowledgeLibrary

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_STORED_BYTES = 256 * 1024 * 1024
MAX_RECORDS = 500
NOTICE = (
    "Original PDFs are stored unchanged, including images, metadata, attachments and any active content. "
    "No malware scan, sanitization, PDF validation or source review is performed. Only store files you "
    "trust and have permission to copy. Records and backups are unencrypted. Nothing opens automatically."
)
STATES = {"unlinked": "No article association", "current": "Article version unchanged",
          "changed": "Article changed since storage", "missing": "Associated article missing"}
_ARTICLE_FIELDS = ("slug", "title", "category", "tags", "source_title", "source_url", "source_publisher",
                   "reviewed_on", "safety_level", "license", "checksum")
_REF_FIELDS = ("id", "file_sha256", "filename", "article_slug", "article_title", "article_version", "stored_at")
_SCHEMA = {
    "knowledge_original_blobs": {"sha256", "byte_count", "payload"},
    "knowledge_original_refs": set(_REF_FIELDS),
}


def _digest(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid checksum or version token")


def _version(row) -> str:
    return hashlib.sha256(json.dumps({key: row[key] for key in _ARTICLE_FIELDS}, sort_keys=True,
                                    ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _filename(value: str) -> None:
    if (not isinstance(value, str) or not value.strip() or len(value) > 255
            or any(ord(c) < 32 or ord(c) == 127 or c in "/\\" for c in value)
            or not value.lower().endswith(".pdf")):
        raise ValueError("use a single-line .pdf filename of at most 255 characters, without path separators")


@dataclass(frozen=True)
class CapturedPDF:
    filename: str
    data: bytes = field(repr=False)
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _filename(self.filename)
        if type(self.data) is not bytes or not 1 <= len(self.data) <= MAX_FILE_BYTES:
            raise ValueError("PDF must contain at most 16 MiB of file bytes")
        if not self.data.startswith(b"%PDF-"):
            raise ValueError("file does not start with a PDF header; nothing stored")
        object.__setattr__(self, "sha256", hashlib.sha256(self.data).hexdigest())


def capture_pdf(source: str | Path) -> CapturedPDF:
    """Bounded regular-file read. Capture once; no reopening on Store.

    No parsing, decryption, OCR or embedded-code execution. A PDF header alone
    does not distinguish valid, damaged, scanned, encrypted or malicious files.
    """
    path = Path(source).expanduser()
    _filename(path.name)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("choose a regular local PDF, not a directory, pipe or device")
        if not 1 <= info.st_size <= MAX_FILE_BYTES:
            raise ValueError("PDF must contain at most 16 MiB of file bytes")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(descriptor)
        if (len(raw) != info.st_size or (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("PDF changed while being captured; wait for the other writer and choose it again")
    finally:
        os.close(descriptor)
    return CapturedPDF(path.name, raw)


@dataclass(frozen=True)
class ArticleAnchor:
    slug: str
    title: str
    version: str


@dataclass(frozen=True)
class OriginalRecord:
    id: int
    file_sha256: str
    filename: str
    article_slug: str
    article_title: str
    article_version: str
    stored_at: str
    byte_count: int
    token: str
    state: str


@dataclass(frozen=True)
class OriginalInventory:
    records: tuple[OriginalRecord, ...]
    references: int
    unique_files: int
    stored_bytes: int


@dataclass(frozen=True)
class StoredOriginal:
    record: OriginalRecord
    added: bool


@dataclass(frozen=True)
class ExportedOriginal:
    path: Path
    sha256: str
    byte_count: int


class OriginalConflict(ValueError):
    """Article or stored reference changed after preview; do not guess/overwrite."""


class OriginalStore:
    def __init__(self, database: str | Path) -> None:
        self.path = Path(database).expanduser().resolve()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            marker = db.execute("SELECT value FROM knowledge_state WHERE key='original_files_schema'").fetchone()
            objects = {r[0]: r[1] for r in db.execute(
                "SELECT name,type FROM sqlite_master WHERE name IN ('knowledge_original_blobs','knowledge_original_refs')"
            )}
            if marker is not None:
                if marker[0] != "1" or objects != {name: "table" for name in _SCHEMA}:
                    raise ValueError("unsupported or incomplete original-file schema; no data was reset")
                for table, fields in _SCHEMA.items():
                    if {r[1] for r in db.execute(f"PRAGMA table_info({table})")} != fields:
                        raise ValueError("unrecognized original-file fields; use a compatible build")
            elif objects:
                raise ValueError("unversioned original-file tables; no data was reset")
            else:
                db.execute("""CREATE TABLE knowledge_original_blobs(
                    sha256 TEXT PRIMARY KEY, byte_count INTEGER NOT NULL CHECK(byte_count>0),
                    payload BLOB NOT NULL CHECK(typeof(payload)='blob' AND length(payload)=byte_count)
                )""")
                # No FK to article: deletion must not discard its only retained original.
                db.execute("""CREATE TABLE knowledge_original_refs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_sha256 TEXT NOT NULL REFERENCES knowledge_original_blobs(sha256),
                    filename TEXT NOT NULL, article_slug TEXT NOT NULL DEFAULT '',
                    article_title TEXT NOT NULL DEFAULT '', article_version TEXT NOT NULL DEFAULT '',
                    stored_at TEXT NOT NULL, UNIQUE(file_sha256,article_slug)
                )""")
                db.execute("INSERT INTO knowledge_state VALUES('original_files_schema','1')")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=0.25)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _anchor(db: sqlite3.Connection, slug: str) -> ArticleAnchor:
        if not isinstance(slug, str) or not slug or len(slug) > 200 or "\x00" in slug:
            raise ValueError("select an installed article before associating a PDF")
        row = db.execute("SELECT * FROM knowledge_articles WHERE slug=?", (slug,)).fetchone()
        if row is None:
            raise OriginalConflict("Article is no longer installed; capture without an association or reopen the article.")
        article = KnowledgeLibrary._article(row)
        if article.checksum != row["checksum"]:
            raise ValueError("Article checksum mismatch; nothing associated")
        return ArticleAnchor(article.slug, article.title, _version(row))

    def anchor(self, slug: str) -> ArticleAnchor:
        with self.connect() as db:
            return self._anchor(db, slug)

    @staticmethod
    def _record(db: sqlite3.Connection, row: sqlite3.Row) -> OriginalRecord:
        metadata = {key: row[key] for key in _REF_FIELDS}
        _filename(row["filename"])
        _digest(row["file_sha256"])
        token = hashlib.sha256(json.dumps(metadata, sort_keys=True, ensure_ascii=False,
                                         allow_nan=False).encode("utf-8")).hexdigest()
        size = db.execute("SELECT byte_count FROM knowledge_original_blobs WHERE sha256=?",
                          (row["file_sha256"],)).fetchone()
        if size is None or type(size[0]) is not int or not 1 <= size[0] <= MAX_FILE_BYTES:
            raise ValueError("Stored PDF size/metadata is missing or invalid; no partial list shown")
        state = "unlinked"
        if row["article_slug"]:
            source = db.execute(f"SELECT {','.join(_ARTICLE_FIELDS)} FROM knowledge_articles WHERE slug=?",
                                (row["article_slug"],)).fetchone()
            state = "missing" if source is None else "current" if _version(source) == row["article_version"] else "changed"
        return OriginalRecord(**metadata, byte_count=size[0], token=token, state=state)

    def browse(self, query: str = "", *, article_slug: str | None = None, offset: int = 0,
               limit: int = 50) -> OriginalInventory:
        if not isinstance(query, str) or len(query) > 200 or "\x00" in query:
            raise ValueError("search must be text of at most 200 characters")
        if article_slug is not None and (not isinstance(article_slug, str) or not article_slug or len(article_slug) > 200):
            raise ValueError("invalid article filter")
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid original-file page")
        with self.connect() as db:
            db.execute("BEGIN")
            db.create_function("casefold", 1, lambda text: str(text).casefold())
            filter_sql = " AND article_slug=?" if article_slug is not None else ""
            parameters = (query.casefold(), article_slug, limit, offset) if article_slug is not None else (query.casefold(), limit, offset)
            rows = db.execute("SELECT * FROM knowledge_original_refs WHERE instr(casefold(filename||' '||article_title||' '||article_slug),?)>0"
                              + filter_sql + " ORDER BY id DESC LIMIT ? OFFSET ?", parameters).fetchall()
            count = db.execute("SELECT COUNT(*) FROM knowledge_original_refs").fetchone()[0]
            files, total = db.execute("SELECT COUNT(*),COALESCE(SUM(length(payload)),0) FROM knowledge_original_blobs").fetchone()
            return OriginalInventory(tuple(self._record(db, row) for row in rows), count, files, total)

    @staticmethod
    def _blob(db: sqlite3.Connection, digest: str) -> bytes:
        _digest(digest)
        row = db.execute("SELECT byte_count,length(payload),typeof(payload) FROM knowledge_original_blobs WHERE sha256=?",
                         (digest,)).fetchone()
        if row is None or type(row[0]) is not int or not 1 <= row[0] <= MAX_FILE_BYTES or row[0] != row[1] or row[2] != "blob":
            raise ValueError("Stored PDF is missing or has an invalid size/type; nothing exported")
        raw = db.execute("SELECT payload FROM knowledge_original_blobs WHERE sha256=?", (digest,)).fetchone()[0]
        if not raw.startswith(b"%PDF-") or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Stored PDF checksum failed; restore a trusted backup instead of exporting damaged bytes")
        return raw

    def store(self, captured: CapturedPDF, *, article: ArticleAnchor | None = None,
              acknowledged: bool = False) -> StoredOriginal:
        if acknowledged is not True:
            raise ValueError("confirm trust, copying permission and the unencrypted storage notice")
        if not isinstance(captured, CapturedPDF):
            raise ValueError("capture a PDF before storing")
        if article is not None and not isinstance(article, ArticleAnchor):
            raise ValueError("preview the article association first")
        slug = article.slug if article else ""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if article is not None and self._anchor(db, slug) != article:
                raise OriginalConflict("Article changed since capture. Your PDF is not stored; recapture or store without association.")
            old = db.execute("SELECT * FROM knowledge_original_refs WHERE file_sha256=? AND article_slug=?",
                             (captured.sha256, slug)).fetchone()
            existing = db.execute("SELECT 1 FROM knowledge_original_blobs WHERE sha256=?", (captured.sha256,)).fetchone()
            if existing and self._blob(db, captured.sha256) != captured.data:
                raise ValueError("Stored bytes differ despite matching hash; nothing replaced")
            if old:
                if article and old["article_version"] != article.version:
                    raise OriginalConflict("This PDF is already associated with an earlier article version; original association preserved.")
                return StoredOriginal(self._record(db, old), False)
            if db.execute("SELECT COUNT(*) FROM knowledge_original_refs").fetchone()[0] >= MAX_RECORDS:
                raise ValueError("original-file reference limit reached (500); remove unused stored references first")
            if not existing:
                total = db.execute("SELECT COALESCE(SUM(length(payload)),0) FROM knowledge_original_blobs").fetchone()[0]
                if total + len(captured.data) > MAX_STORED_BYTES:
                    raise ValueError("original PDF storage limit reached (256 MiB of unique bytes)")
                db.execute("INSERT INTO knowledge_original_blobs VALUES(?,?,?)",
                           (captured.sha256, len(captured.data), captured.data))
            cursor = db.execute("""INSERT INTO knowledge_original_refs
                (file_sha256,filename,article_slug,article_title,article_version,stored_at) VALUES(?,?,?,?,?,?)""",
                (captured.sha256, captured.filename, slug, article.title if article else "",
                 article.version if article else "", datetime.now(timezone.utc).isoformat(timespec="seconds")))
            row = db.execute("SELECT * FROM knowledge_original_refs WHERE id=?", (cursor.lastrowid,)).fetchone()
            return StoredOriginal(self._record(db, row), True)

    def _check(self, db: sqlite3.Connection, record: OriginalRecord) -> OriginalRecord:
        if not isinstance(record, OriginalRecord) or type(record.id) is not int or record.id <= 0:
            raise ValueError("select a saved original PDF")
        row = db.execute("SELECT * FROM knowledge_original_refs WHERE id=?", (record.id,)).fetchone()
        if row is None or (current := self._record(db, row)).token != record.token:
            raise OriginalConflict("Stored PDF reference changed or was removed; refresh the list before continuing")
        return current

    def read_verified(self, record: OriginalRecord) -> bytes:
        with self.connect() as db:
            db.execute("BEGIN")
            current = self._check(db, record)
            return self._blob(db, current.file_sha256)

    def remove(self, record: OriginalRecord) -> int:
        """Remove this association; delete its BLOB only when no other reference uses it.

        Not secure erasure. Do not change the external original, article or notes.
        Returns how many references still use these bytes.
        """
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._check(db, record)
            db.execute("DELETE FROM knowledge_original_refs WHERE id=?", (current.id,))
            remaining = db.execute("SELECT COUNT(*) FROM knowledge_original_refs WHERE file_sha256=?",
                                   (current.file_sha256,)).fetchone()[0]
            if not remaining:
                db.execute("DELETE FROM knowledge_original_blobs WHERE sha256=?", (current.file_sha256,))
            return remaining

    def export(self, record: OriginalRecord, destination: str | Path, *, acknowledged: bool = False) -> ExportedOriginal:
        if acknowledged is not True:
            raise ValueError("confirm copying permission and unchanged PDF/unencrypted export notice")
        path = Path(destination).expanduser().absolute()
        if path.suffix.lower() != ".pdf":
            raise ValueError("choose a NEW .pdf filename")
        raw = self.read_verified(record)  # Verify complete bytes before creating any output.
        identity = None
        try:
            with path.open("xb") as stream:
                identity = os.fstat(stream.fileno())
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            with path.open("rb") as stream:
                actual = stream.read(MAX_FILE_BYTES + 1)
            if actual != raw:
                raise OSError("Export read-back differs from the verified PDF bytes")
        except BaseException:
            if identity is not None:
                try:
                    now = path.lstat()
                    if (now.st_dev, now.st_ino) == (identity.st_dev, identity.st_ino):
                        path.unlink()
                except OSError:
                    pass
            raise
        return ExportedOriginal(path.resolve(), record.file_sha256, len(raw))
