"""Preview-first text intake. File/database work is separate from the Tk thread."""

from __future__ import annotations

import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from fieldforge.knowledge import KnowledgeLibrary
from fieldforge.knowledge.documents import (
    IMPORT_NOTICE,
    DocumentImportResult,
    TextDocument,
    commit_document,
    prepare_article,
    read_text_document,
)

_PREVIEW_CHARACTERS = 20_000


class TextImportDialog(tk.Toplevel):
    """A modal single-file preview; changes to the file after loading are ignored."""

    def __init__(self, parent: tk.Misc, library: KnowledgeLibrary,
                 on_close: Callable[[DocumentImportResult | None], None] | None = None) -> None:
        super().__init__(parent)
        self.library = library
        self.document: TextDocument | None = None
        self.result: DocumentImportResult | None = None
        self._on_close = on_close
        self._busy = ""
        self._disposed = False
        self._poll_id: str | None = None
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-text")
        self.title("FieldForge — Import a text document")
        self.geometry("940x760")
        self.minsize(780, 650)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.acknowledged = tk.BooleanVar(value=False)
        self.info = tk.StringVar(value="Choose one local file. Nothing is imported until you confirm.")
        self.status = tk.StringVar(value="Supported: UTF-8 .txt, .md, .markdown · up to 2 MiB / 2,000,000 characters")
        defaults = {
            "title": "", "category": "local documents", "slug": "", "tags": "",
            "source_title": "", "source_publisher": "", "source_url": "", "license": "",
            "reviewed_on": "", "safety_level": "caution",
        }
        self.fields = {name: tk.StringVar(value=value) for name, value in defaults.items()}
        self._controls: list[tuple[tk.Widget, str]] = []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        header = ttk.Frame(self, padding=(16, 12))
        header.grid(row=0, column=0, sticky="ew")
        self.heading = ttk.Label(header, text="Bring your documents into FieldForge", font=("TkDefaultFont", 18, "bold"))
        self.heading.pack(anchor="w")
        ttk.Label(header, text="Select → preview → label the source → add to your offline library").pack(anchor="w", pady=(4, 8))
        self.choose_button = ttk.Button(header, text="Choose text file…", command=self.choose)
        self.choose_button.pack(anchor="w")
        self._controls.append((self.choose_button, "normal"))
        info = ttk.Label(self, textvariable=self.info, wraplength=880, justify="left", padding=(16, 0, 16, 8))
        info.grid(row=1, column=0, sticky="ew")
        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=2, column=0, sticky="nsew", padx=16)
        preview_page = ttk.Frame(self.tabs, padding=10)
        metadata_page = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(preview_page, text="1 · Text preview")
        self.tabs.add(metadata_page, text="2 · Article details & source")
        self.preview = ScrolledText(preview_page, wrap="word", width=50, height=10,
                                    state="disabled", font=("TkDefaultFont", 11))
        self.preview.pack(fill="both", expand=True)
        self.preview_notice = tk.StringVar(value="Markdown remains plain text. No scripts, images, or links are loaded.")
        ttk.Label(preview_page, textvariable=self.preview_notice, wraplength=830).pack(fill="x", pady=(8, 0))
        metadata_page.columnconfigure(1, weight=1)
        labels = {
            "title": "Article title *", "category": "Category *", "slug": "Article ID *",
            "tags": "Tags (comma separated)", "source_title": "Source title",
            "source_publisher": "Publisher / author", "source_url": "Source URL (optional)",
            "license": "Rights / license (do not guess)",
            "reviewed_on": "Review date, if known (YYYY-MM-DD)", "safety_level": "Safety label (not verification)",
        }
        for index, (name, label) in enumerate(labels.items()):
            ttk.Label(metadata_page, text=label).grid(row=index, column=0, sticky="w", padx=(0, 12), pady=3)
            if name == "safety_level":
                control = ttk.Combobox(metadata_page, textvariable=self.fields[name], state="readonly",
                                       values=("reference", "caution", "high_stakes"))
                idle = "readonly"
            else:
                control = ttk.Entry(metadata_page, textvariable=self.fields[name])
                idle = "normal"
            control.grid(row=index, column=1, sticky="ew", pady=3)
            self._controls.append((control, idle))
        ttk.Label(metadata_page, text="Blank source/review/rights fields stay unknown. The import date is not a review date.\n"
                  "An existing article ID is never overwritten. A different ID deliberately creates another copy.",
                  wraplength=820, justify="left").grid(row=len(labels), column=0, columnspan=2, sticky="ew", pady=(8, 0))
        bottom = ttk.Frame(self, padding=(16, 10, 16, 12))
        bottom.grid(row=3, column=0, sticky="ew")
        notice = ttk.Label(bottom, text=IMPORT_NOTICE, wraplength=890, justify="left")
        self.import_notice = notice
        notice.pack(fill="x")
        self.consent = ttk.Checkbutton(bottom,
                                      text="I have permission to store this text and understand the export/privacy notice.",
                                      variable=self.acknowledged, command=self._update_buttons)
        self.consent.pack(anchor="w", pady=(8, 5))
        self._controls.append((self.consent, "normal"))
        actions = ttk.Frame(bottom)
        actions.pack(fill="x")
        self.import_button = ttk.Button(actions, text="Add previewed document", command=self.import_document, state="disabled")
        self.import_button.pack(side="right")
        self.close_button = ttk.Button(actions, text="Cancel", command=self.close)
        self.close_button.pack(side="right", padx=(0, 8))
        footer = ttk.Label(bottom, textvariable=self.status, wraplength=870, justify="left")
        footer.pack(fill="x", pady=(8, 0))
        self.bind("<Configure>", lambda event: self._resize(info, notice, footer), add=True)
        self.grab_set()

    def _resize(self, *labels: ttk.Label) -> None:
        for label in labels:
            label.configure(wraplength=max(400, self.winfo_width() - 50))

    def _update_buttons(self) -> None:
        for widget, idle in self._controls:
            widget.configure(state="disabled" if self._busy else idle)
        ready = self.document is not None and self.acknowledged.get() and not self._busy
        self.import_button.configure(state="normal" if ready else "disabled")
        self.close_button.configure(state="disabled" if self._busy == "saving" else "normal")

    def choose(self) -> None:
        if self._busy:
            return
        path = filedialog.askopenfilename(parent=self, title="Choose a local UTF-8 text file",
                                         filetypes=[("Text / Markdown", "*.txt *.md *.markdown")])
        if path:
            self.load_path(path)

    def load_path(self, path: str) -> None:
        if self._busy or self._disposed:
            return
        # A failed second load must not leave the first document ready to import.
        self.document = None
        self.acknowledged.set(False)
        for name, variable in self.fields.items():
            variable.set("caution" if name == "safety_level" else "local documents" if name == "category" else "")
        self._text("")
        self.info.set("Reading a bounded local text snapshot…")
        self._start("reading", read_text_document, path)

    def _text(self, value: str) -> None:
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", value)
        self.preview.configure(state="disabled")

    def _start(self, operation: str, function, *args, **kwargs) -> None:
        self._busy = operation
        self._update_buttons()
        self.status.set("Reading file…" if operation == "reading" else "Adding article in one local transaction…")
        future = self._worker.submit(function, *args, **kwargs)
        self._poll_id = self.after(50, self._poll, future, operation)

    def _poll(self, future: Future, operation: str) -> None:
        if self._disposed:
            return
        self._poll_id = None
        if not future.done():
            self._poll_id = self.after(50, self._poll, future, operation)
            return
        self._busy = ""
        try:
            result = future.result()
            if operation == "reading":
                self._loaded(result)
            else:
                self.result = result
                self.destroy()
                return
        except Exception as exc:
            self.status.set("Not imported: " + str(exc))
            if operation == "reading":
                self.info.set("No document loaded. Choose a supported text file.")
        self._update_buttons()

    def _loaded(self, document: TextDocument) -> None:
        self.document = document
        self.fields["title"].set(document.suggested_title)
        self.fields["slug"].set(document.suggested_id)
        self._text(document.body[:_PREVIEW_CHARACTERS])
        self.info.set(f"{document.name} · {len(document.raw):,} bytes · {len(document.body):,} characters\n"
                      f"Captured file SHA-256: {document.file_sha256}")
        self.preview_notice.set(
            f"Showing the first {_PREVIEW_CHARACTERS:,} of {len(document.body):,} characters. "
            "The ENTIRE captured text will be imported, not just this preview."
            if len(document.body) > _PREVIEW_CHARACTERS else
            "Complete captured text shown. UTF-8 BOM removed if present; other text and line endings preserved."
        )
        self.status.set("Preview loaded, nothing saved. Check Article details & source, then confirm the notice.")
        self.tabs.select(0)

    def import_document(self) -> None:
        if self._busy or self.document is None:
            return
        if not self.acknowledged.get():
            self.status.set("Confirm the storage permission and export/privacy notice first.")
            return
        try:
            values = {name: variable.get() for name, variable in self.fields.items()}
            values["tags"] = tuple(tag.strip() for tag in values["tags"].split(",") if tag.strip())
            article = self.prepare_document(values)
        except ValueError as exc:
            self.status.set("Check article details: " + str(exc))
            self.tabs.select(1)
            return
        self._start("saving", commit_document, self.library, article, acknowledged=True)

    def prepare_document(self, values):
        return prepare_article(self.document, **values)

    def close(self) -> None:
        if self._busy == "saving":
            self.status.set("Wait for the database operation to finish before closing.",)
            return
        self.destroy()

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is not self or self._disposed:
            return
        self._disposed = True
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        self._worker.shutdown(wait=False, cancel_futures=True)
        # A read can finish after Cancel; it has no database side effects. Normal
        # close is blocked during a commit so a successful import is not called cancelled.
        if self._on_close is not None:
            self._on_close(self.result)


def open_document_import(knowledge_tab, *, dialog_type=TextImportDialog) -> TextImportDialog | None:
    """Respect existing note-save and application-close guards during the dialog."""
    if knowledge_tab.busy or not knowledge_tab.save_current():
        return None
    knowledge_tab.busy = True

    def finished(result: DocumentImportResult | None) -> None:
        knowledge_tab.busy = False
        try:
            if not knowledge_tab.winfo_exists() or result is None:
                return
            knowledge_tab.query.set("")
            knowledge_tab.category.set("All categories")
            knowledge_tab.favorites.set(False)
            knowledge_tab.refresh()
            if knowledge_tab.results.exists(result.slug):
                knowledge_tab.results.selection_set(result.slug)
                knowledge_tab.results.see(result.slug)
            knowledge_tab.status.set(
                f"{'Added' if result.status == 'added' else 'Already installed, unchanged'}: {result.title}. "
                "Search by title if not shown on this page."
            )
        except tk.TclError:
            pass  # The application itself may be being destroyed.

    try:
        return dialog_type(knowledge_tab, knowledge_tab.library, finished)
    except Exception:
        knowledge_tab.busy = False
        raise


def add_document_import(knowledge_tab) -> ttk.Button:
    row = ttk.Frame(knowledge_tab)
    row.pack(fill="x", pady=(0, 8))
    button = ttk.Button(row, text="Import Text Document…", command=lambda: open_document_import(knowledge_tab))
    button.pack(side="left", padx=(0, 8))
    from fieldforge.ui.pdf_import import PDFImportDialog

    knowledge_tab.pdf_import_button = ttk.Button(
        row, text="Import PDF Text…",
        command=lambda: open_document_import(knowledge_tab, dialog_type=PDFImportDialog),
    )
    knowledge_tab.pdf_import_button.pack(side="left", padx=(0, 8))
    ttk.Label(row, text="Preview local text first. PDF extraction does not preserve diagrams.",
              wraplength=430).pack(side="left", fill="x", expand=True)
    return button
