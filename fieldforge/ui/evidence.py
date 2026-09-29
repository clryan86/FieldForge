"""Desktop passage search. Worker threads only read the local library."""

from __future__ import annotations

import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from fieldforge.knowledge import Evidence, KnowledgeLibrary, retrieve_evidence


class EvidenceWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, library: KnowledgeLibrary,
                 open_article: Callable[[Evidence], bool]) -> None:
        super().__init__(parent)
        self.title("FieldForge — Find local passages")
        self.geometry("900x650")
        self.minsize(600, 450)
        self.library = library
        self.open_article = open_article
        self.query = tk.StringVar()
        self.status = tk.StringVar(value="Ask a question about articles installed in your library.")
        self.evidence: list[Evidence] = []
        self.busy = False
        self._closed = False
        self._poll_id: str | None = None
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-evidence")
        self.bind("<Destroy>", self._destroyed, add=True)
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Find passages in your library",
                  font=("TkDefaultFont", 18, "bold")).pack(anchor="w")
        description = ttk.Label(frame, text="Exact excerpts from installed articles. Source details are supplied by their authors.",
                                wraplength=760)
        description.pack(anchor="w", pady=(4, 12))
        search_row = ttk.Frame(frame)
        search_row.pack(fill="x")
        self.entry = ttk.Entry(search_row, textvariable=self.query)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry.bind("<Return>", lambda _event: self.search())
        self.search_button = ttk.Button(search_row, text="Find passages", command=self.search)
        self.search_button.pack(side="right")
        status_label = ttk.Label(frame, textvariable=self.status, wraplength=760)
        status_label.pack(fill="x", pady=8)
        frame.bind("<Configure>", lambda event: (
            description.configure(wraplength=max(200, event.width - 32)),
            status_label.configure(wraplength=max(200, event.width - 32)),
        ))
        result_frame = ttk.Frame(frame)
        result_frame.pack(fill="x")
        self.results = ttk.Treeview(result_frame, columns=("title", "source"), show="headings", height=5)
        self.results.heading("title", text="Article")
        self.results.heading("source", text="Source")
        self.results.column("title", width=300, minwidth=150)
        self.results.column("source", width=350, minwidth=150)
        scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=self.results.yview)
        self.results.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.results.pack(side="left", fill="x", expand=True)
        self.results.bind("<<TreeviewSelect>>", self._select)
        self.passage = ScrolledText(frame, wrap="word", state="disabled", height=12, font="TkDefaultFont")
        self.passage.pack(fill="both", expand=True, pady=10)
        self.open_button = ttk.Button(frame, text="Open full article", command=self.open_selected,
                                      state="disabled")
        self.open_button.pack(anchor="e")
        self.entry.focus_set()

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self:
            self._closed = True
            if self._poll_id is not None:
                self.after_cancel(self._poll_id)
                self._poll_id = None
            self._worker.shutdown(wait=False, cancel_futures=True)

    def _text(self, value: str) -> None:
        self.passage.configure(state="normal")
        self.passage.delete("1.0", "end")
        self.passage.insert("1.0", value)
        self.passage.configure(state="disabled")

    def search(self) -> None:
        if self.busy:
            return
        question = self.query.get().strip()
        if not question:
            self.status.set("Enter a question or a few keywords.")
            return
        self.evidence = []
        self.results.delete(*self.results.get_children())
        self._text("")
        self.open_button.configure(state="disabled")
        self.search_button.configure(state="disabled")
        self.entry.configure(state="disabled")
        self.busy = True
        self.status.set("Searching the local library…")
        future = self._worker.submit(retrieve_evidence, self.library, question, limit=8)
        self._poll_id = self.after(50, self._poll, future)

    def _poll(self, future: Future) -> None:
        self._poll_id = None
        if self._closed:
            return
        if not future.done():
            self._poll_id = self.after(50, self._poll, future)
            return
        self.busy = False
        self.search_button.configure(state="normal")
        self.entry.configure(state="normal")
        try:
            self.evidence = future.result()
            for index, item in enumerate(self.evidence):
                self.results.insert("", "end", iid=str(index),
                                    values=(item.title, item.source_title or "Source not provided"))
            if self.evidence:
                self.status.set(f"Found {len(self.evidence)} matching article(s). Select a passage to inspect its source.")
                self.results.selection_set("0")
            else:
                self.status.set("No matching passages. Try different keywords or import a relevant knowledge pack.")
        except Exception as exc:
            self.status.set(f"Search failed: {exc}")
        self.entry.focus_set()

    def _selected(self) -> Evidence | None:
        selected = self.results.selection()
        return self.evidence[int(selected[0])] if selected else None

    def _select(self, _event: tk.Event | None = None) -> None:
        item = self._selected()
        if item is None:
            return
        self._text(
            f"{item.title}\n\n{item.passage}\n\n"
            f"Source: {item.source_title or 'Not provided'}\n"
            f"Publisher: {item.source_publisher or 'Not provided'}\n"
            f"Review date: {item.reviewed_on or 'Not provided'}\n"
            f"Safety label: {item.safety_level.upper()}\n"
            f"Rights: {item.license or 'Unspecified'}\n"
            f"{item.source_url or 'No source URL provided'}\n\n"
            f"Article ID: {item.slug}\nCharacters: {item.start_offset} to {item.end_offset}\n"
            f"Body SHA-256: {item.checksum}"
        )
        self.open_button.configure(state="normal")

    def open_selected(self) -> None:
        item = self._selected()
        if item is not None and self.open_article(item):
            self.destroy()
