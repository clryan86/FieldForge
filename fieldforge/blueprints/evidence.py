"""Bounded offline passage search and evidence diagnostics for blueprint makers."""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import unicodedata
from collections import Counter

from fieldforge.knowledge.retrieval import Evidence

MAX_ARTICLES = 10_000
MAX_BYTES = 32 * 1024 * 1024
MAX_PASSAGES = 50_000
STOPWORDS = set("a an and are as at be by can do does for from how i in is it my of on or "
                "should that the their these this to we what when where which who why with "
                "would you your design create build make please need new include using use must".split())


def terms(text):
    folded = unicodedata.normalize("NFKD", text.casefold())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return [word for word in re.findall(r"[^\W_]+", folded) if 1 < len(word) <= 64 and word not in STOPWORDS]


def passages(body, size=1100, overlap=180):
    """Literal character offsets; prefer paragraph/sentence ends without losing text."""
    if type(size) is not int or not 120 <= size <= 1200 or type(overlap) is not int or not 0 <= overlap < size // 2:
        raise ValueError("Invalid passage size or overlap.")
    start = 0
    while start < len(body):
        end = min(start + size, len(body))
        if end < len(body):
            lower = start + size * 2 // 3
            boundaries = [m.end() for m in re.finditer(r"\n\s*\n|[.!?]\s", body[lower:end])]
            if boundaries:
                end = lower + boundaries[-1]
            else:
                while end > lower and body[end - 1].isalnum() and body[end].isalnum():
                    end -= 1
                if end == lower:
                    end = min(start + size, len(body))
        yield start, end, body[start:end]
        if end == len(body):
            break
        next_start = max(start + 1, end - overlap)
        # Do not grow a window to accommodate a very long unbroken token.
        while next_start < end and next_start > 0 and body[next_start - 1].isalnum() and body[next_start].isalnum():
            next_start += 1
        start = next_start


def queries_for(request, instructions=""):
    fields = {
        "evidence keywords": request.evidence_query,
        "requested changes": instructions or request.revision_instructions,
        "brief": request.brief, "constraints": request.constraints, "resources": request.resources,
        "acceptance limits": " ".join(str(row["value"]) for row in request.acceptance_rules
                                       if isinstance(row["value"], str)),
    }
    queries, truncated, empty = [], [], []
    for field, text in fields.items():
        if not text.strip():
            continue
        words = list(dict.fromkeys(terms(text)))
        if not words:
            empty.append(field)
            continue
        if len(words) > 96:
            truncated.append(field)
            # Keep the start and end of a long field visible to retrieval.
            words = words[:48] + words[-48:]
        group = []
        for word in words:
            if group and (len(group) == 24 or len(" ".join(group + [word])) > 480):
                queries.append({"field": field, "terms": group})
                group = []
            group.append(word)
        if group:
            queries.append({"field": field, "terms": group})
    return queries, truncated, empty


class PassageIndex:
    """A disposable snapshot, never a write to the user's library or private notes."""

    def __init__(self, library, checkpoint, *, use_fts=True):
        self.connection = sqlite3.connect(":memory:")
        self.rows, self.articles, self.byte_count = [], 0, 0
        self.fts = False
        try:
            if use_fts:
                try:
                    self.connection.execute("CREATE VIRTUAL TABLE chunks USING fts5(body, tokenize='porter unicode61')")
                    self.fts = True
                except sqlite3.OperationalError as exc:
                    if "no such module" not in str(exc).lower():
                        raise
            with library.connect() as source:
                source.execute("BEGIN")
                for raw in source.execute("SELECT * FROM knowledge_articles ORDER BY slug"):
                    checkpoint("Indexing local source passages")
                    self.articles += 1
                    if self.articles > MAX_ARTICLES:
                        raise ValueError("Blueprint evidence exceeds 10,000 articles; use a smaller reference library.")
                    article = library._article(raw)
                    body_bytes = article.body.encode("utf-8")
                    self.byte_count += len(body_bytes)
                    if self.byte_count > MAX_BYTES:
                        raise ValueError("Blueprint evidence exceeds 32 MiB of source text; use a smaller library.")
                    checksum = hashlib.sha256(body_bytes).hexdigest()
                    if checksum != raw["checksum"]:
                        raise ValueError(f"Stored content checksum mismatch for {article.slug!r}.")
                    for offset, end, passage in passages(article.body):
                        if len(self.rows) >= MAX_PASSAGES:
                            raise ValueError("Blueprint evidence exceeds 50,000 passages; use a smaller library.")
                        if len(self.rows) % 64 == 0:
                            checkpoint("Indexing local source passages")
                        evidence = Evidence(
                            slug=article.slug, title=article.title, passage=passage,
                            start_offset=offset, end_offset=end, checksum=checksum,
                            source_title=article.source_title, source_publisher=article.source_publisher,
                            source_url=article.source_url, reviewed_on=article.reviewed_on,
                            safety_level=article.safety_level, license=article.license,
                        ).as_dict()
                        self.rows.append(evidence)
                        if self.fts:
                            self.connection.execute("INSERT INTO chunks(rowid,body) VALUES(?,?)", (len(self.rows), passage))
            self.connection.commit()
        except BaseException:
            self.close()
            raise

    def close(self):
        self.connection.close()

    def rankings(self, queries, checkpoint):
        if self.fts:
            results = []
            for query in queries:
                checkpoint("Ranking local evidence")
                expression = " OR ".join('"' + word + '"' for word in query["terms"])
                rows = self.connection.execute(
                    "SELECT rowid FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks),rowid LIMIT 40", (expression,))
                results.append([row[0] - 1 for row in rows])
            return results
        # Minimal SQLite fallback: literal Unicode-normalized BM25, no stemming.
        vocabulary = {word for query in queries for word in query["terms"]}
        counters, lengths, document_frequency = [], [], Counter()
        for index, row in enumerate(self.rows):
            if index % 64 == 0:
                checkpoint("Ranking local evidence without FTS5")
            words = terms(row["passage"])
            counter = Counter(word for word in words if word in vocabulary)
            counters.append(counter)
            lengths.append(len(words))
            document_frequency.update(counter.keys())
        average = sum(lengths) / max(1, len(lengths)) or 1
        result = []
        for query in queries:
            checkpoint("Ranking local evidence without FTS5")
            scored = []
            for index, counter in enumerate(counters):
                score = 0
                for word in query["terms"]:
                    frequency = counter[word]
                    if frequency:
                        df = document_frequency[word]
                        idf = math.log(1 + (len(self.rows) - df + 0.5) / (df + 0.5))
                        score += idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * lengths[index] / average))
                if score:
                    scored.append((-score, index))
            result.append([index for _score, index in sorted(scored)[:40]])
        return result


def retrieve_blueprint_evidence(library, request, instructions="", checkpoint=None, *, use_fts=True):
    if not isinstance(instructions, str) or len(instructions) > 4000 or "\x00" in instructions:
        raise ValueError("Evidence change instructions must be at most 4,000 characters.")
    checkpoint = checkpoint or (lambda _message: None)
    checkpoint("Preparing local evidence search")
    queries, truncated, empty = queries_for(request, instructions)
    result = {"method": "none", "article_count": 0, "passage_count": 0,
              "queries": [{"field": row["field"], "query": " ".join(row["terms"])} for row in queries],
              "truncated_fields": truncated, "unmatched_fields": empty, "sources": [],
              "notice": "Query matches are retrieval diagnostics, not proof of source support or completeness."}
    if not queries:
        return result
    index = PassageIndex(library, checkpoint, use_fts=use_fts)
    try:
        rankings = index.rankings(queries, checkpoint)
        # A long field contributes only its best rank per passage, not one vote per chunk.
        votes = {}
        for query, ranked in zip(queries, rankings):
            for rank, number in enumerate(ranked, 1):
                field = query["field"]
                fields = votes.setdefault(number, {})
                fields[field] = max(fields.get(field, 0), 1 / (60 + rank))
        selected, article_counts, used_text, covered = [], Counter(), set(), set()
        remaining = set(votes)
        while remaining and len(selected) < 8:
            checkpoint("Selecting diverse source passages")

            def priority(number):
                fields = votes[number]
                score = sum(fields.values()) + 0.02 * len(set(fields) - covered)
                score /= 1 + article_counts[index.rows[number]["slug"]]
                return (-score, number)

            number = min(remaining, key=priority)
            remaining.remove(number)
            row = index.rows[number]
            text_key = hashlib.sha256(" ".join(row["passage"].split()).casefold().encode()).hexdigest()
            if article_counts[row["slug"]] >= 2 or text_key in used_text:
                continue
            redundant = False
            for old in selected:
                if old["slug"] == row["slug"]:
                    overlap = max(0, min(old["end_offset"], row["end_offset"]) - max(old["start_offset"], row["start_offset"]))
                    if overlap > 0.35 * min(len(old["passage"]), len(row["passage"])):
                        redundant = True
                        break
            if redundant:
                continue
            fields = sorted(votes[number])
            selected.append({"id": f"S{len(selected) + 1}", **row,
                             "retrieval_fields": fields})
            covered.update(fields)
            article_counts[row["slug"]] += 1
            used_text.add(text_key)
        result.update(method="FTS5 BM25 / Porter + field rank fusion" if index.fts else "Literal BM25 + field rank fusion",
                      article_count=index.articles, passage_count=len(index.rows), sources=selected,
                      unmatched_fields=sorted(set(empty) | ({q["field"] for q in queries} - covered)))
        return result
    finally:
        index.close()
