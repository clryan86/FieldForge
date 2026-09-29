"""SQLite FTS-backed offline knowledge library.

The knowledge subsystem deliberately has no network dependencies. Articles carry
provenance and review metadata so emergency guidance can be audited and updated.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

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

    def __post_init__(self) -> None:
        if not self.slug.strip() or not self.title.strip() or not self.body.strip():
            raise ValueError("slug, title, and body are required")
        if self.safety_level not in {"reference", "caution", "high_stakes"}:
            raise ValueError("invalid safety_level")

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


class KnowledgeLibrary:
    """Durable, local-only article storage with SQLite full-text search."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    category TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '',
                    source_title TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    source_publisher TEXT NOT NULL DEFAULT '',
                    reviewed_on TEXT NOT NULL DEFAULT '',
                    safety_level TEXT NOT NULL DEFAULT 'reference',
                    checksum TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                    slug UNINDEXED, title, body, category, tags,
                    content='knowledge_articles', content_rowid='id'
                );
                CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge_articles BEGIN
                    INSERT INTO knowledge_fts(rowid, slug, title, body, category, tags)
                    VALUES (new.id, new.slug, new.title, new.body, new.category, new.tags);
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge_articles BEGIN
                    INSERT INTO knowledge_fts(knowledge_fts, rowid, slug, title, body, category, tags)
                    VALUES('delete', old.id, old.slug, old.title, old.body, old.category, old.tags);
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge_articles BEGIN
                    INSERT INTO knowledge_fts(knowledge_fts, rowid, slug, title, body, category, tags)
                    VALUES('delete', old.id, old.slug, old.title, old.body, old.category, old.tags);
                    INSERT INTO knowledge_fts(rowid, slug, title, body, category, tags)
                    VALUES (new.id, new.slug, new.title, new.body, new.category, new.tags);
                END;
                """
            )

    def upsert(self, article: KnowledgeArticle) -> None:
        tags = ",".join(sorted({tag.strip().lower() for tag in article.tags if tag.strip()}))
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO knowledge_articles
                (slug,title,body,category,tags,source_title,source_url,source_publisher,
                 reviewed_on,safety_level,checksum)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(slug) DO UPDATE SET
                    title=excluded.title, body=excluded.body, category=excluded.category,
                    tags=excluded.tags, source_title=excluded.source_title,
                    source_url=excluded.source_url, source_publisher=excluded.source_publisher,
                    reviewed_on=excluded.reviewed_on, safety_level=excluded.safety_level,
                    checksum=excluded.checksum, updated_at=CURRENT_TIMESTAMP
                """,
                (
                    article.slug.strip(), article.title.strip(), article.body.strip(),
                    article.category.strip().lower(), tags, article.source_title.strip(),
                    article.source_url.strip(), article.source_publisher.strip(),
                    article.reviewed_on.strip(), article.safety_level, article.checksum,
                ),
            )

    def get(self, slug: str) -> KnowledgeArticle | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM knowledge_articles WHERE slug = ?", (slug,)
            ).fetchone()
        return None if row is None else self._article(row)

    def search(self, query: str, limit: int = 20) -> list[SearchResult]:
        query = query.strip()
        if not query:
            return []
        if limit <= 0:
            raise ValueError("limit must be positive")
        # Quote tokens so punctuation in user input cannot become FTS operators.
        tokens = [token for token in re.findall(r"[\w-]+", query, flags=re.UNICODE) if token]
        if not tokens:
            return []
        match = " AND ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT a.*, snippet(knowledge_fts, 2, '[', ']', ' … ', 18) AS excerpt
                FROM knowledge_fts
                JOIN knowledge_articles a ON a.id = knowledge_fts.rowid
                WHERE knowledge_fts MATCH ?
                ORDER BY bm25(knowledge_fts, 2.0, 1.0, 0.6, 0.8)
                LIMIT ?
                """,
                (match, limit),
            ).fetchall()
        return [
            SearchResult(
                slug=row["slug"], title=row["title"], category=row["category"],
                tags=self._tags(row["tags"]), snippet=row["excerpt"],
                source_title=row["source_title"], source_publisher=row["source_publisher"],
                reviewed_on=row["reviewed_on"], safety_level=row["safety_level"],
            )
            for row in rows
        ]

    def count(self) -> int:
        with self.connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM knowledge_articles").fetchone()[0])

    @staticmethod
    def _tags(value: str) -> tuple[str, ...]:
        return tuple(part.strip() for part in _TAG_SPLIT.split(value) if part.strip())

    @classmethod
    def _article(cls, row: sqlite3.Row) -> KnowledgeArticle:
        return KnowledgeArticle(
            slug=row["slug"], title=row["title"], body=row["body"],
            category=row["category"], tags=cls._tags(row["tags"]),
            source_title=row["source_title"], source_url=row["source_url"],
            source_publisher=row["source_publisher"], reviewed_on=row["reviewed_on"],
            safety_level=row["safety_level"],
        )
