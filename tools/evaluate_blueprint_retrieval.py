"""Offline, repeatable passage-retrieval regression evaluation; never calls a model."""

import argparse
import hashlib
import json
import platform
import re
import time
from pathlib import Path

from fieldforge.blueprints.engine import BlueprintRequest
from fieldforge.blueprints.evidence import retrieve_blueprint_evidence
from fieldforge.knowledge.library import KnowledgeLibrary
from fieldforge.knowledge.retrieval import retrieve_evidence


def previous_retrieval(library, request):
    """Frozen pre-passage-index baseline from commit 52ff3e3; do not tune to cases."""
    fields = [request.evidence_query, request.revision_instructions, request.brief,
              request.constraints, request.resources]
    scores, evidence, queries = {}, {}, set()
    for field in fields:
        words = re.findall(r"\w+", field)[:48]
        for offset in range(0, len(words), 24):
            question = " ".join(words[offset:offset + 24])[:512]
            if not question or question in queries:
                continue
            queries.add(question)
            for rank, item in enumerate(retrieve_evidence(library, question, limit=4, passage_chars=1200), 1):
                scores[item.slug] = scores.get(item.slug, 0) + 1 / (20 + rank)
                evidence.setdefault(item.slug, item.as_dict())
    return [evidence[slug] for slug in sorted(evidence, key=lambda slug: (-scores[slug], slug))[:8]]


def metrics(sources, expected):
    ranks = [next((index for index, row in enumerate(sources, 1)
                   if row["slug"] == item["slug"] and item["contains"] in row["passage"]), None) for item in expected]
    return {"expected_passages": len(expected), "found_passages": sum(rank is not None for rank in ranks),
            "recall_at_8": sum(rank is not None for rank in ranks) / len(ranks) if ranks else None,
            "reciprocal_first_rank": 1 / min(rank for rank in ranks if rank is not None) if any(ranks) else 0,
            "correct_empty": not sources if not expected else None, "ranks": ranks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("blueprint_retrieval_cases.json"))
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--literal", action="store_true", help="Exercise the no-FTS5 fallback")
    args = parser.parse_args()
    suite = json.loads(args.cases.read_text(encoding="utf-8"))
    library = KnowledgeLibrary(args.database)
    corpus = []
    with library.connect() as db:
        for row in db.execute("SELECT slug,checksum FROM knowledge_articles ORDER BY slug"):
            corpus.append(tuple(row))
    for case in suite["cases"]:
        for item in case["expected"]:
            article = library.get(item["slug"])
            if article is None or item["contains"] not in article.body:
                parser.error(f"Expected passage missing for {case['id']}; use the matching bundled reference edition.")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"notice": suite["notice"], "platform": platform.platform(), "python": platform.python_version(),
              "corpus_fingerprint": hashlib.sha256(json.dumps(corpus).encode()).hexdigest(),
              "cases_fingerprint": hashlib.sha256(args.cases.read_bytes()).hexdigest(), "article_count": len(corpus),
              "cases": [], "factual_quality": "Not evaluated. Expected passages are regression targets, not exhaustive relevance labels."}
    for case in suite["cases"]:
        request = BlueprintRequest(**case["request"])
        result = {"id": case["id"], "request": case["request"], "expected": case["expected"]}
        for name in ("previous", "passage"):
            start = time.monotonic()
            if name == "previous":
                sources = previous_retrieval(library, request)
                details = {}
            else:
                details = retrieve_blueprint_evidence(library, request, use_fts=not args.literal)
                sources = details.pop("sources")
            result[name] = {**metrics(sources, case["expected"]), "seconds": round(time.monotonic() - start, 4),
                            "sources": sources, "diagnostics": details}
        report["cases"].append(result)
        print(json.dumps({"case": case["id"], "previous": result["previous"]["ranks"],
                          "passage": result["passage"]["ranks"]}), flush=True)
        (args.output / "retrieval-evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["summary"] = {}
    for name in ("previous", "passage"):
        positives = [row[name] for row in report["cases"] if row[name]["expected_passages"]]
        negatives = [row[name] for row in report["cases"] if not row[name]["expected_passages"]]
        report["summary"][name] = {
            "passage_recall_at_8": sum(r["found_passages"] for r in positives) / sum(r["expected_passages"] for r in positives),
            "mean_reciprocal_first_rank": sum(r["reciprocal_first_rank"] for r in positives) / len(positives),
            "correct_empty_cases": sum(r["correct_empty"] for r in negatives), "empty_cases": len(negatives),
            "total_seconds": round(sum(row[name]["seconds"] for row in report["cases"]), 4),
        }
    (args.output / "retrieval-evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
