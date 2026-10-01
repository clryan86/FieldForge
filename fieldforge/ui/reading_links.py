"""Choose installed articles for a learning goal; no automatic source endorsement."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.knowledge.reading_links import NOTICE, STATES, ArticlePreview, ReadingLinks

_ERRORS = (OSError, ValueError, KeyError, sqlite3.Error)
_PAGE = 25


class ReadingLinksDialog(tk.Toplevel):
    def __init__(self, parent, links: ReadingLinks, goal_slug: str, *, on_close=None):
        super().__init__(parent)
        self.links, self.goal, self.on_close = links, links.catalog.get(goal_slug), on_close
        self.candidate: ArticlePreview | None = None
        self.editing = None
        self.rows = {}
        self.offset = 0
        self._disposed = False
        self.title("FieldForge — Link reading to a learning goal")
        self.geometry("1100x820")
        self.minsize(950, 730)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.query = tk.StringVar()
        self.category = tk.StringVar(value="All categories")
        self.status = tk.StringVar(value="Find an installed article, inspect its text, then link it to this goal.")
        self.source = tk.StringVar(value="No source selected. No links have been changed.")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        heading = ttk.Label(self, text=self.goal.title, font=("TkDefaultFont", 18, "bold"), padding=(16, 14), wraplength=1000)
        heading.grid(row=0, column=0, sticky="ew")
        self.notice = ttk.Label(self, text=NOTICE, wraplength=1040, padding=(16, 0, 16, 12), justify="left")
        self.notice.grid(row=1, column=0, sticky="ew")
        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.grid(row=2, column=0, sticky="nsew", padx=16)
        left, right = ttk.Frame(panes), ttk.Frame(panes, padding=(12, 0, 0, 0))
        panes.add(left, weight=1)
        panes.add(right, weight=1)
        self.tabs = ttk.Notebook(left)
        self.tabs.pack(fill="both", expand=True)
        find, saved = ttk.Frame(self.tabs, padding=8), ttk.Frame(self.tabs, padding=8)
        self.tabs.add(find, text="Find in library")
        self.tabs.add(saved, text="My reading links")
        entry = ttk.Entry(find, textvariable=self.query)
        entry.pack(fill="x")
        entry.bind("<Return>", lambda _: self.search())
        filters = ttk.Frame(find)
        filters.pack(fill="x", pady=8)
        self.categories = ttk.Combobox(filters, textvariable=self.category, state="readonly", width=24)
        self.categories.pack(side="left", fill="x", expand=True)
        self.categories.bind("<<ComboboxSelected>>", lambda _: self.search())
        ttk.Button(filters, text="Search / Browse", command=self.search).pack(side="left", padx=(8, 0))
        self.candidates = self._tree(find, ("category",), ("Category",))
        self.candidates.bind("<<TreeviewSelect>>", lambda _: self.preview_candidate())
        paging = ttk.Frame(find)
        paging.pack(fill="x", pady=(8, 0))
        self.previous = ttk.Button(paging, text="Previous", command=lambda: self.page(-1))
        self.previous.pack(side="left")
        self.next = ttk.Button(paging, text="Next", command=lambda: self.page(1))
        self.next.pack(side="left", padx=6)
        ttk.Label(saved, text="Only your links appear here. Built-in starter mappings stay unchanged.",
                  wraplength=430, justify="left").pack(fill="x", pady=(0, 8))
        self.saved = self._tree(saved, ("state",), ("Version status",))
        self.saved.bind("<<TreeviewSelect>>", lambda _: self.preview_saved())
        ttk.Button(saved, text="Refresh links", command=self.refresh_links).pack(anchor="w", pady=(8, 0))
        self.source_label = ttk.Label(right, textvariable=self.source, wraplength=450, justify="left")
        self.source_label.pack(fill="x", pady=(0, 10))
        right.bind("<Configure>", lambda event: self.source_label.configure(wraplength=max(200, event.width-15)), add=True)
        self.preview = ScrolledText(right, wrap="word", height=12, width=38, state="disabled", font=("TkDefaultFont", 11))
        self.preview.pack(fill="both", expand=True)
        self.full_button = ttk.Button(right, text="Open full captured text", command=self.open_full, state="disabled")
        self.full_button.pack(anchor="w", pady=(8, 0))
        self.preview_notice = tk.StringVar(value="Article text only. Private article notes are not read or copied.")
        ttk.Label(right, textvariable=self.preview_notice, wraplength=450, justify="left").pack(fill="x", pady=8)
        actions = ttk.Frame(self, padding=(16, 12))
        actions.grid(row=3, column=0, sticky="ew")
        self.link_button = ttk.Button(actions, text="Link previewed article", command=self.add, state="disabled")
        self.link_button.pack(side="left")
        self.update_button = ttk.Button(actions, text="Update link to this version…", command=self.update_link, state="disabled")
        self.update_button.pack(side="left", padx=8)
        self.remove_button = ttk.Button(actions, text="Remove link only…", command=self.remove, state="disabled")
        self.remove_button.pack(side="left")
        ttk.Button(actions, text="Close", command=self.destroy).pack(side="right")
        self.footer = ttk.Label(self, textvariable=self.status, wraplength=1040, justify="left", padding=(16, 0, 16, 12))
        self.footer.grid(row=4, column=0, sticky="ew")
        self.bind("<Configure>", self._resize, add=True)
        self.refresh_links()
        self.search()
        self.grab_set()

    @staticmethod
    def _tree(parent, columns, labels):
        box = ttk.Frame(parent)
        box.pack(fill="both", expand=True)
        tree = ttk.Treeview(box, columns=columns, show="tree headings", selectmode="browse", height=10)
        tree.heading("#0", text="Article")
        tree.column("#0", width=250, minwidth=170)
        for column, label in zip(columns, labels):
            tree.heading(column, text=label)
            tree.column(column, width=180, minwidth=130)
        vertical = ttk.Scrollbar(box, command=tree.yview)
        vertical.pack(side="right", fill="y")
        horizontal = ttk.Scrollbar(box, command=tree.xview, orient="horizontal")
        horizontal.pack(side="bottom", fill="x")
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.pack(fill="both", expand=True)
        return tree

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

    def _clear_preview(self):
        self.candidate = self.editing = None
        self.source.set("Select an article. Nothing has been linked automatically.")
        self._text(self.preview, "")
        for button in (self.link_button, self.update_button, self.remove_button, self.full_button):
            button.configure(state="disabled")

    def search(self, *, reset=True):
        if reset:
            self.offset = 0
        self._clear_preview()
        self.candidates.delete(*self.candidates.get_children())
        try:
            values = ["All categories", *self.links.library.categories()]
            self.categories.configure(values=values)
            if self.category.get() not in values:
                self.category.set("All categories")
            filters = {"category": None if self.category.get() == "All categories" else self.category.get(), "offset": self.offset}
            found = (self.links.library.search(self.query.get(), _PAGE+1, **filters) if self.query.get().strip()
                     else self.links.library.browse(_PAGE+1, **filters))
            for item in found[:_PAGE]:
                self.candidates.insert("", "end", iid=item.slug, text=item.title, values=(item.category,))
            self.previous.configure(state="normal" if self.offset else "disabled")
            self.next.configure(state="normal" if len(found) > _PAGE else "disabled")
            self.status.set(f"Showing {min(len(found), _PAGE)} articles · page {self.offset // _PAGE+1}. "
                            "Import documents from Knowledge Library if the source you need is not installed.")
        except _ERRORS as exc:
            self.status.set("Could not search installed articles: " + str(exc))

    def page(self, direction):
        self.offset = max(0, self.offset + direction*_PAGE)
        self.search(reset=False)

    def refresh_links(self):
        self._clear_preview()
        self.rows = {}
        self.saved.delete(*self.saved.get_children())
        try:
            for link in self.links.list(self.goal.slug):
                self.rows[str(link.id)] = link
                self.saved.insert("", "end", iid=str(link.id), text=link.current_title, values=(STATES[link.state],))
            self.tabs.tab(1, text=f"My reading links ({len(self.rows)})")
        except _ERRORS as exc:
            self.status.set("Could not refresh reading links: " + str(exc))

    def _show(self, candidate):
        self.candidate = candidate
        article = candidate.article
        self.source.set(f"{article.title}\nSource: {article.source_title or 'Not supplied'}\n"
                        f"Publisher: {article.source_publisher or 'Not supplied'}\n"
                        f"Review date (supplied): {article.reviewed_on or 'Not supplied'}\n"
                        f"Safety: {article.safety_level} | Rights: {article.license or 'Unspecified'}")
        self._text(self.preview, article.body[:20000])
        self.preview_notice.set("Preview limited to 20,000 characters; use Open full captured text for the entire article."
                                if len(article.body) > 20000 else "Full article body shown. Linking is your choice, not independent source review.")
        self.full_button.configure(state="normal")

    def preview_candidate(self):
        selection = self.candidates.selection()
        if not selection:
            return
        self._clear_preview()
        try:
            self._show(self.links.preview(selection[0]))
            built_in = selection[0] in self.goal.articles
            self.link_button.configure(state="disabled" if built_in else "normal")
            self.status.set("Already mapped by the built-in starter list; no personal duplicate is needed." if built_in else
                            "This article is only previewed. Choose Link previewed article to associate this exact version.")
        except _ERRORS as exc:
            self.status.set("Could not preview source: " + str(exc))

    def preview_saved(self):
        selection = self.saved.selection()
        if not selection or selection[0] not in self.rows:
            return
        self._clear_preview()
        self.editing = self.rows[selection[0]]
        self.remove_button.configure(state="normal")
        try:
            self._show(self.links.preview(self.editing.article_slug))
            changed = self.candidate.version != self.editing.version
            self.update_button.configure(state="normal" if changed else "disabled")
            self.status.set("This source changed since you linked it. Inspect the current text before explicitly updating the link."
                            if changed else "Saved version unchanged. This is a version comparison, not an authenticity or content review.")
        except _ERRORS as exc:
            self.source.set("Saved link: " + self.editing.saved_title)
            self.status.set("Cannot open linked source: " + str(exc) + " The link can be removed without deleting other records.")

    def add(self):
        if self.candidate is None or self.editing is not None:
            return
        try:
            linked = self.links.link(self.goal.slug, self.candidate.article.slug, expected_version=self.candidate.version)
            self.refresh_links()
            self.tabs.select(1)
            self.saved.selection_set(str(linked.id))
            self.status.set("Personal reading link saved. Article text, private notes and practice records are unchanged.")
        except _ERRORS as exc:
            self.status.set("Not linked: " + str(exc))

    def update_link(self):
        if self.candidate is None or self.editing is None:
            return
        if not messagebox.askyesno("Use the current source version?", "Update only your reading association to the previewed source version? "
                                   "This is not expert review or an endorsement of the content. Practice records stay unchanged.", parent=self):
            return
        try:
            link = self.links.update(self.editing.id, expected_revision=self.editing.revision, expected_version=self.candidate.version)
            self.refresh_links()
            self.saved.selection_set(str(link.id))
            self.status.set("Link now refers to the version you previewed. No article or learning record was modified.")
        except _ERRORS as exc:
            self.status.set("Not updated: " + str(exc))

    def remove(self):
        if self.editing is None:
            return
        if not messagebox.askyesno("Remove this reading link?", "Remove the association from this learning goal only? "
                                   "The article, its private notes and your learning progress will NOT be deleted.", parent=self):
            return
        try:
            self.links.remove(self.editing.id, expected_revision=self.editing.revision)
            self.refresh_links()
            self.status.set("Reading link removed. The document and your notes/progress are still saved.")
        except _ERRORS as exc:
            self.status.set("Not removed: " + str(exc))

    def open_full(self):
        if self.candidate is None:
            return None
        article = self.candidate.article
        window = tk.Toplevel(self)
        window.title("FieldForge — Captured source: " + article.title)
        window.geometry("820x700")
        text = ScrolledText(window, wrap="word", font=("TkDefaultFont", 12), padx=16, pady=16)
        text.pack(fill="both", expand=True)
        self._text(text, f"{self.source.get()}\nURL (not fetched): {article.source_url or 'Not supplied'}\n"
                   f"Body SHA-256: {article.checksum}\nCaptured for preview; no saved association until confirmed.\n\n{article.body}")
        return window

    def _destroyed(self, event):
        if event.widget is self and not self._disposed:
            self._disposed = True
            if self.on_close is not None:
                self.on_close()
