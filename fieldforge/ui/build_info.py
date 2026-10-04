"""Build identity and actual data location, readable without network or telemetry."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.runtime import build_identity, packaged


def description(database: str | Path) -> str:
    identity = build_identity()
    return ("FIELDFORGE — DEVELOPMENT BUILD\n\n"
            f"Version: {identity['version']}\nBuild type: {identity['target']}\n"
            f"Tested source commit: {identity['source_commit']}\nBranch commit: {identity['branch_commit']}\n\n"
            f"DATABASE USED BY THIS WINDOW\n{Path(database).expanduser().resolve()}\n\n"
            "Your database is not inside the portable application folder by default. "
            "Keeping the program on a USB drive does not move household data onto that drive. "
            "Deleting or replacing the application folder does not erase your database.\n\n"
            "Use Backup & Recovery to create and check a full database backup before updating. "
            "External map files are not included in database backups. Original PDFs are included "
            "only when explicitly stored through Original PDFs. Databases and backups are unencrypted.\n\n"
            "The packaged Windows app includes Python, Tk and the PDF text parser. "
            "Keep FieldForge.exe, FieldForgeTools.exe and the _internal folder together. "
            "The source edition still requires its own Python/Tk installation.\n\n"
            "No automatic updater, cloud sync, administrator installation, native mobile client or "
            "local AI model is provided by this package. Source labels are not independent expert review. "
            "Unsigned development builds are not a verified publisher certificate. "
            "Only run a download you trust; do not disable Windows security protection.\n\n"
            "Build identifiers are embedded labels, not cryptographic proof of authenticity. "
            "The build archive has a separately recorded SHA-256 for byte comparison. "
            "Nothing in this window is transmitted or copied automatically.")


def show_build_info(root, database):
    window = tk.Toplevel(root)
    window.title("FieldForge — Build & data location")
    window.geometry("850x680")
    window.minsize(650, 480)
    window.transient(root)
    text = ScrolledText(window, wrap="word", padx=18, pady=18, font=("TkDefaultFont", 11))
    text.pack(fill="both", expand=True, padx=10, pady=10)
    text.insert("1.0", description(database))
    text.configure(state="disabled")
    ttk.Button(window, text="Close", command=window.destroy).pack(anchor="e", padx=12, pady=(0, 12))
    return window


def install_help_menu(root, database):
    bar = tk.Menu(root)
    help_menu = tk.Menu(bar, tearoff=False)
    help_menu.add_command(label="Build & data location…", command=lambda: show_build_info(root, database))
    bar.add_cascade(label="Help", menu=help_menu)
    root.configure(menu=bar)
    if packaged():
        # A windowed EXE has no stderr console. Make callback errors visible locally.
        def report(kind, value, _traceback):
            messagebox.showerror("FieldForge operation failed", f"{kind.__name__}: {value}\n\n"
                                 "The operation failed. No automatic repair was attempted. "
                                 "Keep any visible edits and check your data before continuing.", parent=root)
        root.report_callback_exception = report
    return bar
