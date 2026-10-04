"""Inventory editor and stock adjustment controls for the existing local database."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.core.models import InventoryCategory
from fieldforge.core.supplies import (
    NOTICE,
    NUMERIC_FIELDS,
    SuppliesService,
    SupplyRecord,
    describe_item,
    flags,
    item_from_fields,
)

_ERRORS = (OSError, ValueError, sqlite3.Error)
_ALL = "All categories"
_PAGE_SIZE = 50


class SupplyDialog(tk.Toplevel):
    """All fields are explicit. Failed saves leave edits visible for reconciliation."""

    def __init__(self, parent, service: SuppliesService, record: SupplyRecord | None, finished):
        super().__init__(parent)
        self.service, self.record, self.finished = service, record, finished
        self.result: SupplyRecord | None = None
        self.title("FieldForge — Edit supply" if record else "FieldForge — Add supply")
        self.geometry("800x690")
        self.minsize(700, 610)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Destroy>", self._destroyed, add=True)
        self._disposed = False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        values = {"name": "", "category": "other", "quantity": "1", "unit": "each",
                  "minimum_quantity": "0", "liters_per_unit": "0", "calories_per_unit": "0",
                  "watt_hours_per_unit": "0", "expires_on": "", "location": "", "notes": ""}
        if record:
            values.update({key: "" if value is None else str(value) for key, value in record.item.as_dict().items()
                           if key != "id"})
        self.fields = {key: tk.StringVar(value=value) for key, value in values.items() if key != "notes"}
        self.status = tk.StringVar(value="Only Save supply writes changes. No container sizes are guessed.")
        self.totals = tk.StringVar()
        ttk.Label(self, text="Supply details", font=("TkDefaultFont", 19, "bold"), padding=16).grid(row=0, column=0, sticky="w")
        notice = ttk.Label(self, text=NOTICE, wraplength=730, padding=(16, 0, 16, 12), justify="left")
        notice.grid(row=1, column=0, sticky="ew")
        notebook = ttk.Notebook(self)
        notebook.grid(row=2, column=0, sticky="nsew", padx=16)
        amounts_page = ttk.Frame(notebook)
        canvas = tk.Canvas(amounts_page, highlightthickness=0)
        scrollbar = ttk.Scrollbar(amounts_page, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        main = ttk.Frame(canvas, padding=12)
        form_window = canvas.create_window(0, 0, anchor="nw", window=main)
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(form_window, width=event.width))
        main.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        notes = ttk.Frame(notebook, padding=12)
        notebook.add(amounts_page, text="Amounts & location")
        notebook.add(notes, text="Notes")
        main.columnconfigure(1, weight=1)
        labels = (
            ("name", "Name *"), ("category", "Category *"), ("quantity", "Quantity on hand *"),
            ("unit", "ONE unit is a… *"), ("liters_per_unit", "Liters in ONE unit (water)"),
            ("calories_per_unit", "kcal in ONE unit (food)"), ("watt_hours_per_unit", "Wh in ONE unit (power)"),
            ("minimum_quantity", "Low-stock threshold (same units)"), ("expires_on", "Recorded expiry date (YYYY-MM-DD)"),
            ("location", "Storage location"),
        )
        for row, (key, label) in enumerate(labels):
            ttk.Label(main, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=2)
            if key == "category":
                control = ttk.Combobox(main, textvariable=self.fields[key], state="readonly",
                                       values=[category.value for category in InventoryCategory])
            else:
                control = ttk.Entry(main, textvariable=self.fields[key])
            control.grid(row=row, column=1, sticky="ew", pady=2)
        ttk.Label(main, text="Example: 6 bottles × 2 liters per bottle = 12 liters. Zero means no amount supplied.\n"
                  "For a food bag, enter kcal for the WHOLE bag, not just one serving. No automatic unit conversions.",
                  wraplength=650, justify="left").grid(row=len(labels), column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.note = ScrolledText(notes, wrap="word", height=10, width=50)
        self.note.pack(fill="both", expand=True)
        self.note.insert("1.0", values["notes"])
        ttk.Label(notes, text="Local inventory note, up to 10,000 characters. Change records and full backups retain it.\n"
                  "Removing a supply is not a secure deletion from change history.", wraplength=650).pack(fill="x", pady=(8, 0))
        self.preview_label = ttk.Label(self, textvariable=self.totals, wraplength=730, padding=(16, 8), justify="left")
        self.preview_label.grid(row=3, column=0, sticky="ew")
        controls = ttk.Frame(self, padding=(16, 0, 16, 8))
        controls.grid(row=4, column=0, sticky="ew")
        self.save_button = ttk.Button(controls, text="Save supply", command=self.save)
        self.save_button.pack(side="right")
        ttk.Button(controls, text="Cancel", command=self.close).pack(side="right", padx=8)
        self.footer = ttk.Label(self, textvariable=self.status, wraplength=730, padding=(16, 0, 16, 12), justify="left")
        self.footer.grid(row=5, column=0, sticky="ew")
        self.initial = self._values()
        for key in ("quantity", "unit", "name", "category", *NUMERIC_FIELDS[1:]):
            self.fields[key].trace_add("write", lambda *_args: self.preview())
        self.preview()
        self.grab_set()

    def _values(self):
        return {**{key: value.get() for key, value in self.fields.items()}, "notes": self.note.get("1.0", "end-1c")}

    def preview(self):
        try:
            self.totals.set(describe_item(item_from_fields(self._values())))
        except ValueError:
            self.totals.set("Enter a name, unit, and valid amounts to see totals. Nothing has been saved.")

    def save(self):
        if self._disposed:
            return
        try:
            item = item_from_fields(self._values(), item_id=self.record.item.id if self.record else None)
            self.result = self.service.save(item, expected=self.record.token if self.record else None)
        except _ERRORS as exc:
            self.status.set("Not saved: " + str(exc))
            return
        self.destroy()

    def close(self):
        if self._values() != self.initial and not messagebox.askyesno(
            "Discard supply edits?", "Changes have not been saved. Discard them?", parent=self
        ):
            return
        self.destroy()

    def _destroyed(self, event):
        if event.widget is self and not self._disposed:
            self._disposed = True
            self.finished(self.result)


class StockDialog(tk.Toplevel):
    def __init__(self, parent, service: SuppliesService, record: SupplyRecord, finished):
        super().__init__(parent)
        self.service, self.record, self.finished = service, record, finished
        self.result = None
        self._disposed = False
        self.title("FieldForge — Record stock change")
        self.geometry("670x410")
        self.minsize(620, 390)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.change = tk.StringVar(value="use")
        self.quantity = tk.StringVar(value="")
        self.reason = tk.StringVar()
        self.status = tk.StringVar(value="Stock cannot go below zero. A private before/after record is saved.")
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text=record.item.name, font=("TkDefaultFont", 17, "bold"), wraplength=570).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text=f"Currently recorded: {record.item.quantity:g} {record.item.unit}").grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 14))
        ttk.Radiobutton(frame, text="Use / remove stock", variable=self.change, value="use").grid(row=2, column=0, sticky="w")
        ttk.Radiobutton(frame, text="Receive stock", variable=self.change, value="receive").grid(row=2, column=1, sticky="w")
        for row, (label, variable) in enumerate(((f"Amount ({record.item.unit})", self.quantity), ("Reason *", self.reason)), 3):
            ttk.Label(frame, text=label, wraplength=250).grid(row=row, column=0, sticky="w", pady=8)
            ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=8)
        self.save_button = ttk.Button(frame, text="Record stock change", command=self.save)
        self.save_button.grid(row=5, column=1, sticky="e", pady=10)
        ttk.Button(frame, text="Cancel", command=self.close).grid(row=5, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.status, wraplength=590, justify="left").grid(row=6, column=0, columnspan=2, sticky="ew")
        self.grab_set()

    def save(self):
        if self._disposed:
            return
        try:
            self.result = self.service.adjust(self.record, self.change.get(), self.quantity.get(), self.reason.get())
        except _ERRORS as exc:
            self.status.set("Not saved: " + str(exc))
            return
        self.destroy()

    def close(self):
        if (self.quantity.get() or self.reason.get()) and not messagebox.askyesno(
            "Discard stock change?", "This change has not been recorded. Discard it?", parent=self
        ):
            return
        self.destroy()

    def _destroyed(self, event):
        if event.widget is self and not self._disposed:
            self._disposed = True
            self.finished(self.result)


class SuppliesTab(ttk.Frame):
    def __init__(self, parent, service: SuppliesService, *, on_change=None):
        super().__init__(parent)
        self.service, self.on_change = service, on_change
        self.dialog = None
        self.records = {}
        self.offset = 0
        self.query = tk.StringVar()
        self.category = tk.StringVar(value=_ALL)
        self.status = tk.StringVar(value="Inventory is stored locally. Select a supply to inspect or edit.")
        self.details = tk.StringVar(value=NOTICE)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text="Supplies & stock", font=("TkDefaultFont", 20, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 10))
        tools = ttk.Frame(self)
        tools.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        tools.columnconfigure(0, weight=1)
        search = ttk.Entry(tools, textvariable=self.query)
        search.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        search.bind("<Return>", lambda _event: self.refresh())
        ttk.Combobox(tools, textvariable=self.category, state="readonly", width=18,
                     values=[_ALL, *(category.value for category in InventoryCategory)]).grid(row=0, column=1, padx=6)
        ttk.Button(tools, text="Search / Refresh", command=self.refresh).grid(row=0, column=2)
        self.add_button = ttk.Button(tools, text="Add supply", command=self.add)
        self.add_button.grid(row=0, column=3, padx=(8, 0))
        box = ttk.Frame(self)
        box.grid(row=2, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        columns = ("name", "category", "quantity", "unit", "location", "flags")
        self.tree = ttk.Treeview(box, columns=columns, show="headings", selectmode="browse", height=9)
        for key, width in zip(columns, (220, 110, 85, 100, 160, 250)):
            self.tree.heading(key, text=key.title())
            self.tree.column(key, width=width, minwidth=65)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(box, command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(box, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.select())
        self.tree.bind("<Double-1>", lambda _event: self.edit())
        actions = ttk.Frame(self)
        actions.grid(row=3, column=0, sticky="ew", pady=8)
        self.edit_button = ttk.Button(actions, text="Edit selected", command=self.edit, state="disabled")
        self.edit_button.pack(side="left")
        self.adjust_button = ttk.Button(actions, text="Use / receive stock", command=self.adjust, state="disabled")
        self.adjust_button.pack(side="left", padx=8)
        self.remove_button = ttk.Button(actions, text="Remove record…", command=self.remove, state="disabled")
        self.remove_button.pack(side="left")
        self.previous = ttk.Button(actions, text="Previous", command=lambda: self.page(-1))
        self.previous.pack(side="right")
        self.next = ttk.Button(actions, text="Next", command=lambda: self.page(1))
        self.next.pack(side="right", padx=6)
        self.detail_label = ttk.Label(self, textvariable=self.details, justify="left", wraplength=950)
        self.detail_label.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        self.footer = ttk.Label(self, textvariable=self.status, wraplength=950, justify="left")
        self.footer.grid(row=5, column=0, sticky="ew")
        self.bind("<Configure>", self._resize, add=True)
        self.refresh()

    def _resize(self, event):
        if event.widget is self:
            for label in (self.detail_label, self.footer):
                label.configure(wraplength=max(300, event.width - 20))

    def selected(self):
        selection = self.tree.selection()
        return self.records.get(selection[0]) if selection else None

    def select(self):
        record = self.selected()
        for button in (self.edit_button, self.adjust_button, self.remove_button):
            button.configure(state="normal" if record else "disabled")
        try:
            self.details.set(describe_item(record.item) if record else NOTICE)
        except ValueError as exc:
            self.details.set("Review this record: " + str(exc))

    def refresh(self, *, reset=True):
        if self.dialog is not None:
            return
        if reset:
            self.offset = 0
        try:
            records = self.service.browse(self.query.get(), "" if self.category.get() == _ALL else self.category.get(),
                                          offset=self.offset, limit=_PAGE_SIZE + 1)
        except _ERRORS as exc:
            self.status.set("Could not refresh inventory: " + str(exc))
            return
        self.tree.delete(*self.tree.get_children())
        self.records = {str(record.item.id): record for record in records[:_PAGE_SIZE]}
        for key, record in self.records.items():
            item = record.item
            self.tree.insert("", "end", iid=key, values=(item.name, item.category.value, f"{item.quantity:g}",
                                                          item.unit, item.location, "; ".join(flags(item))))
        self.previous.configure(state="normal" if self.offset else "disabled")
        self.next.configure(state="normal" if len(records) > _PAGE_SIZE else "disabled")
        self.status.set(f"Showing {len(self.records)} supplies · page {self.offset // _PAGE_SIZE + 1}. "
                        "No sample stock has been added automatically.")
        self.select()

    def page(self, direction):
        if self.dialog is not None:
            return
        self.offset = max(0, self.offset + direction * _PAGE_SIZE)
        self.refresh(reset=False)

    def _finished(self, result):
        self.dialog = None
        if not self.winfo_exists() or result is None:
            return
        self.query.set("")
        self.category.set(_ALL)
        self.refresh()
        if str(result.item.id) in self.records:
            self.tree.selection_set(str(result.item.id))
        self.status.set("Supply saved locally. Search by name if it is on another page.")
        self._notify()

    def _notify(self):
        if self.on_change is not None:
            try:
                self.on_change()
            except _ERRORS as exc:
                self.status.set("Change saved, but dashboard refresh failed: " + str(exc))

    def add(self):
        if self.dialog is None:
            self.dialog = SupplyDialog(self, self.service, None, self._finished)

    def edit(self):
        record = self.selected()
        if record and self.dialog is None:
            self.dialog = SupplyDialog(self, self.service, record, self._finished)

    def adjust(self):
        record = self.selected()
        if record and self.dialog is None:
            self.dialog = StockDialog(self, self.service, record, self._finished)

    def remove(self):
        record = self.selected()
        if not record or self.dialog is not None:
            return
        if not messagebox.askyesno("Remove supply record?", f"Remove {record.item.name!r} from active inventory?\n\n"
                                  "This is not recording consumption. Use Use / receive stock for that. "
                                  "A private change-history copy is retained; this is not permanent data erasure.", parent=self):
            return
        try:
            self.service.remove(record)
        except _ERRORS as exc:
            self.status.set("Not removed: " + str(exc))
            return
        self.refresh()
        self.status.set("Removed from active inventory; private change history retained.")
        self._notify()

    def can_close(self):
        if self.dialog is not None:
            messagebox.showinfo("Supply editor open", "Save or cancel the supply editor before closing FieldForge.", parent=self.dialog)
            return False
        return True
