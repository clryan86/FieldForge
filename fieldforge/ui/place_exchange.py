"""Preview-first private waypoint GPX exchange; workers never access Tk widgets."""

from __future__ import annotations

import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.navigation.gpx import (
    EXPORT_NOTICE,
    IMPORT_NOTICE,
    capture_export,
    commit_import,
    preview_import,
    read_gpx,
    save_gpx,
)


def _read(store, path):
    return preview_import(store, read_gpx(path))


class PlaceExchangeDialog(tk.Toplevel):
    def __init__(self, parent, store, *, ids=None, finished=None):
        super().__init__(parent)
        self.store, self.ids, self.finished = store, ids, finished
        self.importing = ids is None
        self.preview = None
        self.changed = False
        self.busy = ""
        self._disposed = False
        self._poll_id = None
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-gpx")
        self.title("FieldForge — GPX waypoint import" if self.importing else "FieldForge — GPX waypoint export")
        self.geometry("980x760")
        self.minsize(880, 680)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.notes = tk.BooleanVar(value=False)
        self.permission = tk.BooleanVar(value=False)
        self.summary = tk.StringVar(value="Choose a file to preview; no places are imported automatically.")
        self.status = tk.StringVar(value="GPX waypoint exchange does not include maps, routes or a safety assessment.")
        ttk.Label(self, text="Bring in waypoints" if self.importing else "Take selected places with you",
                  font=("TkDefaultFont", 20, "bold"), padding=16).grid(row=0, column=0, sticky="w")
        self.notice = ttk.Label(self, text=IMPORT_NOTICE if self.importing else EXPORT_NOTICE,
                                wraplength=910, justify="left", padding=(16, 0, 16, 12))
        self.notice.grid(row=1, column=0, sticky="ew")
        controls = ttk.Frame(self, padding=(16, 0, 16, 10))
        controls.grid(row=2, column=0, sticky="ew")
        self.choose_button = ttk.Button(controls, text="Choose GPX file…" if self.importing else "Build export preview",
                                         command=self.choose)
        self.choose_button.pack(side="left")
        self.recheck_button = ttk.Button(controls, text="Recheck captured import", command=self.recheck)
        if self.importing:
            self.recheck_button.pack(side="left", padx=8)
        self.notes_box = ttk.Checkbutton(controls, text="Include private place notes in this exported copy",
                                         variable=self.notes)
        if not self.importing:
            self.notes_box.pack(side="left", padx=12)
        main = ttk.Frame(self, padding=(16, 0))
        main.grid(row=3, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        self.summary_label = ttk.Label(main, textvariable=self.summary, wraplength=900, justify="left")
        self.summary_label.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.tree = ttk.Treeview(main, columns=("name", "lat", "lon", "state"), show="headings", selectmode="browse", height=8)
        for key, label, width in (("name", "Place", 300), ("lat", "Latitude", 130), ("lon", "Longitude", 130),
                                  ("state", "Import action" if self.importing else "Notes", 210)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=80)
        self.tree.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(main, command=self.tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.details = ScrolledText(main, wrap="word", height=5, state="disabled")
        self.details.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.select())
        bottom = ttk.Frame(self, padding=16)
        bottom.grid(row=4, column=0, sticky="ew")
        self.consent = ttk.Checkbutton(bottom, variable=self.permission, command=self._buttons,
                                       text="I trust the input and understand the import limits and local storage notice." if self.importing else
                                       "I intend to disclose these names/coordinates and any opted-in notes in an unencrypted file.")
        self.consent.pack(anchor="w", pady=(0, 8))
        actions = ttk.Frame(bottom)
        actions.pack(fill="x")
        self.action_button = ttk.Button(actions, text="Import previewed waypoints" if self.importing else "Save NEW GPX…",
                                         command=self.act)
        self.action_button.pack(side="left")
        self.close_button = ttk.Button(actions, text="Close", command=self.close)
        self.close_button.pack(side="right")
        self.footer = ttk.Label(bottom, textvariable=self.status, wraplength=900, justify="left")
        self.footer.pack(fill="x", pady=(8, 0))
        self.bind("<Configure>", self._resize, add=True)
        self.notes.trace_add("write", lambda *_: self.invalidate())
        self._buttons()
        self.grab_set()
        if not self.importing:
            self.choose()

    def _resize(self, event):
        if event.widget is self:
            for label in (self.notice, self.summary_label, self.footer):
                label.configure(wraplength=max(400, event.width-50))

    def _text(self, value):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", value)
        self.details.configure(state="disabled")

    def invalidate(self):
        self.preview = None
        self.permission.set(False)
        self.tree.delete(*self.tree.get_children())
        self._text("")
        self.summary.set("Build a new preview. No database or file changes have been made.")
        self._buttons()

    def _buttons(self):
        for control in (self.choose_button, self.notes_box, self.consent):
            control.configure(state="disabled" if self.busy else "normal")
        valid = self.preview is not None and (not self.importing or not self.preview.conflicts)
        self.action_button.configure(state="normal" if valid and self.permission.get() and not self.busy else "disabled")
        self.recheck_button.configure(state="normal" if self.importing and self.preview and not self.busy else "disabled")
        self.close_button.configure(state="disabled" if self.busy == "write" else "normal")

    def choose(self):
        if self.busy:
            return
        if self.importing:
            path = filedialog.askopenfilename(parent=self, title="Preview a trusted UTF-8 GPX 1.1 waypoint file",
                                              filetypes=[("GPX waypoints", "*.gpx")])
            if path:
                self.load_path(path)
        else:
            self.invalidate()
            self._start("preview", capture_export, self.store, self.ids, include_notes=self.notes.get())

    def load_path(self, path):
        if not self.busy:
            self.invalidate()
            self._start("preview", _read, self.store, path)

    def recheck(self):
        if self.importing and self.preview and not self.busy:
            captured = self.preview.captured
            self.invalidate()
            self._start("preview", preview_import, self.store, captured)

    def select(self):
        selected = self.tree.selection()
        if self.preview is None or not selected:
            return
        points = self.preview.captured.points if self.importing else self.preview.points
        point = points[int(selected[0])]
        self._text(f"{point.name}\nType: {point.kind}\nLatitude: {point.latitude} / Longitude: {point.longitude}\n"
                   + ("Description becomes a private place note:\n" if self.importing else
                      "Opted-in private note:\n" if self.preview.include_notes else "Private notes excluded.\n")
                   + point.notes)

    def act(self):
        if self.busy or not self.permission.get() or self.preview is None:
            return
        if self.importing:
            if self.preview.conflicts:
                return
            self._start("write", commit_import, self.store, self.preview, acknowledged=True)
        else:
            path = filedialog.asksaveasfilename(parent=self, title="Save a NEW unencrypted GPX file",
                                               initialfile="FieldForge-places.gpx", defaultextension=".gpx",
                                               filetypes=[("GPX waypoints", "*.gpx")])
            if path:
                self._start("write", save_gpx, self.preview, path, acknowledged=True)

    def _start(self, operation, function, *args, **kwargs):
        self.busy = operation
        self._buttons()
        self.status.set("Processing local waypoint data…")
        future = self._worker.submit(function, *args, **kwargs)
        self._poll_id = self.after(50, self._poll, future, operation)

    def _poll(self, future: Future, operation):
        if self._disposed:
            return
        self._poll_id = None
        if not future.done():
            self._poll_id = self.after(50, self._poll, future, operation)
            return
        self.busy = ""
        try:
            result = future.result()
            if operation == "preview":
                self.preview = result
                if self.importing:
                    points = result.captured.points
                    omitted = "; ".join(result.captured.omitted) or "None detected"
                    self.summary.set(f"{result.captured.filename}: {result.added} new, {result.duplicates} exact duplicates, "
                                     f"{result.conflicts} same-name conflicts. All conflicts block import.\n"
                                     f"Not retained: {omitted}. Generated names: {result.captured.generated_names}.\n"
                                     f"Captured file SHA-256: {result.captured.sha256}")
                    states = result.states
                else:
                    points = result.points
                    states = ("INCLUDED" if result.include_notes else "Excluded",) * len(points)
                    self.summary.set(f"{len(points)} selected places captured. Private notes: "
                                     f"{'INCLUDED' if result.include_notes else 'excluded'}. Later edits do not change this preview.\n"
                                     "+180 longitude is exported as the equivalent -180 meridian required by GPX 1.1.")
                for i, (point, state) in enumerate(zip(points, states)):
                    self.tree.insert("", "end", iid=str(i), values=(point.name, point.latitude, point.longitude, state))
                self.tree.selection_set("0")
                self.select()
                self.status.set("Preview ready. Check every location and the field omissions before confirming.")
            elif self.importing:
                self.changed = self.changed or result[0] > 0
                self.invalidate()
                self.status.set(f"Imported {result[0]} new waypoints; {result[1]} exact duplicates skipped. Existing places were not replaced.")
            else:
                self.status.set(f"Saved {result.byte_count:,} bytes to {result.path}. No GPS app, map or browser was opened.")
        except Exception as exc:
            self.status.set("Operation failed: " + str(exc))
        self._buttons()

    def close(self):
        if self.busy == "write":
            self.status.set("Wait for the write operation to finish before closing.")
            return
        self.destroy()

    def _destroyed(self, event):
        if event.widget is self and not self._disposed:
            self._disposed = True
            if self._poll_id is not None:
                self.after_cancel(self._poll_id)
            self._worker.shutdown(wait=False, cancel_futures=True)
            if self.finished:
                self.finished(self.changed)
