"""Inspectable source snapshots, available without any model installed."""

from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.blueprints.render import readable


class BlueprintEvidence(ttk.Frame):
    def __init__(self, parent, maker):
        super().__init__(parent, padding=8)
        self.sources = []
        self.summary = ""
        actions = ttk.Frame(self)
        actions.pack(fill="x")
        self.preview_button = ttk.Button(actions, text="Preview current request", command=maker.preview_evidence)
        self.preview_button.pack(side="left")
        ttk.Button(actions, text="Show design sources", command=lambda: self.show_saved(maker.blueprint)).pack(side="left", padx=8)
        self.header = ttk.Label(self, text="Inspect source passages before generation. No model or network is needed.", wraplength=700)
        self.header.pack(fill="x", pady=6)
        pane = ttk.Panedwindow(self, orient="vertical")
        pane.pack(fill="both", expand=True)
        upper = ttk.Frame(pane)
        self.rows = ttk.Treeview(upper, columns=("id", "title", "fields"), show="headings", height=4)
        for key, label, width in (("id", "Source", 55), ("title", "Article", 300), ("fields", "Matched request fields", 240)):
            self.rows.heading(key, text=label)
            self.rows.column(key, width=width, minwidth=50)
        scroll = ttk.Scrollbar(upper, command=self.rows.yview)
        self.rows.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.rows.pack(fill="both", expand=True)
        self.rows.bind("<<TreeviewSelect>>", self.select)
        pane.add(upper, weight=1)
        self.details = ScrolledText(pane, wrap="word", state="disabled", height=8, font="TkDefaultFont")
        pane.add(self.details, weight=2)
        self.bind("<Configure>", lambda event: self.header.configure(wraplength=max(200, event.width - 20)))

    def _text(self, value):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", value)
        self.details.configure(state="disabled")

    def show(self, report, *, saved=False):
        self.sources = report["sources"]
        self.summary = readable({key: value for key, value in report.items() if key != "sources"})
        self.header.configure(text=("Saved design source snapshot. Preview again to search the current library." if saved else
                                   "Current request preview. Generation searches again; changes to the request or library can change results.")
                              + f" {len(self.sources)} passages. Matches do not verify claims.")
        self.rows.delete(*self.rows.get_children())
        for row in self.sources:
            self.rows.insert("", "end", iid=row["id"], values=(row["id"], row["title"], ", ".join(row.get("retrieval_fields", []))))
        self._text(self.summary)
        if self.sources:
            self.rows.selection_set(self.sources[0]["id"])
            self.select()

    def select(self, _event=None):
        selected = self.rows.selection()
        if selected:
            row = next((row for row in self.sources if row["id"] == selected[0]), None)
            if row:
                self._text(readable(row) + "\n\nSEARCH DIAGNOSTICS\n" + self.summary)

    def show_saved(self, blueprint):
        if blueprint:
            self.show({"sources": blueprint["sources"], "notice": "Original excerpts; not checked against the current library."}, saved=True)
