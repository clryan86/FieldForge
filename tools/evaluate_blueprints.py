"""Opt-in local-model evaluation; records machine checks, not expert factual grades.

Run after installing FieldForge, its reference library and a local Ollama model.
No model is downloaded. Each run requires a new output directory.
"""

import argparse
import json
import platform
import time
from pathlib import Path

from fieldforge.blueprints.engine import BlueprintRequest, generate_blueprint
from fieldforge.blueprints.render import export_blueprint
from fieldforge.knowledge.assistant import OllamaClient
from fieldforge.knowledge.library import KnowledgeLibrary

CASES = [
    BlueprintRequest("engineering", "Create a layout for a workshop inventory shelf. "
                     "Do not assume a load rating; identify missing structural information.",
                     constraints="Envelope at most 1000 by 500 by 1500 mm. Metric units.",
                     resources="Timber dimensions and connections are not yet specified.",
                     evidence_query="woodworking workshop timber tools statics"),
    BlueprintRequest("project", "Plan a small community workshop setup and illustrated guide.",
                     constraints="Three volunteers, ten days, donated tools. Budget is unknown.",
                     resources="One room, an inventory notebook, a coordinator.",
                     evidence_query="project scope risk schedule workshop"),
    BlueprintRequest("software", "Design an offline inventory app with durable local records, "
                     "search, backup, restore and portable exports.",
                     constraints="No network required. Imports are untrusted. One device initially.",
                     resources="Python and SQLite; desktop first.",
                     evidence_query="software operating system file systems data"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    library = KnowledgeLibrary(args.database)
    client = OllamaClient(port=args.port, timeout=300)
    report = {"model": args.model, "platform": platform.platform(),
              "python": platform.python_version(), "article_count": library.count(),
              "expert_review": "Not performed; no factual correctness score is asserted.", "cases": []}
    for request in CASES:
        start = time.monotonic()
        row = {"mode": request.mode}
        try:
            result = generate_blueprint(library, request, args.model, client)
            export_blueprint(result, args.output / request.mode)
            row.update(status=result["status"], attempts=len(result["attempts"]),
                       sources=len(result["sources"]), validation=result["validation"],
                       review_error=result["review_error"], structured_output=True)
        except (ValueError, OSError) as exc:
            row.update(error=str(exc), structured_output=False)
        row["seconds"] = round(time.monotonic() - start, 3)
        report["cases"].append(row)
        (args.output / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(row), flush=True)
    return 0 if all(row["structured_output"] for row in report["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
