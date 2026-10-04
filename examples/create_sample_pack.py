"""Create three application-help examples, NOT a survival/reference corpus."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.packs import export_pack


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    examples = (
        ("example-search", "Browse and search offline", "application-help",
         "Leave the search box empty and choose Search / Browse to list installed articles. "
         "Choose a category or enable Bookmarks only to narrow the list. Enter a few distinctive "
         "words to search the installed library. Nothing in this example downloads reference material."),
        ("example-sources", "Read the source information", "application-help",
         "An article can carry its source title, publisher, URL, review date, reuse rights, and a "
         "safety label. These are supplied metadata, not independent verification. A checksum detects "
         "changed data; it does not prove authorship, truth, or that guidance is safe. Missing sources "
         "and review dates stay visibly missing. These example articles are software help, not "
         "medical or survival instructions."),
        ("example-notes", "Keep personal notes private", "application-help",
         "Notes and bookmarks are stored locally alongside the library. Public knowledge-pack exports "
         "exclude them by default. Explicitly include private notes only for a personal library backup. "
         "That JSON backup is not encrypted. Protect the resulting file and test restoring it to a "
         "different database. The legacy household JSON backup does not include the knowledge library."),
    )
    with tempfile.TemporaryDirectory(prefix="fieldforge-example-") as directory:
        library = KnowledgeLibrary(Path(directory) / "examples.db")
        for slug, title, category, body in examples:
            library.upsert(KnowledgeArticle(
                slug, title, body, category, tags=("example", "help"),
                source_title="FieldForge application-help examples",
                source_publisher="FieldForge project — unreviewed example content",
            ))
        print(export_pack(library, args.destination))


if __name__ == "__main__":
    main()
