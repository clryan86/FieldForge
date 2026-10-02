"""Run three offline blueprint studios or generate/export designs from the CLI."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import threading
from pathlib import Path

from fieldforge.blueprints.engine import BlueprintRequest, generate_blueprint
from fieldforge.blueprints.render import export_blueprint, load_blueprint
from fieldforge.blueprints.schema import MODES
from fieldforge.content import install_reference_library
from fieldforge.knowledge.assistant import OllamaClient
from fieldforge.knowledge.library import KnowledgeLibrary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(
        os.environ.get("FIELDFORGE_DB", "~/.fieldforge/fieldforge.db")).expanduser())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("gui")
    commands.add_parser("install-library")
    generate = commands.add_parser("generate")
    generate.add_argument("mode", choices=MODES)
    generate.add_argument("brief")
    generate.add_argument("--constraints", default="")
    generate.add_argument("--resources", default="")
    generate.add_argument("--evidence-query", default="")
    generate.add_argument("--model", required=True)
    generate.add_argument("--port", type=int, default=11434)
    generate.add_argument("--timeout", type=float, default=300)
    generate.add_argument("--output", type=Path, required=True, help="New export directory")
    export = commands.add_parser("export")
    export.add_argument("source", type=Path)
    export.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            result = {"directory": str(export_blueprint(load_blueprint(args.source), args.destination))}
        else:
            library = KnowledgeLibrary(args.database)
            if args.command == "gui":
                from fieldforge.ui.blueprints import run
                run(library)
                return 0
            if args.command == "install-library":
                result = install_reference_library(library)
            else:
                request = BlueprintRequest(args.mode, args.brief, args.constraints,
                                           args.resources, args.evidence_query)
                blueprint = generate_blueprint(library, request, args.model,
                                               OllamaClient(port=args.port, timeout=args.timeout),
                                               cancel=threading.Event())
                result = {"directory": str(export_blueprint(blueprint, args.output)),
                          "status": blueprint["status"]}
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
