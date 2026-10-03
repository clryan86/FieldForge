"""Three desktop makers with background generation and offline editable artifacts."""

from __future__ import annotations

import copy
import json
import queue
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.blueprints.checks import check_design
from fieldforge.blueprints.constraints import require_consistent_rules
from fieldforge.blueprints.engine import BlueprintRequest, _json, digest, generate_blueprint
from fieldforge.blueprints.evidence import retrieve_blueprint_evidence
from fieldforge.blueprints.render import (
    export_blueprint,
    load_blueprint,
    normalized_document,
    readable,
    save_blueprint,
)
from fieldforge.blueprints.review_files import load_review, validate_review
from fieldforge.blueprints.schema import MODES
from fieldforge.content import install_reference_library
from fieldforge.knowledge.assistant import GenerationCancelled, OllamaClient
from fieldforge.ui.blueprint_acceptance import AcceptanceLimits
from fieldforge.ui.blueprint_diagnostics import BlueprintDiagnostics
from fieldforge.ui.blueprint_evidence import BlueprintEvidence
from fieldforge.ui.blueprint_history import ProjectHistory
from fieldforge.ui.blueprint_parameters import PartParameters
from fieldforge.ui.blueprint_preview import DrawingPreview
from fieldforge.ui.blueprint_revision import RevisionReview, project_identity
from fieldforge.ui.lifecycle import release_tk_references

EXAMPLES = {
    "engineering": ("Engineering Blueprint Maker",
                    "Define dimensions, site conditions, loads, materials and tools. "
                    "Outputs: dimensioned envelope views, materials, calculations and build steps.",
                    "Design a storage rack. State the intended loads, available timber dimensions, "
                    "connections and space constraints; flag missing strength evidence."),
    "project": ("Project Blueprint Maker",
                "Define the result, people, time, budget and acceptance criteria. "
                "Outputs: phases, dependency schedule, resources, risks and illustrated guide.",
                "Plan a community workshop with phased setup, tool inventory, responsibilities "
                "and verifiable acceptance criteria."),
    "software": ("Software Blueprint Maker",
                 "Define users, capabilities, offline requirements, data and trust boundaries. "
                 "Outputs: components, data flows, architecture decisions and implementation steps.",
                 "Design an offline inventory application with SQLite, backup, import/export "
                 "and explicit trust boundaries."),
}


class BlueprintMaker(ttk.Frame):
    def __init__(self, parent, library, mode):
        super().__init__(parent, padding=12)
        self.library, self.mode = library, mode
        self.blueprint = None
        self.part_editor = None
        self.revision_review = None
        self._refinement_context = None
        self.dirty = False
        self.busy = False
        self._closed = False
        self._poll_id = None
        self._cancel = threading.Event()
        self._messages = queue.SimpleQueue()
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-blueprint")
        self.bind("<Destroy>", self._destroyed, add=True)
        self.status = tk.StringVar(value="Create a brief, choose a local model, then Generate.")
        self.model = tk.StringVar()
        self.port = tk.StringVar(value="11434")
        self.query = tk.StringVar()
        title, description, example = EXAMPLES[mode]
        ttk.Label(self, text=title, font=("TkDefaultFont", 18, "bold")).pack(anchor="w")
        ttk.Label(self, text=description, wraplength=980).pack(fill="x", pady=6)
        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Label(row, text="Local Ollama port").pack(side="left")
        ttk.Entry(row, textvariable=self.port, width=7).pack(side="left", padx=6)
        ttk.Button(row, text="Load models", command=self.load_models).pack(side="left")
        self.models = ttk.Combobox(row, textvariable=self.model, state="readonly", width=26)
        self.models.pack(side="left", padx=6, fill="x", expand=True)
        self.generate_button = ttk.Button(row, text="Generate blueprint", command=self.generate)
        self.generate_button.pack(side="left")
        ttk.Button(row, text="Cancel", command=lambda: self._cancel.set()).pack(side="left", padx=6)
        self.pages = ttk.Notebook(self)
        self.pages.pack(fill="both", expand=True, pady=8)
        brief_page, result_page, edit_page = (ttk.Frame(self.pages, padding=8) for _ in range(3))
        self.pages.add(brief_page, text="Requirements")
        self.requirement_pages = ttk.Notebook(brief_page)
        self.requirement_pages.pack(fill="both", expand=True)
        input_page = ttk.Frame(self.requirement_pages, padding=6)
        self.requirement_pages.add(input_page, text="Brief and resources")
        self.acceptance = AcceptanceLimits(self.requirement_pages, self)
        self.requirement_pages.add(self.acceptance, text="Acceptance limits")
        self.evidence = BlueprintEvidence(self.requirement_pages, self)
        self.requirement_pages.add(self.evidence, text="Source evidence")
        self.pages.add(result_page, text="Blueprint and checks")
        self.preview = DrawingPreview(self.pages, self.prepare_clearance_limit)
        self.pages.add(self.preview, text="Drawings")
        self.pages.add(edit_page, text="Edit design")
        refine_page = ttk.Frame(self.pages, padding=8)
        self.pages.add(refine_page, text="Refine with AI")
        self.refinement_pages = ttk.Notebook(refine_page)
        self.refinement_pages.pack(fill="both", expand=True)
        self.revision_input = ttk.Frame(self.refinement_pages, padding=6)
        self.refinement_pages.add(self.revision_input, text="Revision instructions")
        self.diagnostics = BlueprintDiagnostics(self.refinement_pages, self)
        self.refinement_pages.add(self.diagnostics, text="Measured failures")
        self.instructions = self._field(self.revision_input, "What should change in the current design?",
                                        "", 6)
        ttk.Label(self.revision_input, text="The existing design, measured failures and current Requirements are included. "
                  "Evidence is searched again. Review the candidate before applying it to your draft or project.",
                  wraplength=950).pack(fill="x", pady=6)
        revision_actions = ttk.Frame(self.revision_input)
        revision_actions.pack(fill="x")
        ttk.Button(revision_actions, text="Resume saved review", command=self.resume_review).pack(side="left")
        ttk.Button(revision_actions, text="Revise current design", command=self.refine).pack(side="right")
        self.history = ProjectHistory(self.pages, self)
        self.pages.add(self.history, text="Project and revisions")
        self.brief = self._field(input_page, "What do you want to build or achieve?", example, 4)
        self.constraints = self._field(input_page, "Constraints and acceptance criteria", "", 3)
        self.resources = self._field(input_page, "Available materials, tools, people or technology", "", 3)
        ttk.Label(input_page, text="Evidence keywords (optional; improves local reference selection)").pack(anchor="w")
        self.query_entry = ttk.Entry(input_page, textvariable=self.query)
        self.query_entry.pack(fill="x", pady=4)
        self.result = ScrolledText(result_page, wrap="word", state="disabled", font="TkDefaultFont")
        self.result.pack(fill="both", expand=True)
        ttk.Label(edit_page, text="Edit the structured design, then Apply edits. "
                  "Manual edits invalidate the previous model critique.", wraplength=950).pack(anchor="w")
        if mode == "engineering":
            ttk.Button(edit_page, text="Edit part dimensions and position…", command=self.edit_part).pack(anchor="w", pady=4)
        self.editor = ScrolledText(edit_page, wrap="none", undo=True)
        self.editor.pack(fill="both", expand=True, pady=4)
        ttk.Button(edit_page, text="Apply edits and recompute", command=self.apply_edits).pack(anchor="e")
        actions = ttk.Frame(self)
        actions.pack(fill="x")
        ttk.Button(actions, text="Open saved design", command=self.open_saved).pack(side="left")
        ttk.Button(actions, text="Save design", command=self.save).pack(side="left", padx=6)
        ttk.Button(actions, text="Export drawings and report", command=self.export).pack(side="left")
        ttk.Label(self, textvariable=self.status, wraplength=980).pack(fill="x", pady=6)

    def _field(self, parent, label, example, height):
        ttk.Label(parent, text=label).pack(anchor="w")
        entry = ScrolledText(parent, height=height, wrap="word")
        entry.pack(fill="both", expand=True, pady=(2, 6))
        entry.insert("1.0", example)
        return entry

    def _destroyed(self, event):
        if event.widget is self:
            self._closed = True
            self._cancel.set()
            if self._poll_id is not None:
                self.after_cancel(self._poll_id)
                self._poll_id = None
            self._worker.shutdown(wait=False, cancel_futures=True)
            release_tk_references(self)

    def _start(self, function, *args, operation, **kwargs):
        if self.busy:
            return
        if self.revision_review is not None:
            self.revision_review.lift()
            self.status.set("Apply, export or discard the pending AI candidate first.")
            return
        self.busy = True
        self._cancel.clear()
        self.generate_button.configure(state="disabled")
        self._input_state("disabled")
        self.status.set(operation)
        future = self._worker.submit(function, *args, **kwargs)
        self._poll(future, operation)

    def _poll(self, future, operation):
        if self._closed:
            return
        while not self._messages.empty():
            self.status.set(self._messages.get())
        if not future.done():
            self._poll_id = self.after(60, self._poll, future, operation)
            return
        self._poll_id = None
        self.busy = False
        self.generate_button.configure(state="normal")
        self._input_state("normal")
        context, self._refinement_context = self._refinement_context, None
        if self._cancel.is_set():
            self.status.set("Blueprint cancelled. No generated revision was saved.")
            return
        try:
            value = future.result()
            if operation == "Loading local models":
                self.models.configure(values=value)
                self.model.set(value[0] if value else "")
                self.status.set(f"{len(value)} local models available.")
            elif operation == "Previewing evidence":
                self.evidence.show(value)
                self.pages.select(0)
                self.requirement_pages.select(self.evidence)
                self.status.set(f"{len(value['sources'])} source passages found. The design has not changed.")
            elif operation == "Refining design":
                if context is None:
                    raise ValueError("The original refinement context is unavailable; draft unchanged.")
                self.revision_review = RevisionReview(self, value, context)
                self.status.set("AI candidate ready for review. Apply, export or discard it; the working draft is unchanged.")
            else:
                self.show_blueprint(value)
                self.load_request(value)
                self.history.after_change("generated", self._change_note)
        except Exception as exc:
            self.status.set(str(exc))

    def _input_state(self, state):
        for name in ("brief", "constraints", "resources", "instructions", "editor", "query_entry"):
            getattr(self, name).configure(state=state)
        self.models.configure(state="readonly" if state == "normal" else "disabled")
        self.acceptance.set_busy(state != "normal")
        self.evidence.preview_button.configure(state=state)

    def load_models(self):
        try:
            self._start(OllamaClient(port=int(self.port.get())).list_models,
                        cancel=self._cancel, operation="Loading local models")
        except ValueError as exc:
            self.status.set(str(exc))

    def generate(self):
        if self.busy or self._review_pending():
            return
        if not self.model.get():
            self.status.set("Load models and select an installed local model first.")
            return
        if self.blueprint is not None and not self._can_replace():
            return
        self._generate()

    def refine(self):
        if self.busy or self._review_pending() or self.blueprint is None or not self._edits_applied():
            return
        if not self.model.get():
            self.status.set("Load models and select an installed local model first.")
            return
        instruction = self.instructions.get("1.0", "end-1c").strip()
        if not 5 <= len(instruction) <= 4000:
            self.status.set("Describe the requested changes in 5 to 4000 characters.")
            return
        self._generate(instruction)

    def _generate(self, instruction=""):
        try:
            request = self._request()
            require_consistent_rules(request.mode, request.acceptance_rules)
            client = OllamaClient(port=int(self.port.get()), timeout=300)
            if not instruction and not self.history.before_change():
                return
            self._change_note = instruction or "Generate design from requirements"
            extra = {}
            if instruction:
                before = normalized_document(copy.deepcopy(self.blueprint))
                self._refinement_context = {"before": before, "request": copy.deepcopy(request.__dict__),
                                            "instructions": instruction, "project": project_identity(self.history)}
                extra = {"previous": copy.deepcopy(before), "instructions": instruction}
            self._start(generate_blueprint, self.library, request, self.model.get(), client,
                        cancel=self._cancel, progress=self._messages.put,
                        operation="Refining design" if instruction else "Generating design", **extra)
        except ValueError as exc:
            self._refinement_context = None
            self.status.set(str(exc))

    def _review_pending(self):
        if self.revision_review is None:
            return False
        self.revision_review.lift()
        self.status.set("Apply, export or discard the pending AI candidate first.")
        return True

    def resume_review(self):
        if self.busy or self._review_pending():
            return
        if self.blueprint is not None and not self._edits_applied():
            return
        path = filedialog.askopenfilename(parent=self, title="Resume an unapplied revision review",
                                         filetypes=[("Revision review", "*.ffreview.json")])
        if not path:
            return
        try:
            value = load_review(path)
            proposal = validate_review(value)
            candidate = proposal["candidate"]
            if candidate["request"]["mode"] != self.mode:
                raise ValueError("Resume this review in its matching blueprint maker.")
            empty = self.blueprint is None
            if empty and not self._can_replace():
                return
            # Resuming into an empty maker restores the original as an unsaved
            # draft. Existing drafts, requirements and project associations stay put.
            request = copy.deepcopy(candidate["request"])
            request.update(revision_of="", revision_instructions="")
            guard = (BlueprintRequest(**request).__dict__ if empty else self._request().__dict__)
            context = {"before": proposal["before"], "request": request, "guard_request": copy.deepcopy(guard),
                       "instructions": candidate["request"]["revision_instructions"],
                       "lineage_sha256": candidate["request"]["revision_of"],
                       "project": None if empty else project_identity(self.history)}
            review = RevisionReview(self, candidate, context)
            if empty:
                self.show_blueprint(proposal["before"])
                self.history.detach()
                self.load_request(candidate)
            self.revision_review = review
            review._ready()  # Explain a stale baseline immediately; export remains usable.
            self.status.set("Saved review reopened. The candidate remains unapplied.")
        except (ValueError, OSError) as exc:
            self.status.set(str(exc))

    def _request(self):
        return BlueprintRequest(self.mode, self.brief.get("1.0", "end-1c"),
                                self.constraints.get("1.0", "end-1c"),
                                self.resources.get("1.0", "end-1c"), self.query.get(),
                                acceptance_rules=self.acceptance.get_rules())

    def preview_evidence(self):
        if self.busy:
            return

        def checkpoint(message):
            if self._cancel.is_set():
                raise GenerationCancelled("Evidence preview cancelled.")
            self._messages.put(message)

        try:
            self._start(retrieve_blueprint_evidence, self.library, self._request(),
                        self.instructions.get("1.0", "end-1c"), checkpoint,
                        operation="Previewing evidence")
        except ValueError as exc:
            self.status.set(str(exc))

    def show_blueprint(self, value, *, dirty=True):
        value = normalized_document(value)
        self.blueprint = value
        self.dirty = dirty
        self.acceptance.set_rules(value["request"].get("acceptance_rules", []))
        self.evidence.show_saved(value)
        self.preview.show(value)
        self.diagnostics.show(value)
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", json.dumps(value["design"], ensure_ascii=False, indent=2))
        lines = [value["design"]["title"], value["design"]["summary"], "",
                 "STATUS: " + value["status"], "Design draft; not certified.", ""]
        for name, data in value["design"].items():
            if name in {"title", "summary"}:
                continue
            lines += [name.replace("_", " ").upper(), readable(data), ""]
        lines += ["DETERMINISTIC CHECKS", readable(value["validation"]),
                  "MODEL CRITIQUE", readable(value["review"]),
                  value.get("review_error", ""), "SOURCE EVIDENCE",
                  readable(value["sources"])]
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        self.result.insert("1.0", "\n".join(lines))
        self.result.configure(state="disabled")
        self.pages.select(1)
        self.status.set("Design ready for review. Export includes an offline report and vector drawings.")

    def has_unsaved_changes(self):
        if self.revision_review is not None:
            return True
        if self.blueprint is None:
            return bool(self.acceptance.rules)
        expected = json.dumps(self.blueprint["design"], ensure_ascii=False, indent=2)
        return (self.dirty or self.editor.get("1.0", "end-1c") != expected
                or self.acceptance.rules != self.blueprint["request"].get("acceptance_rules", []))

    def _can_replace(self):
        return not self.has_unsaved_changes() or messagebox.askyesno(
            "Replace unsaved design?", "Replace this maker's unsaved design or edits?", parent=self)

    def _edits_applied(self, *, check_limits=True):
        if self.editor.get("1.0", "end-1c") != json.dumps(
                self.blueprint["design"], ensure_ascii=False, indent=2):
            self.status.set("Apply your design edits before saving or exporting.")
            return False
        if check_limits and self.acceptance.rules != self.blueprint["request"].get("acceptance_rules", []):
            self.status.set("Apply your acceptance limits before saving, exporting or refining.")
            return False
        return True

    def apply_limits(self):
        if self.busy or self.blueprint is None or not self._edits_applied(check_limits=False):
            return
        try:
            value = copy.deepcopy(self.blueprint)
            rules = self.acceptance.get_rules()
            if rules == value["request"].get("acceptance_rules", []):
                self.status.set("Acceptance limits are already applied.")
                return
            value["request"]["acceptance_rules"] = rules
            value.update(review=None, review_error="Acceptance limits changed; a new review is required.")
            value = normalized_document(value)
            if not self.history.before_change():
                return
            self.show_blueprint(value)
            self.history.after_change("edited", "Update user acceptance limits")
        except (ValueError, OSError) as exc:
            self.status.set("Limits not applied: " + str(exc))

    def prepare_clearance_limit(self, ids):
        if self.busy or self.blueprint is None:
            return
        form = self.acceptance
        form.metric.set("Pair clearance")
        form._metric_changed()
        form.target.set(ids[0])
        form.second_target.set(ids[1])
        form.operator.set(">=")
        form.value.set("")
        form.label.set(f"Clearance {ids[0]} / {ids[1]}")
        self.pages.select(0)
        self.requirement_pages.select(form)
        form.value_entry.focus_set()
        self.status.set("Enter the required clearance, then Add limit and Apply limits to design.")

    def apply_edits(self):
        if self.busy or self.blueprint is None:
            return
        try:
            design = _json(self.editor.get("1.0", "end-1c"))
            rules = self.acceptance.get_rules()
            validation = check_design(self.mode, design, {s["id"] for s in self.blueprint["sources"]}, rules)
            value = copy.deepcopy(self.blueprint)
            value["request"]["acceptance_rules"] = rules
            value.update(design=design, design_sha256=digest(design), validation=validation,
                         review=None, review_error="Manual edits require a new review.",
                         status="needs_revision")
            if not self.history.before_change():
                return
            self.show_blueprint(value)
            self.history.after_change("edited", "Apply manual design edits")
        except (ValueError, TypeError, RecursionError) as exc:
            self.status.set("Edits not applied: " + str(exc))

    def edit_part(self):
        if self.busy or self.blueprint is None or not self._edits_applied():
            return
        if self.part_editor is not None:
            self.part_editor.lift()
            return
        try:
            self.part_editor = PartParameters(self)
        except ValueError as exc:
            self.status.set(str(exc))

    def open_saved(self):
        if self.busy or not self._can_replace():
            return
        path = filedialog.askopenfilename(parent=self, filetypes=[("Blueprint JSON", "*.json")])
        if path:
            try:
                value = load_blueprint(path)
                if value["request"]["mode"] != self.mode:
                    raise ValueError("Open this design in its matching blueprint maker.")
                self.show_blueprint(value, dirty=False)
                self.load_request(value)
                self.history.detach()
            except (ValueError, OSError) as exc:
                self.status.set(str(exc))

    def load_request(self, value):
        for field in ("brief", "constraints", "resources"):
            widget = getattr(self, field)
            widget.delete("1.0", "end")
            widget.insert("1.0", value["request"].get(field, ""))
        self.query.set(value["request"].get("evidence_query", ""))
        self.instructions.delete("1.0", "end")

    def save(self):
        if self.busy or self.blueprint is None or not self._edits_applied():
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".json",
                                          filetypes=[("Blueprint JSON", "*.json")])
        if path:
            try:
                save_blueprint(self.blueprint, path)
                self.dirty = False
                self.status.set("Saved design locally.")
            except (ValueError, OSError) as exc:
                self.status.set(str(exc))

    def export(self):
        if self.busy or self.blueprint is None or not self._edits_applied():
            return
        directory = filedialog.askdirectory(parent=self, title="Choose parent export folder")
        if directory:
            from pathlib import Path
            from tkinter.simpledialog import askstring
            name = askstring("Export name", "New folder name:", parent=self)
            if not name or Path(name).name != name or name in {".", ".."}:
                return
            try:
                export_blueprint(self.blueprint, Path(directory) / name)
                self.dirty = False
                self.status.set("Exported. Open report.html for drawings and a printable report.")
            except (ValueError, OSError) as exc:
                self.status.set(str(exc))


class BlueprintStudio(tk.Toplevel):
    def __init__(self, parent, library):
        super().__init__(parent)
        self.title("FieldForge — Blueprint Studios")
        self.geometry("1100x760")
        self.minsize(760, 650)
        self.library = library
        self.makers = {}
        self.pages = ttk.Notebook(self)
        self.pages.pack(fill="both", expand=True)
        for mode, title in MODES.items():
            maker = BlueprintMaker(self.pages, library, mode)
            self.pages.add(maker, text=title)
            self.makers[mode] = maker
        self.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        if any(maker.busy or maker.has_unsaved_changes() for maker in self.makers.values()):
            if not messagebox.askyesno("Close blueprint makers?", "Cancel active work, discard unsaved designs and close?",
                                       parent=self):
                return
        self.destroy()


def run(library):
    root = tk.Tk()
    root.withdraw()
    if library.count() == 0:
        install_reference_library(library)
    studio = BlueprintStudio(root, library)
    studio.bind("<Destroy>", lambda event: root.destroy() if event.widget is studio else None, add=True)
    root.mainloop()
