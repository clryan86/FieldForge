"""CI-only relocated EXE verification with no installed Python on child PATH.

Checks the bundle's normal PDF/recovery paths and a missing-helper negative
control. Never bypasses Windows protection or writes a production database.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def files_digest(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob("*") if p.is_file()}


def main() -> None:
    if sys.platform != "win32":
        raise RuntimeError("This validates Windows executables, not a source-mode substitute")
    bundle, report_path, source_commit = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3]
    helper = bundle / "FieldForgeTools.exe"
    before = files_digest(bundle)
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "TCL_LIBRARY", "TK_LIBRARY", "VIRTUAL_ENV"):
        environment.pop(name, None)
    system = Path(environment["SystemRoot"])
    environment["PATH"] = str(system / "System32") + os.pathsep + str(system)
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    with tempfile.TemporaryDirectory(prefix="FieldForge isolated verification ") as temp:
        sentinel = Path(temp) / "must-not-touch-user-data.db"
        sentinel.write_bytes(b"Not a database: this must remain unchanged")
        environment["FIELDFORGE_DB"] = str(sentinel)
        result = subprocess.run([str(helper), "--verify-installation"], env=environment, cwd=temp,
                                capture_output=True, text=True, timeout=120, check=False)
        if result.returncode:
            raise RuntimeError(f"Bundled self-check failed:\n{result.stdout}\n{result.stderr}")
        data = json.loads(result.stdout)
        if not (data["status"] == "passed" and data["packaged"] and data["platform"] == "win32"
                and data["python"] == "3.13.16"
                and data["build"]["source_commit"] == source_commit and len(data["checks"]) == 7):
            raise RuntimeError(f"Incomplete Windows build verification: {data}")
        if sentinel.read_bytes() != b"Not a database: this must remain unchanged":
            raise RuntimeError("Diagnostic touched the inherited user database path")
        # No helper fallback to Python, no second UI startup loop when incomplete.
        moved = helper.with_name("Deliberately-renamed-helper.exe")
        helper.rename(moved)
        try:
            negative = subprocess.run([str(moved), "--verify-installation"], env=environment, cwd=temp,
                                      capture_output=True, text=True, timeout=45, check=False)
            if not (negative.returncode == 1 and 'FieldForgeTools.exe is missing' in negative.stdout):
                raise RuntimeError(f"Missing-helper control failed: {negative.stdout}\n{negative.stderr}")
        finally:
            moved.rename(helper)
        if files_digest(bundle) != before:
            raise RuntimeError("Bundled program wrote to or changed its application folder")
        data["relocated_away_from_source"] = True
        data["child_path_contains_python"] = False
        data["inherited_user_data_untouched"] = True
        data["missing_helper_fails_closed"] = True
        data["application_files_unchanged"] = True
        report_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
