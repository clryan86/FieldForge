"""Backup/recovery UI. All archive/database work runs outside the Tk thread."""

from __future__ import annotations

import os
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from fieldforge.core.recovery import (
    NOTICE,
    BackupPreview,
    create_verified_backup,
    inspect_backup,
    launch_recovered_copy,
    render_preview,
    restore_verified_copy,
)


class RecoveryTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, database: str | Path, *,
                 before_backup: Callable[[], bool] | None = None) -> None:
        super().__init__(parent, padding=16)
        self.database = Path(database).expanduser().resolve()
        self.before_backup = before_backup
        self.preview: BackupPreview | None = None
        self.recovered: Path | None = None
        self.busy = False
        self._disposed = False
        self._poll_id: str | None = None
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-recovery")
        self.status = tk.StringVar(value="Ready. No backup operation has been run in this window.")
        self.location = tk.StringVar(value=str(self.database))
        self.result_title = tk.StringVar(value="Your recovery check will appear here")
        self.bind("<Destroy>", self._destroyed, add=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Backup & Recovery", font=("TkDefaultFont", 21, "bold")).pack(anchor="w")
        ttk.Label(header, text="Save a copy. Check it. Recover without replacing your current work.",
                  font=("TkDefaultFont", 11)).pack(anchor="w", pady=(4, 12))
        location = ttk.LabelFrame(self, text="Database used by this window", padding=10)
        location.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        location.columnconfigure(0, weight=1)
        ttk.Entry(location, textvariable=self.location, state="readonly").grid(row=0, column=0, sticky="ew")
        ttk.Button(location, text="Copy path", command=self.copy_active_path).grid(row=0, column=1, padx=(8, 0))

        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1, uniform="actions")
        actions.columnconfigure(1, weight=1, uniform="actions")
        save = ttk.LabelFrame(actions, text="1 · Protect your current work", padding=12)
        save.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.save_button = ttk.Button(save, text="Create verified backup…", command=self.create)
        self.save_button.pack(anchor="w")
        self.save_help = ttk.Label(save, text="Saves pending article/learning notes in this app, then creates a new "
                                   ".ffbackup file and tests reading it back. Existing files are never replaced.",
                                   wraplength=420, justify="left")
        if self.before_backup is None:
            self.save_help.configure(text="Creates and read-back checks a new .ffbackup file from committed "
                                     "database records. Save notes in other windows first; unsaved edits are not included.")
        self.save_help.pack(fill="x", pady=(8, 0))
        recover = ttk.LabelFrame(actions, text="2 · Check a trusted backup", padding=12)
        recover.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.inspect_button = ttk.Button(recover, text="Inspect backup…", command=self.inspect)
        self.inspect_button.pack(anchor="w")
        self.inspect_help = ttk.Label(recover, text="Checks a .ffbackup archive and shows record counts without "
                                      "opening your current database. Restore creates a separate database file.",
                                      wraplength=420, justify="left")
        self.inspect_help.pack(fill="x", pady=(8, 0))
        self.notice = ttk.Label(self, text=NOTICE, wraplength=950, justify="left")
        self.notice.grid(row=3, column=0, sticky="ew", pady=12)

        results = ttk.LabelFrame(self, text="Verification & recovery report", padding=10)
        results.grid(row=4, column=0, sticky="nsew")
        ttk.Label(results, textvariable=self.result_title, font=("TkDefaultFont", 11, "bold"),
                  wraplength=850).pack(anchor="w", pady=(0, 8))
        self.report = ScrolledText(results, height=12, width=60, wrap="word", state="disabled",
                                   font=("TkDefaultFont", 11))
        self.report.pack(fill="both", expand=True)
        self._text("No archive has been checked yet.\n\nCreate a backup from this window's database, or inspect "
                   "a trusted existing backup. Successful checks show counts only—not the private record text.\n\n"
                   "Recovery never overwrites the active database. The current window stays on its original "
                   "database; opening a recovered copy requires a separate explicit action.")
        controls = ttk.Frame(self)
        controls.grid(row=5, column=0, sticky="ew", pady=(10, 6))
        self.restore_button = ttk.Button(controls, text="Restore to NEW database…", command=self.restore, state="disabled")
        self.restore_button.pack(side="left")
        self.open_button = ttk.Button(controls, text="Open recovered copy", command=self.open_recovered, state="disabled")
        self.open_button.pack(side="left", padx=8)
        self.copy_button = ttk.Button(controls, text="Copy recovered path", command=self.copy_recovered_path, state="disabled")
        self.copy_button.pack(side="left")
        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.grid(row=6, column=0, sticky="ew", pady=(4, 6))
        self.footer = ttk.Label(self, textvariable=self.status, wraplength=950, justify="left")
        self.footer.grid(row=7, column=0, sticky="ew")
        self.bind("<Configure>", self._resize, add=True)

    def _resize(self, event):
        if event.widget is self:
            for label in (self.notice, self.footer):
                label.configure(wraplength=max(300, event.width - 40))
            for label in (self.save_help, self.inspect_help):
                label.configure(wraplength=max(240, event.width // 2 - 60))

    def _text(self, value):
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", value)
        self.report.configure(state="disabled")

    def _controls(self):
        for button in (self.save_button, self.inspect_button):
            button.configure(state="disabled" if self.busy else "normal")
        self.restore_button.configure(state="normal" if self.preview and not self.busy else "disabled")
        for button in (self.open_button, self.copy_button):
            button.configure(state="normal" if self.recovered and not self.busy else "disabled")

    def _reset(self):
        self.preview = None
        self.recovered = None
        self.result_title.set("Checking…")
        self._text("")
        self._controls()

    def _start(self, operation, function, *args, **kwargs):
        self.busy = True
        self._controls()
        self.progress.start(12)
        self.status.set("Working locally. Please let this operation finish before closing the application.")
        future = self._worker.submit(function, *args, **kwargs)
        self._poll_id = self.after(60, self._poll, future, operation)

    def create(self):
        if self.busy:
            return
        if not messagebox.askyesno("Private backup", NOTICE + "\n\nCreate a new private backup?", parent=self):
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Save a NEW private backup", defaultextension=".ffbackup",
            initialfile=datetime.now().strftime("FieldForge-%Y%m%d-%H%M%S.ffbackup"),
            filetypes=[("FieldForge backup", "*.ffbackup")],
        )
        if not path:
            return
        try:
            if self.before_backup is not None and not self.before_backup():
                self.status.set("Backup not started: finish current operations and resolve any unsaved-note error first.")
                return
        except Exception as exc:
            self.status.set("Backup not started; saving current notes failed: " + str(exc))
            return
        self._reset()
        self._start("backup", create_verified_backup, self.database, path)

    def inspect(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self, title="Inspect a trusted FieldForge backup",
                                          filetypes=[("FieldForge backup", "*.ffbackup")])
        if not path:
            return
        self._reset()  # A failed new inspection must not leave an older restore action enabled.
        if not messagebox.askyesno("Trusted source required", "Only inspect backups you trust. Integrity checks "
                                   "do not authenticate an archive's creator. This operation uses temporary disk "
                                   "space but does not open your current database. Continue?", parent=self):
            self.result_title.set("Inspection not started")
            self.status.set("No backup selected for recovery.")
            return
        self._start("inspect", inspect_backup, path)

    def restore(self):
        if self.busy or self.preview is None:
            return
        path = filedialog.asksaveasfilename(parent=self, title="Restore as a NEW database file",
                                           defaultextension=".db", initialfile="fieldforge-recovered.db",
                                           filetypes=[("SQLite database", "*.db")])
        if not path:
            return
        if not messagebox.askyesno("Restore a separate copy?", f"From:\n{self.preview.source}\n\nTo NEW file:\n{path}"
                                   "\n\nYour current database and default settings will not be replaced. "
                                   "The backup will be checked again before recovery. Continue?", parent=self):
            return
        self.recovered = None
        self._start("restore", restore_verified_copy, self.preview, path, active_database=self.database)

    def _poll(self, future: Future, operation: str):
        if self._disposed:
            return
        self._poll_id = None
        if not future.done():
            self._poll_id = self.after(60, self._poll, future, operation)
            return
        self.busy = False
        self.progress.stop()
        try:
            result = future.result()
            if operation == "restore":
                self.recovered = result
                self.result_title.set("Recovery copy created — current database unchanged")
                self._text(f"RECOVERED COPY\n{result}\n\nCURRENT WINDOW STILL USES\n{self.database}\n\n"
                           "Use Open recovered copy to request a separate application window. "
                           "This does not change which database the usual launcher opens.\n\n" + render_preview(self.preview))
                self.status.set("Recovery finished. Original data and default database settings were not replaced.")
            else:
                self.preview = result
                self.result_title.set("New backup saved and read-back checked" if operation == "backup" else "Backup inspection passed")
                self._text(render_preview(result))
                self.status.set("Archive bytes and SQLite structure checked. Content accuracy and every individual record were not verified.")
        except Exception as exc:
            self.preview = None
            self.recovered = None
            self.result_title.set("Operation failed — no success claimed")
            self._text("The operation did not complete. No existing database or backup was replaced by this screen.\n\n" + str(exc))
            self.status.set("Error: " + str(exc))
        self._controls()

    def open_recovered(self):
        if self.busy or self.recovered is None:
            return
        if not messagebox.askyesno("Open a separate FieldForge window?", f"Open:\n{self.recovered}\n\n"
                                   "This window stays on the original database. The usual launcher's default "
                                   "will not change. Any edits in the new window belong to that recovered copy.", parent=self):
            return
        try:
            launch_recovered_copy(self.recovered)
            self.status.set("Separate-window launch requested. Check that it opens; the default database has not changed.")
        except (OSError, ValueError) as exc:
            self.status.set("Could not request the recovered window: " + str(exc))

    def _copy(self, path):
        try:
            self.clipboard_clear()
            self.clipboard_append(str(path))
            self.status.set("Path copied to the system clipboard. It may contain your local username.")
        except tk.TclError as exc:
            self.status.set("Could not copy path: " + str(exc))

    def copy_active_path(self):
        self._copy(self.database)

    def copy_recovered_path(self):
        if not self.busy and self.recovered is not None:
            self._copy(self.recovered)

    def can_close(self) -> bool:
        if self.busy:
            messagebox.showinfo("Backup operation in progress", "Let the backup, inspection, or recovery finish "
                                "before closing this window.", parent=self)
            return False
        return True

    def _destroyed(self, event):
        if event.widget is self and not self._disposed:
            self._disposed = True
            if self._poll_id is not None:
                self.after_cancel(self._poll_id)
                self._poll_id = None
            self._worker.shutdown(wait=False, cancel_futures=True)


def add_recovery_tab(notebook, database, knowledge_tab, pathways_tab) -> RecoveryTab:
    def save_before_backup():
        return (not knowledge_tab.busy and knowledge_tab.save_current() and pathways_tab.save_current())

    frame = RecoveryTab(notebook, database, before_backup=save_before_backup)
    notebook.add(frame, text="Backup & Recovery")
    return frame


def run() -> None:
    # Deliberately does NOT initialize/read the current database. A broken or
    # missing current database must not prevent inspecting a recovery archive.
    root = tk.Tk()
    root.title("FieldForge — Backup & Recovery")
    root.geometry("1080x800")
    root.minsize(850, 700)
    frame = RecoveryTab(root, Path(os.environ.get("FIELDFORGE_DB", "~/.fieldforge/fieldforge.db")))
    frame.pack(fill="both", expand=True)
    root.protocol("WM_DELETE_WINDOW", lambda: root.destroy() if frame.can_close() else None)
    root.mainloop()


if __name__ == "__main__":
    run()
