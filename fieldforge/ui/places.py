"""Offline places workspace: user-entered coordinates, not a map or safe-route tool."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.navigation.places import NOTICE, PlaceStore, coordinate_text, describe_leg, make_place
from fieldforge.ui.place_exchange import PlaceExchangeDialog

_ERRORS = (OSError, ValueError, sqlite3.Error)
_PAGE = 50


class PlaceEditor(tk.Toplevel):
    def __init__(self, parent, store, record=None, *, finished=None):
        super().__init__(parent)
        self.store, self.record, self.finished = store, record, finished
        self.changed = False
        self._disposed = False
        self.title("FieldForge — Edit saved place" if record else "FieldForge — Add a place")
        self.geometry("780x650")
        self.minsize(720, 610)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(6, weight=1)
        point = record.point if record else None
        self.fields = {key: tk.StringVar(value=str(getattr(point, key)) if point else "waypoint" if key == "kind" else "")
                       for key in ("name", "latitude", "longitude", "kind")}
        if point:
            for key in ("latitude", "longitude"):
                self.fields[key].set(coordinate_text(getattr(point, key)))
        self.status = tk.StringVar(value="No location is inferred. Verify WGS 84 coordinates and latitude/longitude order.")
        ttk.Label(self, text="Saved place, not a verified destination", font=("TkDefaultFont", 17, "bold"),
                  padding=16).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(self, text="Enter WGS 84 signed decimal degrees. North/east are positive; south/west are negative. "
                  "Blank is unknown, not zero. This does not find your current location.", wraplength=680,
                  padding=(16, 0, 16, 12), justify="left").grid(row=1, column=0, columnspan=2, sticky="ew")
        for row, (key, label) in enumerate((("name", "Name / alias"), ("latitude", "Latitude (-90 to 90)"),
                                           ("longitude", "Longitude (-180 to 180)"), ("kind", "Type / category")), 2):
            ttk.Label(self, text=label, padding=(16, 6)).grid(row=row, column=0, sticky="w")
            ttk.Entry(self, textvariable=self.fields[key]).grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=6)
        notes = ttk.LabelFrame(self, text="Private place notes — source, access questions, observations (optional)", padding=10)
        notes.grid(row=6, column=0, columnspan=2, sticky="nsew", padx=16, pady=(8, 0))
        self.note = ScrolledText(notes, height=6, width=50, wrap="word")
        self.note.pack(fill="both", expand=True)
        if point:
            self.note.insert("1.0", point.notes)
        ttk.Label(self, text="Names and coordinates are sensitive even without notes. Records and full backups are unencrypted. "
                  "No messages, geocoding or online maps are used.", wraplength=680, padding=(16, 10),
                  justify="left").grid(row=7, column=0, columnspan=2, sticky="ew")
        actions = ttk.Frame(self, padding=(16, 0))
        actions.grid(row=8, column=0, columnspan=2, sticky="ew")
        self.save_button = ttk.Button(actions, text="Save place", command=self.save)
        self.save_button.pack(side="right")
        ttk.Button(actions, text="Cancel", command=self.close).pack(side="right", padx=8)
        self.footer = ttk.Label(self, textvariable=self.status, wraplength=680, padding=16, justify="left")
        self.footer.grid(row=9, column=0, columnspan=2, sticky="ew")
        self.initial = self._values()
        self.grab_set()

    def _values(self):
        return (*(self.fields[key].get() for key in self.fields), self.note.get("1.0", "end-1c"))

    def save(self):
        try:
            point = make_place(**{key: value.get() for key, value in self.fields.items()},
                               notes=self.note.get("1.0", "end-1c"), place_id=self.record.point.id if self.record else None)
            self.store.save(point, expected=self.record)
        except _ERRORS as exc:
            self.status.set("Not saved: " + str(exc))
            return
        self.changed = True
        self.destroy()

    def close(self):
        if self._values() != self.initial and not messagebox.askyesno("Discard unsaved place edits?",
                "Discard these edits? Your saved waypoint remains unchanged.", parent=self):
            return
        self.destroy()

    def _destroyed(self, event):
        if event.widget is self and not self._disposed:
            self._disposed = True
            if self.finished:
                self.finished(self.changed)


class PlacesTab(ttk.Frame):
    def __init__(self, parent, database):
        super().__init__(parent, padding=16)
        self.store = None
        self.dialog = None
        self.records = {}
        self.offset = 0
        self.start_id = self.end_id = None
        self.query = tk.StringVar()
        self.status = tk.StringVar(value="No location access requested; enter or explicitly import your own waypoints.")
        self.start_label = tk.StringVar(value="Start: not chosen")
        self.end_label = tk.StringVar(value="Destination: not chosen")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        ttk.Label(self, text="Places & Bearings", font=("TkDefaultFont", 21, "bold")).grid(row=0, column=0, sticky="w")
        self.notice = ttk.Label(self, text=NOTICE, wraplength=1140, justify="left")
        self.notice.grid(row=1, column=0, sticky="ew", pady=(6, 12))
        controls = ttk.Frame(self)
        controls.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self.search = ttk.Entry(controls, textvariable=self.query, width=20)
        self.search.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.search.bind("<Return>", lambda _: self.refresh())
        self.refresh_button = ttk.Button(controls, text="Search / Refresh", command=self.refresh)
        self.refresh_button.pack(side="left")
        self.add_button = ttk.Button(controls, text="Add place…", command=self.add)
        self.add_button.pack(side="left", padx=6)
        self.edit_button = ttk.Button(controls, text="Edit…", command=self.edit)
        self.edit_button.pack(side="left")
        self.remove_button = ttk.Button(controls, text="Remove…", command=self.remove)
        self.remove_button.pack(side="left", padx=6)
        self.import_button = ttk.Button(controls, text="Import GPX…", command=self.import_gpx)
        self.import_button.pack(side="left")
        self.export_button = ttk.Button(controls, text="Export selected…", command=self.export_gpx)
        self.export_button.pack(side="left", padx=(6, 0))
        main = ttk.Panedwindow(self, orient="horizontal")
        main.grid(row=3, column=0, sticky="nsew")
        left, right = ttk.Frame(main), ttk.Notebook(main)
        main.add(left, weight=3)
        main.add(right, weight=2)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(left, columns=("name", "lat", "lon", "kind"), show="headings", height=7, selectmode="extended")
        for key, label, width in (("name", "Place / alias", 190), ("lat", "Latitude", 110), ("lon", "Longitude", 110), ("kind", "Type", 100)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=80)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(left, command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.select())
        pager = ttk.Frame(left)
        pager.grid(row=2, column=0, columnspan=2, sticky="ew", pady=8)
        self.previous = ttk.Button(pager, text="Previous", command=lambda: self.page(-1))
        self.previous.pack(side="left")
        self.next = ttk.Button(pager, text="Next", command=lambda: self.page(1))
        self.next.pack(side="left", padx=6)
        ttk.Label(left, text="Search names/types. Use Ctrl/Shift to select multiple places for GPX export.",
                  wraplength=450).grid(row=3, column=0, columnspan=2, sticky="ew")
        details, leg = ttk.Frame(right, padding=10), ttk.Frame(right, padding=10)
        right.add(details, text="Place details")
        right.add(leg, text="Distance & bearing")
        self.tabs = right
        self.details = ScrolledText(details, wrap="word", height=10, width=30, state="disabled")
        self.details.pack(fill="both", expand=True)
        ttk.Label(leg, textvariable=self.start_label, wraplength=350).pack(anchor="w")
        self.start_button = ttk.Button(leg, text="Use selected place as start", command=lambda: self.endpoint(True))
        self.start_button.pack(anchor="w", pady=(4, 10))
        ttk.Label(leg, textvariable=self.end_label, wraplength=350).pack(anchor="w")
        self.end_button = ttk.Button(leg, text="Use selected place as destination", command=lambda: self.endpoint(False))
        self.end_button.pack(anchor="w", pady=(4, 10))
        self.calculate_button = ttk.Button(leg, text="Calculate from saved coordinates", command=self.calculate)
        self.calculate_button.pack(anchor="w", pady=(0, 10))
        self.result = ScrolledText(leg, height=7, width=30, wrap="word", state="disabled")
        self.result.pack(fill="both", expand=True)
        self.footer = ttk.Label(self, textvariable=self.status, wraplength=1100, justify="left")
        self.footer.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self.bind("<Configure>", self._resize, add=True)
        self._has_next = False
        try:
            self.store = PlaceStore(database)
            self.refresh()
        except _ERRORS as exc:
            self.status.set("Places unavailable; no records reset. " + str(exc))
            self._buttons()

    def _resize(self, event):
        if event.widget is self:
            for label in (self.notice, self.footer):
                label.configure(wraplength=max(400, event.width-40))

    @staticmethod
    def _text(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def selected(self):
        ids = self.tree.selection()
        return self.records.get(ids[0]) if len(ids) == 1 else None

    def _buttons(self):
        idle = self.dialog is None and self.store is not None
        for button in (self.add_button, self.import_button):
            button.configure(state="normal" if idle else "disabled")
        for button in (self.edit_button, self.remove_button, self.start_button, self.end_button):
            button.configure(state="normal" if idle and self.selected() else "disabled")
        self.export_button.configure(state="normal" if idle and self.tree.selection() else "disabled")
        self.calculate_button.configure(state="normal" if idle and self.start_id and self.end_id else "disabled")
        self.previous.configure(state="normal" if idle and self.offset else "disabled")
        self.next.configure(state="normal" if idle and self._has_next else "disabled")

    def refresh(self, *, reset=True):
        if self.dialog is not None or self.store is None:
            return
        self._text(self.result, "Recalculate after checking the saved endpoint coordinates.")
        self.tree.delete(*self.tree.get_children())
        self.records = {}
        self._has_next = False
        if reset:
            self.offset = 0
        try:
            if len(self.query.get()) > 200:
                raise ValueError("Place search must be at most 200 characters.")
            snapshot = self.store.snapshot()
            term = self.query.get().strip().casefold()
            found = [r for r in snapshot.records if term in (r.point.name + " " + r.point.kind).casefold()]
            self.records = {str(r.point.id): r for r in found[self.offset:self.offset+_PAGE]}
            for key, record in self.records.items():
                p = record.point
                self.tree.insert("", "end", iid=key, values=(p.name, p.latitude, p.longitude, p.kind))
            self._has_next = len(found) > self.offset+_PAGE
            self.status.set(f"{len(snapshot.records)} saved places · {len(found)} match · page {self.offset//_PAGE+1}. "
                            "No maps/GPS or safe-route assessment. Stored locations are private, unencrypted records.")
        except _ERRORS as exc:
            self.status.set("Could not refresh places: " + str(exc))
        self.select()

    def page(self, direction):
        if self.dialog is None:
            self.offset = max(0, self.offset+direction*_PAGE)
            self.refresh(reset=False)

    def select(self):
        record = self.selected()
        if record:
            p = record.point
            self._text(self.details, f"{p.name}\nType: {p.kind}\nID: {p.id}\n\n"
                       f"Latitude: {p.latitude}\nLongitude: {p.longitude}\nAssumed WGS 84; confirm the source/datum.\n\n"
                       f"Private place notes:\n{p.notes or '(none)'}\n\nChoosing a meeting point does not notify anyone or verify access/safety.")
        else:
            self._text(self.details, "Select one place to read/edit it, or multiple places to export. "
                       "No locations are seeded from your accounts or conversations.")
        self._buttons()

    def _finished(self, _changed=False):
        self.dialog = None
        if self.winfo_exists() and self.tree.winfo_exists() and self.result.winfo_exists():
            self.refresh()

    def add(self):
        if self.dialog is None and self.store:
            self.dialog = PlaceEditor(self, self.store, finished=self._finished)
            self._buttons()

    def edit(self):
        if self.dialog is None and self.selected():
            self.dialog = PlaceEditor(self, self.store, self.selected(), finished=self._finished)
            self._buttons()

    def remove(self):
        record = self.selected()
        if self.dialog is not None or record is None:
            return
        if not messagebox.askyesno("Remove this saved place?", "Delete this waypoint and its private notes from the current database? "
                                  "External GPX files and old backups remain unchanged. This is not secure erasure.", parent=self):
            return
        try:
            self.store.remove(record)
            self.refresh()
            self.status.set("Place removed. No external files or prior backups were changed.")
        except _ERRORS as exc:
            self._text(self.result, "Recalculate after refreshing saved places.")
            self.status.set("Not removed: " + str(exc))

    def endpoint(self, start):
        record = self.selected()
        if record and self.dialog is None:
            caption = f"{record.point.name[:65]} [ID {record.point.id}]"
            if start:
                self.start_id = record.point.id
                self.start_label.set("Start: " + caption)
            else:
                self.end_id = record.point.id
                self.end_label.set("Destination: " + caption)
            self._text(self.result, "Inputs changed. Calculate to read the latest saved coordinates together.")
            self._buttons()

    def calculate(self):
        if self.dialog is not None or not self.start_id or not self.end_id:
            return
        self._text(self.result, "")
        try:
            leg = self.store.estimate(self.start_id, self.end_id)
            self.start_label.set("Start: " + leg.start.name[:65])
            self.end_label.set("Destination: " + leg.end.name[:65])
            self._text(self.result, describe_leg(leg))
        except _ERRORS as exc:
            self._text(self.result, "No estimate available. " + str(exc))

    def import_gpx(self):
        if self.dialog is None and self.store:
            self.dialog = PlaceExchangeDialog(self, self.store, finished=self._finished)
            self._buttons()

    def export_gpx(self):
        if self.dialog is None and self.tree.selection():
            ids = tuple(int(key) for key in self.tree.selection())
            self.dialog = PlaceExchangeDialog(self, self.store, ids=ids, finished=self._finished)
            self._buttons()

    def can_close(self):
        if self.dialog is not None:
            messagebox.showinfo("Place editor or GPX dialog open", "Save or close the Places dialog before closing or backing up.", parent=self)
            return False
        return True
