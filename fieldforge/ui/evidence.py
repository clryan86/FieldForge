"""Desktop passage search and optional local drafts; workers never touch Tk."""

from __future__ import annotations

import threading
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from fieldforge.knowledge import Evidence, KnowledgeLibrary, retrieve_evidence
from fieldforge.knowledge.assistant import GenerationCancelled, OllamaClient, draft_answer
from fieldforge.ui.lifecycle import release_tk_references


class EvidenceWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, library: KnowledgeLibrary,
                 open_article: Callable[[Evidence], bool]) -> None:
        super().__init__(parent)
        self.title("FieldForge — Find local passages")
        self.geometry("950x760")
        self.minsize(660, 600)
        self.library = library
        self.open_article = open_article
        self.query = tk.StringVar()
        self.status = tk.StringVar(value="Ask a question about articles installed in your library.")
        self.evidence: list[Evidence] = []
        self.busy = False
        self._closed = False
        self._poll_id: str | None = None
        self._cancel = threading.Event()
        self._operation = "search"
        self._has_draft = False
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-evidence")
        self.bind("<Destroy>", self._destroyed, add=True)
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Find passages in your library",
                  font=("TkDefaultFont", 18, "bold")).pack(anchor="w")
        description = ttk.Label(frame, text="Exact excerpts from installed articles. Source details are supplied by their authors.",
                                wraplength=760)
        description.pack(anchor="w", pady=(4, 12))
        search_row = ttk.Frame(frame)
        search_row.pack(fill="x")
        self.entry = ttk.Entry(search_row, textvariable=self.query)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry.bind("<Return>", lambda _event: self.search())
        self.search_button = ttk.Button(search_row, text="Find passages", command=self.search)
        self.search_button.pack(side="right")
        local = ttk.LabelFrame(frame, text="Optional local AI", padding=8)
        local.pack(fill="x", pady=(12, 0))
        ttk.Label(local, text="Ollama port").pack(side="left")
        self.port = tk.StringVar(value="11434")
        self.port_entry = ttk.Entry(local, textvariable=self.port, width=6)
        self.port_entry.pack(side="left", padx=(4, 8))
        self.models_button = ttk.Button(local, text="Load models", command=self.load_models)
        self.models_button.pack(side="left")
        self.model = tk.StringVar()
        self.model_picker = ttk.Combobox(local, textvariable=self.model, state="readonly", width=22)
        self.model_picker.pack(side="left", fill="x", expand=True, padx=8)
        self.draft_button = ttk.Button(local, text="Draft answer", command=self.draft)
        self.draft_button.pack(side="left")
        self.cancel_button = ttk.Button(local, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        status_label = ttk.Label(frame, textvariable=self.status, wraplength=760)
        status_label.pack(fill="x", pady=8)
        frame.bind("<Configure>", lambda event: (
            description.configure(wraplength=max(200, event.width - 32)),
            status_label.configure(wraplength=max(200, event.width - 32)),
        ))
        self.pages = ttk.Notebook(frame)
        self.pages.pack(fill="both", expand=True)
        self.sources_page = ttk.Frame(self.pages)
        self.answer_page = ttk.Frame(self.pages)
        self.pages.add(self.sources_page, text="Source passages")
        self.pages.add(self.answer_page, text="AI draft")
        self.answer = ScrolledText(self.answer_page, wrap="word", state="disabled", font="TkDefaultFont")
        self.answer.pack(fill="both", expand=True)
        self._answer_text("Choose Load models to connect to Ollama on this computer.\n\n"
                          "Ollama must have cloud features disabled and a local text model installed. "
                          "FieldForge does not download models.\n\n"
                          "Drafts use your question and matching article excerpts. Private notes, "
                          "household records and inventory are excluded. Drafts are not saved.")
        result_frame = ttk.Frame(self.sources_page)
        result_frame.pack(fill="x")
        self.results = ttk.Treeview(result_frame, columns=("title", "source"), show="headings", height=5)
        self.results.heading("title", text="Article")
        self.results.heading("source", text="Source")
        self.results.column("title", width=300, minwidth=150)
        self.results.column("source", width=350, minwidth=150)
        scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=self.results.yview)
        self.results.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.results.pack(side="left", fill="x", expand=True)
        self.results.bind("<<TreeviewSelect>>", self._select)
        self.passage = ScrolledText(self.sources_page, wrap="word", state="disabled", height=12, font="TkDefaultFont")
        self.passage.pack(fill="both", expand=True, pady=10)
        self.open_button = ttk.Button(self.sources_page, text="Open full article", command=self.open_selected,
                                      state="disabled")
        # Reserve the action before the expanding text pane at small sizes.
        self.open_button.pack(side="bottom", anchor="e", before=result_frame)
        self.entry.focus_set()

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self:
            self._closed = True
            self._cancel.set()
            if self._poll_id is not None:
                self.after_cancel(self._poll_id)
                self._poll_id = None
            self._worker.shutdown(wait=False, cancel_futures=True)
            self.open_article = lambda _evidence: False
            release_tk_references(self)

    def _text(self, value: str) -> None:
        self.passage.configure(state="normal")
        self.passage.delete("1.0", "end")
        self.passage.insert("1.0", value)
        self.passage.configure(state="disabled")

    def _answer_text(self, value: str) -> None:
        self.answer.configure(state="normal")
        self.answer.delete("1.0", "end")
        self.answer.insert("1.0", value)
        self.answer.configure(state="disabled")

    def _controls(self, busy: bool) -> None:
        self.busy = busy
        for control in (self.search_button, self.entry, self.models_button,
                        self.port_entry, self.draft_button):
            control.configure(state="disabled" if busy else "normal")
        self.model_picker.configure(state="disabled" if busy else "readonly")
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def _clear_results(self) -> None:
        self._has_draft = False
        self.evidence = []
        self.results.delete(*self.results.get_children())
        self._text("")
        self._answer_text("")
        self.open_button.configure(state="disabled")

    def _begin(self, operation: str, function, *args, **kwargs) -> None:
        self._operation = operation
        self._cancel = threading.Event()
        self._controls(True)
        if operation != "search":
            kwargs["cancel"] = self._cancel
        future = self._worker.submit(function, *args, **kwargs)
        self._poll_id = self.after(50, self._poll, future)

    def _client(self) -> OllamaClient:
        try:
            port = int(self.port.get())
        except ValueError as exc:
            raise ValueError("Enter an Ollama port from 1 to 65535.") from exc
        return OllamaClient(port=port)

    def load_models(self) -> None:
        if self._closed or self.busy:
            return
        try:
            client = self._client()
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self.model_picker.configure(values=())
        self.model.set("")
        self.status.set("Checking local Ollama and installed models…")
        self._begin("models", client.list_models)

    def draft(self) -> None:
        if self._closed or self.busy:
            return
        question = self.query.get().strip()
        if not question:
            self.status.set("Enter a question first.")
            return
        if not self.model.get():
            self.status.set("Choose Load models, then select an installed local model.")
            self.pages.select(self.answer_page)
            return
        try:
            client = self._client()
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self._clear_results()
        self.pages.select(self.answer_page)
        self.status.set("Retrieving sources and drafting locally… You can cancel at any time.")
        self._begin("draft", draft_answer, self.library, question, self.model.get(), client)

    def cancel(self) -> None:
        if self._closed or not self.busy:
            return
        self._cancel.set()
        self.status.set("Cancelling…")
        self.cancel_button.configure(state="disabled")

    def search(self) -> None:
        if self._closed or self.busy:
            return
        question = self.query.get().strip()
        if not question:
            self.status.set("Enter a question or a few keywords.")
            return
        self._clear_results()
        self.pages.select(self.sources_page)
        self.status.set("Searching the local library…")
        self._begin("search", retrieve_evidence, self.library, question, limit=8)

    def _poll(self, future: Future) -> None:
        self._poll_id = None
        if self._closed:
            return
        if not future.done():
            self._poll_id = self.after(50, self._poll, future)
            return
        self._controls(False)
        try:
            result = future.result()
            if self._cancel.is_set():
                raise GenerationCancelled("Cancelled. No draft was saved.")
            if self._operation == "models":
                self.model_picker.configure(values=result)
                self.model.set(result[0] if result else "")
                self.status.set(f"Found {len(result)} local model(s). Choose one to draft from your library."
                                if result else "No local text models found. Install one in Ollama, then load models again.")
                return
            self.evidence = list(result.evidence) if self._operation == "draft" else result
            for index, item in enumerate(self.evidence):
                title = f"[S{index + 1}] {item.title}" if self._operation == "draft" else item.title
                self.results.insert("", "end", iid=str(index),
                                    values=(title, item.source_title or "Source not provided"))
            if self.evidence:
                self.status.set(f"Found {len(self.evidence)} matching article(s). Select a passage to inspect its source.")
                self.results.selection_set("0")
            else:
                self.status.set("No matching passages. Try different keywords or import a relevant knowledge pack.")
            if self._operation == "draft":
                self._answer_text(f"Question: {result.question}\nModel: {result.model or 'Not used'}\n\n"
                                  + "\n".join(result.warnings) + "\n\n" + result.answer)
                if result.status == "draft":
                    self._has_draft = True
                    self.status.set("AI draft ready. Check its claims against the Source passages tab.")
        except GenerationCancelled as exc:
            self.status.set(str(exc))
        except Exception as exc:
            label = "Search" if self._operation == "search" else "Local AI"
            self.status.set(f"{label} failed: {exc}")
        self.entry.focus_set()

    def _selected(self) -> Evidence | None:
        if self._closed:
            return None
        selected = self.results.selection()
        return self.evidence[int(selected[0])] if selected else None

    def _select(self, _event: tk.Event | None = None) -> None:
        item = self._selected()
        if item is None:
            return
        self._text(
            f"{item.title}\n\n{item.passage}\n\n"
            f"Source: {item.source_title or 'Not provided'}\n"
            f"Publisher: {item.source_publisher or 'Not provided'}\n"
            f"Review date: {item.reviewed_on or 'Not provided'}\n"
            f"Safety label: {item.safety_level.upper()}\n"
            f"Rights: {item.license or 'Unspecified'}\n"
            f"{item.source_url or 'No source URL provided'}\n\n"
            f"Article ID: {item.slug}\nCharacters: {item.start_offset} to {item.end_offset}\n"
            f"Body SHA-256: {item.checksum}"
        )
        self.open_button.configure(state="normal")

    def open_selected(self) -> None:
        item = self._selected()
        if item is not None and self.open_article(item):
            if self._has_draft:
                # Keep the answer available while the reader inspects a source.
                self.withdraw()
            else:
                self.destroy()
