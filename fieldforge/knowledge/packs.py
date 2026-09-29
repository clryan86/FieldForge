"""Bounded, integrity-checked, transactional exchange of offline knowledge.

Hashes detect accidental corruption, not an authentic publisher or safe advice.
Personal notes/bookmarks are excluded unless explicitly requested.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from fieldforge.knowledge.library import KnowledgeArticle, KnowledgeLibrary

MAX_PACK_BYTES = 32 * 1024 * 1024
MAX_ARTICLES = 10_000
_FORMAT = "fieldforge-knowledge"


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def export_pack(library: KnowledgeLibrary, destination: str | Path, *,
                include_personal: bool = False) -> Path:
    """Export a consistent snapshot. The destination is atomically replaced."""
    path = Path(destination).expanduser()
    if path.resolve() == library.database_path.resolve() or (
        path.exists() and path.samefile(library.database_path)
    ):
        raise ValueError("cannot overwrite the live database with a knowledge pack")
    with library.connect() as db:
        db.execute("BEGIN")
        count = db.execute("SELECT COUNT(*) FROM knowledge_articles").fetchone()[0]
        if count > MAX_ARTICLES:
            raise ValueError("library exceeds the 10000-article pack limit; use a database backup")
        articles = []
        budget = 0
        for row in db.execute("SELECT * FROM knowledge_articles ORDER BY slug"):
            article = library._article(row)
            if article.checksum != row["checksum"]:
                raise ValueError(f"stored content checksum mismatch: {article.slug}")
            record = {**asdict(article), "checksum": article.checksum}
            budget += len(_canonical(record))
            if budget > MAX_PACK_BYTES:
                raise ValueError("knowledge pack exceeds the 32 MiB limit")
            articles.append(record)
        annotations = []
        if include_personal:
            for row in db.execute("SELECT slug,bookmarked,note FROM knowledge_annotations ORDER BY slug"):
                annotation = dict(row)
                annotation["bookmarked"] = bool(annotation["bookmarked"])
                budget += len(_canonical(annotation))
                if budget > MAX_PACK_BYTES:
                    raise ValueError("knowledge pack exceeds the 32 MiB limit")
                annotations.append(annotation)
    data = {"articles": articles, "annotations": annotations}
    payload = {"format": _FORMAT, "version": 1, "algorithm": "sha256",
               "checksum": _digest(data), "data": data}
    encoded = _canonical(payload)
    if len(encoded) > MAX_PACK_BYTES:
        raise ValueError("knowledge pack exceeds the 32 MiB limit; use a database backup")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".fieldforge-", suffix=".tmp",
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def import_pack(library: KnowledgeLibrary, source: str | Path, *, replace: bool = False,
                restore_personal: bool = False) -> dict[str, int]:
    """Validate every record first, then commit all records or none.

    Different existing content is never silently replaced. Identical imports are
    idempotent. Restoring personal data requires a separate explicit opt-in.
    """
    with Path(source).expanduser().open("rb") as stream:
        raw = stream.read(MAX_PACK_BYTES + 1)
    if len(raw) > MAX_PACK_BYTES:
        raise ValueError("knowledge pack exceeds the 32 MiB limit")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(payload, dict) or set(payload) != {
            "format", "version", "algorithm", "checksum", "data"
        }:
            raise ValueError("invalid knowledge pack envelope")
        if payload["format"] != _FORMAT or type(payload["version"]) is not int or payload["version"] != 1:
            raise ValueError("unsupported knowledge pack format/version")
        if payload["algorithm"] != "sha256":
            raise ValueError("unsupported checksum algorithm")
        digest = payload["checksum"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid knowledge pack checksum")
        data = payload["data"]
        if not isinstance(data, dict) or set(data) != {"articles", "annotations"}:
            raise ValueError("invalid knowledge pack data")
        if not hmac.compare_digest(_digest(data), digest):
            raise ValueError("knowledge pack integrity check failed")
        rows, notes = data["articles"], data["annotations"]
        if not isinstance(rows, list) or len(rows) > MAX_ARTICLES:
            raise ValueError("articles must be an array of at most 10000 records")
        if not isinstance(notes, list) or len(notes) > len(rows):
            raise ValueError("invalid annotations array")
        if notes and not restore_personal:
            raise ValueError("pack contains private notes/bookmarks; explicitly enable restore_personal")
        articles: list[KnowledgeArticle] = []
        slugs: set[str] = set()
        fields = set(KnowledgeArticle.__dataclass_fields__)
        for row in rows:
            if not isinstance(row, dict) or set(row) != fields | {"checksum"}:
                raise ValueError("invalid article fields")
            if not isinstance(row["tags"], list):
                raise ValueError("article tags must be an array")
            article = KnowledgeArticle(**{key: row[key] for key in fields})
            if row["checksum"] != article.checksum:
                raise ValueError(f"article checksum mismatch: {article.slug}")
            if article.slug in slugs:
                raise ValueError(f"duplicate article slug: {article.slug}")
            slugs.add(article.slug)
            articles.append(article)
        noted: set[str] = set()
        for note in notes:
            if not isinstance(note, dict) or set(note) != {"slug", "bookmarked", "note"}:
                raise ValueError("invalid annotation fields")
            slug = note["slug"]
            if not isinstance(slug, str) or slug not in slugs or slug in noted:
                raise ValueError("annotation must uniquely reference an article in this pack")
            if type(note["bookmarked"]) is not bool or not isinstance(note["note"], str):
                raise ValueError("invalid annotation types")
            if len(note["note"]) > 100_000 or "\x00" in note["note"]:
                raise ValueError("invalid annotation text")
            noted.add(slug)
    except (UnicodeError, TypeError, KeyError, RecursionError) as exc:
        raise ValueError("malformed knowledge pack") from exc

    imported = unchanged = 0
    with library.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for article in articles:
            existing = db.execute("SELECT * FROM knowledge_articles WHERE slug=?", (article.slug,)).fetchone()
            if existing is not None and library._article(existing) == article:
                unchanged += 1
                continue
            if existing is not None and not replace:
                raise ValueError(f"article already exists with different content: {article.slug}")
            library._write(db, article)
            imported += 1
        for note in notes:
            existing = db.execute("SELECT bookmarked,note FROM knowledge_annotations WHERE slug=?",
                                  (note["slug"],)).fetchone()
            if existing is not None and (bool(existing[0]), existing[1]) != (note["bookmarked"], note["note"]) and not replace:
                raise ValueError(f"personal annotation already exists: {note['slug']}")
            db.execute(
                "INSERT INTO knowledge_annotations(slug,bookmarked,note) VALUES(?,?,?) "
                "ON CONFLICT(slug) DO UPDATE SET bookmarked=excluded.bookmarked,note=excluded.note",
                (note["slug"], int(note["bookmarked"]), note["note"]),
            )
    return {"imported": imported, "unchanged": unchanged, "annotations": len(notes)}
