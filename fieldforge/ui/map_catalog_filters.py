"""Shared desktop controls for filtering the currently loaded catalog."""

import tkinter as tk
from tkinter import ttk

from fieldforge.online.discovery import filter_maps
from fieldforge_gps.tk_cleanup import TkCleanupMixin


class CatalogFilters(TkCleanupMixin, ttk.Frame):
    def __init__(self, parent, *, changed):
        super().__init__(parent)
        self.query = tk.StringVar()
        self.kind = tk.StringVar(value="All formats")
        self.order = tk.StringVar(value="Title")
        self.count = tk.StringVar(value="Load a catalog to filter available maps.")
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text="Filter loaded maps by name, region or source").grid(row=0, column=0, sticky="w")
        ttk.Label(self, text="Format").grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(self, text="Order").grid(row=0, column=2, sticky="w")
        self.entry = ttk.Entry(self, textvariable=self.query)
        self.entry.grid(row=1, column=0, sticky="ew", pady=5)
        self.kind_box = ttk.Combobox(self, textvariable=self.kind, width=14, values=("All formats", "MBTiles", "Images"))
        self.kind_box.grid(row=1, column=1, padx=8)
        self.order_box = ttk.Combobox(self, textvariable=self.order, width=14, values=("Title", "Smallest first", "Largest first"))
        self.order_box.grid(row=1, column=2)
        self.reset_button = ttk.Button(self, text="Reset", command=self.reset)
        self.reset_button.grid(row=1, column=3, padx=(8, 0))
        ttk.Label(self, textvariable=self.count).grid(row=2, column=0, columnspan=4, sticky="w")
        self._traces = [(value, value.trace_add("write", lambda *_args: changed())) for value in (self.query, self.kind, self.order)]
        self.apply((), loaded=False)

    def apply(self, items, *, loaded):
        for widget in (self.entry, self.reset_button):
            widget.configure(state="normal" if loaded else "disabled")
        for widget in (self.kind_box, self.order_box):
            widget.configure(state="readonly" if loaded else "disabled")
        kind = {"All formats": "all", "MBTiles": "mbtiles", "Images": "image"}.get(self.kind.get(), "invalid")
        order = {"Title": "title", "Smallest first": "smallest", "Largest first": "largest"}.get(self.order.get(), "invalid")
        try:
            visible = filter_maps(items, self.query.get(), kind, order)
            self.count.set(f"{len(visible)} of {len(items)} map packs · filters use only the loaded catalog" +
                           (" · no matches" if items and not visible else ""))
        except ValueError as exc:
            visible = ()
            self.count.set(str(exc))
        if not loaded:
            self.count.set("Load a catalog to filter available maps.")
        return visible

    def reset(self):
        self.query.set("")
        self.kind.set("All formats")
        self.order.set("Title")

    def close(self):
        for value, token in self._traces:
            value.trace_remove("write", token)
        self._traces.clear()

    def destroy(self):
        self.close()
        super().destroy()
