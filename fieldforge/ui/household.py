"""Household editor for the Inventory screen; no automatic personal-data import."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from fieldforge.core.household import (
    FILTERS,
    KINDS,
    NOTICE,
    PRIVACY,
    HouseholdService,
    MemberRecord,
    kind_label,
    member_from_fields,
)

_ERRORS = (OSError, ValueError, sqlite3.Error)
_PAGE = 50


class MemberDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, service: HouseholdService, record: MemberRecord | None,
                 finished: Callable[[MemberRecord | None], None]) -> None:
        super().__init__(parent)
        self.service, self.record, self.finished = service, record, finished
        self.result: MemberRecord | None = None
        self._disposed = False
        self.title("FieldForge — Edit household profile" if record else "FieldForge — Add household profile")
        self.geometry("820x670")
        self.minsize(720, 630)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        initial = {"name": "", "kind": "Adult", "water": "", "calories": "", "notes": ""}
        if record:
            member = record.member
            initial.update(name=member.name, kind=kind_label(member), water=str(member.daily_water_liters),
                           calories=str(member.daily_calories), notes=member.notes)
        self.fields = {key: tk.StringVar(value=value) for key, value in initial.items() if key != "notes"}
        self.status = tk.StringVar(value=("Editing a saved profile. Only Save profile writes changes." if record else
                                        "New profile, not saved. Enter your own planning allowances."))
        self.plan = tk.StringVar()
        ttk.Label(self, text="Household profile", font=("TkDefaultFont", 19, "bold"),
                  padding=(16, 14)).grid(row=0, column=0, sticky="w")
        self.notice = ttk.Label(self, text=NOTICE, wraplength=760, padding=(16, 0, 16, 10), justify="left")
        self.notice.grid(row=1, column=0, sticky="ew")
        form = ttk.Frame(self, padding=(16, 0))
        form.grid(row=2, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        for row, (key, title) in enumerate((("name", "Name or alias *"), ("kind", "Profile kind *"),
                                            ("water", "Water planning allowance (liters/day) *"),
                                            ("calories", "Food planning allowance (kcal/day) *"))):
            ttk.Label(form, text=title).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            control = (ttk.Combobox(form, textvariable=self.fields[key], values=tuple(KINDS), state="readonly")
                       if key == "kind" else ttk.Entry(form, textvariable=self.fields[key]))
            control.grid(row=row, column=1, sticky="ew", pady=5)
        note_box = ttk.LabelFrame(self, text="Private planning note (optional, up to 10,000 characters)", padding=8)
        note_box.grid(row=3, column=0, sticky="nsew", padx=16, pady=10)
        self.note = ScrolledText(note_box, height=5, width=50, wrap="word", font=("TkDefaultFont", 11))
        self.note.pack(fill="both", expand=True)
        self.note.insert("1.0", initial["notes"])
        self.privacy = ttk.Label(self, text=PRIVACY, wraplength=760, padding=(16, 0, 16, 6), justify="left")
        self.privacy.grid(row=4, column=0, sticky="ew")
        self.preview_label = ttk.Label(self, textvariable=self.plan, wraplength=760, padding=(16, 3), justify="left")
        self.preview_label.grid(row=5, column=0, sticky="ew")
        controls = ttk.Frame(self, padding=(16, 8))
        controls.grid(row=6, column=0, sticky="ew")
        self.save_button = ttk.Button(controls, text="Save profile", command=self.save)
        self.save_button.pack(side="right")
        self.cancel_button = ttk.Button(controls, text="Cancel", command=self.close)
        self.cancel_button.pack(side="right", padx=8)
        self.footer = ttk.Label(self, textvariable=self.status, wraplength=760, padding=(16, 0, 16, 12), justify="left")
        self.footer.grid(row=7, column=0, sticky="ew")
        self.initial = self._values()
        for field in self.fields.values():
            field.trace_add("write", lambda *_: self.preview())
        self.bind("<Configure>", self._resize, add=True)
        self.preview()
        self.grab_set()

    def _resize(self, event: tk.Event) -> None:
        if event.widget is self:
            for label in (self.notice, self.privacy, self.preview_label, self.footer):
                label.configure(wraplength=max(360, event.width - 40))

    def _values(self) -> dict[str, str]:
        return {**{key: value.get() for key, value in self.fields.items()}, "notes": self.note.get("1.0", "end-1c")}

    def preview(self) -> None:
        try:
            member = member_from_fields(self._values())
            self.plan.set(f"This profile contributes {member.daily_water_liters:g} liters/day and "
                          f"{member.daily_calories:,} kcal/day to combined planning totals. "
                          "No age/species-specific recommendation is generated.")
        except ValueError:
            self.plan.set("Enter explicit planning allowances to preview this profile's contribution. Nothing is saved yet.")

    def save(self) -> None:
        if self._disposed:
            return
        try:
            member = member_from_fields(self._values(), member_id=self.record.member.id if self.record else None)
            if member.daily_calories == 0 and not messagebox.askyesno(
                "Zero calorie allowance?",
                "This profile will contribute ZERO calories to the food calculation. "
                "That is a planning exclusion, not advice to eat or feed nothing. "
                "Does your plan intentionally use zero?", parent=self,
            ):
                self.status.set("Not saved. Review the food allowance before continuing.")
                return
            self.result = self.service.save(member, expected=self.record.token if self.record else None)
        except _ERRORS as exc:
            self.status.set("Not saved: " + str(exc))
            return
        self.destroy()

    def close(self) -> None:
        if self._values() != self.initial and not messagebox.askyesno(
            "Discard household edits?", "Your profile changes are not saved. Discard them?", parent=self
        ):
            return
        self.destroy()

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self and not self._disposed:
            self._disposed = True
            self.finished(self.result)


class HouseholdTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, service: HouseholdService, *,
                 on_change: Callable[[], None] | None = None) -> None:
        super().__init__(parent, padding=12)
        self.service, self.on_change = service, on_change
        self.dialog: MemberDialog | None = None
        self.records: dict[str, MemberRecord] = {}
        self.offset = 0
        self.query = tk.StringVar()
        self.kind = tk.StringVar(value=FILTERS[0])
        self.summary = tk.StringVar(value="Loading household planning totals…")
        self.status = tk.StringVar()
        self.details = tk.StringVar(value="Select a profile to edit its saved assumptions. Notes are shown only in the editor.")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        ttk.Label(self, text="People & pets", font=("TkDefaultFont", 21, "bold")).grid(row=0, column=0, sticky="w")
        self.notice = ttk.Label(self, text=NOTICE, wraplength=980, justify="left")
        self.notice.grid(row=1, column=0, sticky="ew", pady=(6, 10))
        self.summary_label = ttk.Label(self, textvariable=self.summary, font=("TkDefaultFont", 11, "bold"), wraplength=980)
        self.summary_label.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        tools = ttk.Frame(self)
        tools.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        tools.columnconfigure(1, weight=1)
        ttk.Label(tools, text="Find name / alias").grid(row=0, column=0, padx=(0, 8))
        search = ttk.Entry(tools, textvariable=self.query)
        search.grid(row=0, column=1, sticky="ew")
        search.bind("<Return>", lambda _: self.refresh())
        picker = ttk.Combobox(tools, textvariable=self.kind, values=FILTERS, state="readonly", width=16)
        picker.grid(row=0, column=2, padx=8)
        picker.bind("<<ComboboxSelected>>", lambda _: self.refresh())
        ttk.Button(tools, text="Search / Refresh", command=self.refresh).grid(row=0, column=3)
        self.add_button = ttk.Button(tools, text="Add person / pet", command=self.add)
        self.add_button.grid(row=0, column=4, padx=(8, 0))
        box = ttk.Frame(self)
        box.grid(row=4, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(box, columns=("name", "kind", "water", "food"), show="headings",
                                 selectmode="browse", height=10)
        for column, title, width in (("name", "Name or alias", 300), ("kind", "Kind", 150),
                                     ("water", "Liters/day (planned)", 170), ("food", "kcal/day (planned)", 170)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, minwidth=120)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(box, command=self.tree.yview)
        horizontal = ttk.Scrollbar(box, orient="horizontal", command=self.tree.xview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.select())
        self.tree.bind("<Double-1>", lambda _: self.edit())
        actions = ttk.Frame(self)
        actions.grid(row=5, column=0, sticky="ew", pady=10)
        self.edit_button = ttk.Button(actions, text="Edit selected profile", command=self.edit, state="disabled")
        self.edit_button.pack(side="left")
        self.remove_button = ttk.Button(actions, text="Remove profile…", command=self.remove, state="disabled")
        self.remove_button.pack(side="left", padx=8)
        self.next = ttk.Button(actions, text="Next", command=lambda: self.page(1))
        self.next.pack(side="right")
        self.previous = ttk.Button(actions, text="Previous", command=lambda: self.page(-1))
        self.previous.pack(side="right", padx=8)
        self.detail_label = ttk.Label(self, textvariable=self.details, wraplength=980, justify="left")
        self.detail_label.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        self.footer = ttk.Label(self, textvariable=self.status, wraplength=980, justify="left")
        self.footer.grid(row=7, column=0, sticky="ew")
        self.bind("<Configure>", self._resize, add=True)
        self.refresh()

    def _resize(self, event: tk.Event) -> None:
        if event.widget is self:
            for label in (self.notice, self.summary_label, self.detail_label, self.footer):
                label.configure(wraplength=max(300, event.width - 30))

    def selected(self) -> MemberRecord | None:
        selection = self.tree.selection()
        return self.records.get(selection[0]) if selection else None

    def select(self) -> None:
        record = self.selected()
        for button in (self.edit_button, self.remove_button):
            button.configure(state="normal" if record else "disabled")
        self.details.set(
            f"{record.member.name} · {kind_label(record.member)}. Editing allowances updates combined resource estimates. "
            "The record is not a medical, nutritional, or veterinary assessment." if record else
            "Select a profile to edit its saved assumptions. Notes are shown only in the editor."
        )

    def refresh(self, *, reset: bool = True) -> None:
        if self.dialog is not None:
            return
        if reset:
            self.offset = 0
        try:
            rows = self.service.browse(self.query.get(), self.kind.get(), offset=self.offset, limit=_PAGE + 1)
        except _ERRORS as exc:
            self.summary.set("Could not read household data — no stale totals shown.")
            self.status.set("Refresh failed: " + str(exc))
            self.records.clear()
            self.tree.delete(*self.tree.get_children())
            self.select()
            return
        self.tree.delete(*self.tree.get_children())
        self.records = {str(row.member.id): row for row in rows[:_PAGE]}
        for key, row in self.records.items():
            member = row.member
            self.tree.insert("", "end", iid=key, values=(member.name, kind_label(member),
                                                         f"{member.daily_water_liters:g}", member.daily_calories))
        self.previous.configure(state="normal" if self.offset else "disabled")
        self.next.configure(state="normal" if len(rows) > _PAGE else "disabled")
        try:
            total = self.service.summary()
            self.summary.set(f"People: {total.people} · Children included: {total.children} · Pets: {total.pets}\n"
                             f"All saved profiles: {total.water_liters:g} liters/day · {total.calories:,} kcal/day. "
                             f"{total.zero_calorie_profiles} profiles count zero calories.")
        except _ERRORS as exc:
            self.summary.set("Review saved allowances: " + str(exc))
        self.status.set(f"Showing {len(self.records)} profiles · page {self.offset // _PAGE + 1}. "
                        "Totals include all saved profiles, not just search results. "
                        "Shared totals do not match food/water supplies to individual people or pets.")
        self.select()

    def page(self, direction: int) -> None:
        if self.dialog is None:
            self.offset = max(0, self.offset + direction * _PAGE)
            self.refresh(reset=False)

    def _finished(self, result: MemberRecord | None) -> None:
        self.dialog = None
        if not self.winfo_exists() or result is None:
            return
        self.query.set("")
        self.kind.set(FILTERS[0])
        self.refresh()
        if str(result.member.id) in self.records:
            self.tree.selection_set(str(result.member.id))
            self.tree.see(str(result.member.id))
        self.status.set("Profile saved locally. Search by name if it is on a later page. "
                        "Private notes were not copied into the change-event log.")
        self._notify()

    def _notify(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except _ERRORS as exc:
                self.status.set("Profile change saved, but dashboard refresh failed: " + str(exc))

    def add(self) -> None:
        if self.dialog is None:
            self.dialog = MemberDialog(self, self.service, None, self._finished)

    def edit(self) -> None:
        record = self.selected()
        if record and self.dialog is None:
            self.dialog = MemberDialog(self, self.service, record, self._finished)

    def remove(self) -> None:
        record = self.selected()
        if not record or self.dialog is not None:
            return
        if not messagebox.askyesno(
            "Remove household profile?",
            f"Remove {record.member.name!r} from the active household?\n\n"
            "This removes their allowance from future household totals, but does not change inventory. "
            "It is not a recommendation to reduce anyone's supplies. Old backups may still contain this profile.",
            parent=self,
        ):
            return
        try:
            self.service.remove(record)
        except _ERRORS as exc:
            self.status.set("Not removed: " + str(exc))
            return
        self.refresh()
        self.status.set("Removed from active household; current inventory is unchanged. Old backups are not erased.")
        self._notify()

    def can_close(self) -> bool:
        if self.dialog is not None:
            messagebox.showinfo("Household editor open", "Save or cancel the household editor before continuing.", parent=self.dialog)
            return False
        return True
