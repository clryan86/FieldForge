"""Custom actions and responsibility labels in the saved Emergency Mode workspace."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.core.emergency import NOTICE, STATUS_LABELS, Incident
from fieldforge.core.emergency_actions import (
    ASSIGNMENT_NOTICE,
    ORIGIN_LABELS,
    PRIORITIES,
    ActionStore,
    AssignedTask,
    render_action_checklist,
)
from fieldforge.ui.emergency import EmergencyTab

_ERRORS = (OSError, ValueError, sqlite3.Error)


class ActionEditor(tk.Toplevel):
    def __init__(self, parent, store: ActionStore, incident: Incident, task: AssignedTask | None,
                 finished) -> None:
        super().__init__(parent)
        self.store, self.incident, self.task, self.finished = store, incident, task, finished
        self.result = None
        self._disposed = False
        custom = task is None or task.origin == "custom"
        self.title("FieldForge — Add your own action" if task is None else "FieldForge — Edit action & responsibility")
        self.geometry("840x730")
        self.minsize(740, 650)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.task_title = tk.StringVar(value=task.title if task else "")
        self.priority = tk.StringVar(value=task.priority if task else "medium")
        self.responsible = tk.StringVar(value=task.responsible if task else "")
        self.action_status = tk.StringVar(value=STATUS_LABELS[task.status if task else "pending"])
        self.status = tk.StringVar(value="Nothing is saved until Save. New tasks always start Pending.")
        label = "Your planning task — not reviewed guidance" if custom else "Saved scenario prompt — original wording preserved"
        ttk.Label(self, text=label, font=("TkDefaultFont", 17, "bold"), padding=16).grid(row=0, column=0, sticky="w")
        self.notice = ttk.Label(self, text=ASSIGNMENT_NOTICE, wraplength=780, padding=(16, 0, 16, 12), justify="left")
        self.notice.grid(row=1, column=0, sticky="ew")
        self.pages = ttk.Notebook(self)
        self.pages.grid(row=2, column=0, sticky="nsew", padx=16)
        details, progress = ttk.Frame(self.pages, padding=12), ttk.Frame(self.pages, padding=12)
        self.pages.add(details, text="Task & responsibility")
        self.pages.add(progress, text="Progress & private note")
        details.columnconfigure(1, weight=1)
        details.rowconfigure(4, weight=1)
        ttk.Label(details, text="Action title *").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=6)
        self.title_entry = ttk.Entry(details, textvariable=self.task_title, state="normal" if custom else "readonly")
        self.title_entry.grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Label(details, text="Priority (not an automatic assessment)").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=6)
        self.priority_picker = ttk.Combobox(details, textvariable=self.priority, values=PRIORITIES,
                                           state="readonly" if custom else "disabled")
        self.priority_picker.grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Label(details, text="Responsible name / alias (optional)").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=6)
        ttk.Entry(details, textvariable=self.responsible).grid(row=2, column=1, sticky="ew", pady=6)
        ttk.Label(details, text="Description / context *" if custom else "Original scenario wording (read only)").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(10, 5))
        self.reason = ScrolledText(details, wrap="word", height=6, width=45, font=("TkDefaultFont", 11))
        self.reason.grid(row=4, column=0, columnspan=2, sticky="nsew")
        if task:
            self.reason.insert("1.0", task.reason)
        if not custom:
            self.reason.configure(state="disabled")
        ttk.Label(details, text="Use an alias and only necessary details. Responsibility labels are excluded from "
                  "the copied checklist, but titles/descriptions are copied. All fields are in private full backups.",
                  wraplength=690, justify="left").grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Label(progress, text="Self-reported status; not proof of safety or acceptance.", wraplength=690).pack(anchor="w")
        self.status_picker = ttk.Combobox(progress, textvariable=self.action_status, values=tuple(STATUS_LABELS.values()),
                                         state="readonly" if task else "disabled", width=26)
        self.status_picker.pack(anchor="w", pady=10)
        ttk.Label(progress, text="Private action note — up to 4,000 characters; required for Blocked.",
                  wraplength=690).pack(anchor="w", pady=(0, 6))
        self.text = ScrolledText(progress, wrap="word", height=7, width=45, font=("TkDefaultFont", 11))
        self.text.pack(fill="both", expand=True)
        if task:
            self.text.insert("1.0", task.note)
        else:
            self.text.configure(state="disabled")
        ttk.Label(progress, text="Create a new task first, then record progress or notes. No task is marked done automatically."
                  if task is None else "A note or responsibility change does not send a message. Contact the person separately.",
                  wraplength=690, justify="left").pack(fill="x", pady=(10, 0))
        buttons = ttk.Frame(self, padding=(16, 12))
        buttons.grid(row=3, column=0, sticky="ew")
        self.save_button = ttk.Button(buttons, text="Add pending task" if task is None else "Save action", command=self.save)
        self.save_button.pack(side="right")
        self.cancel_button = ttk.Button(buttons, text="Cancel", command=self.close)
        self.cancel_button.pack(side="right", padx=8)
        self.footer = ttk.Label(self, textvariable=self.status, wraplength=780, padding=(16, 0, 16, 12), justify="left")
        self.footer.grid(row=4, column=0, sticky="ew")
        self.bind("<Configure>", self._resize, add=True)
        self.initial = self._values()
        self.grab_set()

    def _resize(self, event):
        if event.widget is self:
            for label in (self.notice, self.footer):
                label.configure(wraplength=max(350, event.width - 40))

    def _values(self):
        return (self.task_title.get(), self.priority.get(), self.responsible.get(),
                self.reason.get("1.0", "end-1c"), self.action_status.get(), self.text.get("1.0", "end-1c"))

    def save(self):
        if self._disposed:
            return
        title, priority, responsible, reason, status_label, note = self._values()
        try:
            if self.task is None:
                self.store.add_custom(self.incident.id, expected_revision=self.incident.revision,
                                      title=title, reason=reason, priority=priority, responsible=responsible)
            else:
                reverse = {label: key for key, label in STATUS_LABELS.items()}
                if status_label not in reverse:
                    raise ValueError("choose a valid action status")
                self.store.update_task(self.task.id, expected_revision=self.task.revision, status=reverse[status_label],
                                       note=note, responsible=responsible, title=title, reason=reason, priority=priority)
            self.result = self.incident.id
        except _ERRORS as exc:
            self.status.set("Not saved: " + str(exc))
            return
        self.destroy()

    def close(self):
        if self._values() != self.initial and not messagebox.askyesno(
            "Discard unsaved task edits?", "Copy any text you need first. Discard these unsaved changes?", parent=self
        ):
            return
        self.destroy()

    def _destroyed(self, event):
        if event.widget is self and not self._disposed:
            self._disposed = True
            self.finished(self.result)


class ActionWorkspace(EmergencyTab):
    """Keep existing incident lifecycle/journal behavior, extend checklist editing."""

    def __init__(self, parent, store: ActionStore) -> None:
        # The base constructor calls refresh/_clear before these controls exist.
        self.add_action_button = None
        super().__init__(parent, store)
        self.notice.configure(text=NOTICE + " Responsibility labels do not send notifications.")
        self.tasks.configure(columns=("priority", "status", "responsible"))
        for key, label, width in (("priority", "Priority", 80), ("status", "Progress", 150),
                                  ("responsible", "Responsible alias", 160)):
            self.tasks.heading(key, text=label)
            self.tasks.column(key, width=width, minwidth=70, stretch=False)
        self.add_action_button = ttk.Button(self.edit_button.master, text="Add own task…", command=self.add_action, state="disabled")
        self.add_action_button.grid(row=3, column=0, sticky="e")
        self.copy_button.configure(text="Copy checklist (no notes / assignees)")
        self.refresh()

    def _clear(self):
        super()._clear()
        if self.add_action_button is not None:
            self.add_action_button.configure(state="disabled")

    def select_session(self):
        if self.dialog is not None:
            return
        selected_task = self.tasks.selection()
        prior_session = self.current.incident.id if self.current else None
        super().select_session()
        if self.current is None:
            return
        for task in self.current.tasks:
            self.tasks.item(str(task.id), text=f"{task.position}. [{ORIGIN_LABELS[task.origin]}] {task.title}",
                            values=(task.priority.upper(), STATUS_LABELS[task.status], task.responsible or "Unassigned"))
        # Queued Treeview session events may repeat after refresh. Keep a task
        # selected rather than wiping out a just-made keyboard/mouse selection.
        if (selected_task and prior_session == self.current.incident.id
                and self.tasks.exists(selected_task[0])):
            self.tasks.selection_set(selected_task[0])
        unassigned = sum(not task.responsible for task in self.current.tasks)
        self.summary.set(self.summary.get() + f"\n{unassigned} actions unassigned. Labels do not notify or verify acceptance.")
        if self.add_action_button is not None:
            self.add_action_button.configure(state="normal" if self.current.incident.state == "active" else "disabled")

    def select_task(self):
        super().select_task()
        task = self.selected_task()
        if task is not None:
            self._text(self.task_details, f"{ORIGIN_LABELS[task.origin]} · {task.title}\n{task.reason}\n\n"
                       f"Responsible alias: {task.responsible or 'Unassigned'} (no notification sent)\n\n"
                       f"Private note:\n{task.note or '(none)'}")

    def add_action(self):
        if self.current and self.dialog is None and self.current.incident.state == "active":
            self.dialog = ActionEditor(self, self.store, self.current.incident, None, self._finished)

    def edit_task(self):
        task = self.selected_task()
        if task and self.dialog is None and self.current.incident.state == "active":
            self.dialog = ActionEditor(self, self.store, self.current.incident, task, self._finished)

    def copy(self):
        if self.current is None or self.dialog is not None:
            return
        try:
            detail = self.store.detail(self.current.incident.id)
            self.clipboard_clear()
            self.clipboard_append(render_action_checklist(detail))
            self.status.set("Copied titles, descriptions and statuses. Responsibility labels, private notes and logs excluded. "
                            "Titles/descriptions may contain personal text. This is not a backup.")
        except (OSError, ValueError, sqlite3.Error, tk.TclError) as exc:
            self.status.set("Could not copy checklist: " + str(exc))
