"""Review an AI refinement before it replaces the working draft or project history."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.blueprints.comparison import comparison_text
from fieldforge.blueprints.engine import digest
from fieldforge.blueprints.projects import head
from fieldforge.blueprints.render import normalized_document
from fieldforge.blueprints.review_files import create_review, save_review
from fieldforge.blueprints.revision import candidate_text, export_revision, prepare_revision
from fieldforge.ui.blueprint_preview import DrawingPreview
from fieldforge.ui.lifecycle import release_tk_references


def project_identity(history):
    return (str(history.path), head(history.project)) if history.project is not None else None


class RevisionReview(tk.Toplevel):
    def __init__(self, maker, value, context):
        proposal = prepare_revision(context["before"], value)
        expected = {**context["request"], "revision_of": context.get("lineage_sha256", proposal["base_snapshot_sha256"]),
                    "revision_instructions": context["instructions"]}
        if proposal["candidate"]["request"] != expected:
            raise ValueError("The candidate does not match the submitted revision request.")
        super().__init__(maker)
        self.maker, self.proposal, self.context = maker, proposal, context
        self.title("FieldForge — Review AI revision")
        self.geometry("1050x800")
        self.minsize(760, 650)
        self.transient(maker.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.discard)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.status = tk.StringVar(value="The working draft and project history are unchanged.")
        content = ttk.Frame(self, padding=12)
        content.pack(fill="both", expand=True)
        outcomes = proposal["comparison"]["acceptance"]["outcomes"]
        self.heading = ttk.Label(content, text=(
            f"Proposed revision: {proposal['candidate']['status']} • "
            f"{outcomes.get('regressed', 0)} regressed limits • {outcomes.get('now_passes', 0)} now pass.\n"
            "Review the full design, evidence and checks. Apply keeps it as a draft; it does not certify the design."),
            wraplength=1000)
        self.heading.pack(fill="x", pady=(0, 8))
        actions = ttk.Frame(content)
        actions.pack(fill="x")
        self.apply_button = ttk.Button(actions, text="Apply as draft revision", command=self.apply)
        self.apply_button.pack(side="left")
        self.export_button = ttk.Button(actions, text="Export report", command=self.export)
        self.export_button.pack(side="left", padx=8)
        self.save_button = ttk.Button(actions, text="Save review for later", command=self.save)
        self.save_button.pack(side="left")
        ttk.Button(actions, text="Discard candidate", command=self.discard).pack(side="right")
        self.status_label = ttk.Label(content, textvariable=self.status, wraplength=1000)
        self.status_label.pack(fill="x", pady=8)
        self.pages = ttk.Notebook(content)
        self.pages.pack(fill="both", expand=True)
        self.changes = self._text_page("Changes and checks", comparison_text(proposal["comparison"]))
        self.details = self._text_page("Candidate and evidence", candidate_text(proposal["candidate"]))
        self.preview = DrawingPreview(self.pages, notice_text="Proposed draft drawings. Candidate and evidence contains "
                                      "the full text. The working design changes only when you Apply.")
        self.preview.show(proposal["candidate"])
        self.pages.add(self.preview, text="Candidate drawings")
        self.original = DrawingPreview(self.pages, notice_text="Original draft captured when the revision started.")
        self.original.show(proposal["before"])
        self.pages.add(self.original, text="Original drawings")
        self.bind("<Configure>", self._resize)
        self.grab_set()
        self.changes.focus_set()

    def _text_page(self, label, text):
        widget = ScrolledText(self.pages, wrap="word", font="TkDefaultFont")
        widget.insert("1.0", text)
        widget.configure(state="disabled")
        self.pages.add(widget, text=label)
        return widget

    def _resize(self, event):
        if event.widget is self:
            for label in (self.heading, self.status_label):
                label.configure(wraplength=max(200, event.width - 36))

    def _destroyed(self, event):
        if event.widget is self:
            if self.maker and getattr(self.maker, "revision_review", None) is self:
                self.maker.revision_review = None
            release_tk_references(self)

    def _ready(self):
        maker = self.maker
        if maker.busy or maker.blueprint is None:
            self.status.set("The maker is busy or has no applied design. The candidate remains available for export.")
            return False
        if not maker._edits_applied():
            self.status.set(maker.status.get())
            return False
        if digest(normalized_document(maker.blueprint)) != self.proposal["base_snapshot_sha256"]:
            self.status.set("The working draft changed. Export or discard this candidate and start a new revision.")
            return False
        if project_identity(maker.history) != self.context["project"]:
            self.status.set("The open project changed. Export or discard this candidate and start a new revision.")
            return False
        if maker._request().__dict__ != self.context.get("guard_request", self.context["request"]):
            self.status.set("The requirements changed. Export or discard this candidate and start a new revision.")
            return False
        return True

    def apply(self):
        try:
            if not self._ready():
                return
            # Freshly verify the candidate before touching the project. It must still
            # match the exact proposal displayed in this review window.
            checked = prepare_revision(self.proposal["before"], self.proposal["candidate"])
            if checked != self.proposal:
                raise ValueError("The candidate changed. Export or discard it and start a new revision.")
            if not self.maker.history.before_change():
                self.status.set(self.maker.status.get())
                return
            self.maker.show_blueprint(checked["candidate"])
            self.maker.load_request(checked["candidate"])
            if self.maker.history.after_change("refined", self.context["instructions"]):
                self.maker.status.set("AI revision applied as a draft. Previous revisions are preserved.")
            # If the append fails, the applied draft remains in the maker for saving.
            self.destroy()
        except (ValueError, OSError) as exc:
            self.status.set(str(exc))

    def export(self):
        parent = filedialog.askdirectory(parent=self, title="Choose a parent folder for the candidate review")
        if not parent:
            return
        name = simpledialog.askstring("Candidate export", "New folder name:", parent=self)
        if not name or Path(name).name != name or name in {".", ".."}:
            return
        try:
            destination = export_revision(self.proposal["before"], self.proposal["candidate"], Path(parent) / name)
            self.status.set(f"Unapplied candidate exported to {destination}. Project history is unchanged.")
        except (ValueError, OSError) as exc:
            self.status.set(str(exc))

    def save(self):
        path = filedialog.asksaveasfilename(parent=self, title="Save unapplied review",
                                          defaultextension=".ffreview.json",
                                          filetypes=[("Revision review", "*.ffreview.json")])
        if not path:
            return
        try:
            save_review(create_review(self.proposal["before"], self.proposal["candidate"]), path)
            self.status.set(f"Review saved to {path}. It remains unapplied; project history is unchanged.")
        except (ValueError, OSError) as exc:
            self.status.set(str(exc))

    def discard(self):
        if not messagebox.askyesno("Discard AI candidate?", "Discard this unapplied candidate? "
                                  "The original working draft and saved revisions will be kept.", parent=self):
            return
        self.maker.status.set("AI candidate discarded. Working draft and project history are unchanged.")
        self.destroy()
