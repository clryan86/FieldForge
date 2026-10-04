"""Twenty bundled original lessons, with explicit, non-destructive installation.

Preview/practice never read private notes or mark learning progress. Install only
adds absent article IDs in one transaction; different or damaged existing rows
are preserved and reported. No downloads, migrations or specialist-review claims.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge._foundations_content import lessons
from fieldforge.knowledge._learning_model import Lesson
from fieldforge.knowledge.packs import export_pack
from fieldforge.knowledge.starter import RIGHTS

VERSION = "foundations-v1"
PREFIX = "foundation-v1-"
TITLE = "Foundations: Mathematics, Measurement & Records"
NOTICE = (
    "Original AI-drafted learning material; not independently reviewed by a subject specialist. "
    "Fictional paper-based exercises, not medical advice, engineering designs or safety approval. "
    "Correct arithmetic does not establish real-world competence."
)
STATES = {"missing": "Not installed", "installed": "Installed — same edition",
          "preserved": "Different / unreadable — preserved"}


@lru_cache(maxsize=1)
def catalog() -> tuple[Lesson, ...]:
    result = lessons()
    seen: set[str] = set()
    for lesson in result:
        if lesson.slug in seen or not set(lesson.prerequisites) <= seen:
            raise ValueError("lesson IDs must be unique and prerequisites must come earlier")
        seen.add(lesson.slug)
    if len(result) != 20:
        raise ValueError("this edition must contain exactly 20 lessons")
    return result


def article_for(lesson: Lesson) -> KnowledgeArticle:
    items = catalog()
    if lesson not in items:
        raise ValueError("choose a lesson from the bundled edition")
    number = items.index(lesson) + 1
    names = {item.slug: item.title for item in items}
    prerequisites = "; ".join(names[slug] for slug in lesson.prerequisites) or "None in this collection."
    questions = "\n\n".join(f"{i}. {ex.question}\nAnswer unit: {ex.unit}."
                              for i, ex in enumerate(lesson.exercises, 1))
    answers = "\n\n".join(f"{i}. {ex.answer} {ex.unit}. {ex.explanation}"
                            for i, ex in enumerate(lesson.exercises, 1))
    related = (
        f"\n\nRELATED TECHNICAL REFERENCE (unit conventions only)\n{lesson.reference_title}\n"
        f"{lesson.reference_url}\nConsulted 2026-10-01. Not a copied source chapter. "
        "The linked organization has not reviewed or endorsed this original lesson."
        if lesson.reference_url else ""
    )
    body = (f"{TITLE}\nLesson {number:02d} of {len(items)} · Bundled edition: {VERSION}\n\n{NOTICE}\n\n"
            f"LEARNING GOAL\n{lesson.objective}\n\nBEFORE THIS LESSON\n{prerequisites}\n\n"
            f"{lesson.text.strip()}\n\nPRACTICE — TRY BEFORE READING THE ANSWERS\n{questions}\n\n"
            f"WORKED ANSWERS\n{answers}\n\nLEARNING RECORD\n"
            "Explain the units and assumptions to another learner. A checked answer is not a qualification. "
            "No practice status is recorded automatically.\n"
            f"Optional Civilization Pathways goal IDs: {', '.join(lesson.goals)}. "
            "Use Manage reading links to choose your own associations; none are added by installation."
            f"{related}\n\nORIGIN AND RIGHTS\nOriginal FieldForge lesson and fictional exercises. {RIGHTS}")
    return KnowledgeArticle(
        slug=PREFIX + lesson.slug, title=f"Foundations {number:02d}: {lesson.title}",
        body=body, category=lesson.category, tags=("foundations", "learning-pack", lesson.slug, *lesson.goals),
        source_title=f"FieldForge original learning collection — {VERSION}", source_publisher="FieldForge",
        source_url="", reviewed_on="", safety_level="caution", license=RIGHTS,
    )


@lru_cache(maxsize=1)
def foundation_articles() -> tuple[KnowledgeArticle, ...]:
    return tuple(article_for(lesson) for lesson in catalog())


@dataclass(frozen=True)
class LessonState:
    slug: str
    state: str


@dataclass(frozen=True)
class InstallReport:
    added: tuple[str, ...]
    unchanged: tuple[str, ...]
    preserved: tuple[str, ...]

    def __str__(self) -> str:
        return (f"Added {len(self.added)} lessons; {len(self.unchanged)} already identical; "
                f"{len(self.preserved)} different/unreadable records preserved. No notes or progress changed.")


def _state(library: KnowledgeLibrary, row: sqlite3.Row | None, article: KnowledgeArticle) -> str:
    if row is None:
        return "missing"
    try:
        same = library._article(row) == article and row["checksum"] == article.checksum
    except (TypeError, ValueError, KeyError, AttributeError):
        same = False
    return "installed" if same else "preserved"


def inspect_foundations(library: KnowledgeLibrary) -> tuple[LessonState, ...]:
    """One read transaction, bounded to exact bundled IDs. No private annotations."""
    with library.connect() as db:
        db.execute("BEGIN")
        return tuple(LessonState(article.slug, _state(library, db.execute(
            "SELECT * FROM knowledge_articles WHERE slug=?", (article.slug,)
        ).fetchone(), article)) for article in foundation_articles())


def install_foundations(library: KnowledgeLibrary, *, acknowledged: bool = False) -> InstallReport:
    """Recheck under a writer lock; add all absent lessons or roll back on failure."""
    if acknowledged is not True:
        raise ValueError("acknowledge the original, unreviewed learning-material notice before installing")
    articles = foundation_articles()
    added, unchanged, preserved = [], [], []
    with library.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for article in articles:
            state = _state(library, db.execute(
                "SELECT * FROM knowledge_articles WHERE slug=?", (article.slug,)
            ).fetchone(), article)
            if state == "missing":
                library._write(db, article)
                added.append(article.slug)
            elif state == "installed":
                unchanged.append(article.slug)
            else:
                preserved.append(article.slug)
    return InstallReport(tuple(added), tuple(unchanged), tuple(preserved))


def export_foundations(destination: str | Path) -> Path:
    """Create a compatible JSON pack from bundled content only, never a user's DB.

    Existing destinations are refused. Publication is not atomic; forced process
    termination can leave a partial new file. No reader feature is installed by JSON.
    """
    target = Path(destination).expanduser().absolute()
    if target.suffix.lower() != ".json":
        raise ValueError("choose a new .json filename")
    with tempfile.TemporaryDirectory(prefix="fieldforge-foundations-") as folder:
        library = KnowledgeLibrary(Path(folder) / "content.db")
        install_foundations(library, acknowledged=True)
        data = export_pack(library, Path(folder) / "content.json").read_bytes()
    identity = None
    try:
        with target.open("xb") as stream:
            identity = os.fstat(stream.fileno())
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if identity is not None:
            try:
                current = target.lstat()
                if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                    target.unlink()
            except OSError:
                pass
        raise
    return target.resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install", help="Add missing lessons; never replace existing rows")
    install.add_argument("--database", type=Path, required=True)
    install.add_argument("--acknowledge-unreviewed", action="store_true", required=True)
    export = commands.add_parser("export", help="Write the bundled lessons as a new JSON knowledge pack")
    export.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            print(export_foundations(args.destination))
        else:
            print(install_foundations(KnowledgeLibrary(args.database), acknowledged=args.acknowledge_unreviewed))
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
