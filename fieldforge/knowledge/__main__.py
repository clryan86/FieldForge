"""Run ``python -m fieldforge.knowledge --help`` for portable knowledge tools."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from dataclasses import asdict
from pathlib import Path

from fieldforge.knowledge import KnowledgeLibrary
from fieldforge.knowledge.assistant import OllamaClient, draft_answer
from fieldforge.knowledge.packs import export_pack, import_pack
from fieldforge.knowledge.retrieval import retrieve_evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FieldForge offline knowledge tools")
    parser.add_argument("--database", type=Path, default=Path(
        os.environ.get("FIELDFORGE_DB", "~/.fieldforge/fieldforge.db")
    ).expanduser())
    sub = parser.add_subparsers(dest="command", required=True)
    browse = sub.add_parser("list", help="Browse without guessing a search query")
    browse.add_argument("--category")
    browse.add_argument("--bookmarked", action="store_true")
    browse.add_argument("--limit", type=int, default=100)
    browse.add_argument("--offset", type=int, default=0)
    load = sub.add_parser("import", help="Import an integrity-checked JSON knowledge pack")
    load.add_argument("source", type=Path)
    load.add_argument("--replace", action="store_true", help="Allow conflicting content/notes to be replaced")
    load.add_argument("--restore-personal", action="store_true")
    save = sub.add_parser("export", help="Export articles; excludes personal notes by default")
    save.add_argument("destination", type=Path)
    save.add_argument("--include-personal", action="store_true")
    sub.add_parser("gui", help="Open the offline knowledge window")
    context = sub.add_parser("context", help="Find cited local passages for a question")
    context.add_argument("question")
    context.add_argument("--limit", type=int, default=5)
    models = sub.add_parser("models", help="List installed local Ollama models (cloud must be disabled)")
    models.add_argument("--port", type=int, default=11434)
    ask = sub.add_parser("ask", help="Draft an answer from local evidence with an installed model")
    ask.add_argument("question")
    ask.add_argument("--model", required=True)
    ask.add_argument("--port", type=int, default=11434)
    ask.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args(argv)
    try:
        if args.command == "models":
            print(json.dumps({"models": OllamaClient(port=args.port).list_models()}, indent=2))
            return 0
        library = KnowledgeLibrary(args.database)
        if args.command == "list":
            result = [asdict(item) for item in library.browse(
                args.limit, offset=args.offset, category=args.category, bookmarked=args.bookmarked
            )]
        elif args.command == "import":
            result = import_pack(library, args.source, replace=args.replace,
                                 restore_personal=args.restore_personal)
        elif args.command == "export":
            result = {"path": str(export_pack(library, args.destination,
                                               include_personal=args.include_personal))}
        elif args.command == "context":
            result = {"question": args.question, "evidence": [item.as_dict() for item in
                      retrieve_evidence(library, args.question, limit=args.limit)]}
        elif args.command == "ask":
            result = draft_answer(library, args.question, args.model,
                                  OllamaClient(port=args.port, timeout=args.timeout)).as_dict()
        else:
            from fieldforge.ui.knowledge import run

            run(library)
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
