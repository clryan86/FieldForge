"""Desktop backup, verification, and recovery to a separate database."""

from __future__ import annotations

import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from fieldforge.core.database_archive import export_snapshot, inspect_snapshot, restore_snapshot
from fieldforge.ui.lifecycle import release_tk_references

_LABELS = {
    "household_members": "Household members", "inventory_items": "Inventory items",
    "waypoints": "Waypoints", "incident_entries": "Incident entries", "app_events": "App events",
    "knowledge_articles": "Knowledge articles", "knowledge_annotations": "Notes and bookmark records",
}


class BackupsTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, database_path: str | Path,
                 prepare: Callable[[], bool]) -> None:
        super().__init__(parent, padding=16)
        self.database_path = Path(database_path).expanduser().resolve()
        self.prepare = prepare
        self.busy = False
        self._closed = False
        self._poll_id: str | None = None
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-backup")
        self.bind("<Destroy>", self._destroyed, add=True)
        self.status = tk.StringVar(value="Ready. Make a backup before replacing your working database.")
        ttk.Label(self, text="Backups and recovery", font=("TkDefaultFont", 18, "bold")).pack(anchor="w")
        description = ttk.Label(self, justify="left", wraplength=800, text=(
            "A full backup includes household data, inventory, waypoints, incidents, knowledge articles, "
            "and private notes. Backup files are unencrypted; store them privately.\n\n"
            "Verify a backup to check its integrity and record counts. Restore a copy creates a separate "
            "database for recovery checks; your current database remains active."
        ))
        description.pack(fill="x", pady=(8, 12))
        current = ttk.Label(self, text=f"Current database: {self.database_path}", wraplength=800)
        current.pack(fill="x", pady=(0, 12))
        controls = ttk.Frame(self)
        controls.pack(fill="x")
        self.backup_button = ttk.Button(controls, text="Create full backup", command=self._backup)
        self.backup_button.pack(side="left")
        self.verify_button = ttk.Button(controls, text="Verify backup", command=self._verify)
        self.verify_button.pack(side="left", padx=8)
        self.restore_button = ttk.Button(controls, text="Restore a copy", command=self._restore)
        self.restore_button.pack(side="left")
        status_label = ttk.Label(self, textvariable=self.status, wraplength=800)
        status_label.pack(fill="x", pady=12)
        self.details = ScrolledText(self, state="disabled", wrap="word", font="TkDefaultFont", height=16)
        self.details.pack(fill="both", expand=True)
        self.bind("<Configure>", lambda event: [label.configure(wraplength=max(250, event.width - 32))
                                               for label in (description, current, status_label)], add=True)

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self:
            self._closed = True
            if self._poll_id is not None:
                self.after_cancel(self._poll_id)
                self._poll_id = None
            self._worker.shutdown(wait=False, cancel_futures=True)
            self.prepare = lambda: False
            release_tk_references(self)

    def _source(self) -> str:
        return filedialog.askopenfilename(parent=self, title="Choose a full FieldForge backup",
                                          filetypes=[("Full backup", "*.zip"), ("All files", "*")])

    def _backup(self) -> None:
        if self.busy:
            return
        destination = filedialog.asksaveasfilename(
            parent=self, title="Create full backup", defaultextension=".zip",
            initialfile=f"fieldforge-full-{date.today().isoformat()}.zip",
        )
        if destination:
            self._start("backup", export_snapshot, self.database_path, destination)

    def _verify(self) -> None:
        if self.busy:
            return
        source = self._source()
        if source:
            self._start("verify", inspect_snapshot, source)

    def _restore(self) -> None:
        if self.busy:
            return
        source = self._source()
        if not source:
            return
        destination = filedialog.asksaveasfilename(
            parent=self, title="Choose a new database file for the recovered copy",
            defaultextension=".db", initialfile="fieldforge-recovered.db", confirmoverwrite=False,
        )
        if destination:
            self._start("restore", restore_snapshot, destination, source,
                        protected_database=self.database_path)

    def _start(self, action: str, operation, *args, **kwargs) -> None:
        if self.busy:
            return
        if not self.prepare():
            self.status.set("Finish the active library operation or save your note, then try again.")
            return
        self.busy = True
        for button in (self.backup_button, self.verify_button, self.restore_button):
            button.configure(state="disabled")
        self.status.set("Processing local files…")
        self._text("")
        future = self._worker.submit(operation, *args, **kwargs)
        self._poll_id = self.after(50, self._poll, action, future)

    def _text(self, text: str) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _poll(self, action: str, future: Future) -> None:
        self._poll_id = None
        if self._closed:
            return
        if not future.done():
            self._poll_id = self.after(50, self._poll, action, future)
            return
        self.busy = False
        for button in (self.backup_button, self.verify_button, self.restore_button):
            button.configure(state="normal")
        try:
            result = future.result()
            if action == "verify":
                self.status.set("Backup verified. File integrity, database structure, and record references passed.")
                self._text("Records in this backup\n\n" + "\n".join(
                    f"{_LABELS.get(table, table)}: {count}" for table, count in result["records"].items()
                ) + f"\n\nDatabase size: {result['database_bytes']:,} bytes")
            elif action == "backup":
                self.status.set("Full backup created.")
                self._text(f"Saved to:\n{result}\n\nUse Verify backup to inspect this archive or Restore a copy to test recovery.")
            else:
                self.status.set("Recovered copy created. Your current database is still active.")
                self._text(f"Recovered database:\n{result}\n\nTo use this copy, close FieldForge and launch it with "
                           "FIELDFORGE_DB set to this path. Keep the backup until you have checked your recovered data.")
        except Exception as exc:
            self.status.set("Operation failed. See the details below.")
            self._text(str(exc))
