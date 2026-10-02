"""Configure user-owned acceptance limits without editing JSON."""

import copy
import tkinter as tk
from tkinter import ttk

from fieldforge.blueprints.acceptance import METRICS, validate_rules
from fieldforge.ui.lifecycle import release_tk_references


class AcceptanceLimits(ttk.Frame):
    def __init__(self, parent, maker):
        super().__init__(parent, padding=8)
        self.maker = maker
        self.rules = []
        self._busy = False
        self._widgets = []
        self.metric = tk.StringVar()
        self.target = tk.StringVar()
        self.operator = tk.StringVar(value="<=")
        self.value = tk.StringVar(value="1")
        self.label = tk.StringVar()
        self.unit = tk.StringVar()
        self.note = tk.StringVar(value="No acceptance limits configured.")
        self.choices = {spec[3]: key for key, spec in METRICS.items() if spec[0] in (maker.mode, "all")}
        self.bind("<Destroy>", self._destroyed, add=True)
        self.notice = ttk.Label(self, text="Set limits the app will check on every design and revision. "
                                "Missing targets fail the check. These checks do not verify real-world performance.",
                                wraplength=650)
        self.notice.pack(fill="x", pady=(0, 6))
        form = ttk.Frame(self)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        ttk.Label(form, text="Measurement").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.measurements = ttk.Combobox(form, textvariable=self.metric, values=list(self.choices), state="readonly")
        self.measurements.grid(row=0, column=1, columnspan=3, sticky="ew", pady=3)
        self.measurements.bind("<<ComboboxSelected>>", self._metric_changed)
        self.target_label = ttk.Label(form, text="Target ID")
        self.target_label.grid(row=1, column=0, sticky="w")
        self.target_entry = ttk.Entry(form, textvariable=self.target, width=18)
        self.target_entry.grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(form, text="Comparison").grid(row=1, column=2, padx=8)
        self.operators = ttk.Combobox(form, textvariable=self.operator, width=6, state="readonly")
        self.operators.grid(row=1, column=3, sticky="ew")
        ttk.Label(form, text="Limit").grid(row=2, column=0, sticky="w")
        value_entry = ttk.Entry(form, textvariable=self.value)
        value_entry.grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Label(form, textvariable=self.unit).grid(row=2, column=2, sticky="w", padx=8)
        ttk.Label(form, text="Label").grid(row=3, column=0, sticky="w")
        label_entry = ttk.Entry(form, textvariable=self.label)
        label_entry.grid(row=3, column=1, columnspan=3, sticky="ew", pady=3)
        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=5)
        for text, command in (("Add limit", self.add), ("Remove selected", self.remove),
                              ("Apply limits to design", maker.apply_limits)):
            button = ttk.Button(actions, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            self._widgets.append(button)
        self._widgets.extend([value_entry, label_entry])
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True)
        self.rows = ttk.Treeview(tree_frame, columns=("label", "limit", "target"), show="headings", height=4)
        for key, title, width in (("label", "Label", 220), ("limit", "Limit", 240), ("target", "Target", 80)):
            self.rows.heading(key, text=title)
            self.rows.column(key, width=width, minwidth=60)
        scroll = ttk.Scrollbar(tree_frame, command=self.rows.yview)
        self.rows.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.rows.pack(fill="both", expand=True)
        self.rows.bind("<<TreeviewSelect>>", self._selected)
        self.details = ttk.Label(self, textvariable=self.note, wraplength=650)
        self.details.pack(fill="x", pady=5)
        self.bind("<Configure>", self._resize)
        default = {"engineering": "Overall X span", "project": "Dependency schedule duration",
                   "software": "Component retained"}[maker.mode]
        self.metric.set(default)
        self._metric_changed()

    def _destroyed(self, event):
        if event.widget is self:
            release_tk_references(self)

    def _resize(self, event):
        width = max(200, event.width - 20)
        self.notice.configure(wraplength=width)
        self.details.configure(wraplength=width)

    def _metric_changed(self, _event=None):
        key = self.choices[self.metric.get()]
        spec = METRICS[key]
        self.unit.set(spec[1])
        self.target_label.configure(text=spec[2] or "Whole design")
        if not spec[2]:
            self.target.set("")
        allowed = ("=",) if spec[4] == "string" or key.endswith(".exists") else ("<=", "=", ">=")
        self.operators.configure(values=allowed)
        if self.operator.get() not in allowed:
            self.operator.set(allowed[0])
        if key.endswith(".exists"):
            self.value.set("1")
        self.set_busy(self._busy)

    def set_busy(self, busy):
        self._busy = busy
        for widget in self._widgets:
            widget.configure(state="disabled" if busy else "normal")
        for widget in (self.measurements, self.operators):
            widget.configure(state="disabled" if busy else "readonly")
        needs_target = METRICS[self.choices[self.metric.get()]][2]
        self.target_entry.configure(state="normal" if needs_target and not busy else "disabled")

    def get_rules(self):
        validate_rules(self.maker.mode, self.rules)
        return copy.deepcopy(self.rules)

    def set_rules(self, rules):
        validate_rules(self.maker.mode, rules)
        self.rules = copy.deepcopy(rules)
        self.refresh()

    def refresh(self):
        self.rows.delete(*self.rows.get_children())
        for rule in self.rules:
            self.rows.insert("", "end", iid=rule["id"], values=(rule["label"],
                             f"{METRICS[rule['metric']][3]} {rule['operator']} {rule['value']} {rule['unit']}",
                             rule["target"] or "Whole design"))
        self.note.set(f"{len(self.rules)} limits. Add/remove, then apply to the current design or generate a new one.")

    def _selected(self, _event=None):
        selected = self.rows.selection()
        if selected:
            rule = next(row for row in self.rules if row["id"] == selected[0])
            self.note.set(f"{rule['id']}: {rule['label']} — {METRICS[rule['metric']][3]} "
                          f"({rule['target'] or 'whole design'}) {rule['operator']} {rule['value']} {rule['unit']}")

    def add(self):
        if self._busy:
            return
        try:
            metric = self.choices[self.metric.get()]
            spec = METRICS[metric]
            value = self.value.get().strip()
            if spec[4] == "number":
                value = float(value)
            ids = {row["id"] for row in self.rules}
            index = next(i for i in range(1, 32) if f"L{i}" not in ids)
            rule = {"id": f"L{index}", "label": self.label.get().strip() or spec[3], "metric": metric,
                    "target": self.target.get().strip(), "operator": self.operator.get(), "value": value,
                    "unit": spec[1]}
            updated = self.get_rules() + [rule]
            validate_rules(self.maker.mode, updated)
            self.set_rules(updated)
            self.maker.status.set("Limit added. Apply limits to save them with the current design.")
        except ValueError as exc:
            self.maker.status.set("Limit not added: " + str(exc))

    def remove(self):
        if not self._busy:
            selected = set(self.rows.selection())
            self.set_rules([row for row in self.rules if row["id"] not in selected])
