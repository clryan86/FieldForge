"""Explicit, read-only place import/search and manual-coordinate controls."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from .place_jobs import LatestPlaceWorker
from .places import manual_place
from .tk_cleanup import TkCleanupMixin


class PlaceSearchFrame(TkCleanupMixin, ttk.Frame):
    def __init__(self, parent, map_frame):
        super().__init__(parent, padding=14)
        self.pack(fill="both", expand=True)
        self.map_frame = map_frame
        self.catalog = None
        self._included_catalog = False
        self._results = ()
        self._job = None
        self._closed = False
        self._after = None
        self.worker = LatestPlaceWorker()
        self.permission = tk.BooleanVar(value=False)
        self.wgs84 = tk.BooleanVar(value=False)
        self.query = tk.StringVar(value="")
        self.status = tk.StringVar(
            value="No place catalogue loaded. No network requests, saved searches, or automatic file scans."
        )
        self.source_info = tk.StringVar(
            value="Catalogue coordinates and names are source claims, not verified locations or addresses."
        )
        self.detail = tk.StringVar(
            value="Select a result explicitly. A matching name does not establish the intended destination."
        )
        self.latitude = tk.StringVar(value="")
        self.longitude = tk.StringVar(value="")
        self.manual_status = tk.StringVar(
            value="Manual decimal degrees: latitude first, longitude second. No GPS fix or route is created."
        )
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)
        ttk.Label(
            self, text="Offline places & coordinates", font=("TkDefaultFont", 20, "bold")
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            self, text="REFERENCE POINTS — NOT LIVE GPS / NOT DIRECTIONS", foreground="#8b4d16"
        ).grid(row=1, column=0, sticky="w", pady=(4, 9))
        consent = ttk.Frame(self)
        consent.grid(row=2, column=0, sticky="ew")
        included = ttk.Frame(consent)
        included.pack(fill="x", pady=(0, 7))
        self.included_button = ttk.Button(
            included, text="Included U.S. towns", command=self.atlas_places
        )
        self.included_button.pack(side="left", padx=(0, 8))
        ttk.Label(included, text="Natural Earth reference points · works offline").pack(side="left")
        self.permission_check = ttk.Checkbutton(
            consent,
            text="I trust this place file, have permission to use it, and consent to reading its contents in memory.",
            variable=self.permission,
        )
        self.wgs84_check = ttk.Checkbutton(
            consent,
            text="These are WGS84 decimal-degree coordinates. GeoJSON positions are longitude, latitude.",
            variable=self.wgs84,
        )
        self.permission_check.pack(anchor="w")
        self.wgs84_check.pack(anchor="w")
        actions = ttk.Frame(self)
        actions.grid(row=3, column=0, sticky="ew", pady=7)
        self.open_button = ttk.Button(
            actions, text="Open place CSV / GeoJSON…", command=self.choose
        )
        self.demo_button = ttk.Button(actions, text="Load fictional places", command=self.example)
        self.clear_button = ttk.Button(actions, text="Clear places / cancel", command=self.clear)
        for button in (self.open_button, self.demo_button, self.clear_button):
            button.pack(side="left", padx=(0, 7))
        search = ttk.Frame(self)
        search.grid(row=4, column=0, sticky="ew", pady=(0, 7))
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text="Name, alias, country / area or region").grid(
            row=0, column=0, padx=(0, 7)
        )
        self.query_entry = ttk.Entry(search, textvariable=self.query)
        self.query_entry.grid(row=0, column=1, sticky="ew")
        self.query_entry.bind("<Return>", lambda _event: self.search())
        self.search_button = ttk.Button(search, text="Search", command=self.search)
        self.search_button.grid(row=0, column=2, padx=(7, 0))
        result_box = ttk.Frame(self)
        result_box.grid(row=5, column=0, sticky="nsew")
        result_box.rowconfigure(0, weight=1)
        result_box.columnconfigure(0, weight=1)
        columns = ("name", "country", "region", "latitude", "longitude")
        self.table = ttk.Treeview(
            result_box, columns=columns, show="headings", selectmode="browse", height=8
        )
        for column, width in zip(columns, (230, 180, 150, 105, 105)):
            self.table.heading(
                column,
                text=column.capitalize() if column != "country" else "Country / area (source)",
            )
            self.table.column(column, width=width, minwidth=70)
        self.table.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(result_box, orient="vertical", command=self.table.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.table.configure(yscrollcommand=scroll.set)
        self.table.bind("<<TreeviewSelect>>", self._selected)
        action = ttk.Frame(self)
        action.grid(row=6, column=0, sticky="ew", pady=7)
        self.show_button = ttk.Button(
            action, text="Show selected place on map", command=self.show_selected
        )
        self.show_button.pack(side="left")
        ttk.Label(action, text="Showing a point does not confirm map coverage or access.").pack(
            side="left", padx=10
        )
        self._fixed_label(7, self.status, 48)
        self._fixed_label(8, self.detail, 52)
        self._fixed_label(9, self.source_info, 48)
        manual = ttk.LabelFrame(
            self, text="Go to a manually entered coordinate — independent of place files", padding=8
        )
        manual.grid(row=10, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(manual, text="Latitude (−90 to 90)").grid(row=0, column=0, padx=(0, 5))
        ttk.Entry(manual, textvariable=self.latitude, width=18).grid(row=0, column=1)
        ttk.Label(manual, text="Longitude (−180 to 180)").grid(row=0, column=2, padx=(12, 5))
        ttk.Entry(manual, textvariable=self.longitude, width=18).grid(row=0, column=3)
        self.manual_button = ttk.Button(manual, text="Show coordinate", command=self.show_manual)
        self.manual_button.grid(row=0, column=4, padx=(10, 0))
        ttk.Label(manual, textvariable=self.manual_status, wraplength=850).grid(
            row=1, column=0, columnspan=5, sticky="w", pady=(5, 0)
        )
        self.permission.trace_add("write", self._permissions)
        self.wgs84.trace_add("write", self._permissions)
        self.query.trace_add("write", self._query_changed)
        self.bind("<Destroy>", self._destroyed, add=True)
        self._buttons()
        self._poll()

    def _fixed_label(self, row, variable, height):
        box = ttk.Frame(self, height=height)
        box.grid(row=row, column=0, sticky="ew")
        box.pack_propagate(False)
        label = ttk.Label(box, textvariable=variable, wraplength=900, anchor="nw")
        label.pack(fill="both", expand=True)
        box.bind("<Configure>", lambda event: label.configure(wraplength=max(200, event.width - 4)))

    def _permitted(self):
        return self.permission.get() and self.wgs84.get()

    def _catalog_permitted(self):
        return self._included_catalog or self._permitted()

    def _buttons(self):
        permitted = self._permitted()
        for button in (self.open_button, self.demo_button):
            button.configure(state="normal" if permitted else "disabled")
        searchable = self._catalog_permitted() and self.catalog is not None
        self.query_entry.configure(state="normal" if searchable else "disabled")
        self.search_button.configure(state="normal" if searchable else "disabled")
        self.show_button.configure(
            state="normal" if searchable and self.table.selection() else "disabled"
        )
        self.clear_button.configure(state="normal" if self.catalog or self._job else "disabled")

    def _permissions(self, *_):
        if not self._catalog_permitted():
            self.clear()
        self._buttons()

    def _clear_results(self):
        self._results = ()
        self.table.delete(*self.table.get_children())
        self.detail.set("Select a result explicitly. No place is selected automatically.")
        self.show_button.configure(state="disabled")

    def _query_changed(self, *_):
        if self._closed:
            return
        if self._job and self._job[1] == "search":
            self.worker.cancel()
            self._job = None
        self._clear_results()
        if self.catalog:
            self.status.set(
                "Search text changed. Press Search; previous results are no longer selectable."
            )

    def choose(self):
        if not self._permitted():
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="Read a trusted WGS84 place file",
            filetypes=[("Place files", "*.csv *.geojson *.json")],
        )
        if path:
            self.start_read(path)

    def example(self):
        return self.start_read(Path(__file__).parent / "data" / "FICTIONAL-PLACES.csv")

    def atlas_places(self):
        return self.open_included()

    def open_included(self):
        if self._closed:
            return False
        from .bundled_atlas import places_path

        return self._start_read(places_path(), included=True)

    def start_read(self, path):
        return self._start_read(path)

    def _start_read(self, path, *, included=False):
        if self._closed or (not included and not self._permitted()):
            if not self._closed:
                self.status.set(
                    "Confirm file permission/privacy and WGS84 first. Nothing was read."
                )
            return False
        self.clear()
        self._included_catalog = included
        token = self.worker.submit("load", path)
        self._job = (token, "load", None)
        self.status.set(
            "Reading the included U.S. town catalogue. No downloads or address lookup."
            if included else
            "Reading the selected place file. Old catalogue and file marker cleared; no downloads."
        )
        self._buttons()
        return True

    def clear(self):
        if self._closed:
            return
        self.worker.cancel()
        self._job = None
        self.catalog = None
        self._included_catalog = False
        self._clear_results()
        self.query.set("")
        self.map_frame.clear_place_marker(file_only=True)
        self.source_info.set(
            "No catalogue retained. Source files, GPX review, map packs, and manual markers are unchanged."
        )
        self.status.set("Place catalogue cleared from memory. This is not secure erasure.")
        self._buttons()

    def search(self):
        if self._closed or not self._catalog_permitted() or self.catalog is None:
            return False
        self._clear_results()
        query = self.query.get()
        token = self.worker.submit("search", self.catalog, query)
        self._job = (token, "search", query)
        self.status.set(
            "Searching only the loaded catalogue. No address lookup or network request."
        )
        return True

    def _poll(self):
        if self._closed:
            return
        result = self.worker.poll()
        if result and self._job and result[0] == self._job[0] and self._catalog_permitted():
            task = self._job
            self._job = None
            _, kind, value, error = result
            if error:
                if kind == "load":
                    self._included_catalog = False
                self.status.set("Place operation failed: " + error)
            elif kind == "load":
                self.catalog = value
                self.status.set(
                    f"{len(value.places):,} named places loaded. Type a name or contextual words, then press Search."
                )
                label = value.declared_name or "Not supplied"
                self.source_info.set(
                    f"Source label (unverified): {label[:100]} · {value.source_bytes:,} bytes · "
                    f"SHA-256 {value.source_sha256[:16]}… · {value.ignored_elevations} elevations ignored. "
                    "A snapshot, not a live file watch; reopen after file changes."
                )
                self.query_entry.focus_set()
            elif kind == "search" and self.catalog and task[2] == self.query.get():
                self._results = value.places
                for index, place in enumerate(value.places):
                    self.table.insert(
                        "",
                        "end",
                        iid=str(index),
                        values=(
                            place.name,
                            place.country,
                            place.region,
                            f"{place.latitude:.6f}",
                            f"{place.longitude:.6f}",
                        ),
                    )
                self.status.set(
                    f"{value.total:,} matches; showing {len(value.places):,} (limit 100). "
                    "Refine the name / country / region to narrow duplicates."
                    if value.query
                    else "Enter a name or contextual words to search."
                )
                # Deliberately do not choose the first result.
            self._buttons()
        self._after = self.after(40, self._poll)

    def _selected_place(self):
        selected = self.table.selection()
        if not selected or not self.catalog or not self._catalog_permitted():
            return None
        try:
            index = int(selected[0])
            return self._results[index] if 0 <= index < len(self._results) else None
        except (ValueError, IndexError):
            return None

    def _selected(self, _event=None):
        if self._closed:
            return
        place = self._selected_place()
        if place:
            self.detail.set(
                f"{place.name} · record {place.ordinal} · source ID: {place.source_id or 'not supplied'} · "
                f"latitude {place.latitude:.8f}, longitude {place.longitude:.8f}. "
                f"Source: {place.source or 'not supplied'}. Coordinates are not a verified address or GPS fix."
            )
        self._buttons()

    def show_selected(self):
        if self._closed:
            return False
        place = self._selected_place()
        if place is None:
            self.status.set("Select a result explicitly first.")
            return False
        try:
            self.map_frame.show_place(place, "FILE PLACE")
        except ValueError as exc:
            self.status.set(str(exc))
            return False
        self.status.set(
            "Selected FILE PLACE centered on the map. No route, access, accuracy, or tile coverage was verified."
        )
        return True

    def show_manual(self):
        if self._closed:
            return False
        try:
            place = manual_place(self.latitude.get(), self.longitude.get())
            self.map_frame.show_place(place, "MANUAL COORDINATE")
        except ValueError as exc:
            self.manual_status.set(str(exc))
            return False
        self.manual_status.set(
            "MANUAL COORDINATE centered. It is not a GPS fix, address match, or route."
        )
        return True

    def destroy(self):
        # Close while children/variables still exist; Tk Destroy events arrive
        # after descendant controls have already been destroyed.
        self.close()
        super().destroy()

    def _destroyed(self, event):
        if event.widget is self:
            self.close()

    def close(self):
        if self._closed:
            return
        self.clear()
        self._closed = True
        self.worker.close()
        if self._after is not None:
            self.after_cancel(self._after)
            self._after = None
        self.latitude.set("")
        self.longitude.set("")
        self.manual_status.set("")
