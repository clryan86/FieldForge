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


def _passages(article: KnowledgeArticle, terms: set[str], limit: int) -> list[tuple[int, str]]:
    """Select short verbatim windows, preserving offsets within the original body."""
    body = article.body
    windows: list[tuple[int, str]] = []
    for match in _WORDS.finditer(body):
        if match.group().casefold() not in terms:
            continue
        start = max(0, match.start() - limit // 3)
        end = min(len(body), start + limit)
        start = max(0, end - limit)
        # Avoid starting or ending mid-word when possible.
        while start > 0 and body[start - 1].isalnum() and body[start].isalnum():
            start -= 1
        while end < len(body) and body[end - 1].isalnum() and body[end].isalnum():
            end += 1
        passage = body[start:end]
        if not any(a <= match.start() < a + len(p) for a, p in windows):
            windows.append((start, passage))
        if len(windows) >= 12:
            break
    return windows or [(0, body[:limit])]


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
    candidates = {}
    for term in sorted(terms)[:12]:
        for hit in library.search(term, limit=100):
            candidates.setdefault(hit.slug, hit)
    ranked: list[tuple[int, int, str, Evidence]] = []
    for rank, candidate in enumerate(candidates.values()):
        article = library.get(candidate.slug)
        if article is None:
            continue
        with library.connect() as connection:
            stored = connection.execute(
                "SELECT checksum FROM knowledge_articles WHERE slug=?", (article.slug,)
            ).fetchone()
        if stored is None or stored[0] != article.checksum:
            raise ValueError(f"stored content checksum mismatch for {article.slug!r}")
        for offset, passage in _passages(article, terms, passage_chars):
            score = len({word.casefold() for word in _WORDS.findall(passage)} & terms)
            ranked.append((-score, rank, f"{candidate.slug}:{offset:010d}", Evidence(
                slug=article.slug, title=article.title, passage=passage,
                start_offset=offset, end_offset=offset + len(passage),
                checksum=article.checksum, source_title=article.source_title,
                source_publisher=article.source_publisher, source_url=article.source_url,
                reviewed_on=article.reviewed_on, safety_level=article.safety_level,
                license=article.license,
            )))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    result: list[Evidence] = []
    seen: set[str] = set()
    for _, _, _, evidence in ranked:
        if evidence.slug in seen:
            continue
        result.append(evidence)
        seen.add(evidence.slug)
        if len(result) == limit:
            break
    return result
