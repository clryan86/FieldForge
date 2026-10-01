"""PDF-specific preview reuses the tested text-import consent and commit workflow."""

from __future__ import annotations

from threading import Event
from tkinter import filedialog, messagebox, ttk

from fieldforge.knowledge.pdf_import import (
    EMPTY_PAGE,
    EXTRA_HELP,
    PDFTextDocument,
    prepare_pdf_article,
    read_pdf_document,
)
from fieldforge.ui.documents import TextImportDialog


class PDFImportDialog(TextImportDialog):
    def __init__(self, parent, library, on_close=None):
        self._cancel_pdf = Event()
        super().__init__(parent, library, on_close)
        self.title("FieldForge — Import PDF text")
        self.heading.configure(text="Import PDF text — keep the original")
        self.geometry("980x850")
        self.minsize(860, 780)
        self.choose_button.configure(text="Choose trusted PDF…")
        self.import_button.configure(text="Add extracted text as article")
        self.consent.configure(text="I accept the text-only limitations and the copying/privacy notice.")
        self.import_notice.configure(
            text="TEXT ONLY: diagrams, images, annotations and original PDF bytes are NOT stored. "
                 "Tables, symbols and reading order may be wrong. Compare the original before relying on this text.\n"
                 "Copy only material you have permission to store. Extracted text becomes searchable and is included "
                 "in ordinary article exports. Do not import private records. Sources/rights are not verified."
        )
        self.status.set("Optional PDF support; 16 MiB / 200 pages. No OCR, cloud service or automatic downloads.")
        self.info.set("Choose a trusted PDF with a readable text layer. No articles are added until you confirm.")
        self.preview_notice.set("A text extraction preview is not a visual preview of the original PDF.")
        controls = ttk.Frame(self.preview.frame.master)
        controls.pack(fill="x", before=self.preview.frame, pady=(0, 8))
        ttk.Label(controls, text="Inspect extracted text:").pack(side="left", padx=(0, 8))
        self.page_picker = ttk.Combobox(controls, state="readonly", values=(), width=26)
        self.page_picker.pack(side="left")
        self.page_picker.bind("<<ComboboxSelected>>", lambda _: self.show_page())
        self._controls.append((self.page_picker, "readonly"))
        ttk.Button(controls, text="PDF setup help", command=self.setup_help).pack(side="right")

    def setup_help(self):
        messagebox.showinfo("Optional PDF support", EXTRA_HELP + "\n\nUse python instead of py on systems "
                            "without the Windows launcher. Install before going offline. No installation is "
                            "performed by this button. Core FieldForge functions work without this extra.", parent=self)

    def choose(self):
        if self._busy:
            return
        path = filedialog.askopenfilename(parent=self, title="Choose a trusted local PDF",
                                          filetypes=[("PDF documents", "*.pdf")])
        if path:
            self.load_path(path)

    def load_path(self, path):
        if self._busy or self._disposed:
            return
        # Clear the old preview even if the new attempt is declined or fails.
        self.document = None
        self.acknowledged.set(False)
        self.page_picker.configure(values=())
        self.page_picker.set("")
        self._text("")
        for name, variable in self.fields.items():
            variable.set("caution" if name == "safety_level" else "PDF references" if name == "category" else "")
        self._update_buttons()
        if not messagebox.askyesno(
            "Only process PDFs you trust",
            "PDF extraction runs locally in a separate process, but is not a security sandbox. "
            "Only continue with a file from a source you trust. Images, charts, scans and layout are "
            "not preserved. Keep and compare the original. Continue?", parent=self,
        ):
            self.info.set("No PDF selected for import.")
            self.status.set("Extraction not started.")
            return
        self._cancel_pdf = Event()
        self.info.set("Extracting the captured PDF text in a separate local process…")
        self._start("reading", read_pdf_document, path, cancel=self._cancel_pdf)

    def _loaded(self, document: PDFTextDocument):
        self.document = document
        self.fields["title"].set(document.suggested_title)
        self.fields["slug"].set(document.suggested_id)
        self.page_picker.configure(values=["Overview / beginning", *(
            f"PDF page {i}" for i in range(1, len(document.pages) + 1)
        )])
        self.page_picker.current(0)
        missing = ", ".join(map(str, document.empty_pages)) or "none detected"
        self.info.set(f"{document.name} · {document.file_bytes:,} bytes · {len(document.pages)} physical PDF pages\n"
                      f"Pages with no extracted text: {missing}\nOriginal PDF SHA-256: {document.file_sha256}")
        self.show_page()
        self.status.set("PDF text preview ready, not imported. Compare the original, check source/rights details, "
                        "then confirm. Original file and visual content are NOT saved in the library.")
        self.tabs.select(0)

    def show_page(self):
        if self.document is None:
            return
        index = self.page_picker.current()
        if index <= 0:
            text = self.document.body
        else:
            page = self.document.pages[index - 1]
            text = (f"EXTRACTED TEXT — PHYSICAL PDF PAGE {index}\n"
                    "Not a visual copy. All pages, not just this page, will be included in the text article.\n\n"
                    + (page if page.strip() else EMPTY_PAGE))
        self._text(text[:20000])
        self.preview_notice.set(
            ("Showing the first 20,000 characters of this view. The stored article includes all extracted pages. "
             if len(text) > 20000 else "Entire extracted text for this view shown. ")
            + "No diagrams, OCR or visual verification. PDF page positions are not printed page labels."
        )

    def prepare_document(self, values):
        return prepare_pdf_article(self.document, **values)

    def _poll(self, future, operation):
        super()._poll(future, operation)
        if not self._disposed and not self._busy and operation == "reading" and self.document is None:
            self.info.set("No PDF text preview available; nothing imported.")

    def _destroyed(self, event):
        if event.widget is self:
            self._cancel_pdf.set()
        super()._destroyed(event)
