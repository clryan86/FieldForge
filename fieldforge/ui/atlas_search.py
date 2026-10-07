"""Browse and search the application's bundled public town catalogue."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from fieldforge_gps.bundled_atlas import places_path
from fieldforge_gps.place_jobs import LatestPlaceWorker
from fieldforge_gps.places import MAX_RESULTS
from fieldforge_gps.tk_cleanup import TkCleanupMixin


class AtlasSearchFrame(TkCleanupMixin, ttk.Frame):
    """Read only included data; never touch saved places or a receiver."""

    def __init__(self, parent, on_show):
        super().__init__(parent, padding=16)
        self.pack(fill="both", expand=True)
        self.on_show = on_show
        self.catalog = None
        self._results = ()
        self._job = None
        self._after = None
        self._closed = False
        self.worker = LatestPlaceWorker()
        self.query = tk.StringVar()
        self.status = tk.StringVar(value="Loading towns included with the application…")
        self.detail = tk.StringVar(value="Select a town to read its source and show it on the atlas.")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        ttk.Label(self, text="Find included U.S. towns", font=("TkDefaultFont", 19, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        notice = ttk.Label(
            self,
            text="Natural Earth · selected towns stored in this app · works offline. "
                 "This catalogue is a selection, not an address directory. "
                 "The included atlas has no street detail or route guidance.",
            wraplength=820, justify="left",
        )
        notice.grid(row=1, column=0, sticky="ew", pady=(6, 12))
        self.bind("<Configure>", lambda e: notice.configure(wraplength=max(300, e.width - 32)))
        search = ttk.Frame(self)
        search.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text="Town, state or area").grid(row=0, column=0, padx=(0, 8))
        self.query_entry = ttk.Entry(search, textvariable=self.query)
        self.query_entry.grid(row=0, column=1, sticky="ew")
        self.query_entry.bind("<Return>", lambda _event: self.search())
        self.search_button = ttk.Button(search, text="Search", command=self.search)
        self.search_button.grid(row=0, column=2, padx=(8, 0))
        results = ttk.Frame(self)
        results.grid(row=3, column=0, sticky="nsew")
        results.columnconfigure(0, weight=1)
        results.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(
            results, columns=("name", "region", "area", "latitude", "longitude"),
            show="headings", selectmode="browse", height=10,
        )
        for column, heading, width in (
            ("name", "Town", 190), ("region", "State / region", 155),
            ("area", "Country / area", 180), ("latitude", "Latitude", 100),
            ("longitude", "Longitude", 105),
        ):
            self.table.heading(column, text=heading)
            self.table.column(column, width=width, minwidth=70)
        self.table.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(results, orient="vertical", command=self.table.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.table.configure(yscrollcommand=scroll.set)
        self.table.bind("<<TreeviewSelect>>", self._selected)
        self._fixed_label(4, self.status, 44)
        self._fixed_label(5, self.detail, 70)
        self.show_button = ttk.Button(
            self, text="Show selected town on included atlas", command=self.show_selected
        )
        self.show_button.grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Label(self, text="This opens the included atlas at the selected town. Saved places are unchanged.").grid(
            row=7, column=0, sticky="w", pady=(7, 0)
        )
        self.query.trace_add("write", self._query_changed)
        self.bind("<Destroy>", self._destroyed, add=True)
        self._buttons()
        token = self.worker.submit("load", places_path())
        self._job = (token, "load", None)
        self._poll()

    def _fixed_label(self, row, variable, height):
        box = ttk.Frame(self, height=height)
        box.grid(row=row, column=0, sticky="ew", pady=(6, 0))
        box.pack_propagate(False)
        label = ttk.Label(box, textvariable=variable, wraplength=820, justify="left", anchor="nw")
        label.pack(fill="both", expand=True)
        box.bind("<Configure>", lambda e: label.configure(wraplength=max(300, e.width)))

    def _buttons(self):
        ready = self.catalog is not None
        self.query_entry.configure(state="normal" if ready else "disabled")
        self.search_button.configure(state="normal" if ready else "disabled")
        self.show_button.configure(state="normal" if ready and self.table.selection() else "disabled")

    def _clear_results(self):
        self._results = ()
        self.table.delete(*self.table.get_children())
        self.detail.set("Select a town explicitly. No destination is chosen automatically.")
        self.show_button.configure(state="disabled")

    def _query_changed(self, *_):
        if self._closed:
            return
        if self._job and self._job[1] == "search":
            self.worker.cancel()
            self._job = None
        self._clear_results()
        if self.catalog is not None:
            self.status.set("Press Search or Enter. Leave the search empty to browse included towns.")

    def _show_results(self, places, total, *, query=""):
        self._clear_results()
        self._results = tuple(places)
        for index, place in enumerate(self._results):
            self.table.insert("", "end", iid=str(index), values=(
                place.name, place.region, place.country,
                f"{place.latitude:.5f}", f"{place.longitude:.5f}",
            ))
        if not total:
            self.status.set("No included town matches. Try its town or state name. "
                            "An absent result does not mean the place does not exist.")
        elif query:
            self.status.set(f"{total:,} matches · {len(self._results):,} shown. "
                            "Choose the intended town; refine the search if needed.")
        else:
            self.status.set(f"{total:,} towns included · {len(self._results):,} shown. "
                            "Search by town or state to narrow the list.")
        self._buttons()

    def search(self):
        if self._closed or self.catalog is None:
            return False
        self._clear_results()
        self.worker.cancel()
        self._job = None
        query = self.query.get()
        if not query.strip():
            self._show_results(self.catalog.places[:MAX_RESULTS], len(self.catalog.places))
        else:
            token = self.worker.submit("search", self.catalog, query)
            self._job = (token, "search", query)
            self.status.set("Searching the included offline town catalogue…")
        return True

    def _poll(self):
        if self._closed:
            return
        result = self.worker.poll()
        if result and self._job and result[0] == self._job[0]:
            task = self._job
            self._job = None
            _, kind, value, error = result
            if error:
                self.status.set("Included-town search unavailable: " + error)
            elif kind == "load":
                self.catalog = value
                self._show_results(value.places[:MAX_RESULTS], len(value.places))
                self.query_entry.focus_set()
            elif kind == "search" and task[2] == self.query.get():
                self._show_results(value.places, value.total, query=value.query)
            self._buttons()
        self._after = self.after(40, self._poll)

    def _selected_place(self):
        selected = self.table.selection()
        if not selected or self.catalog is None:
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
            area = ", ".join(part for part in (place.region, place.country) if part)
            self.detail.set(f"{place.name} · {area}\n"
                            f"Source: {place.source or 'not supplied'} · reference point; no street address.")
        self._buttons()

    def show_selected(self):
        if self._closed:
            return False
        place = self._selected_place()
        if place is None:
            self.status.set("Select the intended town first.")
            return False
        try:
            if not self.on_show(place):
                return False
        except ValueError as exc:
            self.status.set(str(exc))
            return False
        self.status.set(f"Opening the included atlas at {place.name}. No saved place was created.")
        self.winfo_toplevel().withdraw()
        return True

    def destroy(self):
        self.close()
        super().destroy()

    def _destroyed(self, event):
        if event.widget is self:
            self.close()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.worker.close()
        self.catalog = None
        self._results = ()
        self._job = None
        self.on_show = None
        if self._after is not None:
            self.after_cancel(self._after)
            self._after = None
