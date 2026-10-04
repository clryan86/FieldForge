"""Build/verify an unsigned Windows x64 onedir archive. Run on Windows, not Linux.

Dependencies are installed explicitly by CI before this script. No data, secrets,
credentials or user databases are read. Runtime notices come from installed
components or version-matched upstream copies, never a new project license.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TCLTK_NOTICE_HASHES = {
    "Tcl": "c0a69a2bfd757361ec7e6143973b103c90409316b49e9c88db26ad6388e79f16",
    "Tk": "2cde822b93ca16ae535c954b7dfe658b4ad10df2a193628d1b358f1765e8b198",
}
PYSERIAL_NOTICE_HASH = "f91cb9813de6a5b142b8f7f2dede630b5134160aedaeaf55f4d6a7e2593ca3f3"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def tcltk_notice(name: str, directory: Path, version: str) -> Path:
    for candidate in (directory / "license.terms", directory.parent / "license.terms"):
        if candidate.is_file():
            return candidate
    # CPython's Windows installer can omit the standalone notice files.
    # These exact upstream copies apply only to the runtime version below.
    if version == "8.6.15" and name in TCLTK_NOTICE_HASHES:
        source = ROOT / "packaging/notices/tcltk-8.6.15" / f"{name}-license.terms"
        if source.is_file() and digest(source) == TCLTK_NOTICE_HASHES[name]:
            return source
    raise FileNotFoundError(
        f"{name} license.terms is required for runtime {version}; do not ship without it"
    )


def distribution_notices(name: str, package: importlib.metadata.Distribution) -> list[Path]:
    notices = []
    for item in package.files or ():
        filename = Path(str(item)).name.lower()
        if (any(word in filename for word in ("license", "copying"))
                and filename.endswith((".txt", "license", "copying", ".rst", ".md"))):
            source = Path(package.locate_file(item))
            if source.is_file():
                notices.append(source)
    if notices:
        return notices
    # The published pySerial 3.5 wheel omits its upstream BSD notice.
    if name.lower() == "pyserial" and package.version == "3.5":
        source = ROOT / "packaging/notices/pyserial-3.5/LICENSE.txt"
        if source.is_file() and digest(source) == PYSERIAL_NOTICE_HASH:
            return [source]
    raise FileNotFoundError(
        f"Installed {name} {package.version} has no discoverable version-matched license text"
    )


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
        libraries = {"Tcl": Path(str(root.tk.call("info", "library"))),
                     "Tk": Path(str(root.tk.call("set", "tk_library")))}
        versions = {"Python": platform.python_version(),
                    **{name: str(root.tk.call("package", "provide", name)) for name in libraries}}
    finally:
        root.destroy()
    for name, directory in libraries.items():
        notice = tcltk_notice(name, directory, versions[name])
        shutil.copy2(notice, destination / f"{name}-license.terms")
        if notice.parent == ROOT / "packaging/notices/tcltk-8.6.15":
            shutil.copy2(notice.parent / "SOURCES.json", destination / "TCLTK-NOTICE-SOURCES.json")
    for name in ("pypdf", "pyinstaller", "pyserial", "Pillow"):
        package = importlib.metadata.distribution(name)
        notices = distribution_notices(name, package)
        versions[name] = package.version
        for index, source in enumerate(notices):
            shutil.copy2(source, destination / f"{name}-{index}-{source.name}")
            if source.parent == ROOT / "packaging/notices/pyserial-3.5":
                shutil.copy2(source.parent / "SOURCES.json", destination / "pyserial-NOTICE-SOURCES.json")
    (destination / "COMPONENTS.json").write_text(json.dumps(versions, indent=2) + "\n", encoding="utf-8")


def validate_bundle_file(path: Path, bundle: Path) -> None:
    """Only the exact bundled fictional map may pass the database-file exclusion."""
    if path.is_symlink():
        raise ValueError("Unexpected symlink in the application bundle")
    if path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".mbtiles"}:
        expected = Path("_internal/fieldforge_gps/data/FICTIONAL-MAP.mbtiles")
        source = ROOT / "fieldforge_gps/data/FICTIONAL-MAP.mbtiles"
        if path.relative_to(bundle) != expected or digest(path) != digest(source):
            raise ValueError("Unexpected data file in the application bundle")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--branch-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if (sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}
            or struct.calcsize("P") != 8):
        parser.error("Build on Windows x64 with an x64 Python interpreter")
    if sys.version_info[:3] != (3, 13, 16):
        parser.error("Use the tested Python 3.13.16 runtime for this Windows development bundle")
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
        validate_bundle_file(path, bundle)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in files:
            zipped.write(path, str(Path("FieldForge-Windows") / path.relative_to(bundle)))
    checksum = digest(archive)
    (output / "FieldForge-Windows-x64.sha256").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(f"Verified Windows x64 archive: {archive.name}, {archive.stat().st_size} bytes, SHA-256 {checksum}")


if __name__ == "__main__":
    main()
