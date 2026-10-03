"""Preview and apply a single engineering part edit without replacing JSON by hand."""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.blueprints.comparison import comparison_text
from fieldforge.blueprints.engine import digest
from fieldforge.blueprints.parameters import NOTICE, editable_parts, prepare_part_edit
from fieldforge.blueprints.render import normalized_document
from fieldforge.ui.blueprint_preview import DrawingPreview
from fieldforge.ui.lifecycle import release_tk_references


class PartParameters(tk.Toplevel):
    def __init__(self, maker):
        # Validate before creating a window, so bad input leaves no partial editor.
        baseline = normalized_document(copy.deepcopy(maker.blueprint))
        parts = editable_parts(baseline)
        super().__init__(maker)
        self.maker, self.baseline, self.parts = maker, baseline, {p["id"]: p for p in parts}
        self.base_hash = digest(baseline)
        self.candidate = None
        self._loading = False
        self._traces = []
        self._loaded_inputs = None
        self._part_id = parts[0]["id"]
        self.title("FieldForge — Part measurement editor")
        self.geometry("1050x800")
        self.minsize(760, 650)
        self.transient(maker.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.part = tk.StringVar(value=self._part_id)
        self.status = tk.StringVar(value="Edit a dimension or position, then preview the changes.")
        self.sizes = [tk.StringVar() for _ in range(3)]
        self.positions = [tk.StringVar() for _ in range(3)]
        self.entries = []
        content = ttk.Frame(self, padding=12)
        content.pack(fill="both", expand=True)
        self.notice = ttk.Label(content, text=NOTICE, wraplength=980)
        self.notice.pack(fill="x", pady=(0, 6))
        selector = ttk.Frame(content)
        selector.pack(fill="x")
        ttk.Label(selector, text="Part ID").pack(side="left")
        self.parts_box = ttk.Combobox(selector, textvariable=self.part, values=list(self.parts), state="readonly")
        self.parts_box.pack(side="left", padx=8, fill="x", expand=True)
        self.parts_box.bind("<<ComboboxSelected>>", self._select_part)
        ttk.Button(selector, text="Reset edits", command=self.reset).pack(side="left")
        self.description = ttk.Label(content, wraplength=980)
        self.description.pack(fill="x", pady=6)
        form = ttk.Frame(content)
        form.pack(fill="x")
        for i, axis in enumerate("XYZ", 1):
            form.columnconfigure(i, weight=1)
            ttk.Label(form, text=axis).grid(row=0, column=i, sticky="w", padx=6)
        for row, label, variables in ((1, "Size", self.sizes), (2, "Position", self.positions)):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w")
            for column, variable in enumerate(variables, 1):
                entry = ttk.Entry(form, textvariable=variable, width=15)
                entry.grid(row=row, column=column, sticky="ew", padx=6, pady=3)
                self.entries.append(entry)
                self._traces.append((variable, variable.trace_add("write", self._edited)))
        ttk.Label(content, text="Bare numbers are millimeters. Examples: 250 mm, 25 cm, 0.25 m, 12 in, 1 ft.").pack(anchor="w", pady=5)
        actions = ttk.Frame(content)
        actions.pack(fill="x")
        self.preview_button = ttk.Button(actions, text="Preview changes", command=self.preview_changes)
        self.preview_button.pack(side="left")
        self.apply_button = ttk.Button(actions, text="Apply as draft revision", command=self.apply, state="disabled")
        self.apply_button.pack(side="left", padx=8)
        ttk.Button(actions, text="Close", command=self.close).pack(side="right")
        self.status_label = ttk.Label(content, textvariable=self.status, wraplength=980)
        self.status_label.pack(fill="x", pady=6)
        self.pages = ttk.Notebook(content)
        self.pages.pack(fill="both", expand=True)
        self.preview = DrawingPreview(self.pages, notice_text="Recorded rectangular envelopes. Checks and comparison describes "
                                      "the proposed changes and validation. Only Apply changes the main design.")
        self.pages.add(self.preview, text="Preview drawings")
        self.changes = ScrolledText(self.pages, wrap="word", state="disabled", font="TkDefaultFont")
        self.pages.add(self.changes, text="Checks and comparison")
        self.bind("<Configure>", self._resize)
        self.reset()
        self.grab_set()

    def _resize(self, event):
        if event.widget is self:
            for label in (self.notice, self.description, self.status_label):
                label.configure(wraplength=max(200, event.width - 36))

    def _destroyed(self, event):
        if event.widget is self:
            for variable, name in self._traces:
                variable.trace_remove("write", name)
            self._traces.clear()
            self.sizes.clear()
            self.positions.clear()
            self.entries.clear()
            if self.maker and getattr(self.maker, "part_editor", None) is self:
                self.maker.part_editor = None
            release_tk_references(self)

    def _inputs(self):
        return (self._part_id, tuple(v.get() for v in self.sizes), tuple(v.get() for v in self.positions))

    def _edited(self, *_args):
        if self._loading:
            return
        self.candidate = None
        self.apply_button.configure(state="disabled")
        self.status.set("Inputs changed. Preview again before applying; displayed drawings show the last computed state.")

    def _select_part(self, _event=None):
        if self._inputs() != self._loaded_inputs:
            self.part.set(self._part_id)
            self.status.set("Apply or reset this part's edits before choosing another part.")
            return
        self._part_id = self.part.get()
        self.reset()

    def reset(self):
        self._loading = True
        part = self.parts[self._part_id]
        for variables, field in ((self.sizes, "size_mm"), (self.positions, "position_mm")):
            for variable, value in zip(variables, part[field]):
                variable.set(str(value))
        self._loading = False
        self._loaded_inputs = self._inputs()
        self.candidate = None
        self.apply_button.configure(state="disabled")
        self.description.configure(text=f"{part['name']} — {part['material']}\n"
                                   f"{len(part['source_ids'])} source references. Inspect their details in the main design.")
        self.preview.show(self.baseline)
        self.preview.highlight_parts([self._part_id])
        self._text("Original applied design. Enter changed measurements and choose Preview changes.\n\n" + NOTICE)
        self.status.set("Original applied design displayed. Enter measurements to preview a change.")

    def _text(self, text):
        self.changes.configure(state="normal")
        self.changes.delete("1.0", "end")
        self.changes.insert("1.0", text)
        self.changes.configure(state="disabled")

    def _ready(self):
        if self.maker.busy or self.maker.blueprint is None:
            self.status.set("The maker is busy or has no applied design.")
            return False
        if not self.maker._edits_applied():
            self.status.set(self.maker.status.get())
            return False
        if digest(normalized_document(self.maker.blueprint)) != self.base_hash:
            self.status.set("The applied design changed. Close and reopen the part editor before continuing.")
            return False
        return True

    def preview_changes(self):
        if not self._ready():
            return
        self.candidate = None
        self.apply_button.configure(state="disabled")
        try:
            _, size, position = self._inputs()
            candidate = prepare_part_edit(self.baseline, self._part_id, size=size, position=position)
            self.preview.show(candidate["blueprint"])
            self.preview.highlight_parts([self._part_id])
            self._text(NOTICE + "\n\n" + comparison_text(candidate["comparison"]))
            self.candidate = candidate
            self.apply_button.configure(state="normal")
            outcomes = candidate["comparison"]["acceptance"]["outcomes"]
            self.status.set(f"Unapplied preview: {outcomes.get('regressed', 0)} regressed limits; "
                            f"{outcomes.get('now_passes', 0)} now pass. Review Checks and comparison before applying.")
            self.pages.select(self.changes)
        except ValueError as exc:
            self.status.set(str(exc))

    def apply(self):
        if not self._ready():
            return
        if self.candidate is None:
            self.status.set("Preview the current inputs before applying.")
            return
        if not self.maker.history.before_change():
            self.status.set(self.maker.status.get())
            return
        value = self.candidate["blueprint"]
        self.maker.show_blueprint(value)
        saved = self.maker.history.after_change("edited", f"Edit part {self._part_id} dimensions/position")
        if saved:
            self.maker.status.set("Part measurements applied as a draft. Review material schedules, calculations and build steps.")
        # If saving failed, the maker retains the applied draft and its explicit save error.
        self.destroy()

    def close(self):
        if self._inputs() != self._loaded_inputs and not messagebox.askyesno(
                "Discard part edits?", "Close without applying these part measurements?", parent=self):
            return
        self.destroy()
