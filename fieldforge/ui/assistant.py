"""Ask Library desktop panel. Workers perform retrieval; only the main thread uses Tk."""

from __future__ import annotations

import os
import sqlite3
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.knowledge import KnowledgeLibrary
from fieldforge.knowledge.assistant import (
    NOTICE,
    ReferenceAssistant,
    ReferenceReport,
    SearchCancelled,
    question_terms,
    render_report,
)

_EXAMPLES = (
    "How do I store water?",
    "How do I calculate a power budget?",
    "How do I track tool maintenance?",
)
_ALL = "All categories"


class AskLibraryTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, library: KnowledgeLibrary) -> None:
        super().__init__(parent, padding=16)
        self.library = library
        self.assistant = ReferenceAssistant(library.database_path)
        self.report: ReferenceReport | None = None
        self.busy = False
        self._destroyed = False
        self._generation = 0
        self._cancel = Event()
        self._poll_id = None
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-reference")
        self.question = tk.StringVar()
        self.category = tk.StringVar(value=_ALL)
        self.summary = tk.StringVar(value="Ask a question to look for related text in installed articles.")
        self.status = tk.StringVar(value="No question history is saved. No model, network request, or account required.")
        self.metadata = tk.StringVar(value="Source excerpts will appear here.")
        self.bind("<Destroy>", self._on_destroy, add=True)

        ttk.Label(self, text="Ask your offline library", font=("TkDefaultFont", 21, "bold")).pack(anchor="w")
        ttk.Label(self, text="SOURCE EXCERPTS  ·  NO AI MODEL", font=("TkDefaultFont", 10, "bold")).pack(
            anchor="w", pady=(5, 6)
        )
        notice = ttk.Label(self, text=NOTICE, wraplength=1000, justify="left")
        notice.pack(fill="x", pady=(0, 12))
        self.bind("<Configure>", lambda event: notice.configure(wraplength=max(300, event.width-40)), add=True)

        form = ttk.Frame(self)
        form.pack(fill="x")
        form.columnconfigure(0, weight=1)
        ttk.Label(form, text="Your question (up to 512 characters)").grid(row=0, column=0, sticky="w")
        ttk.Label(form, text="Search within").grid(row=0, column=1, sticky="w")
        self.entry = ttk.Entry(form, textvariable=self.question, width=55)
        self.entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.entry.bind("<Return>", lambda _event: self.ask())
        self.entry.bind("<Escape>", lambda _event: self.cancel())
        self.categories = ttk.Combobox(form, textvariable=self.category, state="readonly", width=24)
        self.categories.grid(row=1, column=1, padx=(0, 8))
        self.ask_button = ttk.Button(form, text="Find sources", command=self.ask)
        self.ask_button.grid(row=1, column=2, padx=(0, 6))
        self.cancel_button = ttk.Button(form, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_button.grid(row=1, column=3)
        samples = ttk.Frame(self)
        samples.pack(fill="x", pady=(9, 8))
        ttk.Label(samples, text="Try:").pack(side="left", padx=(0, 6))
        for index, question in enumerate(_EXAMPLES):
            ttk.Button(samples, text=("Water storage", "Power budget", "Tool maintenance")[index],
                       command=lambda value=question: self.example(value)).pack(side="left", padx=(0, 6))
        ttk.Button(samples, text="Refresh categories", command=self.refresh_categories).pack(side="right")

        summary = ttk.Label(self, textvariable=self.summary, wraplength=1040, justify="left")
        summary.pack(fill="x", pady=(0, 8))
        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left, right = ttk.Frame(panes), ttk.Frame(panes, padding=(12, 0, 0, 0))
        panes.add(left, weight=4)
        panes.add(right, weight=6)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.sources = ttk.Treeview(left, columns=("words",), show="tree headings", selectmode="browse")
        self.sources.heading("#0", text="Related local sources")
        self.sources.heading("words", text="Word matches")
        self.sources.column("#0", width=290, minwidth=170)
        self.sources.column("words", width=122, minwidth=122, stretch=False)
        self.sources.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(left, command=self.sources.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(left, command=self.sources.xview, orient="horizontal")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.sources.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.sources.bind("<<TreeviewSelect>>", lambda _event: self.select_source())
        self.sources.bind("<Double-1>", lambda _event: self.open_source())
        source_meta = ttk.Label(right, textvariable=self.metadata, wraplength=600, justify="left")
        source_meta.pack(fill="x", pady=(0, 8))
        right.bind("<Configure>", lambda event: source_meta.configure(wraplength=max(250, event.width-24)), add=True)
        self.excerpt = ScrolledText(right, wrap="word", height=12, width=45, font=("TkDefaultFont", 12),
                                    state="disabled", padx=8, pady=8)
        self.excerpt.pack(fill="both", expand=True)
        self.open_button = ttk.Button(right, text="Open full source snapshot", command=self.open_source, state="disabled")
        self.open_button.pack(side="bottom", anchor="w", pady=(8, 0), before=self.excerpt)

        bottom = ttk.Frame(self)
        bottom.pack(side="bottom", fill="x", pady=(12, 6), before=panes)
        self.copy_button = ttk.Button(bottom, text="Copy question + source report", command=self.copy_report, state="disabled")
        self.copy_button.pack(side="left")
        ttk.Button(bottom, text="Clear question and results", command=self.clear).pack(side="left", padx=8)
        self.footer = ttk.Label(self, textvariable=self.status, wraplength=1050, justify="left")
        self.footer.pack(side="bottom", fill="x", before=bottom)
        self.bind("<Configure>", lambda event: self.footer.configure(
            wraplength=max(300, event.width-40)), add=True)
        self.refresh_categories()
        self._text(self.excerpt, "HOW THIS WORKS\n\nType a question and choose Find sources. "
                   "This screen retrieves exact passages, not a generated answer.\n\n"
                   "It searches article titles and bodies only—not your private notes, household records, "
                   "or learning-progress tables. Private information copied into an article is still searchable. "
                   "This screen does not save a question log.\n\n"
                   "An empty library? Use Load Starter Library or Import Pack in the Knowledge Library tab.")

    @staticmethod
    def _text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def refresh_categories(self):
        try:
            values = [_ALL, *self.library.categories()]
            self.categories.configure(values=values)
            if self.category.get() not in values:
                self.category.set(_ALL)
        except (OSError, sqlite3.Error) as exc:
            self.status.set("Could not read categories: " + str(exc))

    def _reset_results(self):
        self.report = None
        self.sources.delete(*self.sources.get_children())
        self.open_button.configure(state="disabled")
        self.copy_button.configure(state="disabled")
        self.metadata.set("No source selected.")
        self._text(self.excerpt, "")

    def _buttons(self, busy):
        self.busy = busy
        self.ask_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def example(self, question):
        if self.busy:
            return
        self.question.set(question)
        self.category.set(_ALL)
        self.ask()

    def ask(self):
        if self.busy or self._destroyed:
            return
        question = self.question.get()
        try:
            question_terms(question)
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self._reset_results()
        self._generation += 1
        generation = self._generation
        self._cancel = Event()
        self._buttons(True)
        self.summary.set("Searching for: " + question)
        self.status.set("Searching installed article text locally. No question history is being saved.")
        category = None if self.category.get() == _ALL else self.category.get()
        future = self._worker.submit(self.assistant.ask, question, category=category, cancel=self._cancel)
        self._poll_id = self.after(50, self._poll, future, generation)

    def _poll(self, future: Future, generation: int):
        if self._destroyed or generation != self._generation:
            return
        self._poll_id = None
        if not future.done():
            self._poll_id = self.after(50, self._poll, future, generation)
            return
        self._buttons(False)
        try:
            self._show_report(future.result())
        except SearchCancelled:
            self.status.set("Search cancelled. No question history was saved.")
        except Exception as exc:
            # Workers never call Tk; errors are shown here on the UI thread.
            self.summary.set("Search did not complete. No answer is being presented.")
            self.status.set("Could not search: " + str(exc))

    def cancel(self):
        if not self.busy:
            return
        self._cancel.set()
        self._generation += 1  # Never display a completed-but-cancelled request.
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        self._buttons(False)
        self._reset_results()
        self.summary.set("Search cancelled.")
        self.status.set("Cancelled results will not appear. No question history was saved.")

    def clear(self):
        self.cancel()
        self._reset_results()
        self.question.set("")
        self.summary.set("Question and results cleared from this view.")
        self.status.set("This does not clear previously copied text from your system clipboard.")

    def _show_report(self, report: ReferenceReport):
        self.report = report
        if not report.references:
            self.summary.set("No articles installed." if report.status == "empty_library" else
                             "No matching sources in this search—not proof that the information is absent.")
            self._text(self.excerpt, render_report(report))
        else:
            self.summary.set(f"Question: {report.question}\n{len(report.references)} related source(s). "
                             "These are keyword matches, not a verified answer.")
            for ref in report.references:
                self.sources.insert("", "end", iid=ref.label, text=f"[{ref.label}] {ref.article.title}",
                                    values=(f"{len(ref.matched_terms)} / {len(report.terms)}",))
            self.sources.selection_set(report.references[0].label)
            self.select_source()
        self.copy_button.configure(state="normal")
        self.status.set(
            f"{report.library_count} installed articles | {report.search_mode} | "
            f"{report.candidates_checked} candidates checked. " + " ".join(report.warnings)
        )

    def _selected(self):
        selected = self.sources.selection()
        if self.report is None or not selected:
            return None
        return next((ref for ref in self.report.references if ref.label == selected[0]), None)

    def select_source(self):
        ref = self._selected()
        if ref is None:
            return
        article = ref.article
        missing = [term for term in self.report.terms if term not in ref.matched_terms]
        self.metadata.set(
            f"[{ref.label}] {article.title}\nMatched: {', '.join(ref.matched_terms)} | "
            f"Not matched: {', '.join(missing) or 'None'}\n"
            f"Safety label: {article.safety_level.upper()} | Review date: {article.reviewed_on or 'Not supplied'}\n"
            f"Source: {article.source_title or 'Not supplied'}\n"
            f"Publisher: {article.source_publisher or 'Not supplied'}\n"
            f"{ref.excerpt_notice}"
        )
        text = (f"EXACT EXCERPT · article body lines {ref.line_start}–{ref.line_end}\n\n"
                + ref.excerpt if ref.excerpt else ref.excerpt_notice)
        self._text(self.excerpt, text)
        self.open_button.configure(state="normal")

    def open_source(self):
        ref = self._selected()
        if ref is None:
            return None
        article = ref.article
        window = tk.Toplevel(self)
        window.title(f"FieldForge — [{ref.label}] {article.title}")
        window.geometry("880x740")
        details = ttk.Label(
            window,
            text=f"SEARCH SNAPSHOT · {self.report.captured_at}\n{article.title}\n"
                 f"Source: {article.source_title or 'Not supplied'} | Publisher: {article.source_publisher or 'Not supplied'}\n"
                 f"URL (not fetched): {article.source_url or 'Not supplied'}\n"
                 f"Review date (author-supplied): {article.reviewed_on or 'Not supplied'} | Safety: {article.safety_level}\n"
                 f"Rights: {article.license or 'Unspecified'}\nBody SHA-256: {article.checksum}\n"
                 "This is the exact version retrieved. Search again to see subsequent article updates.",
            wraplength=830, justify="left", padding=12,
        )
        details.pack(fill="x")
        window.bind("<Configure>", lambda event: details.configure(wraplength=max(300, window.winfo_width()-30)), add=True)
        text = ScrolledText(window, wrap="word", font=("TkDefaultFont", 12), padx=12, pady=8)
        text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._text(text, article.body)
        if ref.line_start is not None:
            text.tag_configure("passage", background="#f8e9b0", foreground="#171717")
            text.tag_add("passage", f"{ref.line_start}.0", f"{ref.line_end + 1}.0")
            text.see(f"{ref.line_start}.0")
        return window

    def copy_report(self):
        if self.report is None:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(render_report(self.report))
            self.status.set("Copied the question and source excerpts to your system clipboard. No database history was saved.")
        except tk.TclError as exc:
            messagebox.showerror("Could not copy report", str(exc), parent=self)

    def _on_destroy(self, event):
        if event.widget is not self:
            return
        self._destroyed = True
        self._cancel.set()
        self._generation += 1
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        self._worker.shutdown(wait=False, cancel_futures=True)


def add_ask_library_tab(notebook: ttk.Notebook, library: KnowledgeLibrary) -> AskLibraryTab:
    frame = AskLibraryTab(notebook, library)
    notebook.add(frame, text="Ask Library")
    return frame


def run() -> None:
    library = KnowledgeLibrary(Path(os.environ.get("FIELDFORGE_DB", "~/.fieldforge/fieldforge.db")).expanduser())
    root = tk.Tk()
    root.title("FieldForge — Ask Library")
    root.geometry("1240x840")
    root.minsize(1000, 700)
    frame = AskLibraryTab(root, library)
    frame.pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    run()
