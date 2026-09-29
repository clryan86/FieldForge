"""Local knowledge storage, search, bookmarks and notes; no network dependencies."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

_TAG_SPLIT = re.compile(r"[,;]")


@dataclass(frozen=True)
class KnowledgeArticle:
    slug: str
    title: str
    body: str
    category: str
    tags: tuple[str, ...] = ()
    source_title: str = ""
    source_url: str = ""
    source_publisher: str = ""
    reviewed_on: str = ""
    safety_level: str = "reference"
    license: str = ""

    def __post_init__(self) -> None:
        for key, maximum in (
            ("slug", 200), ("title", 500), ("body", 2_000_000), ("category", 100),
            ("source_title", 1000), ("source_url", 2048), ("source_publisher", 1000),
            ("reviewed_on", 10), ("safety_level", 20), ("license", 1000),
        ):
            value = getattr(self, key)
            if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
                raise ValueError(f"invalid {key}")
            # Preserve the exact body, including whitespace, so its hash is reproducible.
            if key != "body":
                object.__setattr__(self, key, value.strip())
        if not all(getattr(self, key).strip() for key in ("slug", "title", "body", "category")):
            raise ValueError("slug, title, body, and category are required")
        if self.safety_level not in {"reference", "caution", "high_stakes"}:
            raise ValueError("invalid safety_level")
        if self.reviewed_on:
            if date.fromisoformat(self.reviewed_on).isoformat() != self.reviewed_on:
                raise ValueError("reviewed_on must be YYYY-MM-DD")
        if self.source_url:
            url = urlsplit(self.source_url)
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
                raise ValueError("source_url must be an HTTP(S) URL without credentials")
        if not isinstance(self.tags, (tuple, list)) or len(self.tags) > 64:
            raise ValueError("tags must contain at most 64 strings")
        if any(not isinstance(tag, str) or len(tag) > 100 or "\x00" in tag for tag in self.tags):
            raise ValueError("invalid tag")
        tags = {part.strip().lower() for tag in self.tags for part in _TAG_SPLIT.split(tag)}
        object.__setattr__(self, "tags", tuple(sorted(tags - {""})))
        object.__setattr__(self, "category", self.category.lower())

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SearchResult:
    slug: str
    title: str
    category: str
    tags: tuple[str, ...]
    snippet: str
    source_title: str
    source_publisher: str
    reviewed_on: str
    safety_level: str
    source_url: str = ""
    bookmarked: bool = False
    license: str = ""


class KnowledgeLibrary:
    """An FTS5 library with a slower literal-search fallback on minimal SQLite builds."""

    def __init__(self, database_path: str | Path, *, use_fts: bool = True) -> None:
        self.database_path = Path(database_path).expanduser()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.fts_enabled = False
        self.initialize(use_fts=use_fts)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.create_function("casefold", 1, lambda value: str(value).casefold())
        try:
            with connection:
                yield connection
        finally:
            # sqlite3's own context manager commits/rolls back but does NOT close.
            connection.close()

    def initialize(self, *, use_fts: bool = True) -> None:
        self.fts_enabled = False
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL, body TEXT NOT NULL, category TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '', source_title TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '', source_publisher TEXT NOT NULL DEFAULT '',
                    reviewed_on TEXT NOT NULL DEFAULT '', safety_level TEXT NOT NULL DEFAULT 'reference',
                    checksum TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS knowledge_category ON knowledge_articles(category);
                CREATE TABLE IF NOT EXISTS knowledge_annotations (
                    slug TEXT PRIMARY KEY REFERENCES knowledge_articles(slug) ON DELETE CASCADE,
                    bookmarked INTEGER NOT NULL DEFAULT 0 CHECK(bookmarked IN (0,1)),
                    note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS knowledge_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(knowledge_articles)")}
            if "license" not in columns:
                db.execute("ALTER TABLE knowledge_articles ADD COLUMN license TEXT NOT NULL DEFAULT ''")
            had_index = db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='knowledge_fts'"
            ).fetchone() is not None
            try:
                if use_fts:
                    db.execute("CREATE VIRTUAL TABLE temp.knowledge_probe USING fts5(text)")
                    db.execute("DROP TABLE temp.knowledge_probe")
                    self.fts_enabled = True
            except sqlite3.OperationalError as exc:
                if "no such module" not in str(exc).lower():
                    raise
            if not self.fts_enabled:
                # Existing FTS triggers must not prevent ordinary article writes without FTS5.
                for trigger in ("knowledge_ai", "knowledge_ad", "knowledge_au"):
                    db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
                db.execute("INSERT OR REPLACE INTO knowledge_state VALUES('fts_dirty','1')")
                return
            db.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                    slug UNINDEXED, title, body, category, tags,
                    content='knowledge_articles', content_rowid='id'
                );
                CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge_articles BEGIN
                    INSERT INTO knowledge_fts(rowid,slug,title,body,category,tags)
                    VALUES(new.id,new.slug,new.title,new.body,new.category,new.tags);
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge_articles BEGIN
                    INSERT INTO knowledge_fts(knowledge_fts,rowid,slug,title,body,category,tags)
                    VALUES('delete',old.id,old.slug,old.title,old.body,old.category,old.tags);
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge_articles BEGIN
                    INSERT INTO knowledge_fts(knowledge_fts,rowid,slug,title,body,category,tags)
                    VALUES('delete',old.id,old.slug,old.title,old.body,old.category,old.tags);
                    INSERT INTO knowledge_fts(rowid,slug,title,body,category,tags)
                    VALUES(new.id,new.slug,new.title,new.body,new.category,new.tags);
                END;
            """)
            dirty = db.execute("SELECT value FROM knowledge_state WHERE key='fts_dirty'").fetchone()
            if not had_index or (dirty is not None and dirty[0] == "1"):
                db.execute("INSERT INTO knowledge_fts(knowledge_fts) VALUES('rebuild')")
            db.execute("INSERT OR REPLACE INTO knowledge_state VALUES('fts_dirty','0')")

    @staticmethod
    def _write(db: sqlite3.Connection, article: KnowledgeArticle) -> None:
        values = asdict(article)
        values["tags"] = ",".join(article.tags)
        values["checksum"] = article.checksum
        columns = ",".join(values)
        updates = ",".join(f"{key}=excluded.{key}" for key in values if key != "slug")
        db.execute(
            f"INSERT INTO knowledge_articles({columns}) VALUES({','.join('?' for _ in values)}) "
            f"ON CONFLICT(slug) DO UPDATE SET {updates}, updated_at=CURRENT_TIMESTAMP",
            tuple(values.values()),
        )

    def upsert(self, article: KnowledgeArticle) -> None:
        if not isinstance(article, KnowledgeArticle):
            raise ValueError("expected a KnowledgeArticle")
        with self.connect() as db:
            self._write(db, article)

    def get(self, slug: str) -> KnowledgeArticle | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM knowledge_articles WHERE slug=?", (slug,)).fetchone()
        return None if row is None else self._article(row)

    @staticmethod
    def _page(limit: int, offset: int = 0) -> None:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer between 1 and 500")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer")

    @staticmethod
    def _filters(category: str | None, bookmarked: bool) -> tuple[list[str], list[object]]:
        clauses, parameters = [], []
        if category:
            clauses.append("a.category=?")
            parameters.append(category.strip().lower())
        if bookmarked:
            clauses.append("COALESCE(n.bookmarked,0)=1")
        return clauses, parameters

    def browse(self, limit: int = 100, *, offset: int = 0, category: str | None = None,
               bookmarked: bool = False) -> list[SearchResult]:
        self._page(limit, offset)
        clauses, parameters = self._filters(category, bookmarked)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as db:
            rows = db.execute(
                "SELECT a.*, substr(a.body,1,220) AS excerpt, COALESCE(n.bookmarked,0) AS bookmarked "
                "FROM knowledge_articles a LEFT JOIN knowledge_annotations n ON n.slug=a.slug"
                + where + " ORDER BY a.title COLLATE NOCASE,a.slug LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
        return [self._result(row) for row in rows]

    def search(self, query: str, limit: int = 20, *, offset: int = 0,
               category: str | None = None, bookmarked: bool = False) -> list[SearchResult]:
        self._page(limit, offset)
        if not isinstance(query, str) or len(query) > 512:
            raise ValueError("query must be a string of at most 512 characters")
        tokens = re.findall(r"\w+", query, flags=re.UNICODE)
        if not tokens:
            return []
        if len(tokens) > 32:
            raise ValueError("query must contain at most 32 words")
        clauses, parameters = self._filters(category, bookmarked)
        with self.connect() as db:
            dirty = db.execute("SELECT value FROM knowledge_state WHERE key='fts_dirty'").fetchone()
            use_fts = self.fts_enabled and (dirty is None or dirty[0] == "0")
            if use_fts:
                tables = "knowledge_fts JOIN knowledge_articles a ON a.id=knowledge_fts.rowid"
                excerpt = "snippet(knowledge_fts,2,'[',']',' … ',18)"
                clauses.append("knowledge_fts MATCH ?")
                parameters.append(" AND ".join(f'"{token}"' for token in tokens))
                order = "bm25(knowledge_fts,0.0,4.0,1.0,0.5,2.0),a.slug"
            else:
                tables, excerpt, order = "knowledge_articles a", "substr(a.body,1,220)", "a.title,a.slug"
                for token in tokens:
                    clauses.append("instr(casefold(a.title||' '||a.body||' '||a.category||' '||a.tags),?)>0")
                    parameters.append(token.casefold())
            rows = db.execute(
                f"SELECT a.*, {excerpt} AS excerpt, COALESCE(n.bookmarked,0) AS bookmarked "
                f"FROM {tables} LEFT JOIN knowledge_annotations n ON n.slug=a.slug "
                f"WHERE {' AND '.join(clauses)} ORDER BY {order} LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
        return [self._result(row) for row in rows]

    def categories(self) -> list[str]:
        with self.connect() as db:
            return [row[0] for row in db.execute(
                "SELECT DISTINCT category FROM knowledge_articles ORDER BY category"
            )]

    def count(self) -> int:
        with self.connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM knowledge_articles").fetchone()[0])

    def annotation(self, slug: str) -> dict[str, object]:
        with self.connect() as db:
            if db.execute("SELECT 1 FROM knowledge_articles WHERE slug=?", (slug,)).fetchone() is None:
                raise KeyError(f"knowledge article {slug!r} not found")
            row = db.execute("SELECT bookmarked,note FROM knowledge_annotations WHERE slug=?", (slug,)).fetchone()
        return {"bookmarked": bool(row[0]) if row else False, "note": row[1] if row else ""}

    def annotate(self, slug: str, *, bookmarked: bool, note: str) -> None:
        if type(bookmarked) is not bool or not isinstance(note, str) or len(note) > 100_000 or "\x00" in note:
            raise ValueError("annotation requires a boolean bookmark and a note of at most 100000 characters")
        with self.connect() as db:
            if db.execute("SELECT 1 FROM knowledge_articles WHERE slug=?", (slug,)).fetchone() is None:
                raise KeyError(f"knowledge article {slug!r} not found")
            db.execute(
                "INSERT INTO knowledge_annotations(slug,bookmarked,note) VALUES(?,?,?) "
                "ON CONFLICT(slug) DO UPDATE SET bookmarked=excluded.bookmarked,note=excluded.note",
                (slug, int(bookmarked), note),
            )

    @staticmethod
    def _tags(value: str) -> tuple[str, ...]:
        return tuple(part.strip() for part in _TAG_SPLIT.split(value) if part.strip())

    @classmethod
    def _article(cls, row: sqlite3.Row) -> KnowledgeArticle:
        return KnowledgeArticle(**{
            key: cls._tags(row[key]) if key == "tags" else row[key]
            for key in KnowledgeArticle.__dataclass_fields__
        })

    @classmethod
    def _result(cls, row: sqlite3.Row) -> SearchResult:
        return SearchResult(
            slug=row["slug"], title=row["title"], category=row["category"], tags=cls._tags(row["tags"]),
            snippet=row["excerpt"], source_title=row["source_title"], source_url=row["source_url"],
            source_publisher=row["source_publisher"], reviewed_on=row["reviewed_on"],
            safety_level=row["safety_level"], bookmarked=bool(row["bookmarked"]), license=row["license"],
        )
