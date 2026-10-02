"""Maintainer-only acquisition of attributed, revision-pinned Wikibooks references.

Networking occurs only when this script is explicitly run. The shipped library
and the application's installer operate on bundled files, never on this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

API = "https://en.wikibooks.org/w/api.php"
LICENSE = "CC BY-SA 4.0; https://creativecommons.org/licenses/by-sa/4.0/"
BOOKS = {
    "survival": ["Outdoor Survival", "Survival"],
    "agriculture": ["Horticulture", "Organic Horticulture", "Gardening", "Sustainable Agriculture"],
    "water-sanitation": ["Drinking Water"],
    "medicine": ["First Aid", "Human Physiology"],
    "science": ["General Biology", "General Chemistry", "Physics Study Guide"],
    "measurement": ["Basic Algebra", "Geometry", "Trigonometry"],
    "engineering": ["Engineering Mechanics", "Statics", "Engineering Tables", "High School Engineering"],
    "manufacturing": ["Woodworking", "Metalworking", "Manufacturing"],
    "energy": ["Circuit Theory", "Electronics"],
    "communications": ["Communication Systems"],
    "computing": ["Computer Networks", "Operating System Design", "Python Programming"],
    "software": ["Software Engineering", "Embedded Systems"],
    "projects": ["Project Management", "Systems Engineering"],
    "education": ["Instructional Design", "Learning Theories"],
}
PRIORITY = {"Horticulture": [
    "Elements of a Garden Location", "Soil Improvement", "Irrigation", "Compost Introduction",
    "The Benefits of Compost", "Hot Composting", "Square Foot Gardening", "No Till Gardening",
    "Seed Saving", "Plant Propagation", "Soil Testing", "Raised Beds",
]}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


class PlainText(HTMLParser):
    """Preserve prose, lists, table cells and math alternative text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        skip = bool(self.stack and self.stack[-1][1]) or tag in {"script", "style"} or bool(
            classes & {"noprint", "navbox", "toc", "mw-editsection", "metadata", "sistersitebox"}
        )
        if tag not in {"img", "br", "hr", "input", "meta", "link", "wbr"}:
            self.stack.append((tag, skip))
        if skip:
            return
        if tag in {"p", "div", "section", "tr", "h1", "h2", "h3", "h4", "h5", "pre"}:
            self.parts.append("\n\n")
        if tag == "li":
            self.parts.append("\n- ")
        if tag in {"td", "th"}:
            self.parts.append(" | ")
        if tag == "br":
            self.parts.append("\n")
        if tag == "img" and attrs.get("alt"):
            self.parts.append(" [Image or formula: " + attrs["alt"] + "] ")

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if tag in {"p", "div", "section", "tr", "h1", "h2", "h3", "h4", "pre"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.stack or not self.stack[-1][1]:
            self.parts.append(data)

    def text(self):
        text = "".join(self.parts).replace("\xa0", " ")
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def fetch(params, cache):
    query = {"format": "json", **params}
    key = hashlib.sha256(canonical(query)).hexdigest()
    path = cache / (key + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    request = urllib.request.Request(
        API + "?" + urllib.parse.urlencode(query),
        headers={"User-Agent": "FieldForgeReferenceBuilder/0.1 (https://github.com/clryan86/FieldForge)"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
            if "error" in data:
                raise ValueError(data["error"])
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            time.sleep(0.15)
            return data
        except (OSError, ValueError):
            if attempt == 3:
                raise
            time.sleep(1 + attempt)


def build(output, cache, per_book):
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    catalog, skipped, seen, all_articles = [], [], set(), []
    for category, books in BOOKS.items():
        for book in books:
            listing = fetch({"action": "query", "list": "allpages", "apprefix": book + "/",
                             "aplimit": 100, "apfilterredir": "nonredirects"}, cache)
            titles = ([book + "/" + title for title in PRIORITY.get(book, [])] + [book] +
                      ([] if book in PRIORITY else [p["title"] for p in listing["query"]["allpages"]]))
            accepted = 0
            for title in titles:
                if accepted >= per_book:
                    break
                if title in seen:
                    continue
                if any(word in title.lower() for word in
                       ("print version", "printable", "/all", "/authors", "/contributors",
                        "/licens", "/cover", "/contents", "/glossary", "/answers",
                        "/appendix", "/assignments", "/formatting", "/further reading",
                        "/book structure", "/for contributors", "/creating python programs/solutions",
                        "(contents)", "/faqs", "/northstar", "/human physiology authors")):
                    continue
                try:
                    parsed = fetch({"action": "parse", "page": title, "prop": "text|revid",
                                    "disableeditsection": 1}, cache)["parse"]
                except (ValueError, OSError) as exc:
                    skipped.append({"title": title, "reason": str(exc)[:160]})
                    continue
                parser = PlainText()
                parser.feed(parsed["text"]["*"])
                plain = parser.text()
                if len(plain.split()) < 180 or len(plain) > 200_000:
                    continue
                if any(marker in plain.lower() for marker in
                       ("copyright violation", "all rights reserved", "permission pending")):
                    skipped.append({"title": title, "reason": "rights marker needs manual review"})
                    continue
                revision = parsed["revid"]
                source = "https://en.wikibooks.org/w/index.php?oldid=" + str(revision)
                history = "https://en.wikibooks.org/w/index.php?" + urllib.parse.urlencode(
                    {"title": title, "action": "history"}
                )
                header = (
                    f"{title}\n\n"
                    "Community textbook reference. Not independently technically or clinically "
                    "reviewed by FieldForge. Consult the complete source and qualified expertise "
                    "before high-consequence use. This text-only edition omits images; image/formula "
                    "alternative text is retained where supplied. Navigation/layout converted.\n\n"
                )
                footer = (
                    f"\n\nSOURCE AND REUSE\nBy Wikibooks contributors. Revision {revision}.\n"
                    f"Source: {source}\nContributor history: {history}\n"
                    f"License: {LICENSE}\nText adapted to a plain-text offline edition; "
                    "attribution and share-alike terms apply to this article. "
                    "No independent FieldForge review date is asserted.\n"
                )
                body = header + plain + footer
                article = {
                    "slug": "wikibooks-" + str(parsed["pageid"]), "title": title,
                    "body": body, "category": category,
                    "tags": sorted({category, book.lower(), "community-reference", "text-only"}),
                    "source_title": title, "source_url": source,
                    "source_publisher": "Wikibooks contributors",
                    "reviewed_on": "",
                    "safety_level": "high_stakes" if category in {
                        "medicine", "water-sanitation", "survival", "engineering", "energy"
                    } else "caution",
                    "license": LICENSE,
                    "checksum": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                }
                all_articles.append(article)
                catalog.append({"slug": article["slug"], "title": title, "category": category,
                                "revision": revision, "source_url": source,
                                "contributors": history, "words": len(plain.split()),
                                "body_sha256": article["checksum"]})
                seen.add(title)
                accepted += 1
            print(f"{category}: {book}: {accepted} articles", flush=True)
    all_articles.sort(key=lambda row: row["slug"])
    data = {"articles": all_articles, "annotations": []}
    envelope = {"format": "fieldforge-knowledge", "version": 1, "algorithm": "sha256",
                "checksum": hashlib.sha256(canonical(data)).hexdigest(), "data": data}
    encoded = canonical(envelope)
    if len(encoded) > 32 * 1024 * 1024:
        raise ValueError("combined reference pack exceeds importer limit")
    (output / "reference-library.json").write_bytes(encoded)
    (output / "catalog.json").write_text(
        json.dumps({"license": LICENSE, "articles": catalog, "skipped": skipped},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"TOTAL: {len(catalog)} articles, {sum(row['words'] for row in catalog)} words", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--per-book", type=int, default=12)
    args = parser.parse_args()
    build(args.output, args.cache, args.per_book)
