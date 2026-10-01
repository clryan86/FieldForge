"""Civilization learning-path explorer. Tk stays on the main thread; no network I/O."""

from __future__ import annotations

import os
import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.knowledge import KnowledgeLibrary
from fieldforge.knowledge.pathways import (
    NOTICE,
    STAGES,
    STATUS_LABELS,
    LearningProgress,
    PathwayStore,
)
from fieldforge.ui.reading_links import ReadingLinksDialog

_ERRORS = (OSError, ValueError, KeyError, sqlite3.Error)
_VIEWS = {
    "All topics": "all",
    "Reading installed": "reading_available",
    "Reading missing / changed": "reading_missing",
    "Guides still needed": "guide_needed",
    "Next to explore": "next",
}
_ALL_STAGES = "All learning stages"


class PathwaysTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, store: PathwayStore) -> None:
        super().__init__(parent, padding=16)
        self.store = store
        self.reading_dialog = None
        self.slug: str | None = None
        self._saved = LearningProgress()
        self._rows = {}
        self.query = tk.StringVar()
        self.stage = tk.StringVar(value=_ALL_STAGES)
        self.view = tk.StringVar(value="All topics")
        self.title = tk.StringVar(value="Choose a learning goal")
        self.summary = tk.StringVar()
        self.status = tk.StringVar(value=STATUS_LABELS["not_started"])
        self.message = tk.StringVar(value="Your private learning record is stored on this device.")
        self._stage_options = [_ALL_STAGES, *(f"{i}. {name}" for i, name in enumerate(STAGES, 1))]

        ttk.Label(self, text="Civilization Pathways", font=("TkDefaultFont", 21, "bold")).pack(anchor="w")
        ttk.Label(self, text="Explore the foundations. Plan the next skill. See what is still missing.",
                  font=("TkDefaultFont", 11)).pack(anchor="w", pady=(3, 12))
        ttk.Label(self, textvariable=self.summary, font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        disclaimer = ttk.Label(self, text=NOTICE, wraplength=1000, justify="left")
        disclaimer.pack(fill="x", pady=(6, 12))
        self.bind("<Configure>", lambda event: disclaimer.configure(wraplength=max(400, event.width-40)), add=True)

        tools = ttk.Frame(self)
        tools.pack(fill="x")
        tools.columnconfigure(0, weight=1)
        ttk.Label(tools, text="Find a topic").grid(row=0, column=0, sticky="w")
        ttk.Label(tools, text="Learning stage, not emergency severity").grid(row=0, column=1, sticky="w")
        ttk.Label(tools, text="Show").grid(row=0, column=2, sticky="w")
        entry = ttk.Entry(tools, textvariable=self.query, width=24)
        entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        entry.bind("<Return>", lambda _event: self.refresh())
        stage = ttk.Combobox(tools, textvariable=self.stage, values=self._stage_options,
                             state="readonly", width=32)
        stage.grid(row=1, column=1, padx=(0, 8))
        stage.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        view = ttk.Combobox(tools, textvariable=self.view, values=list(_VIEWS),
                            state="readonly", width=24)
        view.grid(row=1, column=2, padx=(0, 8))
        view.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        ttk.Button(tools, text="Browse", command=self.refresh).grid(row=1, column=3)
        ttk.Button(tools, text="Clear filters", command=self.clear_filters).grid(row=1, column=4, padx=(6, 0))

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(12, 8))
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left, weight=4)
        panes.add(right, weight=6)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(left, columns=("reading",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Learning goal")
        self.tree.heading("reading", text="Local material")
        self.tree.column("#0", width=290, minwidth=170)
        self.tree.column("reading", width=140, minwidth=120, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(left, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(left, command=self.tree.xview, orient="horizontal")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.tree.bind("<<TreeviewSelect>>", self._select)
        heading = ttk.Label(right, textvariable=self.title, font=("TkDefaultFont", 15, "bold"), wraplength=560)
        heading.pack(anchor="w", pady=(0, 8), padx=(12, 0))
        right.bind("<Configure>", lambda event: heading.configure(wraplength=max(200, event.width-30)), add=True)
        self.details = ttk.Notebook(right)
        self.details.pack(fill="both", expand=True, padx=(12, 0))
        overview = ttk.Frame(self.details, padding=10)
        plan = ttk.Frame(self.details, padding=10)
        reading = ttk.Frame(self.details, padding=10)
        progress = ttk.Frame(self.details, padding=10)
        for frame, title in ((overview, "Overview"), (plan, "Study plan"),
                             (reading, "Local reading"), (progress, "My progress")):
            self.details.add(frame, text=title)
        self.overview = ScrolledText(overview, wrap="word", height=10, width=36,
                                    font=("TkDefaultFont", 11), state="disabled")
        self.overview.pack(fill="both", expand=True)
        ttk.Label(plan, text="Suggested order. Browse any step; this does not certify readiness.",
                  wraplength=540).pack(anchor="w", pady=(0, 8))
        self.plan = ttk.Treeview(plan, columns=("progress",), show="tree headings", height=8,
                                 selectmode="browse")
        self.plan.heading("#0", text="Prerequisites → chosen goal")
        self.plan.heading("progress", text="Your record")
        self.plan.column("#0", width=280, minwidth=160)
        self.plan.column("progress", width=130, minwidth=120, stretch=False)
        self.plan.pack(fill="both", expand=True)
        plan_scroll = ttk.Scrollbar(plan, orient="horizontal", command=self.plan.xview)
        plan_scroll.pack(fill="x")
        self.plan.configure(xscrollcommand=plan_scroll.set)
        self.plan.bind("<Double-1>", lambda _event: self.go_to_step())
        self.step_button = ttk.Button(plan, text="Explore selected step", command=self.go_to_step)
        self.step_button.pack(anchor="w", pady=(8, 0))
        self.reading_notice = tk.StringVar()
        ttk.Label(reading, textvariable=self.reading_notice, wraplength=530,
                  justify="left").pack(fill="x", pady=(0, 8))
        self.manage_reading_button = ttk.Button(reading, text="Manage reading links…", command=self.manage_reading)
        self.manage_reading_button.pack(anchor="w", pady=(0, 8))
        self.reading = ttk.Treeview(reading, columns=(), show="tree", selectmode="browse", height=8)
        self.reading.column("#0", width=360)
        self.reading.pack(fill="both", expand=True)
        self.reading.bind("<Double-1>", lambda _event: self.open_article())
        self.open_button = ttk.Button(reading, text="Open selected article offline", command=self.open_article)
        self.open_button.pack(anchor="w", pady=(8, 0))
        ttk.Label(progress, text="Self-reported practice, not verified competence.",
                  wraplength=500).pack(anchor="w")
        self.status_box = ttk.Combobox(progress, textvariable=self.status, state="readonly",
                                       values=list(STATUS_LABELS.values()), width=24)
        self.status_box.pack(anchor="w", pady=8)
        ttk.Label(progress, text="Private learning notes (up to 20,000 characters)").pack(anchor="w")
        self.note = ScrolledText(progress, wrap="word", height=8, width=36, font=("TkDefaultFont", 11))
        self.note.pack(fill="both", expand=True, pady=(4, 8))
        self.note.bind("<Control-s>", lambda _event: self._save_shortcut())
        buttons = ttk.Frame(progress)
        buttons.pack(fill="x")
        self.save_button = ttk.Button(buttons, text="Save progress", command=self._save_button)
        self.save_button.pack(side="left")
        self.reload_button = ttk.Button(buttons, text="Reload saved progress", command=self.reload_progress)
        self.reload_button.pack(side="left", padx=(8, 0))
        ttk.Label(self, textvariable=self.message, wraplength=1000, justify="left").pack(fill="x")
        self.refresh()

    @staticmethod
    def _text(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _inputs(self):
        reverse = {label: key for key, label in STATUS_LABELS.items()}
        if self.status.get() not in reverse:
            raise ValueError("choose a valid learning status")
        return reverse[self.status.get()], self.note.get("1.0", "end-1c")

    def save_current(self) -> bool:
        if self.reading_dialog is not None:
            return False
        if self.slug is None:
            return True
        try:
            status, note = self._inputs()
            if (status, note) != (self._saved.status, self._saved.note):
                self._saved = self.store.save(self.slug, status=status, note=note,
                                               expected_revision=self._saved.revision)
                self.message.set("Progress and private note saved on this device. Practice is self-reported.")
            return True
        except _ERRORS as exc:
            self.message.set("Not saved. Your edits remain visible; resolve the error before leaving this goal.")
            messagebox.showerror("Could not save learning progress", str(exc), parent=self)
            return False

    def _save_shortcut(self):
        self._save_button()
        return "break"

    def _save_button(self):
        if self.save_current():
            self.refresh()

    def _clear(self):
        self.slug = None
        self._saved = LearningProgress()
        self.title.set("Choose a learning goal")
        self.status.set(STATUS_LABELS["not_started"])
        self.note.configure(state="normal")
        self.note.delete("1.0", "end")
        self.note.configure(state="disabled")
        self.status_box.configure(state="disabled")
        for button in (self.save_button, self.reload_button, self.step_button, self.open_button, self.manage_reading_button):
            button.configure(state="disabled")
        self.plan.delete(*self.plan.get_children())
        self.reading.delete(*self.reading.get_children())
        self.reading_notice.set("Choose a goal to see its related local reading.")
        self._text(self.overview, "Choose a topic on the left.\n\nThe map shows learning goals, not installed books. "
                   "Use Local reading to see what is actually installed. Use Study plan to follow prerequisites. "
                   "Use My progress to record practice and questions.\n\n" + NOTICE)

    def refresh(self) -> bool:
        if not self.save_current():
            return False
        try:
            stage = self._stage_options.index(self.stage.get()) or None
            rows = self.store.views(query=self.query.get(), stage=stage, content=_VIEWS[self.view.get()])
            all_rows = self.store.views()
            prior = self.slug
            self._rows = {row.goal.slug: row for row in all_rows}
            self.tree.delete(*self.tree.get_children())
            for index, name in enumerate(STAGES, 1):
                group = [row for row in rows if row.goal.stage == index]
                if not group:
                    continue
                parent = self.tree.insert("", "end", iid=f"stage:{index}", text=f"{index}. {name}", open=True)
                for row in group:
                    self.tree.insert(parent, "end", iid=row.goal.slug, text=row.goal.title,
                                     values=(row.reading_state,))
            installed = len({slug for row in all_rows for slug, _ in row.installed_articles})
            practiced = sum(row.progress.status == "practiced" for row in all_rows)
            self.summary.set(f"{len(all_rows)} learning goals  |  {installed} linked articles installed  |  "
                             f"{practiced} goals with practice recorded")
            self._clear()
            if prior and self.tree.exists(prior):
                self.tree.selection_set(prior)
                self.tree.see(prior)
                self._load(prior)
            if not rows:
                self._text(self.overview, "No topics match this view. Your records have not been removed.\n\n"
                           "Clear filters to browse the whole map. 'Next to explore' requires linked reading "
                           "to be installed and all prerequisite practice to be recorded. It does not mean "
                           "you are qualified to perform a task.")
            self.message.set(f"Showing {len(rows)} of {len(all_rows)} goals. Notes save on goal changes and normal close.")
            return True
        except _ERRORS as exc:
            messagebox.showerror("Pathways could not refresh", str(exc), parent=self)
            return False

    def _load(self, slug):
        row = self._rows[slug]
        goal = row.goal
        # Re-read progress for its revision token, not a stale snapshot from the tree.
        progress = self.store.progress(slug)
        self.slug = slug
        self._saved = progress
        self.title.set(goal.title)
        self.status.set(STATUS_LABELS[progress.status])
        self.status_box.configure(state="readonly")
        self.note.configure(state="normal")
        self.note.delete("1.0", "end")
        self.note.insert("1.0", progress.note)
        for button in (self.save_button, self.reload_button, self.step_button, self.manage_reading_button):
            button.configure(state="normal")
        self.open_button.configure(state="normal" if row.installed_articles else "disabled")
        pending = "\n".join("• " + self.store.catalog.get(dep).title for dep in row.pending_prerequisites)
        self._text(self.overview,
                   f"LEARNING STAGE {goal.stage} · {STAGES[goal.stage - 1]}\n{goal.domain}\n\n"
                   f"OBJECTIVE\n{goal.objective}\n\nSAFE PLANNING / PRACTICE EXERCISE\n{goal.exercise}\n\n"
                   f"WHAT YOU STILL NEED\n{goal.requirements}\n\n"
                   f"LOCAL READING\n{row.reading_state}. Introductory material is not a full course.\n\n"
                   f"PREREQUISITE PRACTICE NOT RECORDED\n{pending or 'None in this proposed map. This does not certify readiness.'}\n\n"
                   "Progress can be recorded at any stage to reflect prior experience. "
                   "No progress is filled in automatically when you read an article.")
        self.plan.delete(*self.plan.get_children())
        for index, step in enumerate(self.store.catalog.plan(slug), 1):
            recorded = self._rows[step.slug].progress.status
            if step.slug == slug:
                recorded = progress.status
            self.plan.insert("", "end", iid=step.slug, text=f"{index}. {step.title}",
                             values=(STATUS_LABELS[recorded],))
        self.reading.delete(*self.reading.get_children())
        for article_slug, title in row.installed_articles:
            origin = "[Your link] " if any(link.article_slug == article_slug for link in row.user_links) else "[Starter] "
            self.reading.insert("", "end", iid=article_slug, text=origin + title)
        if row.installed_articles:
            self.reading.selection_set(row.installed_articles[0][0])
        installed_ids = {article_slug for article_slug, _ in row.installed_articles}
        missing = sum(article_slug not in installed_ids for article_slug in goal.articles)
        issues = sum(link.state != "current" for link in row.user_links)
        if goal.articles or row.user_links:
            self.reading_notice.set(
                f"{len(row.installed_articles)} readings available; {missing} starter articles not installed. "
                f"{len(row.user_links)} personal links; {issues} missing/changed sources to check. "
                "Your links are not independent source review and do not mark practice complete."
            )
        else:
            self.reading_notice.set(
                "No dedicated guide is linked in this version of the map. This planning goal is not an installed lesson. "
                "Use Manage reading links to choose relevant documents from your installed library."
            )
        if goal.articles and not row.installed_articles:
            self.reading_notice.set(self.reading_notice.get() + " Load the Starter Library from the Knowledge Library tab.")

    def manage_reading(self):
        if self.slug is None or self.reading_dialog is not None or not self.save_current():
            return
        def closed():
            self.reading_dialog = None
            # Parent widgets can still exist while their children are being destroyed.
            if self.winfo_exists() and self.note.winfo_exists() and self.tree.winfo_exists():
                self.refresh()
        self.reading_dialog = ReadingLinksDialog(self, self.store.reading_links, self.slug, on_close=closed)

    def _select(self, _event=None):
        selected = self.tree.selection()
        if not selected or selected[0].startswith("stage:") or selected[0] == self.slug:
            return
        old = self.slug
        if not self.save_current():
            if old and self.tree.exists(old):
                self.tree.selection_set(old)
            return
        try:
            self._rows = {row.goal.slug: row for row in self.store.views()}
            self._load(selected[0])
        except _ERRORS as exc:
            messagebox.showerror("Could not open learning goal", str(exc), parent=self)

    def clear_filters(self):
        if not self.save_current():
            return
        self.query.set("")
        self.stage.set(_ALL_STAGES)
        self.view.set("All topics")
        self.refresh()

    def go_to_step(self):
        selected = self.plan.selection()
        if not selected or not self.save_current():
            return
        slug = selected[0]
        self.clear_filters()
        if self.tree.exists(slug):
            self.tree.selection_set(slug)
            self.tree.focus(slug)
            self.tree.see(slug)
            self._select()
            self.details.select(0)

    def reload_progress(self):
        if self.slug is None:
            return
        try:
            if self._inputs() != (self._saved.status, self._saved.note):
                if not messagebox.askyesno(
                    "Discard unsaved edits?", "Reloading discards the edits in this learning note. "
                    "Copy anything you want to keep first. Continue?", parent=self
                ):
                    return
            self._rows = {row.goal.slug: row for row in self.store.views()}
            self._load(self.slug)
            self.message.set("Reloaded saved progress. Other windows' edits have not been overwritten.")
        except _ERRORS as exc:
            messagebox.showerror("Could not reload progress", str(exc), parent=self)

    def open_article(self):
        selected = self.reading.selection()
        if not selected:
            return None
        try:
            row = self._rows.get(self.slug)
            linked = next((link for link in row.user_links if link.article_slug == selected[0]), None) if row else None
            article = (self.store.reading_links.open_link(linked.id, expected_revision=linked.revision)
                       if linked else self.store.library.get(selected[0]))
            if article is None:
                messagebox.showinfo("Article not installed", "Refresh the map to update local availability.", parent=self)
                return None
            window = tk.Toplevel(self)
            window.title("FieldForge reference — " + article.title)
            window.geometry("800x650")
            text = ScrolledText(window, wrap="word", font=("TkDefaultFont", 12), padx=16, pady=16)
            text.pack(fill="both", expand=True)
            self._text(text, f"{article.title}\n\nSource: {article.source_title or 'Not supplied'}\n"
                       f"Publisher: {article.source_publisher or 'Not supplied'}\n"
                       f"Review date: {article.reviewed_on or 'Not supplied'} (author-supplied metadata)\n"
                       f"Safety label: {article.safety_level}\nURL: {article.source_url or 'Not supplied'}\n"
                       f"Rights: {article.license or 'Unspecified'}\n\n{article.body}")
            return window
        except _ERRORS as exc:
            messagebox.showerror("Could not open local article", str(exc), parent=self)
            return None



def add_pathways_tab(notebook: ttk.Notebook, knowledge_tab) -> PathwaysTab:
    """Integrate with the desktop and stop tab changes if a private-note save fails."""
    frame = PathwaysTab(notebook, PathwayStore(knowledge_tab.library))
    notebook.add(frame, text="Civilization Pathways")
    active = notebook.select()

    def changing_tab(_event):
        nonlocal active
        chosen = notebook.select()
        if chosen == active:
            return
        if not knowledge_tab.save_current() or not frame.save_current():
            notebook.select(active)
            return
        active = chosen
        if chosen == str(frame):
            frame.refresh()

    notebook.bind("<<NotebookTabChanged>>", changing_tab, add=True)
    return frame


def run() -> None:
    library = KnowledgeLibrary(Path(os.environ.get("FIELDFORGE_DB", "~/.fieldforge/fieldforge.db")).expanduser())
    store = PathwayStore(library)
    root = tk.Tk()
    root.title("FieldForge — Civilization Pathways")
    root.geometry("1260x820")
    root.minsize(1000, 700)
    frame = PathwaysTab(root, store)
    frame.pack(fill="both", expand=True)

    def close():
        if frame.save_current():
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


if __name__ == "__main__":
    run()
