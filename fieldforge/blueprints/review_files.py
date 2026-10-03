"""Portable, bounded review snapshots; no project paths or trusted cached checks."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from fieldforge.blueprints.engine import _json, digest
from fieldforge.blueprints.projects import _writer
from fieldforge.blueprints.render import _atomic
from fieldforge.blueprints.revision import prepare_revision

MAX_BYTES = 6_000_000
BLUEPRINT_BYTES = 2_000_000
FIELDS = {"format", "version", "created_at", "before", "candidate", "checksum"}


def validate_review(value):
    """Verify stored bytes' canonical hashes first, then recompute current checks."""
    if (not isinstance(value, dict) or set(value) != FIELDS
            or value["format"] != "fieldforge-revision-review"
            or type(value["version"]) is not int or value["version"] != 1):
        raise ValueError("Unsupported revision review file.")
    if not isinstance(value["created_at"], str) or len(value["created_at"]) > 100:
        raise ValueError("Invalid review timestamp.")
    try:
        stamp = datetime.fromisoformat(value["created_at"])
        if stamp.tzinfo is None:
            raise ValueError()
    except ValueError as exc:
        raise ValueError("Invalid review timestamp.") from exc
    payload = {key: item for key, item in value.items() if key != "checksum"}
    if value["checksum"] != digest(payload):
        raise ValueError("Revision review checksum mismatch.")
    for key in ("before", "candidate"):
        if len(json.dumps(value[key], ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")) > BLUEPRINT_BYTES:
            raise ValueError("A review blueprint exceeds the 2 MB limit.")
    proposal = prepare_revision(value["before"], value["candidate"])
    request = proposal["candidate"]["request"]
    if request.get("revision_of") != digest(value["before"]):
        raise ValueError("Review lineage does not match its recorded original snapshot.")
    if not 5 <= len(request.get("revision_instructions", "").strip()) <= 4000:
        raise ValueError("The review must contain the original revision instructions.")
    return proposal


def create_review(before, candidate):
    proposal = prepare_revision(before, candidate)
    value = {"format": "fieldforge-revision-review", "version": 1,
             "created_at": datetime.now(timezone.utc).isoformat(),
             "before": proposal["before"], "candidate": proposal["candidate"]}
    value["checksum"] = digest(value)
    validate_review(value)
    return value


def load_review(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Revision review exceeds the 6 MB limit.")
    try:
        value = _json(raw.decode("utf-8"))
        validate_review(value)
        # Keep the historical record intact. Callers use validate_review for fresh
        # derived outcomes, never the stored validation/status as authoritative.
        return value
    except (KeyError, TypeError, UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("Malformed revision review file.") from exc


def review_from_files(before_path, candidate_path):
    """Retain the exact historical baseline, including old derived checker fields."""
    snapshots = []
    for path in (before_path, candidate_path):
        with Path(path).open("rb") as stream:
            raw = stream.read(BLUEPRINT_BYTES + 1)
        if len(raw) > BLUEPRINT_BYTES:
            raise ValueError("A review blueprint exceeds the 2 MB limit.")
        try:
            snapshots.append(_json(raw.decode("utf-8")))
        except (UnicodeError, RecursionError) as exc:
            raise ValueError("Malformed review source blueprint.") from exc
    try:
        return create_review(*snapshots)
    except (KeyError, TypeError, RecursionError, OverflowError) as exc:
        raise ValueError("Malformed review source blueprint.") from exc


def save_review(value, path):
    value = copy.deepcopy(value)
    validate_review(value)
    path = Path(path)
    if not path.name.endswith(".ffreview.json"):
        raise ValueError("Use the .ffreview.json extension for a saved revision review.")
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    if len(data.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Revision review exceeds the 6 MB limit.")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Same cooperating-writer protocol as projects. Reviews are immutable files;
    # even another valid review is never an eligible overwrite target.
    with _writer(path):
        if path.exists():
            raise FileExistsError("Review destination already exists. Choose a new filename.")
        _atomic(path, data)
    return path
