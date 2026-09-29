"""Deterministic, offline passage retrieval for a future local answer engine."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from fieldforge.knowledge.library import KnowledgeArticle, KnowledgeLibrary

_WORDS = re.compile(r"\w+", re.UNICODE)
_STOPWORDS = {"a", "an", "and", "are", "can", "do", "does", "for", "from", "how", "i",
              "in", "is", "it", "my", "of", "on", "or", "should", "the", "to", "what",
              "when", "where", "which", "who", "why", "with"}


@dataclass(frozen=True)
class Evidence:
    slug: str
    title: str
    passage: str
    start_offset: int
    end_offset: int
    checksum: str
    source_title: str
    source_publisher: str
    source_url: str
    reviewed_on: str
    safety_level: str
    license: str

    def as_dict(self) -> dict[str, str | int]:
        return asdict(self)


def _best_passage(article: KnowledgeArticle, terms: set[str], limit: int) -> tuple[int, str, int]:
    """Scan overlapping windows across the full article, with a strict size bound."""
    body = article.body
    best = (0, body[:limit], 0)
    for window_start in range(0, len(body), limit // 2):
        start, end = window_start, min(len(body), window_start + limit)
        # Trim at most a quarter-window to avoid ordinary partial words. A long
        # unbroken token must never grow the output past its context budget.
        while (start < min(end - 1, window_start + limit // 4) and start > 0
               and body[start - 1].isalnum() and body[start].isalnum()):
            start += 1
        while (end > max(start + 1, window_start + limit * 3 // 4) and end < len(body)
               and body[end - 1].isalnum() and body[end].isalnum()):
            end -= 1
        passage = body[start:end]
        score = len({word.casefold() for word in _WORDS.findall(passage)} & terms)
        if score > best[2]:
            best = (start, passage, score)
        if score == len(terms):
            break
    return best


def retrieve_evidence(library: KnowledgeLibrary, question: str, *, limit: int = 5,
                      passage_chars: int = 360) -> list[Evidence]:
    """Return literal source passages; never generate claims or use the network."""
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    if type(passage_chars) is not int or not 120 <= passage_chars <= 1200:
        raise ValueError("passage_chars must be between 120 and 1200")
    if not isinstance(question, str) or len(question) > 512:
        raise ValueError("question must be at most 512 characters")
    words = [word.casefold() for word in _WORDS.findall(question)]
    if not words:
        return []
    if len(words) > 32:
        raise ValueError("question must contain at most 32 words")
    terms = set(words) - _STOPWORDS or set(words)
    # A natural-language question rarely appears word-for-word in one article.
    # Collect matches per term, then favor passages covering more distinct terms.
    candidates: dict[str, tuple[int, int]] = {}
    for term in sorted(terms):
        for rank, hit in enumerate(library.search(term, limit=100)):
            matches, best_rank = candidates.get(hit.slug, (0, rank))
            candidates[hit.slug] = (matches + 1, min(rank, best_rank))
    slugs = sorted(candidates, key=lambda slug: (-candidates[slug][0], candidates[slug][1], slug))
    ranked: list[tuple[int, int, str, Evidence]] = []
    for rank, slug in enumerate(slugs[:100]):
        with library.connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_articles WHERE slug=?", (slug,)
            ).fetchone()
        if row is None:
            continue
        article = library._article(row)
        if row["checksum"] != article.checksum:
            raise ValueError(f"stored content checksum mismatch for {article.slug!r}")
        offset, passage, score = _best_passage(article, terms, passage_chars)
        ranked.append((-score, rank, slug, Evidence(
            slug=article.slug, title=article.title, passage=passage,
            start_offset=offset, end_offset=offset + len(passage),
            checksum=article.checksum, source_title=article.source_title,
            source_publisher=article.source_publisher, source_url=article.source_url,
            reviewed_on=article.reviewed_on, safety_level=article.safety_level,
            license=article.license,
        )))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in ranked[:limit]]
