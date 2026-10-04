"""Personal, version-aware links from learning goals to installed article records.

Links do not endorse sources, verify learning or copy article/annotation content.
Missing sources remain visible. Only whole-database backups carry these links.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterator

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary

if TYPE_CHECKING:
    from fieldforge.knowledge.pathways import LearningCatalog

MAX_LINKS_PER_GOAL = 50
MAX_LINKS = 5000
NOTICE = (
    "These are your reading choices, not reviewed curriculum links or proof of competence. "
    "Linking never marks a goal practiced or changes an article's safety/review labels. "
    "Imported PDF text still has its original extraction limitations."
)
STATES = {"current": "Saved version unchanged", "changed": "Source changed — check again",
          "missing": "Article not installed"}
_VERSION_FIELDS = tuple(key for key in KnowledgeArticle.__dataclass_fields__ if key != "body") + ("checksum",)
_FIELDS = {"id", "goal_slug", "article_slug", "version", "saved_title", "revision", "linked_at"}


def _fingerprint(row) -> str:
    """Compare stored body hash + metadata, not timestamps or private annotations."""
    return hashlib.sha256(json.dumps({key: row[key] for key in _VERSION_FIELDS},
                                    ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _digest(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid source version; preview the article first")


def _id(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("select a valid saved reading link")


@dataclass(frozen=True)
class ArticlePreview:
    article: KnowledgeArticle
    version: str


@dataclass(frozen=True)
class ReadingLink:
    id: int
    goal_slug: str
    article_slug: str
    version: str
    saved_title: str
    revision: int
    linked_at: str
    state: str
    current_title: str


class ReadingConflict(ValueError):
    """The source or association changed; refresh rather than overwrite blindly."""


class ReadingLinks:
    def __init__(self, library: KnowledgeLibrary, catalog: LearningCatalog) -> None:
        self.library, self.catalog = library, catalog

    @staticmethod
    def initialize(db: sqlite3.Connection) -> None:
        """Called inside PathwayStore's initialization transaction; no separate commit."""
        marker = db.execute("SELECT value FROM knowledge_state WHERE key='reading_links_schema'").fetchone()
        table = db.execute("SELECT type FROM sqlite_master WHERE name='pathway_reading_links'").fetchone()
        if marker is not None:
            if marker[0] != "1" or table is None or table[0] != "table":
                raise ValueError("unsupported reading-link schema; use a compatible FieldForge build")
            if {row[1] for row in db.execute("PRAGMA table_info(pathway_reading_links)")} != _FIELDS:
                raise ValueError("unrecognized reading-link columns; no changes made")
        elif table is not None:
            raise ValueError("unversioned reading links found; no changes made")
        else:
            # Deliberately no cascading FK: a missing/deleted article must remain
            # visible as a missing source instead of erasing the user's reading plan.
            db.execute("""CREATE TABLE pathway_reading_links(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_slug TEXT NOT NULL, article_slug TEXT NOT NULL,
                version TEXT NOT NULL, saved_title TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision>0), linked_at TEXT NOT NULL,
                UNIQUE(goal_slug,article_slug)
            )""")
            db.execute("INSERT INTO knowledge_state VALUES('reading_links_schema','1')")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        path = self.library.database_path.resolve()
        db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=0.25)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _preview(db: sqlite3.Connection, slug: str) -> ArticlePreview:
        if not isinstance(slug, str) or not slug or len(slug) > 200 or "\x00" in slug:
            raise ValueError("select an installed article")
        row = db.execute("SELECT * FROM knowledge_articles WHERE slug=?", (slug,)).fetchone()
        if row is None:
            raise ReadingConflict("Article is no longer installed. Import it or choose another source.")
        article = KnowledgeLibrary._article(row)
        if article.checksum != row["checksum"]:
            raise ValueError("Article body checksum mismatch. Nothing linked; repair or reimport the source.")
        return ArticlePreview(article, _fingerprint(row))

    def preview(self, slug: str) -> ArticlePreview:
        with self.connect() as db:
            return self._preview(db, slug)

    @staticmethod
    def snapshot(db: sqlite3.Connection, goal_slug: str | None = None) -> tuple[ReadingLink, ...]:
        """Metadata/hash comparison only; full body validation occurs on link/open.

        May share the caller's read transaction for consistent progress and source
        availability. No private note bodies or whole article bodies are read here.
        """
        columns = ",".join(f"a.{key} AS source_{key}" for key in _VERSION_FIELDS)
        where = " WHERE l.goal_slug=?" if goal_slug is not None else ""
        parameters = (goal_slug, MAX_LINKS + 1) if goal_slug is not None else (MAX_LINKS + 1,)
        rows = db.execute(f"SELECT l.*,{columns} FROM pathway_reading_links l "
                          "LEFT JOIN knowledge_articles a ON a.slug=l.article_slug" + where +
                          " ORDER BY l.id LIMIT ?", parameters).fetchall()
        if len(rows) > MAX_LINKS:
            raise ValueError("reading links exceed the supported limit; no partial list shown")
        result = []
        for row in rows:
            source = {key: row['source_' + key] for key in _VERSION_FIELDS}
            state = "missing" if source["slug"] is None else (
                "current" if _fingerprint(source) == row["version"] else "changed")
            result.append(ReadingLink(**{key: row[key] for key in _FIELDS}, state=state,
                                      current_title=source["title"] or row["saved_title"]))
        return tuple(result)

    def list(self, goal_slug: str) -> tuple[ReadingLink, ...]:
        self.catalog.get(goal_slug)
        with self.connect() as db:
            return self.snapshot(db, goal_slug)

    @staticmethod
    def _check(db: sqlite3.Connection, link_id: int, revision: int) -> sqlite3.Row:
        _id(link_id)
        _id(revision)
        row = db.execute("SELECT * FROM pathway_reading_links WHERE id=?", (link_id,)).fetchone()
        if row is None or row["revision"] != revision:
            raise ReadingConflict("This reading link changed or was removed in another window. Refresh and try again.")
        return row

    def link(self, goal_slug: str, article_slug: str, *, expected_version: str) -> ReadingLink:
        goal = self.catalog.get(goal_slug)
        _digest(expected_version)
        if article_slug in goal.articles:
            raise ValueError("This source is already linked by the built-in map; no duplicate personal link needed.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            preview = self._preview(db, article_slug)
            if preview.version != expected_version:
                raise ReadingConflict("Article changed since preview. Preview it again before linking.")
            old = db.execute("SELECT * FROM pathway_reading_links WHERE goal_slug=? AND article_slug=?",
                             (goal_slug, article_slug)).fetchone()
            if old is not None:
                if old["version"] != expected_version:
                    raise ReadingConflict("A different source version is already linked. Use Update link after checking the current text.")
            else:
                count = db.execute("SELECT COUNT(*) FROM pathway_reading_links WHERE goal_slug=?", (goal_slug,)).fetchone()[0]
                total = db.execute("SELECT COUNT(*) FROM pathway_reading_links").fetchone()[0]
                if count >= MAX_LINKS_PER_GOAL or total >= MAX_LINKS:
                    raise ValueError("reading-link limit reached; remove unused links before adding more")
                db.execute("INSERT INTO pathway_reading_links(goal_slug,article_slug,version,saved_title,revision,linked_at) "
                           "VALUES(?,?,?,?,1,?)", (goal_slug, article_slug, preview.version, preview.article.title,
                                                   datetime.now(timezone.utc).isoformat(timespec="seconds")))
            return next(link for link in self.snapshot(db, goal_slug) if link.article_slug == article_slug)

    def update(self, link_id: int, *, expected_revision: int, expected_version: str) -> ReadingLink:
        _digest(expected_version)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self._check(db, link_id, expected_revision)
            self.catalog.get(old["goal_slug"])
            preview = self._preview(db, old["article_slug"])
            if preview.version != expected_version:
                raise ReadingConflict("Article changed again since preview. Preview its current text before updating the link.")
            if old["version"] != preview.version:
                db.execute("UPDATE pathway_reading_links SET version=?,saved_title=?,revision=revision+1,linked_at=? WHERE id=?",
                           (preview.version, preview.article.title, datetime.now(timezone.utc).isoformat(timespec="seconds"), link_id))
            return next(link for link in self.snapshot(db, old["goal_slug"]) if link.id == link_id)

    def remove(self, link_id: int, *, expected_revision: int) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check(db, link_id, expected_revision)
            db.execute("DELETE FROM pathway_reading_links WHERE id=?", (link_id,))

    def open_link(self, link_id: int, *, expected_revision: int) -> KnowledgeArticle:
        with self.connect() as db:
            db.execute("BEGIN")
            link = self._check(db, link_id, expected_revision)
            preview = self._preview(db, link["article_slug"])
            if preview.version != link["version"]:
                raise ReadingConflict("Linked source changed. Use Manage reading links to inspect and explicitly update it.")
            return preview.article
