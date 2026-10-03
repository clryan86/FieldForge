"""Run three offline blueprint studios or generate/export designs from the CLI."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sqlite3
import threading
from pathlib import Path

from fieldforge.blueprints.acceptance import METRICS, validate_rules
from fieldforge.blueprints.comparison import compare_results
from fieldforge.blueprints.comparison_report import export_comparison
from fieldforge.blueprints.constraints import analyze_constraints
from fieldforge.blueprints.diagnostics import diagnose_blueprint
from fieldforge.blueprints.engine import BlueprintRequest, _json, digest, generate_blueprint
from fieldforge.blueprints.evidence import retrieve_blueprint_evidence
from fieldforge.blueprints.geometry import analyze_envelopes
from fieldforge.blueprints.parameters import prepare_part_edit
from fieldforge.blueprints.projects import (
    append_revision,
    checkout,
    compare_designs,
    create_project,
    head,
    load_project,
    restore_revision,
)
from fieldforge.blueprints.render import export_blueprint, load_blueprint, normalized_document
from fieldforge.blueprints.schema import MODES
from fieldforge.content import install_reference_library
from fieldforge.knowledge.assistant import OllamaClient
from fieldforge.knowledge.library import KnowledgeLibrary


def read_limits(path, mode):
    with path.open("rb") as stream:
        raw = stream.read(65_537)
    if len(raw) > 65_536:
        raise ValueError("Acceptance limits file exceeds 64 KiB.")
    rules = _json(raw.decode("utf-8"))
    validate_rules(mode, rules)
    return rules


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
    generate.add_argument("--limits", type=Path, help="JSON list of user acceptance rules")
    evidence = commands.add_parser("evidence", help="Inspect current source passages without a model")
    evidence.add_argument("mode", choices=MODES)
    evidence.add_argument("brief")
    evidence.add_argument("--constraints", default="")
    evidence.add_argument("--resources", default="")
    evidence.add_argument("--evidence-query", default="")
    evidence.add_argument("--changes", default="")
    evidence.add_argument("--limits", type=Path)
    refine = commands.add_parser("refine", help="Revise an existing design using fresh local evidence")
    refine.add_argument("source", type=Path)
    refine.add_argument("changes")
    for field in ("brief", "constraints", "resources", "evidence-query"):
        refine.add_argument("--" + field)
    refine.add_argument("--model", required=True)
    refine.add_argument("--port", type=int, default=11434)
    refine.add_argument("--timeout", type=float, default=300)
    refine.add_argument("--output", type=Path, required=True)
    refine.add_argument("--limits", type=Path, help="Explicitly replace inherited acceptance limits")
    export = commands.add_parser("export")
    export.add_argument("source", type=Path)
    export.add_argument("destination", type=Path)
    edit_part = commands.add_parser("edit-part", help="Edit one part's measurements and export a draft plus comparison")
    edit_part.add_argument("source", type=Path)
    edit_part.add_argument("part_id")
    edit_part.add_argument("--size", nargs=3, metavar=("X", "Y", "Z"), help="Sizes, positive; mm by default or explicit cm/m/in/ft")
    edit_part.add_argument("--position", nargs=3, metavar=("X", "Y", "Z"), help="Nonnegative positions; mm by default or explicit units")
    edit_part.add_argument("--output", type=Path, required=True, help="New export directory")
    limits = commands.add_parser("apply-limits", help="Apply user limits and export a new offline report")
    limits.add_argument("source", type=Path)
    limits.add_argument("limits", type=Path)
    limits.add_argument("destination", type=Path)
    metrics = commands.add_parser("acceptance-metrics", help="List supported measurements and units")
    metrics.add_argument("mode", choices=MODES)
    check = commands.add_parser("check", help="Recompute saved checks; exit 1 if the design needs revision")
    check.add_argument("source", type=Path)
    diagnose = commands.add_parser("diagnose", help="Inspect measured failures and conflicting limits without a model")
    diagnose.add_argument("source", type=Path)
    limits_check = commands.add_parser("limits-check", help="Check supported exact-rule conflicts before generation")
    limits_check.add_argument("mode", choices=MODES)
    limits_check.add_argument("limits", type=Path)
    geometry = commands.add_parser("geometry", help="Inspect engineering envelope pairs without a model")
    geometry.add_argument("source", type=Path)
    compare = commands.add_parser("compare")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.add_argument("--results", action="store_true", help="Recompute outcomes against fixed baseline limits")
    compare.add_argument("--output", type=Path, help="Export computed comparison and snapshots to a new directory")
    project_compare = commands.add_parser("project-compare", help="Compare saved revisions without changing history")
    project_compare.add_argument("project", type=Path)
    project_compare.add_argument("before", type=int)
    project_compare.add_argument("after", type=int)
    project_compare.add_argument("--output", type=Path)
    project_init = commands.add_parser("project-init")
    project_init.add_argument("source", type=Path)
    project_init.add_argument("destination", type=Path)
    project_init.add_argument("--name")
    history = commands.add_parser("project-history")
    history.add_argument("project", type=Path)
    project_add = commands.add_parser("project-add")
    project_add.add_argument("project", type=Path)
    project_add.add_argument("source", type=Path)
    project_add.add_argument("--expect", required=True, help="Expected project head checksum")
    project_add.add_argument("--note", default="Import updated design")
    restore = commands.add_parser("project-restore")
    restore.add_argument("project", type=Path)
    restore.add_argument("revision", type=int)
    restore.add_argument("--expect", required=True)
    project_export = commands.add_parser("project-export")
    project_export.add_argument("project", type=Path)
    project_export.add_argument("destination", type=Path)
    project_export.add_argument("--revision", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "acceptance-metrics":
            result = {key: {"unit": spec[1], "target": spec[2], "label": spec[3], "type": spec[4]}
                      for key, spec in METRICS.items() if spec[0] in (args.mode, "all")}
        elif args.command in {"diagnose", "limits-check"}:
            if args.command == "limits-check":
                result = analyze_constraints(args.mode, read_limits(args.limits, args.mode))
                failed = bool(result["conflicts"])
            else:
                result = diagnose_blueprint(load_blueprint(args.source))
                failed = bool(result["blocking_issues"] or result["constraints"]["conflicts"])
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
            return 1 if failed else 0
        elif args.command == "geometry":
            value = load_blueprint(args.source)
            if value["request"]["mode"] != "engineering":
                raise ValueError("Geometry inspection requires an engineering blueprint.")
            result = {"format": "fieldforge-envelope-analysis", "version": 1,
                      "design_sha256": digest(value["design"]),
                      **analyze_envelopes(value["design"]["parts"])}
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
            return 0 if result["summary"]["status"] == "analyzed" else 1
        elif args.command == "check":
            value = load_blueprint(args.source)
            print(json.dumps({"status": value["status"], "validation": value["validation"],
                              "review": value["review"], "review_error": value["review_error"]},
                             ensure_ascii=False, indent=2))
            return 1 if value["status"] == "needs_revision" else 0
        elif args.command == "apply-limits":
            value = copy.deepcopy(load_blueprint(args.source))
            rules = read_limits(args.limits, value["request"]["mode"])
            if value["request"].get("acceptance_rules", []) != rules:
                value["request"]["acceptance_rules"] = rules
                value.update(review=None, review_error="Acceptance limits changed; a new review is required.")
            value = normalized_document(value)
            result = {"directory": str(export_blueprint(value, args.destination)),
                      "status": value["status"], "validation": value["validation"]}
        elif args.command == "export":
            result = {"directory": str(export_blueprint(load_blueprint(args.source), args.destination))}
        elif args.command == "edit-part":
            before = load_blueprint(args.source)
            proposal = prepare_part_edit(before, args.part_id, size=args.size, position=args.position)
            value = proposal["blueprint"]
            export_blueprint(value, args.output)
            export_comparison(before, value, args.output / "comparison")
            result = {"directory": str(args.output), "status": value["status"], "notice": proposal["notice"],
                      "validation": value["validation"], "acceptance_outcomes": proposal["comparison"]["acceptance"]["outcomes"]}
        elif args.command == "compare":
            before, after = load_blueprint(args.before), load_blueprint(args.after)
            result = compare_results(before, after) if args.results or args.output else compare_designs(before, after)
            if args.output:
                result["directory"] = str(export_comparison(before, after, args.output))
        elif args.command == "project-compare":
            project = load_project(args.project)
            before, after = checkout(project, args.before), checkout(project, args.after)
            result = compare_results(before, after)
            if args.output:
                result["directory"] = str(export_comparison(before, after, args.output))
        elif args.command.startswith("project-"):
            if args.command == "project-init":
                value = load_blueprint(args.source)
                project = create_project(args.destination, args.name or value["design"]["title"], value)
            elif args.command == "project-add":
                project = append_revision(args.project, load_blueprint(args.source),
                                          expected_head=args.expect, note=args.note)
            elif args.command == "project-restore":
                project = restore_revision(args.project, args.revision, expected_head=args.expect)
            else:
                project = load_project(args.project)
            result = {"name": project["name"], "head": head(project),
                      "revisions": [{key: row[key] for key in ("number", "kind", "note", "created_at", "checksum")}
                                    for row in project["revisions"]]}
            if args.command == "project-export":
                result["directory"] = str(export_blueprint(checkout(project, args.revision), args.destination))
        else:
            if args.command in {"generate", "refine"} and args.output.exists():
                raise FileExistsError("Output directory already exists. Choose a new directory.")
            library = KnowledgeLibrary(args.database)
            if args.command == "gui":
                from fieldforge.ui.blueprints import run
                run(library)
                return 0
            if args.command == "install-library":
                result = install_reference_library(library)
            elif args.command == "evidence":
                request = BlueprintRequest(args.mode, args.brief, args.constraints, args.resources, args.evidence_query,
                                           acceptance_rules=read_limits(args.limits, args.mode) if args.limits else [])
                result = retrieve_blueprint_evidence(library, request, args.changes)
            else:
                extra = {}
                if args.command == "refine":
                    previous = load_blueprint(args.source)
                    fields = dict(previous["request"])
                    for field in ("brief", "constraints", "resources", "evidence_query"):
                        if getattr(args, field) is not None:
                            fields[field] = getattr(args, field)
                    if args.limits is not None:
                        fields["acceptance_rules"] = read_limits(args.limits, fields["mode"])
                    request = BlueprintRequest(**fields)
                    extra = {"previous": previous, "instructions": args.changes}
                else:
                    request = BlueprintRequest(args.mode, args.brief, args.constraints,
                                               args.resources, args.evidence_query,
                                               acceptance_rules=read_limits(args.limits, args.mode) if args.limits else [])
                blueprint = generate_blueprint(library, request, args.model,
                                               OllamaClient(port=args.port, timeout=args.timeout),
                                               cancel=threading.Event(), **extra)
                result = {"directory": str(export_blueprint(blueprint, args.output)),
                          "status": blueprint["status"]}
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
