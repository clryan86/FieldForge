"""Portable, append-only blueprint history with atomic writes and stale-writer checks."""

from __future__ import annotations

import copy
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fieldforge.blueprints.engine import _json, digest
from fieldforge.blueprints.render import _atomic, normalized_document

MAX_BYTES = 32 * 1024 * 1024
MAX_REVISIONS = 100
KINDS = {"initial", "generated", "edited", "refined", "restored"}


class RevisionConflict(ValueError):
    """Another writer advanced the project; never overwrite their revision."""


def _text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise ValueError("Invalid project text.")


def _validate(project):
    if (not isinstance(project, dict) or set(project) != {
            "format", "version", "id", "name", "revisions"}
            or project["format"] != "fieldforge-blueprint-project"
            or type(project["version"]) is not int or project["version"] != 1):
        raise ValueError("Unsupported blueprint project.")
    _text(project["id"], 64)
    _text(project["name"], 160)
    revisions = project["revisions"]
    if not isinstance(revisions, list) or not 1 <= len(revisions) <= MAX_REVISIONS:
        raise ValueError("A project must have between 1 and 100 revisions.")
    parent, mode = "", None
    for index, revision in enumerate(revisions, 1):
        if not isinstance(revision, dict) or set(revision) != {
                "number", "parent", "created_at", "kind", "note", "blueprint", "checksum"}:
            raise ValueError("Malformed project revision.")
        if (type(revision["number"]) is not int or revision["number"] != index
                or revision["parent"] != parent or revision["kind"] not in KINDS):
            raise ValueError("Broken project revision chain.")
        _text(revision["created_at"], 100)
        _text(revision["note"], 4000)
        record = {key: value for key, value in revision.items() if key != "checksum"}
        if digest({"project_id": project["id"], **record}) != revision["checksum"]:
            raise ValueError("Project revision checksum mismatch.")
        value = normalized_document(revision["blueprint"])
        if mode is not None and value["request"]["mode"] != mode:
            raise ValueError("A project cannot mix different blueprint makers.")
        mode = value["request"]["mode"]
        parent = revision["checksum"]
    return project


def load_project(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Project exceeds the 32 MiB limit.")
    try:
        # Keep original records for hash continuity. Normalize on checkout, not in-place.
        return _validate(_json(raw.decode("utf-8")))
    except (KeyError, TypeError, RecursionError, UnicodeError) as exc:
        raise ValueError("Malformed blueprint project.") from exc


def head(project):
    return project["revisions"][-1]["checksum"]


def checkout(project, number=None):
    if number is None:
        number = len(project["revisions"])
    if type(number) is not int or not 1 <= number <= len(project["revisions"]):
        raise ValueError("Unknown revision number.")
    return normalized_document(copy.deepcopy(project["revisions"][number - 1]["blueprint"]))


@contextmanager
def _writer(path):
    """Non-blocking advisory OS lock. The sidecar remains; OS releases crashed locks."""
    lock = path.with_name(path.name + ".lock")
    with lock.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RevisionConflict("Project is being saved by another process. Try again.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _revision(project, blueprint, kind, note):
    if kind not in KINDS:
        raise ValueError("Unknown revision kind.")
    _text(note, 4000)
    value = normalized_document(copy.deepcopy(blueprint))
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 2_000_000:
        raise ValueError("Blueprint exceeds the 2 MB limit.")
    if project["revisions"] and value["request"]["mode"] != checkout(project)["request"]["mode"]:
        raise ValueError("A project cannot mix different blueprint makers.")
    revision = {"number": len(project["revisions"]) + 1,
                "parent": head(project) if project["revisions"] else "",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "kind": kind, "note": note, "blueprint": value}
    revision["checksum"] = digest({"project_id": project["id"], **revision})
    return revision


def _write(path, project):
    _validate(project)
    data = json.dumps(project, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    if len(data.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Project exceeds the 32 MiB limit. Save the current design as a new project.")
    _atomic(path, data)


def create_project(path, name, blueprint):
    path = Path(path)
    _text(name, 160)
    if not path.name.endswith(".ffproject.json"):
        raise ValueError("Use the .ffproject.json extension for a blueprint project.")
    project = {"format": "fieldforge-blueprint-project", "version": 1,
               "id": str(uuid4()), "name": name, "revisions": []}
    project["revisions"].append(_revision(project, blueprint, "initial", "Initial design"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with _writer(path):
        if path.exists():
            raise FileExistsError("Project already exists. Choose a new filename.")
        _write(path, project)
    return project


def append_revision(path, blueprint, *, expected_head, kind="edited", note="Design update"):
    path = Path(path)
    with _writer(path):
        project = load_project(path)
        if head(project) != expected_head:
            raise RevisionConflict("Project changed on disk. Reopen it or save this draft as a new project.")
        if len(project["revisions"]) >= MAX_REVISIONS:
            raise ValueError("Project has 100 revisions. Save the current design as a new project.")
        project["revisions"].append(_revision(project, blueprint, kind, note))
        _write(path, project)
    return project


def restore_revision(path, number, *, expected_head):
    project = load_project(path)
    return append_revision(path, checkout(project, number), expected_head=expected_head,
                           kind="restored", note=f"Restore revision {number}")


def compare_designs(before, after, *, limit=200):
    """Readable, ID-aware differences. Never align parts solely by list position."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Comparison limit must be between 1 and 1000.")
    changes = []
    missing = object()

    def short(value):
        if value is missing:
            return "(absent)"
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return text if len(text) <= 2000 else text[:2000] + "… [truncated]"

    def walk(a, b, path):
        if len(changes) > limit or a == b:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                walk(a.get(key, missing), b.get(key, missing), path + "/" + key)
        elif (isinstance(a, list) and isinstance(b, list) and a and b
              and all(isinstance(row, dict) and isinstance(row.get("id"), str) for row in a + b)
              and len({row["id"] for row in a}) == len(a)
              and len({row["id"] for row in b}) == len(b)):
            walk({row["id"]: row for row in a}, {row["id"]: row for row in b}, path)
            walk([row["id"] for row in a], [row["id"] for row in b], path + "/order")
        else:
            changes.append({"path": path, "before": short(a), "after": short(b)})

    for field in ("request", "design", "sources", "review", "review_error"):
        walk(before.get(field), after.get(field), "/" + field)
    return {"changes": changes[:limit], "truncated": len(changes) > limit}
