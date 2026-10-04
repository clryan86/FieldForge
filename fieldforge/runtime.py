"""Explicit source/frozen entry points; never treat a bundled EXE as python -m.

Packaged PDF extraction uses a separate console-capable helper with redirected
handles. New desktop instances use the graphical executable. No PATH lookup,
shell command, arbitrary module dispatcher or installed Python fallback.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def packaged() -> bool:
    return bool(getattr(sys, "frozen", False))


def _sibling(name: str) -> str:
    suffix = ".exe" if sys.platform == "win32" else ""
    path = Path(sys.executable).resolve().with_name(name + suffix)
    if not path.is_file():
        raise FileNotFoundError(
            f"The application folder is incomplete: {path.name} is missing. "
            "Extract the whole FieldForge folder again; do not move only the EXE."
        )
    return str(path)


def pdf_command() -> list[str]:
    if packaged():
        return [_sibling("FieldForgeTools"), "--pdf-worker"]
    return [sys.executable, "-m", "fieldforge.knowledge.pdf_worker"]


def desktop_command() -> list[str]:
    if packaged():
        return [_sibling("FieldForge")]
    return [sys.executable, "-m", "fieldforge.ui.desktop"]


def desktop_environment(database: str | Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["FIELDFORGE_DB"] = str(Path(database).expanduser().resolve())
    if packaged():
        # Recovery launches an independent desktop, not a transient parser worker.
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return environment


def build_identity() -> dict[str, str]:
    """Read bounded build-owned metadata. Unknown source identity stays unknown."""
    path = Path(__file__).with_name("_build.json")
    fallback = {"version": "0.1.0", "source_commit": "Not recorded in this source build",
                "branch_commit": "Not recorded", "target": "Source / local Python"}
    if not packaged():
        return fallback
    try:
        with path.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise ValueError("oversized build metadata")
        value = json.loads(raw)
        keys = {"version", "source_commit", "branch_commit", "target"}
        if not isinstance(value, dict) or set(value) != keys:
            raise ValueError("invalid build metadata")
        if any(not isinstance(item, str) or len(item) > 200 or any(ord(c) < 32 for c in item)
               for item in value.values()):
            raise ValueError("invalid build labels")
        for key in ("source_commit", "branch_commit"):
            if re.fullmatch(r"[0-9a-f]{40}", value[key]) is None:
                raise ValueError("invalid build commit")
        return value
    except (OSError, ValueError, UnicodeError):
        return {**fallback, "target": "Packaged build — identity unavailable; verify your download"}
