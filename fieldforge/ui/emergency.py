"""Persistent Emergency Mode: existing prompts, self-reported progress and private logs."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.core.emergency import (
    NOTICE,
    PRIVACY,
    STATUS_LABELS,
    EmergencyStore,
    IncidentDetail,
    Task,
    render_checklist,
    template,
)
from fieldforge.scenarios.engine import available_scenarios

_ERRORS = (OSError, ValueError, sqlite3.Error)
_PAGE = 50


class EmergencyEditor(tk.Toplevel):
    """Modal editor: explicit save, confirmed discard, no hidden automatic actions."""

    def __init__(self, parent, store: EmergencyStore, operation: str, finished,
                 *, session_id: int | None = None, task: Task | None = None) -> None:
        super().__init__(parent)
        self.store, self.operation, self.finished = store, operation, finished
        self.session_id, self.task = session_id, task
        self.result = None
        self._disposed = False
        self.title({"create": "FieldForge — Start a saved checklist",
                    "task": "FieldForge — Update checklist action",
                    "note": "FieldForge — Add incident log note"}[operation])
        self.geometry("820x710")
        self.minsize(720, 640)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.name = tk.StringVar()
        self.scenario = tk.StringVar(value=available_scenarios()[0])
        self.exercise = tk.BooleanVar(value=True)
        self.action_status = tk.StringVar(value=STATUS_LABELS[task.status] if task else STATUS_LABELS["pending"])
        self.status = tk.StringVar(value="Nothing is saved until you select Save. " + PRIVACY)
        heading = {"create": "Start a separate incident or exercise", "task": "Record action progress",
                   "note": "Append a private incident note"}[operation]
        ttk.Label(self, text=heading, font=("TkDefaultFont", 18, "bold"), padding=16).grid(row=0, column=0, sticky="w")
        self.notice = ttk.Label(self, text=NOTICE, wraplength=740, justify="left", padding=(16, 0, 16, 12))
        self.notice.grid(row=1, column=0, sticky="ew")
        form = ttk.Frame(self, padding=(16, 0))
        form.grid(row=2, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        if operation == "create":
            ttk.Label(form, text="Title / alias *").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=5)
            ttk.Entry(form, textvariable=self.name).grid(row=0, column=1, sticky="ew", pady=5)
            ttk.Label(form, text="Existing scenario template").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=5)
            picker = ttk.Combobox(form, textvariable=self.scenario, values=available_scenarios(), state="readonly")
            picker.grid(row=1, column=1, sticky="ew", pady=5)
            picker.bind("<<ComboboxSelected>>", lambda _: self.show_template())
            ttk.Checkbutton(form, text="Training / exercise (not a live incident)", variable=self.exercise).grid(
                row=2, column=0, columnspan=2, sticky="w", pady=5)
            label = "Template preview — copied when you create this record"
        elif operation == "task":
            self.description = ttk.Label(form, text=f"[{task.priority.upper()}] {task.title}\n{task.reason}",
                                         wraplength=730, justify="left")
            self.description.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
            ttk.Label(form, text="Self-reported status").grid(row=1, column=0, sticky="w", padx=(0, 12))
            ttk.Combobox(form, textvariable=self.action_status, values=tuple(STATUS_LABELS.values()),
                         state="readonly").grid(row=1, column=1, sticky="ew")
            label = "Private action note (up to 4,000 characters; required for Blocked)"
        else:
            ttk.Label(form, text="This appends a record with the device's current UTC timestamp.\n"
                      "Previous log notes are not edited or deleted. Add a correction as a new note.",
                      wraplength=730).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
            label = "Private log note (up to 4,000 characters)"
        box = ttk.LabelFrame(self, text=label, padding=10)
        box.grid(row=3, column=0, sticky="nsew", padx=16, pady=12)
        self.text = ScrolledText(box, wrap="word", width=50, height=10, font=("TkDefaultFont", 11))
        self.text.pack(fill="both", expand=True)
        if operation == "create":
            self.show_template()
        elif task:
            self.text.insert("1.0", task.note)
        actions = ttk.Frame(self, padding=(16, 0))
        actions.grid(row=4, column=0, sticky="ew")
        self.save_button = ttk.Button(actions, text="Create saved checklist" if operation == "create" else "Save", command=self.save)
        self.save_button.pack(side="right")
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.close)
        self.cancel_button.pack(side="right", padx=8)
        self.footer = ttk.Label(self, textvariable=self.status, wraplength=740, padding=16, justify="left")
        self.footer.grid(row=5, column=0, sticky="ew")
        self.bind("<Configure>", self._resize, add=True)
        self.initial = self._values()
        self.grab_set()

    def _resize(self, event):
        if event.widget is self:
            for widget in (self.notice, self.footer):
                widget.configure(wraplength=max(300, event.width - 40))
            if hasattr(self, "description"):
                self.description.configure(wraplength=max(300, event.width - 50))

    def show_template(self):
        try:
            rows = template(self.scenario.get())
            body = "\n\n".join(f"{i}. [{a['priority'].upper()}] {a['title']}\n{a['reason']}"
                               for i, a in enumerate(rows, 1))
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.insert("1.0", body)
            self.text.configure(state="disabled")
        except _ERRORS as exc:
            self.status.set("Could not preview template: " + str(exc))

    def _values(self):
        if self.operation == "create":
            return (self.name.get(), self.scenario.get(), self.exercise.get())
        return (self.action_status.get(), self.text.get("1.0", "end-1c"))

    def save(self):
        if self._disposed:
            return
        try:
            if self.operation == "create":
                incident = self.store.create(self.name.get(), self.scenario.get(),
                                             mode="exercise" if self.exercise.get() else "incident")
                self.result = incident.id
            elif self.operation == "task":
                reverse = {label: key for key, label in STATUS_LABELS.items()}
                if self.action_status.get() not in reverse:
                    raise ValueError("choose a valid action status")
                self.store.update_task(self.task.id, expected_revision=self.task.revision,
                                       status=reverse[self.action_status.get()], note=self.text.get("1.0", "end-1c"))
                self.result = self.session_id
            else:
                self.store.add_note(self.session_id, self.text.get("1.0", "end-1c"))
                self.result = self.session_id
        except _ERRORS as exc:
            self.status.set("Not saved: " + str(exc))
            return
        self.destroy()

    def close(self):
        if self._values() != self.initial and not messagebox.askyesno(
            "Discard unsaved incident edits?", "Copy any text you need to keep first. Discard these unsaved edits?", parent=self
        ):
            return
        self.destroy()

    def _destroyed(self, event):
        if event.widget is self and not self._disposed:
            self._disposed = True
            self.finished(self.result)


class EmergencyTab(ttk.Frame):
    def __init__(self, parent, store: EmergencyStore) -> None:
        super().__init__(parent)
        self.store = store
        self.dialog = None
        self.current: IncidentDetail | None = None
        self.offset = 0
        self.include_archived = tk.BooleanVar(value=False)
        self.heading = tk.StringVar(value="No saved incident selected")
        self.summary = tk.StringVar(value="Choose New incident / exercise to preview the existing prompts and start a checklist.")
        self.status = tk.StringVar(value="No incident has been created automatically.")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        ttk.Label(self, text="Emergency workspace", font=("TkDefaultFont", 21, "bold")).grid(row=0, column=0, sticky="w")
        self.notice = ttk.Label(self, text=NOTICE, wraplength=1000, justify="left")
        self.notice.grid(row=1, column=0, sticky="ew", pady=(6, 12))
        tools = ttk.Frame(self)
        tools.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.new_button = ttk.Button(tools, text="New incident / exercise…", command=self.new)
        self.new_button.pack(side="left")
        ttk.Button(tools, text="Refresh / Resume", command=self.refresh).pack(side="left", padx=8)
        ttk.Checkbutton(tools, text="Include archived", variable=self.include_archived,
                        command=self.refresh).pack(side="left")
        self.previous = ttk.Button(tools, text="Previous", command=lambda: self.page(-1))
        self.next = ttk.Button(tools, text="Next", command=lambda: self.page(1))
        self.next.pack(side="right")
        self.previous.pack(side="right", padx=8)
        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.grid(row=3, column=0, sticky="nsew")
        left, right = ttk.Frame(panes), ttk.Frame(panes, padding=(12, 0, 0, 0))
        panes.add(left, weight=3)
        panes.add(right, weight=7)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.sessions = ttk.Treeview(left, columns=("state",), show="tree headings", selectmode="browse")
        self.sessions.heading("#0", text="Saved incidents / exercises")
        self.sessions.heading("state", text="Record")
        self.sessions.column("#0", width=220, minwidth=120)
        self.sessions.column("state", width=90, minwidth=80, stretch=False)
        self.sessions.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(left, command=self.sessions.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(left, command=self.sessions.xview, orient="horizontal")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.sessions.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.sessions.bind("<<TreeviewSelect>>", lambda _: self.select_session())
        title = ttk.Label(right, textvariable=self.heading, wraplength=630, font=("TkDefaultFont", 15, "bold"))
        title.pack(fill="x")
        subtitle = ttk.Label(right, textvariable=self.summary, wraplength=630, justify="left")
        subtitle.pack(fill="x", pady=(4, 10))
        right.bind("<Configure>", lambda event: self._wrap_right(event, title, subtitle), add=True)
        self.pages = ttk.Notebook(right)
        self.pages.pack(fill="both", expand=True)
        checklist, journal = ttk.Frame(self.pages, padding=10), ttk.Frame(self.pages, padding=10)
        self.pages.add(checklist, text="Saved checklist")
        self.pages.add(journal, text="Private incident log")
        checklist.columnconfigure(0, weight=1)
        checklist.rowconfigure(0, weight=1)
        self.tasks = ttk.Treeview(checklist, columns=("priority", "status"), show="tree headings", selectmode="browse")
        for key, label, width in (("#0", "Action", 320), ("priority", "Priority", 80), ("status", "Progress", 150)):
            self.tasks.heading(key, text=label)
            self.tasks.column(key, width=width, minwidth=70, stretch=key == "#0")
        self.tasks.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(checklist, command=self.tasks.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(checklist, command=self.tasks.xview, orient="horizontal")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tasks.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.tasks.bind("<<TreeviewSelect>>", lambda _: self.select_task())
        self.tasks.bind("<Double-1>", lambda _: self.edit_task())
        self.task_details = ScrolledText(checklist, wrap="word", height=6, width=40, state="disabled")
        self.task_details.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 6))
        self.edit_button = ttk.Button(checklist, text="Update selected action…", command=self.edit_task, state="disabled")
        self.edit_button.grid(row=3, column=0, sticky="w")
        self.log = ScrolledText(journal, wrap="word", height=12, width=40, state="disabled")
        self.log.pack(fill="both", expand=True)
        self.note_button = ttk.Button(journal, text="Add private log note…", command=self.add_note, state="disabled")
        self.note_button.pack(anchor="w", pady=(8, 0))
        controls = ttk.Frame(self)
        controls.grid(row=4, column=0, sticky="ew", pady=10)
        self.archive_button = ttk.Button(controls, text="Archive record…", command=self.archive, state="disabled")
        self.archive_button.pack(side="left")
        self.copy_button = ttk.Button(controls, text="Copy checklist (without notes)", command=self.copy, state="disabled")
        self.copy_button.pack(side="left", padx=8)
        self.footer = ttk.Label(self, textvariable=self.status, wraplength=1000, justify="left")
        self.footer.grid(row=5, column=0, sticky="ew")
        self.bind("<Configure>", self._resize, add=True)
        self.refresh()

    @staticmethod
    def _wrap_right(event, title, subtitle):
        if event.widget is title.master:
            for label in (title, subtitle):
                label.configure(wraplength=max(200, event.width - 24))

    def _resize(self, event):
        if event.widget is self:
            for label in (self.notice, self.footer):
                label.configure(wraplength=max(300, event.width - 20))

    @staticmethod
    def _text(widget, content):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _clear(self):
        self.current = None
        self.tasks.delete(*self.tasks.get_children())
        self.heading.set("No saved incident selected")
        self.summary.set("Select a saved record or create a new one. Existing progress is never reset on startup.")
        self._text(self.log, "")
        self._text(self.task_details, "")
        for button in (self.edit_button, self.note_button, self.archive_button, self.copy_button):
            button.configure(state="disabled")

    def refresh(self, *, reset=True):
        if self.dialog is not None:
            return
        if reset:
            self.offset = 0
        prior = self.current.incident.id if self.current else None
        try:
            rows = self.store.browse(archived=self.include_archived.get(), offset=self.offset, limit=_PAGE+1)
            self.sessions.delete(*self.sessions.get_children())
            self._clear()
            for incident in rows[:_PAGE]:
                self.sessions.insert("", "end", iid=str(incident.id), text=f"[{incident.mode}] {incident.title}", values=(incident.state,))
            self.previous.configure(state="normal" if self.offset else "disabled")
            self.next.configure(state="normal" if len(rows) > _PAGE else "disabled")
            self.status.set(f"Showing {min(len(rows), _PAGE)} records · page {self.offset // _PAGE+1}. " + PRIVACY)
            if prior is not None and self.sessions.exists(str(prior)):
                self.sessions.selection_set(str(prior))
                self.select_session()
        except _ERRORS as exc:
            self.sessions.delete(*self.sessions.get_children())
            self._clear()
            self.status.set("Could not refresh incidents: " + str(exc))

    def page(self, direction):
        if self.dialog is None:
            self.offset = max(0, self.offset + direction*_PAGE)
            self.refresh(reset=False)

    def select_session(self):
        chosen = self.sessions.selection()
        if self.dialog is not None or not chosen:
            return
        try:
            detail = self.store.detail(int(chosen[0]))
            self.current = detail
            incident = detail.incident
            self.heading.set(f"{incident.title} · {incident.mode.upper()}")
            self.summary.set(f"{incident.state.upper()} · {detail.done}/{len(detail.tasks)} actions marked done. Not a readiness score.\n"
                             f"Created: {incident.created_at} (device UTC). Template: {incident.scenario}.")
            self.tasks.delete(*self.tasks.get_children())
            for task in detail.tasks:
                self.tasks.insert("", "end", iid=str(task.id), text=f"{task.position}. {task.title}",
                                  values=(task.priority.upper(), STATUS_LABELS[task.status]))
            self._text(self.task_details, "Select an action to read its full reason and private note.")
            self.edit_button.configure(state="disabled")
            self.note_button.configure(state="normal" if incident.state == "active" else "disabled")
            self.archive_button.configure(text="Reopen record…" if incident.state == "archived" else "Archive record…", state="normal")
            self.copy_button.configure(state="normal")
            lines = [f"Latest {len(detail.log)} of {detail.log_count} entries, newest first. Device UTC timestamps.",
                     "Private notes are append-only. Add a new note to correct a previous entry.", ""]
            for entry in detail.log:
                lines += [f"{entry.created_at} · {entry.kind.upper()}", entry.message, ""]
            self._text(self.log, "\n".join(lines))
        except _ERRORS as exc:
            self._clear()
            self.status.set("Could not open incident: " + str(exc))

    def selected_task(self):
        selected = self.tasks.selection()
        return next((task for task in self.current.tasks if str(task.id) == selected[0]), None) if selected and self.current else None

    def select_task(self):
        task = self.selected_task()
        if task:
            self._text(self.task_details, f"{task.title}\n{task.reason}\n\nPrivate note:\n{task.note or '(none)'}")
        active = bool(task and self.current.incident.state == "active")
        self.edit_button.configure(state="normal" if active else "disabled")

    def _finished(self, session_id):
        self.dialog = None
        if not self.winfo_exists() or session_id is None:
            return
        self.refresh()
        if self.sessions.exists(str(session_id)):
            self.sessions.selection_set(str(session_id))
            self.sessions.see(str(session_id))
            self.select_session()
        self.status.set("Saved locally. Resume this record later; no emergency message or alert was sent.")

    def new(self):
        if self.dialog is None:
            self.dialog = EmergencyEditor(self, self.store, "create", self._finished)

    def edit_task(self):
        task = self.selected_task()
        if task and self.dialog is None and self.current.incident.state == "active":
            self.dialog = EmergencyEditor(self, self.store, "task", self._finished,
                                          session_id=self.current.incident.id, task=task)

    def add_note(self):
        if self.current and self.dialog is None and self.current.incident.state == "active":
            self.dialog = EmergencyEditor(self, self.store, "note", self._finished, session_id=self.current.incident.id)

    def archive(self):
        if self.current is None or self.dialog is not None:
            return
        incident = self.current.incident
        archived = incident.state != "archived"
        verb = "Archive" if archived else "Reopen"
        if not messagebox.askyesno(verb + " record?", f"{verb} {incident.title!r}?\n\n"
                                  f"{self.current.done}/{len(self.current.tasks)} actions are marked done. "
                                  "Archiving only makes this saved record read-only; it does not declare an emergency over. "
                                  "Checklist and notes are retained.", parent=self):
            return
        try:
            self.store.set_archived(incident.id, expected_revision=incident.revision, archived=archived)
            self.include_archived.set(True)
            self.refresh()
        except _ERRORS as exc:
            self.status.set("Record not changed: " + str(exc))

    def copy(self):
        if self.current is None or self.dialog is not None:
            return
        try:
            # Explicitly refresh the captured data rather than copying stale statuses.
            detail = self.store.detail(self.current.incident.id)
            self.clipboard_clear()
            self.clipboard_append(render_checklist(detail))
            self.status.set("Copied the incident title and checklist to the system clipboard. "
                            "Private task notes and log entries excluded. This is not a full backup.")
        except (OSError, ValueError, sqlite3.Error, tk.TclError) as exc:
            self.status.set("Could not copy checklist: " + str(exc))

    def can_close(self):
        if self.dialog is not None:
            messagebox.showinfo("Incident editor open", "Save or cancel the incident editor before continuing.", parent=self.dialog)
            return False
        return True
