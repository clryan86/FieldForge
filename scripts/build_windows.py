"""Build/verify an unsigned Windows x64 onedir archive. Run on Windows, not Linux.

Dependencies are installed explicitly by CI before this script. No data, secrets,
credentials or user databases are read. Runtime notices are copied from installed
component distributions, not paraphrased or replaced with a new project license.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def component_notices(destination: Path) -> None:
    import tkinter as tk

    destination.mkdir()
    python_notice = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_notice.is_file():
        raise FileNotFoundError("CPython distribution LICENSE.txt is required for the bundle")
    shutil.copy2(python_notice, destination / "CPython-LICENSE.txt")
    root = tk.Tk()
    try:
        root.withdraw()
        libraries = {"Tcl": Path(root.tk.call("info", "library")),
                     "Tk": Path(root.tk.call("set", "tk_library"))}
    finally:
        root.destroy()
    for name, directory in libraries.items():
        # Official CPython Windows distributions normally put these alongside scripts.
        candidates = [directory / "license.terms", directory.parent / "license.terms"]
        notice = next((p for p in candidates if p.is_file()), None)
        if notice is None:
            raise FileNotFoundError(f"{name} license.terms is required; do not ship without it")
        shutil.copy2(notice, destination / f"{name}-license.terms")
    versions = {"Python": platform.python_version()}
    for name in ("pypdf", "pyinstaller"):
        package = importlib.metadata.distribution(name)
        notices = [item for item in package.files or () if
                   any(word in Path(str(item)).name.lower() for word in ("license", "copying"))
                   and str(item).lower().endswith((".txt", "license", "copying", ".rst", ".md"))]
        if not notices:
            raise FileNotFoundError(f"Installed {name} distribution has no discoverable license text")
        versions[name] = package.version
        for index, item in enumerate(notices):
            source = Path(package.locate_file(item))
            if source.is_file():
                shutil.copy2(source, destination / f"{name}-{index}-{source.name}")
    (destination / "COMPONENTS.json").write_text(json.dumps(versions, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--branch-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        parser.error("Build on Windows x64 with an x64 Python interpreter")
    for value in (args.source_commit, args.branch_commit):
        if re.fullmatch(r"[0-9a-f]{40}", value) is None:
            parser.error("Commit identifiers must be exact SHA-1 hex IDs")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    meta = ROOT / "build/windows-metadata"
    meta.mkdir(parents=True, exist_ok=True)
    identity = {"version": "0.1.0", "source_commit": args.source_commit,
                "branch_commit": args.branch_commit, "target": "Windows x64 / unsigned development"}
    (meta / "_build.json").write_text(json.dumps(identity) + "\n", encoding="utf-8")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
                    "packaging/FieldForge.spec"], cwd=ROOT, check=True)
    bundle = ROOT / "dist/FieldForge-Windows"
    component_notices(bundle / "THIRD-PARTY-NOTICES")
    shutil.copy2(ROOT / "docs/WINDOWS_PORTABLE.md", bundle / "READ-ME-FIRST.txt")
    (bundle / "Open Recovery.cmd").write_text(
        '@echo off\ncd /d "%~dp0"\nstart "" "%~dp0FieldForge.exe" --recovery\n', encoding="utf-8")
    (bundle / "Check Installation.cmd").write_text(
        '@echo off\ncd /d "%~dp0"\n"%~dp0FieldForgeTools.exe" --verify-installation\n'
        'echo.\necho This check used temporary samples, not your database.\npause\n', encoding="utf-8")
    # Move away from the source/build environment and verify the relocated copy.
    with tempfile.TemporaryDirectory(prefix="FieldForge portable ") as temp:
        isolated = Path(temp) / "Relocated résumé app"
        shutil.copytree(bundle, isolated)
        report = output / "FieldForge-Windows-Verification.json"
        subprocess.run([sys.executable, str(ROOT / "scripts/verify_windows_bundle.py"),
                        str(isolated), str(report), args.source_commit], cwd=temp, check=True)
        shutil.copy2(report, bundle / "VERIFICATION.json")
    archive = output / "FieldForge-Windows-x64.zip"
    if archive.exists():
        raise FileExistsError("Use a new output directory; an existing artifact is never overwritten")
    files = sorted(path for path in bundle.rglob("*") if path.is_file())
    for path in files:
        if path.is_symlink() or path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".mbtiles"}:
            raise ValueError("Unexpected data file or symlink in the application bundle")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in files:
            zipped.write(path, str(Path("FieldForge-Windows") / path.relative_to(bundle)))
    checksum = digest(archive)
    (output / "FieldForge-Windows-x64.sha256").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(f"Verified Windows x64 archive: {archive.name}, {archive.stat().st_size} bytes, SHA-256 {checksum}")


if __name__ == "__main__":
    main()
