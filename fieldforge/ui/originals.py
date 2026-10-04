"""Original PDF storage/export UI; never automatically opens or parses a PDF."""

from __future__ import annotations

import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import filedialog, messagebox, ttk

from fieldforge.knowledge.originals import NOTICE, STATES, OriginalStore, capture_pdf

_PAGE = 25


def _brief(value):
    text = " ".join(value.split())
    return text if len(text) <= 120 else text[:117] + "…"


def _capture(path, store, slug):
    captured = capture_pdf(path)
    return captured, store.anchor(slug) if slug else None


class OriginalsDialog(tk.Toplevel):
    def __init__(self, parent, database, current_slug=None, *, on_close=None):
        super().__init__(parent)
        self.database, self.current_slug, self.on_close = database, current_slug, on_close
        self.store = None
        self.captured = self.anchor = None
        self.records = {}
        self.offset = 0
        self.busy = ""
        self._disposed = False
        self._poll_id = None
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-originals")
        self.title("FieldForge — Original PDF Library")
        self.geometry("1120x830")
        self.minsize(980, 760)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.query = tk.StringVar()
        self.current_only = tk.BooleanVar(value=False)
        self.associate = tk.BooleanVar(value=False)
        self.permission = tk.BooleanVar(value=False)
        self.summary = tk.StringVar(value="Loading stored originals…")
        self.file_info = tk.StringVar(value="No PDF captured. Choose a local file; nothing is stored until you confirm.")
        self.details = tk.StringVar(value="Select a stored PDF. File listings do not verify the stored bytes; use Verify bytes.")
        self.status = tk.StringVar(value="Original files are separate from extracted article text. No files are opened automatically.")
        header = ttk.Frame(self, padding=(16, 14))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Keep the original. Keep the diagrams.", font=("TkDefaultFont", 20, "bold")).pack(anchor="w")
        self.notice = ttk.Label(header, text=NOTICE, wraplength=1040, justify="left")
        self.notice.pack(fill="x", pady=(8, 0))
        self.summary_label = ttk.Label(self, textvariable=self.summary, padding=(16, 0, 16, 10), wraplength=1040)
        self.summary_label.grid(row=1, column=0, sticky="ew")
        saved = ttk.LabelFrame(self, text="Stored original PDFs — all originals, including those without an article", padding=10)
        saved.grid(row=2, column=0, sticky="nsew", padx=16)
        saved.columnconfigure(0, weight=1)
        saved.rowconfigure(1, weight=1)
        tools = ttk.Frame(saved)
        tools.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        tools.columnconfigure(1, weight=1)
        ttk.Label(tools, text="Filename / saved article title").grid(row=0, column=0, padx=(0, 8))
        self.search_entry = ttk.Entry(tools, textvariable=self.query)
        self.search_entry.grid(row=0, column=1, sticky="ew")
        self.search_entry.bind("<Return>", lambda _: self.refresh())
        self.current_filter = ttk.Checkbutton(tools, text="Open article only", variable=self.current_only, command=self.refresh)
        self.current_filter.grid(row=0, column=2, padx=8)
        self.refresh_button = ttk.Button(tools, text="Search / Refresh", command=self.refresh)
        self.refresh_button.grid(row=0, column=3)
        self.tree = ttk.Treeview(saved, columns=("file", "size", "article"), show="headings", selectmode="browse", height=6)
        for key, label, width in (("file", "Original filename", 320), ("size", "Bytes", 100),
                                   ("article", "Article association (not source verification)", 430)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=85)
        self.tree.grid(row=1, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(saved, command=self.tree.yview)
        vertical.grid(row=1, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(saved, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=2, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.select())
        actions = ttk.Frame(saved)
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.verify_button = ttk.Button(actions, text="Verify bytes", command=self.verify)
        self.verify_button.pack(side="left")
        self.export_button = ttk.Button(actions, text="Export original PDF…", command=self.export)
        self.export_button.pack(side="left", padx=8)
        self.remove_button = ttk.Button(actions, text="Remove stored reference…", command=self.remove)
        self.remove_button.pack(side="left")
        self.next = ttk.Button(actions, text="Next", command=lambda: self.page(1))
        self.next.pack(side="right")
        self.previous = ttk.Button(actions, text="Previous", command=lambda: self.page(-1))
        self.previous.pack(side="right", padx=8)
        self.detail_label = ttk.Label(saved, textvariable=self.details, wraplength=1000, justify="left")
        self.detail_label.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        intake = ttk.LabelFrame(self, text="Capture one PDF — metadata preview only, not a visual preview", padding=12)
        intake.grid(row=3, column=0, sticky="ew", padx=16, pady=10)
        top = ttk.Frame(intake)
        top.pack(fill="x")
        self.choose_button = ttk.Button(top, text="Choose local PDF…", command=self.choose)
        self.choose_button.pack(side="left")
        self.association_box = ttk.Checkbutton(top, text="Associate with the article open in the Library (optional)",
                                              variable=self.associate, command=self.invalidate_capture)
        self.association_box.pack(side="left", padx=12)
        self.file_label = ttk.Label(intake, textvariable=self.file_info, wraplength=1000, justify="left")
        self.file_label.pack(fill="x", pady=8)
        self.consent = ttk.Checkbutton(intake, variable=self.permission, command=self._buttons,
                                      text="I trust this PDF, have permission to copy it, and accept unencrypted storage of the unchanged file.")
        self.consent.pack(anchor="w", pady=(0, 8))
        self.store_button = ttk.Button(intake, text="Store captured original", command=self.save)
        self.store_button.pack(anchor="e")
        bottom = ttk.Frame(self, padding=(16, 0, 16, 12))
        bottom.grid(row=4, column=0, sticky="ew")
        self.close_button = ttk.Button(bottom, text="Close", command=self.close)
        self.close_button.pack(side="right")
        self.footer = ttk.Label(bottom, textvariable=self.status, wraplength=900, justify="left")
        self.footer.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.bind("<Configure>", self._resize, add=True)
        self.associate.trace_add("write", lambda *_: self.invalidate_capture())
        self._has_next = False
        self._buttons()
        self._start("setup", OriginalStore, database)
        self.grab_set()

    def _resize(self, event):
        if event.widget is self:
            for label in (self.notice, self.summary_label, self.detail_label, self.file_label):
                label.configure(wraplength=max(450, event.width - 80))
            self.footer.configure(wraplength=max(400, event.width - 140))

    def selected(self):
        choice = self.tree.selection()
        return self.records.get(choice[0]) if choice else None

    def _buttons(self):
        idle = not self.busy and self.store is not None
        for widget in (self.choose_button, self.search_entry, self.consent):
            widget.configure(state="normal" if idle else "disabled")
        self.refresh_button.configure(state="disabled" if self.busy else "normal")
        for widget in (self.association_box, self.current_filter):
            widget.configure(state="normal" if idle and self.current_slug else "disabled")
        for button in (self.verify_button, self.export_button, self.remove_button):
            button.configure(state="normal" if idle and self.selected() else "disabled")
        self.store_button.configure(state="normal" if idle and self.captured and self.permission.get() else "disabled")
        self.previous.configure(state="normal" if idle and self.offset else "disabled")
        self.next.configure(state="normal" if idle and self._has_next else "disabled")
        self.close_button.configure(state="disabled" if self.busy in {"store", "export", "remove"} else "normal")

    def select(self):
        record = self.selected()
        self.details.set((f"{STATES[record.state]} · saved with: {_brief(record.article_title) or '(none)'}\n"
                          f"PDF SHA-256: {record.file_sha256}\n"
                          "Association and hashes do not certify content, safety, or extraction accuracy.") if record else
                         "Select a stored PDF. Listings show metadata only; use Verify bytes before relying on a saved copy.")
        self._buttons()

    def invalidate_capture(self):
        self.captured = self.anchor = None
        self.permission.set(False)
        self.file_info.set("Choose a PDF to capture with these association settings. No original is stored yet.")
        self._buttons()

    def choose(self):
        if self.busy or self.store is None:
            return
        path = filedialog.askopenfilename(parent=self, title="Choose an original PDF to preserve unchanged",
                                          filetypes=[("Original PDF", "*.pdf")])
        if path:
            self.load_path(path)

    def load_path(self, path):
        if self.busy or self.store is None:
            return
        self.invalidate_capture()
        self._start("capture", _capture, path, self.store, self.current_slug if self.associate.get() else None)

    def refresh(self, *, reset=True, message="", select_id=None):
        if self.busy:
            return
        if self.store is None:
            self._start("setup", OriginalStore, self.database)
            return
        if reset:
            self.offset = 0
        self._start("list", self.store.browse, self.query.get(),
                    article_slug=self.current_slug if self.current_only.get() else None,
                    offset=self.offset, limit=_PAGE+1, _message=message, _select_id=select_id)

    def page(self, direction):
        if not self.busy:
            self.offset = max(0, self.offset + direction*_PAGE)
            self.refresh(reset=False)

    def save(self):
        if not self.busy and self.store and self.captured and self.permission.get():
            self._start("store", self.store.store, self.captured, article=self.anchor, acknowledged=True)

    def verify(self):
        if not self.busy and self.selected():
            self._start("verify", self.store.read_verified, self.selected())

    def export(self):
        record = self.selected()
        if self.busy or record is None:
            return
        if not messagebox.askyesno("Export this unchanged PDF?", "Confirm you have permission to copy this file. "
                                   "The unencrypted PDF includes all its original metadata, attachments and any active content. "
                                   "Only open it in a viewer you trust. No file will open automatically. Continue?", parent=self):
            return
        path = filedialog.asksaveasfilename(parent=self, title="Export to a NEW PDF file — no overwrite",
                                           initialfile=f"FieldForge-original-{record.file_sha256[:12]}.pdf",
                                           defaultextension=".pdf", filetypes=[("Original PDF", "*.pdf")])
        if path:
            self._start("export", self.store.export, record, path, acknowledged=True)

    def remove(self):
        record = self.selected()
        if self.busy or record is None:
            return
        if messagebox.askyesno("Remove this stored reference?", "This removes the selected reference, and the stored PDF bytes "
                               "if no other reference uses them. It does NOT delete external files, articles or notes. "
                               "Old backups and SQLite free pages may retain the data; this is not secure erasure. Continue?", parent=self):
            self._start("remove", self.store.remove, record)

    def _start(self, operation, function, *args, _message="", _select_id=None, **kwargs):
        self.busy = operation
        self._buttons()
        self.status.set("Working with the local original-file library…")
        future = self._worker.submit(function, *args, **kwargs)
        self._poll_id = self.after(50, self._poll, future, operation, _message, _select_id)

    def _poll(self, future: Future, operation, message, select_id):
        if self._disposed:
            return
        self._poll_id = None
        if not future.done():
            self._poll_id = self.after(50, self._poll, future, operation, message, select_id)
            return
        self.busy = ""
        try:
            result = future.result()
            if operation == "setup":
                self.store = result
                self.refresh()
                return
            if operation == "list":
                self.records = {str(r.id): r for r in result.records[:_PAGE]}
                self.tree.delete(*self.tree.get_children())
                for key, record in self.records.items():
                    self.tree.insert("", "end", iid=key, values=(record.filename, f"{record.byte_count:,}",
                                     STATES[record.state] + (" — " + record.article_title if record.article_title else "")))
                self._has_next = len(result.records) > _PAGE
                self.summary.set(f"{result.references} stored references · {result.unique_files} unique PDF files · "
                                 f"{result.stored_bytes:,} bytes total. Full SQLite backups include these files; article packs do not.")
                if select_id is not None and str(select_id) in self.records:
                    self.tree.selection_set(str(select_id))
                self.select()
                self.status.set(message or f"Showing {len(self.records)} references · page {self.offset//_PAGE+1}. "
                                "Limits: 16 MiB per PDF, 256 MiB unique stored bytes, 500 references. No PDF viewer is launched.")
            elif operation == "capture":
                self.captured, self.anchor = result
                self.file_info.set(f"{self.captured.filename} · {len(self.captured.data):,} bytes · Captured, not stored\n"
                                   f"SHA-256: {self.captured.sha256}\n"
                                   + (f"Associate with: {_brief(self.anchor.title)} (user choice, not a verified extraction match)" if self.anchor else
                                      "Store without an article association. Scans need no OCR for byte preservation."))
                self.status.set("File bytes captured. This is not a visual preview or a PDF validity/safety check. Confirm the notice to store.")
            elif operation == "store":
                self.invalidate_capture()
                self.query.set("")
                self.current_only.set(False)
                self.refresh(message=("Original stored." if result.added else "Already stored; original filename and association preserved.")
                             + " Extracted text and private notes are unchanged.", select_id=result.record.id)
                return
            elif operation == "remove":
                self.refresh(message=(f"Stored reference removed. {result} other references retain these PDF bytes." if result else
                                      "Stored reference and last active copy removed. External files, articles and old backups are unchanged."))
                return
            elif operation == "verify":
                self.status.set(f"Verified {len(result):,} stored bytes against their captured SHA-256. "
                                "This does not validate the PDF or its advice. Nothing opened or exported.")
            elif operation == "export":
                self.status.set(f"Exported and read-back checked {result.byte_count:,} bytes: {result.path}. "
                                "Open this file manually in your trusted PDF viewer. Nothing opened automatically.")
        except Exception as exc:
            if operation in {"setup", "list"}:
                self.records.clear()
                self.tree.delete(*self.tree.get_children())
                self._has_next = False
                self.summary.set("Original-file list unavailable; no stale counts shown.")
                self.select()
            self.status.set("Operation failed: " + str(exc))
        self._buttons()

    def close(self):
        if self.busy in {"store", "export", "remove"}:
            self.status.set("Wait for the write operation to finish before closing.")
            return
        self.destroy()

    def _destroyed(self, event):
        if event.widget is self and not self._disposed:
            self._disposed = True
            if self._poll_id is not None:
                self.after_cancel(self._poll_id)
                self._poll_id = None
            self._worker.shutdown(wait=False, cancel_futures=True)
            self.captured = self.anchor = None
            if self.on_close:
                self.on_close()


def open_originals(knowledge_tab):
    if knowledge_tab.busy or not knowledge_tab.save_current():
        return None
    knowledge_tab.busy = True

    def finished():
        knowledge_tab.busy = False

    try:
        return OriginalsDialog(knowledge_tab, knowledge_tab.library.database_path, knowledge_tab.slug, on_close=finished)
    except Exception:
        knowledge_tab.busy = False
        raise
