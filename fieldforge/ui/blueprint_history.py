"""Revision history and comparisons shared by the three blueprint makers."""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.blueprints.engine import digest
from fieldforge.blueprints.projects import (
    append_revision,
    checkout,
    compare_designs,
    create_project,
    head,
    load_project,
    restore_revision,
)
from fieldforge.ui.lifecycle import release_tk_references


class ProjectHistory(ttk.Frame):
    def __init__(self, parent, maker):
        super().__init__(parent, padding=8)
        self.maker = maker
        self.project = None
        self.path = None
        self.previous = None
        self._wrap_width = 0
        self.label = tk.StringVar(value="No project open. Save a project to preserve revisions offline.")
        self.bind("<Destroy>", self._destroyed, add=True)
        self.header = ttk.Label(self, textvariable=self.label, wraplength=950)
        self.header.pack(fill="x")
        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=6)
        for label, command in (("New project", self.create), ("Open project", self.open),
                               ("Save revision", self.save), ("Restore selected", self.restore),
                               ("Undo last draft change", self.undo)):
            ttk.Button(actions, text=label, command=command).pack(side="left", padx=(0, 5))
        self.notice = ttk.Label(self, text="Open projects automatically record generated, refined and applied "
                                "edits. Project files are separate from database backups.", wraplength=950)
        self.notice.pack(fill="x")
        self.bind("<Configure>", self._resize)
        panes = ttk.Panedwindow(self, orient="vertical")
        panes.pack(fill="both", expand=True, pady=6)
        upper = ttk.Frame(panes)
        self.rows = ttk.Treeview(upper, columns=("number", "kind", "note"), show="headings", height=5)
        for key, label, width in (("number", "Revision", 70), ("kind", "Change", 100), ("note", "Note", 600)):
            self.rows.heading(key, text=label)
            self.rows.column(key, width=width, minwidth=60, stretch=key == "note")
        scroll = ttk.Scrollbar(upper, command=self.rows.yview)
        self.rows.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.rows.pack(fill="both", expand=True)
        self.rows.bind("<<TreeviewSelect>>", self.compare_selected)
        panes.add(upper, weight=1)
        self.changes = ScrolledText(panes, wrap="word", state="disabled", height=8, font="TkDefaultFont")
        panes.add(self.changes, weight=2)

    def _destroyed(self, event):
        if event.widget is self:
            release_tk_references(self)

    def _resize(self, event):
        if event.width != self._wrap_width:
            self._wrap_width = event.width
            self.header.configure(wraplength=max(200, event.width - 24))
            self.notice.configure(wraplength=max(200, event.width - 24))

    def _show_changes(self, before, after, heading=""):
        difference = compare_designs(before, after)
        lines = [f"{row['path']}\nBefore: {row['before']}\nAfter: {row['after']}"
                 for row in difference["changes"]]
        if difference["truncated"]:
            lines.append("More changes omitted. Inspect the full revisions before relying on them.")
        if not lines:
            lines.append("No design, request, source or critique changes.")
        if heading:
            lines.insert(0, heading)
        self.changes.configure(state="normal")
        self.changes.delete("1.0", "end")
        self.changes.insert("1.0", "\n\n".join(lines))
        self.changes.configure(state="disabled")

    def refresh(self):
        self.rows.delete(*self.rows.get_children())
        if self.project:
            self.label.set(f"{self.project['name']} — {len(self.project['revisions'])} revisions\n{self.path}")
            for row in self.project["revisions"]:
                self.rows.insert("", "end", iid=str(row["number"]),
                                 values=(row["number"], row["kind"], row["note"]))
        else:
            self.label.set("No project open. Save a project to preserve revisions offline.")

    def detach(self):
        self.project, self.path, self.previous = None, None, None
        self.refresh()

    def ready(self):
        return (not self.maker.busy and self.maker.blueprint is not None
                and self.maker._edits_applied())

    def create(self):
        if not self.ready():
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".ffproject.json",
                                          filetypes=[("Blueprint project", "*.ffproject.json")])
        if not path:
            return
        try:
            project = create_project(path, self.maker.blueprint["design"]["title"], self.maker.blueprint)
            self.project, self.path = project, path
            self.maker.dirty = False
            self.refresh()
            self.maker.status.set("Project created. Future design changes will be saved as new revisions.")
        except (OSError, ValueError) as exc:
            self.maker.status.set(str(exc))

    def open(self):
        if self.maker.busy or not self.maker._can_replace():
            return
        path = filedialog.askopenfilename(parent=self, filetypes=[("Blueprint project", "*.ffproject.json")])
        if not path:
            return
        try:
            project = load_project(path)
            value = checkout(project)
            if value["request"]["mode"] != self.maker.mode:
                raise ValueError("Open this project in its matching blueprint maker.")
            self.maker.show_blueprint(value, dirty=False)
            self.maker.load_request(value)
            self.project, self.path, self.previous = project, path, None
            self.refresh()
        except (OSError, ValueError) as exc:
            self.maker.status.set(str(exc))

    def record(self, *, kind="edited", note="Design update"):
        if self.project is None:
            return True
        try:
            value = self.maker.blueprint
            if digest(checkout(self.project)) == digest(value):
                if head(load_project(self.path)) != head(self.project):
                    raise ValueError("Project changed on disk. Reopen it before continuing.")
                self.maker.dirty = False
                return True
            self.project = append_revision(self.path, value, expected_head=head(self.project),
                                           kind=kind, note=note)
            self.maker.dirty = False
            self.refresh()
            return True
        except (OSError, ValueError) as exc:
            self.maker.status.set("Draft kept in memory; project was not saved: " + str(exc))
            return False

    def before_change(self):
        if self.maker.blueprint is not None:
            if not self.record(note="Save draft before the next change"):
                return False
            self.previous = copy.deepcopy(self.maker.blueprint)
        return True

    def after_change(self, kind, note):
        if self.previous:
            self._show_changes(self.previous, self.maker.blueprint)
        return self.record(kind=kind, note=note)

    def save(self):
        if not self.ready():
            return
        if self.project is None:
            self.create()
        elif self.record():
            self.maker.status.set("Project revision saved locally.")

    def compare_selected(self, _event=None):
        selection = self.rows.selection()
        if selection and self.project and self.maker.blueprint:
            number = int(selection[0])
            row = self.project["revisions"][number - 1]
            heading = f"Revision {number} ({row['kind']}) — {row['created_at']}\nNote: {row['note']}"
            self._show_changes(checkout(self.project, number), self.maker.blueprint, heading)

    def restore(self):
        selection = self.rows.selection()
        if not self.ready() or not selection or self.project is None:
            return
        if not self.before_change():
            return
        try:
            project = restore_revision(self.path, int(selection[0]), expected_head=head(self.project))
            self.maker.show_blueprint(checkout(project), dirty=False)
            self.maker.load_request(self.maker.blueprint)
            self.project = project
            self.refresh()
            self._show_changes(self.previous, self.maker.blueprint)
            self.maker.status.set("Restored as a new revision. All previous revisions are preserved.")
        except (OSError, ValueError) as exc:
            self.maker.status.set(str(exc))

    def undo(self):
        if not self.ready() or self.previous is None:
            return
        value = copy.deepcopy(self.previous)
        if not self.before_change():
            return
        self.maker.show_blueprint(value)
        self.maker.load_request(value)
        self.after_change("restored", "Undo the last draft change")
