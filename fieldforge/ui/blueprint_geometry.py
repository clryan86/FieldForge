"""Model-free inspection of envelope pairs and assembly groups."""

import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.blueprints.geometry import RELATIONS, analyze_envelopes
from fieldforge.ui.lifecycle import release_tk_references


class GeometryInspector(ttk.Frame):
    def __init__(self, parent, show_parts):
        super().__init__(parent, padding=8)
        self.show_parts = show_parts
        self.analysis = None
        self.filter = tk.StringVar(value="All relations")
        self.summary = tk.StringVar(value="Open an engineering design to inspect its envelopes.")
        self.notice = ttk.Label(self, textvariable=self.summary, wraplength=700)
        self.notice.pack(fill="x", pady=(0, 6))
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="Pair filter").pack(side="left", padx=(0, 6))
        options = ["All relations", *(v.replace("_", " ") for v in RELATIONS)]
        self.filters = ttk.Combobox(toolbar, textvariable=self.filter, values=options, state="readonly", width=20)
        self.filters.pack(side="left")
        self.filters.bind("<<ComboboxSelected>>", self.refresh)
        self.show_button = ttk.Button(toolbar, text="Show pair in drawing", command=self.highlight, state="disabled")
        self.show_button.pack(side="left", padx=8)
        ttk.Button(toolbar, text="Clear highlight", command=lambda: self.show_parts([])).pack(side="left")
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, pady=6)
        self.rows = ttk.Treeview(frame, columns=("a", "b", "relation"), show="headings", height=5)
        for key, title in (("a", "Part A"), ("b", "Part B"), ("relation", "Envelope relation")):
            self.rows.heading(key, text=title)
            self.rows.column(key, width=180, minwidth=90)
        scroll = ttk.Scrollbar(frame, command=self.rows.yview)
        self.rows.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.rows.pack(fill="both", expand=True)
        self.rows.bind("<<TreeviewSelect>>", self.selected)
        self.details = ScrolledText(self, height=7, wrap="word", state="disabled", font="TkDefaultFont")
        self.details.pack(fill="both", expand=True)
        self.bind("<Configure>", lambda event: self.notice.configure(wraplength=max(200, event.width - 20)))
        self.bind("<Destroy>", self._destroyed, add=True)

    def _destroyed(self, event):
        if event.widget is self:
            release_tk_references(self)

    def show(self, parts):
        self.analysis = analyze_envelopes(parts)
        self.filter.set("All relations")
        self.refresh()

    def _details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def refresh(self, _event=None):
        self.rows.delete(*self.rows.get_children())
        self.show_button.configure(state="disabled")
        if self.analysis is None:
            return
        summary = self.analysis["summary"]
        self._details(summary["scope"] + "\n\n" + "\n".join(
            f'Group {i}: ' + ", ".join(group) for i, group in enumerate(summary["groups"], 1)))
        if summary["status"] != "analyzed":
            self.summary.set("Geometry unresolved: " + " ".join(summary["problems"]))
            return
        self.summary.set(f'{summary["part_count"]} parts · {summary["pair_count"]} pairs · '
                         f'{summary["overlap_pairs"]} overlaps · {summary["connected_groups"]} touching/overlapping groups. '
                         'Contact is not a verified joint. Optional geometry limits are in Requirements → Acceptance limits.')
        selected = self.filter.get().replace(" ", "_")
        for index, pair in enumerate(self.analysis["pairs"]):
            if self.filter.get() == "All relations" or selected == pair["relation"]:
                self.rows.insert("", "end", iid=str(index), values=(*pair["part_ids"], pair["relation"].replace("_", " ")))

    def selected(self, _event=None):
        selection = self.rows.selection()
        self.show_button.configure(state="normal" if selection else "disabled")
        if not selection:
            return
        row = self.analysis["pairs"][int(selection[0])]
        self._details(" / ".join(row["part_ids"]) + ": " + row["relation"].replace("_", " ") +
                      "\nOverlap XYZ (mm): " + " / ".join(row["overlap_mm"]) +
                      "\nGap XYZ (mm): " + " / ".join(row["gap_mm"]) +
                      "\n\nPositive overlap on one axis alone is not a volume intersection. " + self.analysis["summary"]["scope"])

    def highlight(self):
        selection = self.rows.selection()
        if selection:
            self.show_parts(self.analysis["pairs"][int(selection[0])]["part_ids"])
