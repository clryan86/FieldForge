"""Graphical packaged-app launcher. No downloads, installation or data migration.

The default matches Start FieldForge.cmd: ~/.fieldforge/playground.db. An explicit
--database path or FIELDFORGE_DB overrides it. Existing source module/CLI defaults
are unchanged. Errors are shown locally, never uploaded or logged automatically.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, help="Use this database (no copying or resetting)")
    parser.add_argument("--recovery", action="store_true", help="Open only recovery; do not initialize a broken database")
    args = parser.parse_args(argv)
    # The GUI entry point must not pretend that its EXE is a general Python runner.
    if args.database is not None:
        os.environ["FIELDFORGE_DB"] = str(args.database.expanduser().resolve())
    elif not os.environ.get("FIELDFORGE_DB"):
        os.environ["FIELDFORGE_DB"] = str(Path.home() / ".fieldforge" / "playground.db")
    try:
        if args.recovery:
            from fieldforge.ui.recovery import run
        else:
            from fieldforge.ui.desktop import run
        run()
        return 0
    except Exception as exc:
        # No private record dumps, traceback logs, reset, or second database fallback.
        detail = ("FieldForge could not start. No data reset or fallback database was attempted.\n\n"
                  f"{type(exc).__name__}: {exc}\n\n"
                  "Keep your data and backups. Check that the entire application folder was extracted. "
                  "Use the recovery launcher to inspect a trusted backup separately.")
        if sys.stderr is not None:
            print(detail, file=sys.stderr)
        try:
            from tkinter import messagebox
            messagebox.showerror("FieldForge could not start", detail)
        except Exception:
            pass  # Tk itself may be unavailable; the exit code still indicates failure.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
