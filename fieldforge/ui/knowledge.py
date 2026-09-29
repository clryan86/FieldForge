"""Offline knowledge reader; import/export workers never access Tk widgets."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.knowledge import Evidence, KnowledgeLibrary
from fieldforge.knowledge.packs import export_pack, import_pack
from fieldforge.ui.evidence import EvidenceWindow
from fieldforge.ui.lifecycle import release_tk_references

_ERRORS = (OSError, ValueError, KeyError, sqlite3.Error)
_PAGE_SIZE = 50


class KnowledgeTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, library: KnowledgeLibrary) -> None:
        super().__init__(parent, padding=12)
        self.library = library
        self.slug: str | None = None
        self.offset = 0
        self.busy = False
        self.evidence_window: EvidenceWindow | None = None
        self._poll_id: str | None = None
        self._saved = (False, "")
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-pack")
        self.bind("<Destroy>", self._destroyed, add=True)
        self.query = tk.StringVar()
        self.category = tk.StringVar(value="All categories")
        self.favorites = tk.BooleanVar()
        self.bookmark = tk.BooleanVar()
        self.personal = tk.BooleanVar()
        self.replace = tk.BooleanVar()
        self.status = tk.StringVar()
        self.metadata = tk.StringVar(value="Import a knowledge pack or add articles with the CLI.")

        ttk.Label(self, text="Offline Knowledge Library", font=("TkDefaultFont", 18, "bold")).pack(anchor="w")
        ttk.Label(self, text="No cloud connection. Sources and review dates are supplied by the article author; they are not verification.",
                  wraplength=900).pack(anchor="w", pady=(4, 10))
        tools = ttk.Frame(self)
        tools.pack(fill="x")
        search = ttk.Entry(tools, textvariable=self.query)
        search.pack(side="left", fill="x", expand=True, padx=(0, 6))
        search.bind("<Return>", lambda _event: self.refresh())
        ttk.Button(tools, text="Search / Browse", command=self.refresh).pack(side="left")
        ttk.Button(tools, text="Find passages", command=self._evidence).pack(side="left", padx=(6, 0))
        self.categories = ttk.Combobox(tools, state="readonly", textvariable=self.category, width=20)
        self.categories.pack(side="left", padx=6)
        self.categories.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        ttk.Checkbutton(tools, text="Bookmarks only", variable=self.favorites, command=self.refresh).pack(side="left")

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=10)
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=2)
        self.results = ttk.Treeview(left, columns=("title", "category"), show="headings", height=12)
        self.results.heading("title", text="Article")
        self.results.heading("category", text="Category")
        self.results.column("title", width=230, minwidth=150)
        self.results.column("category", width=100, minwidth=80)
        scrollbar = ttk.Scrollbar(left, orient="vertical", command=self.results.yview)
        self.results.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.results.pack(fill="both", expand=True)
        self.results.bind("<<TreeviewSelect>>", self._select)
        ttk.Label(right, textvariable=self.metadata, wraplength=600, justify="left").pack(fill="x", pady=(0, 6))
        self.body = ScrolledText(right, wrap="word", height=12, font=("TkDefaultFont", 12), state="disabled")
        self.body.pack(fill="both", expand=True)
        ttk.Checkbutton(right, text="Bookmark this article", variable=self.bookmark, command=self.save_current).pack(anchor="w")
        ttk.Label(right, text="Private note (saved on navigation or with Save Note):").pack(anchor="w")
        self.note = ScrolledText(right, wrap="word", height=4)
        self.note.pack(fill="x")
        ttk.Button(right, text="Save Note", command=self.save_current).pack(anchor="e", pady=4)

        paging = ttk.Frame(self)
        paging.pack(fill="x")
        self.previous = ttk.Button(paging, text="Previous", command=lambda: self._page(-1))
        self.previous.pack(side="left")
        self.next = ttk.Button(paging, text="Next", command=lambda: self._page(1))
        self.next.pack(side="left", padx=5)
        ttk.Label(paging, textvariable=self.status, wraplength=700).pack(side="left", padx=8)
        files = ttk.Frame(self)
        files.pack(fill="x", pady=(10, 0))
        ttk.Button(files, text="Import Pack", command=self._import).pack(side="left")
        ttk.Button(files, text="Export Pack", command=self._export).pack(side="left", padx=6)
        ttk.Checkbutton(files, text="Include / restore private notes", variable=self.personal).pack(side="left")
        ttk.Checkbutton(files, text="Allow replacing conflicts", variable=self.replace).pack(side="left", padx=6)
        self.refresh()

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self:
            if self._poll_id is not None:
                self.after_cancel(self._poll_id)
                self._poll_id = None
            self.evidence_window = None
            self._worker.shutdown(wait=False, cancel_futures=True)
            release_tk_references(self)

    def save_current(self) -> bool:
        if self.busy:
            return False
        if self.slug is None:
            return True
        current = (self.bookmark.get(), self.note.get("1.0", "end-1c"))
        if current != self._saved:
            try:
                self.library.annotate(self.slug, bookmarked=current[0], note=current[1])
                self._saved = current
                self.status.set("Private note and bookmark saved locally.")
            except _ERRORS as exc:
                messagebox.showerror("Could not save note", str(exc), parent=self)
                return False
        return True

    def _clear(self) -> None:
        self.slug = None
        self._saved = (False, "")
        self.bookmark.set(False)
        self.note.delete("1.0", "end")
        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        self.body.tag_remove("evidence", "1.0", "end")
        self.body.configure(state="disabled")
        self.metadata.set("Select an article. No bundled survival corpus or AI model is installed by this feature.")

    def refresh(self, *, reset: bool = True) -> None:
        if self.busy or not self.save_current():
            return
        if reset:
            self.offset = 0
        try:
            categories = ["All categories", *self.library.categories()]
            self.categories.configure(values=categories)
            if self.category.get() not in categories:
                self.category.set("All categories")
            filters = {"category": None if self.category.get() == "All categories" else self.category.get(),
                       "bookmarked": self.favorites.get(), "offset": self.offset}
            found = (self.library.search(self.query.get(), _PAGE_SIZE + 1, **filters)
                     if self.query.get().strip() else self.library.browse(_PAGE_SIZE + 1, **filters))
            self._clear()
            self.results.delete(*self.results.get_children())
            for row in found[:_PAGE_SIZE]:
                self.results.insert("", "end", iid=row.slug, values=(row.title, row.category))
            self.previous.configure(state="normal" if self.offset else "disabled")
            self.next.configure(state="normal" if len(found) > _PAGE_SIZE else "disabled")
            mode = "FTS5" if self.library.fts_enabled else "literal fallback"
            count = min(len(found), _PAGE_SIZE)
            self.status.set(f"Showing {count} article(s), page {self.offset // _PAGE_SIZE + 1}. Local search: {mode}.")
        except _ERRORS as exc:
            messagebox.showerror("Library error", str(exc), parent=self)

    def _page(self, direction: int) -> None:
        if not self.save_current():
            return
        self.offset = max(0, self.offset + direction * _PAGE_SIZE)
        self.refresh(reset=False)

    def _select(self, _event: tk.Event | None = None) -> None:
        selection = self.results.selection()
        if self.busy or not selection or selection[0] == self.slug:
            return
        previous = self.slug
        if not self.save_current():
            if previous and self.results.exists(previous):
                self.results.selection_set(previous)
            return
        self._load_article(selection[0])

    def _load_article(self, slug: str, evidence: Evidence | None = None) -> bool:
        try:
            article = self.library.get(slug)
            if article is None:
                raise ValueError("This article is no longer installed. Search again.")
            if evidence and (article.checksum != evidence.checksum or
                             article.body[evidence.start_offset:evidence.end_offset] != evidence.passage):
                raise ValueError("This article changed after the search. Search again for a current passage.")
            annotation = self.library.annotation(article.slug)
            self._clear()
            self.slug = article.slug
            self.bookmark.set(annotation["bookmarked"])
            self.note.insert("1.0", annotation["note"])
            self._saved = (self.bookmark.get(), self.note.get("1.0", "end-1c"))
            self.metadata.set(
                f"{article.title}\nSafety label: {article.safety_level.upper()} | Review date: {article.reviewed_on or 'Not provided'}\n"
                f"Source: {article.source_title or 'Not provided'} | Publisher: {article.source_publisher or 'Not provided'}\n"
                f"{article.source_url or 'No source URL provided'}\nRights: {article.license or 'Unspecified — verify reuse rights'}"
            )
            self.body.configure(state="normal")
            self.body.insert("1.0", article.body)
            self.body.configure(state="disabled")
            if evidence:
                start = self.tk.call("string", "length", article.body[:evidence.start_offset])
                end = self.tk.call("string", "length", article.body[:evidence.end_offset])
                self.body.tag_configure("evidence", background="#ffe8a3", foreground="#1c261d")
                self.body.tag_add("evidence", f"1.0+{start}c", f"1.0+{end}c")
                self.body.see(f"1.0+{start}c")
            return True
        except _ERRORS as exc:
            messagebox.showerror("Could not open article", str(exc), parent=self)
            return False

    def _evidence(self) -> None:
        if self.busy:
            return
        if self.evidence_window is not None and self.evidence_window.winfo_exists():
            self.evidence_window.lift()
            return
        self.evidence_window = EvidenceWindow(self, self.library, self._open_evidence)
        self.evidence_window.bind("<Destroy>", self._evidence_closed, add=True)
        self.evidence_window.query.set(self.query.get())

    def _evidence_closed(self, event: tk.Event) -> None:
        if event.widget is self.evidence_window:
            # Break parent/window/callback cycles on the Tk thread. Otherwise a
            # later worker allocation can collect Tk variables on the wrong thread.
            self.evidence_window = None

    def _open_evidence(self, evidence: Evidence) -> bool:
        if self.busy or not self.save_current():
            return False
        if not self._load_article(evidence.slug, evidence):
            return False
        # An evidence result may be outside the current browse filter or page.
        if not self.results.exists(evidence.slug):
            self.results.insert("", "end", iid=evidence.slug, values=(evidence.title, "Search result"))
        self.results.selection_set(evidence.slug)
        self.results.see(evidence.slug)
        self.status.set("Showing the full source article. The retrieved passage is highlighted.")
        return True

    def _start(self, operation, *args, **kwargs) -> None:
        if not self.save_current():
            return
        self.busy = True
        self.note.configure(state="disabled")
        self.status.set("Processing local knowledge pack…")
        future = self._worker.submit(operation, *args, **kwargs)
        self._poll_id = self.after(100, self._poll, future)

    def _poll(self, future: Future) -> None:
        self._poll_id = None
        if not future.done():
            self._poll_id = self.after(100, self._poll, future)
            return
        self.busy = False
        self.note.configure(state="normal")
        try:
            result = future.result()
            # Do not overwrite annotations just restored by the worker with stale widget values.
            self._clear()
            self.refresh()
            self.status.set(f"Completed: {result}")
        except Exception as exc:
            messagebox.showerror("Knowledge pack failed", str(exc), parent=self)
            self.status.set("Operation failed; see the error. Failed imports roll back all records.")

    def _import(self) -> None:
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self, title="Import local knowledge pack",
                                          filetypes=[("Knowledge pack", "*.json"), ("All files", "*")])
        if path:
            if self.replace.get() and not messagebox.askyesno(
                "Replace conflicts?", "Different existing articles and restored notes may be replaced. Continue?", parent=self
            ):
                return
            self._start(import_pack, self.library, path, replace=self.replace.get(), restore_personal=self.personal.get())

    def _export(self) -> None:
        if self.busy:
            return
        if self.personal.get() and not messagebox.askyesno(
            "Export private notes?", "This unencrypted JSON file will contain your private notes and bookmarks. Continue?", parent=self
        ):
            return
        path = filedialog.asksaveasfilename(parent=self, title="Export local knowledge pack",
                                           defaultextension=".json", initialfile="fieldforge-knowledge.json")
        if path:
            self._start(export_pack, self.library, path, include_personal=self.personal.get())


def run(library: KnowledgeLibrary) -> None:
    root = tk.Tk()
    root.title("FieldForge — Offline Knowledge Library")
    root.geometry("1150x820")
    root.minsize(800, 650)
    frame = KnowledgeTab(root, library)
    frame.pack(fill="both", expand=True)

    def close() -> None:
        if frame.busy:
            messagebox.showinfo("Pack operation in progress", "Finish the local pack operation before closing.", parent=root)
        elif frame.save_current():
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()
