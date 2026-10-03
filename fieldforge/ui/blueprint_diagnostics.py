"""Inspect deterministic failures and prepare a focused, user-reviewed revision."""

from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.blueprints.diagnostics import diagnose_blueprint, repair_instructions
from fieldforge.blueprints.render import readable


class BlueprintDiagnostics(ttk.Frame):
    def __init__(self, parent, maker):
        super().__init__(parent, padding=6)
        self.maker, self.report = maker, None
        actions = ttk.Frame(self)
        actions.pack(fill="x")
        ttk.Button(actions, text="Refresh checks", command=self.refresh).pack(side="left")
        self.prepare_button = ttk.Button(actions, text="Add selected failures to revision", command=self.prepare)
        self.prepare_button.pack(side="left", padx=6)
        self.header = ttk.Label(self, text="Open a design to inspect its applied acceptance limits. No model is needed.",
                                wraplength=680)
        self.header.pack(fill="x", pady=6)
        self.bind("<Configure>", lambda event: self.header.configure(wraplength=max(200, event.width - 20)))
        panes = ttk.Panedwindow(self, orient="vertical")
        panes.pack(fill="both", expand=True)
        upper = ttk.Frame(panes)
        self.rows = ttk.Treeview(upper, columns=("id", "status", "target", "actual"), show="headings", height=4)
        for key, label, width in (("id", "Rule", 70), ("status", "Result", 100), ("target", "Target", 120),
                                   ("actual", "Measured value", 230)):
            self.rows.heading(key, text=label)
            self.rows.column(key, width=width, minwidth=50)
        scroll = ttk.Scrollbar(upper, command=self.rows.yview)
        self.rows.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.rows.pack(fill="both", expand=True)
        self.rows.bind("<<TreeviewSelect>>", self.select)
        panes.add(upper, weight=1)
        self.details = ScrolledText(panes, wrap="word", state="disabled", height=6, font="TkDefaultFont")
        panes.add(self.details, weight=2)

    def _text(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def show(self, value):
        self.report = diagnose_blueprint(value)
        report = self.report
        self.rows.delete(*self.rows.get_children())
        for row in report["acceptance"]:
            approx = "approximately " if row.get("actual_is_rounded") else ""
            actual = "unresolved" if row["actual"] is None else approx + str(row["actual"]) + " " + row["unit"]
            self.rows.insert("", "end", iid=row["id"], values=(row["id"], row["status"], row["target"], actual))
        self.header.configure(text=(f"Applied design: {len(report['failing_rule_ids'])} failed, "
                                   f"{len(report['unresolved_rule_ids'])} unresolved, {len(report['passing_rule_ids'])} passed. "
                                   f"{len(report['constraints']['conflicts'])} conflicting rule groups. "
                                   "Select failures to prepare instructions; generation starts only when you choose Revise."))
        self.rows.selection_set(report["failing_rule_ids"] + report["unresolved_rule_ids"])
        self.select()

    def select(self, _event=None):
        if self.report is None:
            return
        selected = set(self.rows.selection())
        rows = [row for row in self.report["acceptance"] if row["id"] in selected]
        text = readable({"selected_rules": rows,
                         **{key: value for key, value in self.report.items() if key != "acceptance"}})
        self._text(text)

    def refresh(self):
        if self.maker.busy or self.maker.blueprint is None or not self.maker._edits_applied():
            return
        self.show(self.maker.blueprint)
        self.maker.status.set("Diagnostics recomputed for the applied design. No model was called.")

    def prepare(self):
        if self.maker.busy or self.maker.blueprint is None or not self.maker._edits_applied():
            return
        try:
            # Never trust cached measurements if the applied design has since changed.
            report = diagnose_blueprint(self.maker.blueprint)
            instruction = repair_instructions(report, list(self.rows.selection()))
            existing = self.maker.instructions.get("1.0", "end-1c").strip()
            combined = existing + "\n\n" + instruction if existing else instruction
            if len(combined) > 4000:
                raise ValueError("Revision instructions would exceed 4000 characters. Shorten the existing text first.")
            self.maker.instructions.delete("1.0", "end")
            self.maker.instructions.insert("1.0", combined)
            self.maker.refinement_pages.select(self.maker.revision_input)
            self.maker.instructions.focus_set()
            self.maker.status.set("Repair instructions added. Review them, choose a local model, then Revise current design.")
        except ValueError as exc:
            self.maker.status.set(str(exc))
