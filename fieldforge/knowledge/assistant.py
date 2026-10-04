"""Read-only question-to-reference search. No model, network, or saved question log.

Results are exact local excerpts, never synthesized answers. Lexical overlap is
not evidence that a source answers a question or that its guidance is correct.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import time
import unicodedata
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary

MAX_QUESTION = 512
MAX_TERMS = 24
MAX_CANDIDATES = 64
MAX_BODY_BYTES = 8_000_000  # The existing article model permits 2M Unicode characters.
MAX_READ_BYTES = 16 * 1024 * 1024
MAX_EXCERPT = 2400
NOTICE = (
    "Source excerpts, not an AI-generated answer. Keyword matches do not establish relevance, "
    "truth, completeness, or safety. Read the full sources and their conditions. "
    "Source/review labels are author-supplied, not independently verified."
)
# Only English conversational filler is removed. Negations and numbers are NOT
# removed, and the original question is always displayed. No stemming/synonyms.
_FILLER = frozenset(
    "a an the i me my we our you your it its is are was were be been am "
    "how what which when where why who can could should would will do does did "
    "to of for in on at by and or with as about this that these those "
    "please tell explain help need want find some any".split()
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_BREAK = re.compile(r"\n[ \t\r]*\n")


class SearchCancelled(Exception):
    """The caller cancelled an in-progress lookup; discard its results."""


def _fold(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(char))


def question_terms(question: str) -> tuple[str, ...]:
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION:
        raise ValueError("enter a question of 1 to 512 characters")
    if any(ord(char) < 32 and char not in "\t\r\n" for char in question):
        raise ValueError("question contains unsupported control characters")
    terms = tuple(dict.fromkeys(word for word in _WORD.findall(_fold(question))
                                if word not in _FILLER))
    if not terms:
        raise ValueError("add a topic, such as water storage or a power budget")
    if len(terms) > MAX_TERMS or any(len(term) > 80 for term in terms):
        raise ValueError("use at most 24 distinct search words, each at most 80 characters")
    return terms


@dataclass(frozen=True)
class Reference:
    label: str
    article: KnowledgeArticle
    matched_terms: tuple[str, ...]
    excerpt: str
    start: int | None
    end: int | None
    line_start: int | None
    line_end: int | None
    excerpt_notice: str

    def as_dict(self) -> dict[str, object]:
        # Exclude full article bodies from CLI/clipboard output, but retain exact
        # source snapshots in memory so an update cannot silently change a quote.
        article = asdict(self.article)
        article.pop("body")
        return {
            "label": self.label, "article": article, "body_sha256": self.article.checksum,
            "matched_terms": self.matched_terms, "excerpt": self.excerpt,
            "start": self.start, "end": self.end, "line_start": self.line_start,
            "line_end": self.line_end, "excerpt_notice": self.excerpt_notice,
        }


@dataclass(frozen=True)
class ReferenceReport:
    question: str
    terms: tuple[str, ...]
    references: tuple[Reference, ...]
    status: str
    search_mode: str
    library_count: int
    category: str | None
    candidates_checked: int
    limited: bool
    warnings: tuple[str, ...]
    captured_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "question": self.question, "terms": self.terms,
            "references": [reference.as_dict() for reference in self.references],
            "status": self.status, "search_mode": self.search_mode,
            "library_count": self.library_count, "category": self.category,
            "candidates_checked": self.candidates_checked, "limited": self.limited,
            "warnings": self.warnings, "captured_at": self.captured_at,
            "generation": "none", "notice": NOTICE,
        }


def _paragraphs(body: str):
    start = 0
    for boundary in _BREAK.finditer(body):
        yield start, boundary.start()
        start = boundary.end()
    yield start, len(body)


def _reference(article: KnowledgeArticle, terms: tuple[str, ...], pattern: re.Pattern,
               check) -> tuple[Reference | None, tuple[int, int, int]]:
    title_hits = set(pattern.findall(_fold(article.title)))
    body_hits: set[str] = set()
    best = None
    before = None
    previous = None
    following = None
    best_count = 0
    best_quality = (False, 0)
    # Keep only the best matching paragraph and its neighbors, not a list of all
    # paragraphs or token sets for a potentially large imported article.
    for start, end in _paragraphs(article.body):
        check()
        if start == end:
            continue
        hits = set(pattern.findall(_fold(article.body[start:end])))
        body_hits.update(hits)
        if best is not None and following is None:
            following = (start, end)
        heading = article.body[start:end].split("\n", 1)[0].strip().casefold()
        attribution = heading in {"source", "sources", "references", "origin", "bibliography"}
        quality = (not attribution, len(hits))
        if hits and quality > best_quality:
            before, best, following = previous, (start, end), None
            best_count, best_quality = len(hits), quality
        previous = (start, end)
    hits = title_hits | body_hits
    if not hits:
        return None, (0, 0, 0)
    notice = "Title match only; open the full source to assess relevance."
    excerpt = ""
    start = end = line_start = line_end = None
    if best is not None:
        start, end = best
        if end - start <= MAX_EXCERPT:
            # Preserve whole neighboring paragraphs where they fit. Never turn a
            # clipped sentence into an apparent complete instruction.
            if before is not None and end - before[0] <= MAX_EXCERPT:
                start = before[0]
            if following is not None and following[1] - start <= MAX_EXCERPT:
                end = following[1]
            excerpt = article.body[start:end]
            line_start = article.body.count("\n", 0, start) + 1
            line_end = article.body.count("\n", 0, max(start, end - 1)) + 1
            notice = "Exact local excerpt. Additional conditions may occur elsewhere in the full source."
        else:
            notice = "Matching paragraph is too long to excerpt safely; open the full source."
            # No quote or line citation is fabricated for an omitted paragraph.
            start = end = None
    reference = Reference("", article, tuple(term for term in terms if term in hits),
                          excerpt, start, end, line_start, line_end, notice)
    return reference, (len(hits) + 2 * len(title_hits), len(hits), best_count)


class ReferenceAssistant:
    """Stateless, bounded retrieval in one SQLite read snapshot per question."""

    def __init__(self, database_path: str | Path, *, use_fts: bool = True) -> None:
        self.database_path = Path(database_path).expanduser()
        if type(use_fts) is not bool:
            raise ValueError("use_fts must be a boolean")
        self.use_fts = use_fts

    def ask(self, question: str, *, category: str | None = None, limit: int = 5,
            cancel: Event | None = None, timeout: float = 5.0) -> ReferenceReport:
        terms = question_terms(question)
        if type(limit) is not int or not 1 <= limit <= 8:
            raise ValueError("result limit must be an integer from 1 to 8")
        if category is not None:
            if not isinstance(category, str) or len(category) > 100 or "\x00" in category:
                raise ValueError("category must be text of at most 100 characters")
            category = category.strip().lower() or None
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError("timeout must be between 0 and 30 seconds")
        cancelled = cancel if cancel is not None else Event()
        deadline = time.monotonic() + timeout

        def check():
            if cancelled.is_set():
                raise SearchCancelled("search cancelled")
            if time.monotonic() >= deadline:
                raise TimeoutError("search timed out; use a narrower question or category")

        check()
        if not self.database_path.is_file():
            raise FileNotFoundError("library database not found; open FieldForge and load articles first")
        pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(term) for term in terms) + r")(?!\w)")
        uri = self.database_path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=min(timeout, 0.25))) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            db.set_progress_handler(lambda: int(cancelled.is_set() or time.monotonic() >= deadline), 1000)
            try:
                db.execute("BEGIN")
                return self._search(db, question, terms, pattern, category, limit, check)
            except sqlite3.OperationalError:
                check()  # Distinguish explicit cancellation/time limit from a database error.
                raise
            finally:
                db.set_progress_handler(None, 0)

    def _search(self, db, question, terms, pattern, category, limit, check):
        count = db.execute("SELECT COUNT(*) FROM knowledge_articles").fetchone()[0]
        state = db.execute("SELECT value FROM knowledge_state WHERE key='fts_dirty'").fetchone()
        has_index = db.execute("SELECT 1 FROM sqlite_master WHERE name='knowledge_fts'").fetchone()
        fts = self.use_fts and has_index is not None and (state is None or state[0] == "0")
        parameters: list[object] = []
        condition = ""
        if category:
            condition = " AND a.category=?"
            parameters.append(category)
        warnings: list[str] = []
        candidates = None
        if fts:
            match = "{title body} : (" + " OR ".join(f'"{term}"' for term in terms) + ")"
            try:
                candidates = db.execute(
                    "SELECT a.id,length(CAST(a.body AS BLOB)) AS size FROM knowledge_fts "
                    "JOIN knowledge_articles a ON a.id=knowledge_fts.rowid "
                    "WHERE knowledge_fts MATCH ?" + condition +
                    " ORDER BY bm25(knowledge_fts,0.0,4.0,1.0,0.0,0.0),a.slug LIMIT ?",
                    (match, *parameters, MAX_CANDIDATES + 1),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                # A missing FTS module is a portability issue. Corruption, syntax,
                # permission, and other errors must NOT be disguised as no hits.
                if "no such module: fts5" not in str(exc).lower():
                    raise
                fts = False
        if candidates is None:
            def matches(title, body):
                # A local SQL function; no writes, shell, URLs, or model calls.
                return bool(pattern.search(_fold(title)) or pattern.search(_fold(body)))

            db.create_function("ask_matches", 2, matches)
            candidates = db.execute(
                "SELECT a.id,length(CAST(a.body AS BLOB)) AS size FROM knowledge_articles a "
                "WHERE ask_matches(a.title,a.body)" + condition + " ORDER BY a.id LIMIT ?",
                (*parameters, MAX_CANDIDATES + 1),
            ).fetchall()
            warnings.append("Literal fallback search is in use; it can be slower and rank differently from FTS5.")
        limited = len(candidates) > MAX_CANDIDATES
        checked = used_bytes = 0
        ranked = []
        for candidate in candidates[:MAX_CANDIDATES]:
            check()
            size = candidate["size"]
            if size > MAX_BODY_BYTES or used_bytes + size > MAX_READ_BYTES:
                limited = True
                continue
            used_bytes += size
            checked += 1
            row = db.execute("SELECT * FROM knowledge_articles WHERE id=?", (candidate["id"],)).fetchone()
            try:
                article = KnowledgeLibrary._article(row)
                if article.checksum != row["checksum"]:
                    raise ValueError("content checksum mismatch")
            except (ValueError, TypeError, UnicodeError):
                warnings.append("A candidate with invalid metadata or a content checksum mismatch was skipped.")
                continue
            reference, score = _reference(article, terms, pattern, check)
            if reference is not None:
                ranked.append((score, reference))
        check()
        ranked.sort(key=lambda item: (-item[0][0], -item[0][1], -item[0][2], item[1].article.slug))
        references = tuple(Reference(f"S{index}", ref.article, ref.matched_terms, ref.excerpt,
                                     ref.start, ref.end, ref.line_start, ref.line_end, ref.excerpt_notice)
                           for index, (_, ref) in enumerate(ranked[:limit], 1))
        if limited:
            warnings.append("Candidate or byte limits were reached. Results are partial; narrow the question/category.")
        if any(ref.article.safety_level in {"caution", "high_stakes"} for ref in references):
            warnings.append("Caution/high-stakes source labels are present. Excerpts are not personalized advice or an operating procedure.")
        if any(not ref.article.reviewed_on for ref in references):
            warnings.append("At least one displayed source has no recorded review date.")
        status = "related_sources" if references else ("empty_library" if count == 0 else "no_matches")
        return ReferenceReport(question, terms, references, status, "fts5" if fts else "literal",
                               count, category, checked, limited, tuple(dict.fromkeys(warnings)),
                               datetime.now(timezone.utc).isoformat(timespec="seconds"))


def render_report(report: ReferenceReport) -> str:
    lines = ["FIELDFORGE — LOCAL SOURCE REPORT", NOTICE, "", "Question: " + report.question,
             "Search words: " + ", ".join(report.terms),
             "Category: " + (report.category or "All categories"),
             f"Captured: {report.captured_at} | Search: {report.search_mode}", ""]
    if not report.references:
        lines.append("No articles installed. Load a starter library or import a knowledge pack."
                     if report.status == "empty_library" else
                     "No matching sources found in this search. Try other wording or clear the category. "
                     "This does not prove the information is absent from the library.")
    for warning in report.warnings:
        lines.append("Notice: " + warning)
    for ref in report.references:
        article = ref.article
        missing = [term for term in report.terms if term not in ref.matched_terms]
        lines += ["", f"[{ref.label}] {article.title}", f"Article ID: {article.slug}",
                  "Matched words: " + ", ".join(ref.matched_terms),
                  "Words not matched in this source: " + (", ".join(missing) or "None"),
                  f"Source: {article.source_title or 'Not supplied'}",
                  f"Publisher: {article.source_publisher or 'Not supplied'}",
                  f"Source URL (not fetched): {article.source_url or 'Not supplied'}",
                  f"Review date (author-supplied): {article.reviewed_on or 'Not supplied'}",
                  f"Safety label: {article.safety_level} | Rights: {article.license or 'Unspecified'}",
                  f"Body SHA-256: {article.checksum}", ref.excerpt_notice]
        if ref.excerpt:
            lines += [f"BEGIN EXACT EXCERPT — body lines {ref.line_start}–{ref.line_end}",
                      ref.excerpt, "END EXACT EXCERPT"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Question in quotes; retrieves sources, not generated answers")
    parser.add_argument("--database", type=Path, default=Path(
        os.environ.get("FIELDFORGE_DB", "~/.fieldforge/fieldforge.db")
    ).expanduser())
    parser.add_argument("--category")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="Print references and exact offsets as JSON")
    args = parser.parse_args(argv)
    try:
        report = ReferenceAssistant(args.database).ask(args.question, category=args.category, limit=args.limit)
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) if args.json else render_report(report))
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
