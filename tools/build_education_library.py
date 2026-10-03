"""Compile the checked-in education lessons into offline knowledge packs.

Run from the repository root: python -m tools.build_education_library
This maintainer command makes no network requests and preserves other articles.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fieldforge.knowledge.library import KnowledgeArticle

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "fieldforge-education-"
LICENSE = "CC BY-SA 4.0; https://creativecommons.org/licenses/by-sa/4.0/"
NOTICE = (
    "Original AI-assisted FieldForge lesson draft. Not independently reviewed by an educator. "
    "Activities and answer keys are local teaching examples, not a validated curriculum. "
    "The references supply background; their authors have not approved these lessons."
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def envelope(articles):
    data = {"articles": sorted(articles, key=lambda row: row["slug"]), "annotations": []}
    return {"format": "fieldforge-knowledge", "version": 1, "algorithm": "sha256",
            "checksum": digest(data), "data": data}


def compile_lessons(source):
    lessons = source["lessons"]
    by_id = {lesson["id"]: lesson for lesson in lessons}
    if len(by_id) != len(lessons):
        raise ValueError("duplicate education lesson ID")
    seen = set()
    articles, catalog = [], []
    for lesson in lessons:
        lesson_id = lesson["id"]
        if any(item not in seen for item in lesson["prerequisites"]):
            raise ValueError("prerequisites must refer to earlier lessons")
        seen.add(lesson_id)
        if not lesson["practice"] or len(lesson["practice"]) != len(lesson["answers"]):
            raise ValueError("each practice item needs an answer or assessment guide")
        references = [source["references"][key] for key in lesson["references"]]
        prerequisite_text = "; ".join(
            f"{item}: {by_id[item]['title']}" for item in lesson["prerequisites"]
        ) or "None. Begin with the learner's existing knowledge."
        def numbered(rows):
            return "\n".join(f"{i}. {v}" for i, v in enumerate(rows, 1))
        body = "\n\n".join([
            lesson["title"], NOTICE,
            f"LESSON {lesson_id} | {lesson['track']}\nAudience: {lesson['audience']}",
            "PREREQUISITES\n" + prerequisite_text,
            "LEARNING GOAL\n" + lesson["goal"],
            "MATERIALS\n" + lesson["materials"],
            "LESSON AND WORKED EXAMPLES\n" + "\n\n".join(lesson["lesson"]),
            "PRACTICE\n" + numbered(lesson["practice"]),
            "ANSWERS AND CHECKS\n" + numbered(lesson["answers"]),
            "ADAPT AND CONTINUE\n" + lesson["adaptation"],
            "BACKGROUND REFERENCES\n" + "\n".join(
                f"{item['title']} ({item['publisher']}). {item['url']}\n"
                f"Scope: {item['scope']}" for item in references
            ),
            "SOURCE AND REUSE\nBy FieldForge (AI-assisted draft). Original education content, "
            f"edition {source['edition']}. No independent review date is asserted.\n"
            f"License for this original lesson: {LICENSE}\n"
            "No third-party textbook text or images are reproduced. External references "
            "retain their own rights and are not bundled. All lesson instructions, practice "
            "and answers above are available offline.",
        ]) + "\n"
        row = {
            "slug": PREFIX + lesson_id, "title": f"Education {lesson_id}: {lesson['title']}",
            "body": body, "category": "education",
            "tags": sorted({"education", "education-foundations", "original-draft",
                            "offline-lesson", lesson["track"], *lesson["tags"]}),
            "source_title": f"FieldForge Education Foundations, edition {source['edition']}",
            "source_url": "https://github.com/clryan86/FieldForge",
            "source_publisher": "FieldForge (AI-assisted draft)", "reviewed_on": "",
            "safety_level": "caution", "license": LICENSE,
            "checksum": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        }
        KnowledgeArticle(**{k: v for k, v in row.items() if k != "checksum"})
        articles.append(row)
        catalog.append({
            "slug": row["slug"], "title": row["title"], "category": "education",
            "origin": "fieldforge-original", "edition": source["edition"],
            "source_file": "fieldforge/content/education/lessons.json",
            "source_url": row["source_url"], "contributors": row["source_publisher"],
            "words": len(body.split()), "body_sha256": row["checksum"],
            "prerequisites": [PREFIX + item for item in lesson["prerequisites"]],
            "references": [item["url"] for item in references],
            "review_status": "unreviewed-ai-assisted-draft",
        })
    return articles, catalog


def build(root=ROOT):
    source = json.loads((root / "fieldforge/content/education/lessons.json").read_text("utf-8"))
    articles, entries = compile_lessons(source)
    packs = root / "fieldforge/content/packs"
    pack = json.loads((packs / "reference-library.json").read_text("utf-8"))
    catalog = json.loads((packs / "catalog.json").read_text("utf-8"))
    if pack["checksum"] != digest(pack["data"]) or pack["data"]["annotations"]:
        raise ValueError("expected an intact reference pack without personal annotations")
    # Only our reserved namespace is regenerated. All existing references stay verbatim.
    combined = [row for row in pack["data"]["articles"] if not row["slug"].startswith(PREFIX)]
    retained = [row for row in catalog["articles"] if not row["slug"].startswith(PREFIX)]
    if {row["slug"]: row["checksum"] for row in combined} != {
        row["slug"]: row["body_sha256"] for row in retained
    }:
        raise ValueError("reference pack and catalog disagree")
    catalog["articles"] = retained + entries
    (packs / "education-foundations.json").write_bytes(canonical(envelope(articles)))
    (packs / "reference-library.json").write_bytes(canonical(envelope(combined + articles)))
    (packs / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"education_added": len(articles), "total_articles": len(combined) + len(articles),
            "education_words": sum(row["words"] for row in entries)}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
