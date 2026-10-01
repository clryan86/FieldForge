"""Preview/save an offline field binder; printing is an explicit browser operation."""

from __future__ import annotations

import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.knowledge.binder import (
    NOTICE,
    PRIVACY,
    FieldBinder,
    SavedBinder,
    capture_binder,
    open_saved_binder,
    save_binder,
)


class BinderDialog(tk.Toplevel):
    def __init__(self, parent, database, current_slug=None, *, on_close=None):
        super().__init__(parent)
        self.database, self.current_slug, self.on_close = database, current_slug, on_close
        self.binder: FieldBinder | None = None
        self.saved: SavedBinder | None = None
        self.busy = ""
        self._disposed = False
        self._poll_id = None
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-binder")
        self.title("FieldForge — Printable Field Binder")
        self.geometry("940x800")
        self.minsize(800, 700)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.binder_title = tk.StringVar(value="FieldForge Field Binder")
        self.mode = tk.StringVar(value="current" if current_slug else "bookmarks")
        self.notes = tk.BooleanVar(value=False)
        self.permission = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Preview first. No file is saved or printed automatically.")
        self.summary = tk.StringVar(value="Choose the open article or every bookmarked article (up to 50).")
        self._controls = []
        header = ttk.Frame(self, padding=(16, 14))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Take your references off-screen", font=("TkDefaultFont", 20, "bold")).pack(anchor="w")
        self.notice = ttk.Label(header, text=NOTICE, wraplength=870, justify="left")
        self.notice.pack(fill="x", pady=(6, 0))
        options = ttk.LabelFrame(self, text="Build a captured reference collection", padding=12)
        options.grid(row=1, column=0, sticky="ew", padx=16)
        options.columnconfigure(1, weight=1)
        ttk.Label(options, text="Binder title").grid(row=0, column=0, sticky="w", padx=(0, 8))
        title = ttk.Entry(options, textvariable=self.binder_title)
        title.grid(row=0, column=1, sticky="ew", columnspan=2)
        self._controls.append((title, "normal"))
        current = ttk.Radiobutton(options, text="Currently open article", value="current", variable=self.mode)
        current.grid(row=1, column=0, sticky="w", pady=8)
        self._controls.append((current, "normal" if current_slug else "disabled"))
        bookmarks = ttk.Radiobutton(options, text="All library bookmarks (ignores search filters)",
                                     value="bookmarks", variable=self.mode)
        bookmarks.grid(row=1, column=1, columnspan=2, sticky="w", pady=8)
        self._controls.append((bookmarks, "normal"))
        self.note_box = ttk.Checkbutton(options, text="Include private ARTICLE notes in this copy", variable=self.notes)
        self.note_box.grid(row=2, column=0, columnspan=2, sticky="w")
        self._controls.append((self.note_box, "normal"))
        self.preview_button = ttk.Button(options, text="Build preview", command=self.build)
        self.preview_button.grid(row=2, column=2, sticky="e")
        ttk.Label(self, textvariable=self.summary, wraplength=870, padding=(16, 10),
                  justify="left").grid(row=2, column=0, sticky="ew")
        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=3, column=0, sticky="nsew", padx=16)
        contents = ttk.Frame(self.tabs, padding=8)
        reading = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(contents, text="Contents & source labels")
        self.tabs.add(reading, text="Selected article preview")
        self.tree = ttk.Treeview(contents, columns=("title", "review", "safety"), show="headings", height=8)
        for key, label, width in (("title", "Article", 440), ("review", "Review date supplied", 160),
                                   ("safety", "Safety label supplied", 150)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=100)
        scroll = ttk.Scrollbar(contents, command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.select())
        self.text = ScrolledText(reading, height=10, width=60, wrap="word", state="disabled")
        self.text.pack(fill="both", expand=True)
        self.text_notice = tk.StringVar(value="Select a source in Contents. Output uses full articles, not excerpts.")
        ttk.Label(reading, textvariable=self.text_notice, wraplength=840).pack(fill="x", pady=(6, 0))
        bottom = ttk.Frame(self, padding=(16, 12))
        bottom.grid(row=4, column=0, sticky="ew")
        self.privacy = ttk.Label(bottom, text=PRIVACY, wraplength=870, justify="left")
        self.privacy.pack(fill="x")
        consent = ttk.Checkbutton(bottom, text="I have permission to copy this material and understand the privacy notice.",
                                  variable=self.permission, command=self._buttons)
        consent.pack(anchor="w", pady=8)
        self._controls.append((consent, "normal"))
        actions = ttk.Frame(bottom)
        actions.pack(fill="x")
        self.save_button = ttk.Button(actions, text="Save NEW binder HTML…", command=self.save, state="disabled")
        self.save_button.pack(side="left")
        self.open_button = ttk.Button(actions, text="Open saved binder / print…", command=self.open_saved, state="disabled")
        self.open_button.pack(side="left", padx=8)
        self.close_button = ttk.Button(actions, text="Close", command=self.close)
        self.close_button.pack(side="right")
        self.footer = ttk.Label(bottom, textvariable=self.status, wraplength=870, justify="left")
        self.footer.pack(fill="x", pady=(8, 0))
        for variable in (self.binder_title, self.mode, self.notes):
            variable.trace_add("write", lambda *_: self.invalidate())
        self.bind("<Configure>", self._resize, add=True)
        self._buttons()
        self.grab_set()

    def _resize(self, event):
        if event.widget is self:
            for label in (self.notice, self.privacy, self.footer):
                label.configure(wraplength=max(350, event.width - 48))

    def _text(self, value):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)
        self.text.configure(state="disabled")

    def invalidate(self):
        self.binder = self.saved = None
        self.permission.set(False)
        self.tree.delete(*self.tree.get_children())
        self._text("")
        self.summary.set("Options changed. Build a new preview before saving.")
        self._buttons()

    def _buttons(self):
        for control, idle in self._controls:
            control.configure(state="disabled" if self.busy else idle)
        self.preview_button.configure(state="disabled" if self.busy else "normal")
        self.save_button.configure(state="normal" if self.binder and self.permission.get() and not self.busy else "disabled")
        self.open_button.configure(state="normal" if self.saved and not self.busy else "disabled")
        self.close_button.configure(state="disabled" if self.busy == "save" else "normal")

    def _start(self, mode, function, *args, **kwargs):
        self.busy = mode
        self._buttons()
        self.status.set("Reading local source snapshots…" if mode == "preview" else "Saving a new readable reference file…")
        future = self._worker.submit(function, *args, **kwargs)
        self._poll_id = self.after(50, self._poll, future, mode)

    def build(self):
        if self.busy or self._disposed:
            return
        self.invalidate()
        if self.notes.get() and not messagebox.askyesno(
            "Include private article notes?", "Your article notes will be readable in the binder and any printed copy. "
            "This is separate from the knowledge-pack export checkbox. Include them?", parent=self,
        ):
            self.status.set("Preview not built; private-note export was not confirmed.")
            return
        if self.mode.get() == "current" and not self.current_slug:
            self.status.set("Open an article in the library first, or choose bookmarks.")
            return
        self._start("preview", capture_binder, self.database,
                    slugs=(self.current_slug,) if self.mode.get() == "current" else None,
                    bookmarks=self.mode.get() == "bookmarks", include_notes=self.notes.get(),
                    title=self.binder_title.get())

    def _poll(self, future: Future, mode: str):
        if self._disposed:
            return
        self._poll_id = None
        if not future.done():
            self._poll_id = self.after(50, self._poll, future, mode)
            return
        self.busy = ""
        try:
            result = future.result()
            if mode == "preview":
                self.binder = result
                for i, entry in enumerate(result.entries):
                    self.tree.insert("", "end", iid=str(i), values=(entry.article.title,
                                     entry.article.reviewed_on or "Not supplied", entry.article.safety_level))
                self.tree.selection_set("0")
                self.select()
                self.summary.set(f"{len(result.entries)} FULL articles captured at {result.captured_at}. "
                                 f"Private article notes: {'INCLUDED' if result.include_notes else 'excluded'}. "
                                 "Review labels and copying rights before saving.")
                self.status.set("Preview ready. Later database edits will not change this captured copy. Confirm permission to save.")
            else:
                self.saved = result
                self.status.set(f"Saved {result.bytes_written:,} bytes to {result.path}. Nothing was printed or opened automatically.")
        except Exception as exc:
            if mode == "preview":
                self.binder = None
                self.summary.set("Preview failed; no binder is ready to save.")
            self.saved = None
            self.status.set("Operation failed: " + str(exc))
        self._buttons()

    def select(self):
        selected = self.tree.selection()
        if self.binder is None or not selected:
            return
        entry = self.binder.entries[int(selected[0])]
        article = entry.article
        text = (f"{article.title}\n\nSource: {article.source_title or 'Not supplied'}\n"
                f"Publisher: {article.source_publisher or 'Not supplied'}\n"
                f"Rights: {article.license or 'Not supplied'}\n\n{article.body}")
        if self.binder.include_notes:
            text += "\n\nPRIVATE ARTICLE NOTE (not source guidance)\n" + entry.note
        self._text(text[:20000])
        self.text_notice.set("Preview displays only the first 20,000 characters; saved output includes the FULL article and selected note."
                             if len(text) > 20000 else "Complete captured text shown. Markdown remains plain text in the binder.")

    def save(self):
        if self.busy or self.binder is None or not self.permission.get():
            return
        path = filedialog.asksaveasfilename(parent=self, title="Save a NEW offline field binder",
                                           initialfile="FieldForge-Binder.html", defaultextension=".html",
                                           filetypes=[("Offline HTML binder", "*.html")])
        if path:
            self.saved = None
            self._start("save", save_binder, self.binder, path, acknowledged=True)

    def open_saved(self):
        if self.busy or self.saved is None:
            return
        if not messagebox.askyesno("Open local binder in your browser?",
                                   "The saved file will be opened by your default browser. "
                                   "Use its Print command when ready; FieldForge will not submit a print job. "
                                   "Browser extensions/history have their own privacy behavior. Continue?", parent=self):
            return
        try:
            requested = open_saved_binder(self.saved)
            self.status.set("Browser opening requested. Check the document and print preview before printing."
                            if requested else "Browser did not accept the request. Open the saved .html file manually.")
        except (OSError, ValueError) as exc:
            self.status.set("Could not open saved binder: " + str(exc))

    def close(self):
        if self.busy == "save":
            self.status.set("Wait for saving to finish before closing.")
            return
        self.destroy()

    def _destroyed(self, event):
        if event.widget is not self or self._disposed:
            return
        self._disposed = True
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        self._worker.shutdown(wait=False, cancel_futures=True)
        if self.on_close:
            self.on_close()


def open_binder(knowledge_tab):
    """Save the current article note and retain the existing modal/close guards."""
    if knowledge_tab.busy or not knowledge_tab.save_current():
        return None
    knowledge_tab.busy = True

    def finished():
        knowledge_tab.busy = False

    try:
        return BinderDialog(knowledge_tab, knowledge_tab.library.database_path,
                            knowledge_tab.slug, on_close=finished)
    except Exception:
        knowledge_tab.busy = False
        raise
