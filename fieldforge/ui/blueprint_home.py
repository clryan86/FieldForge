"""Visible desktop entry point and form-based creation of dimensioned layouts."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from fieldforge.blueprints.layout import create_layout, layout_part
from fieldforge.ui.blueprints import BlueprintStudio
from fieldforge.ui.lifecycle import release_tk_references


class LayoutForm(tk.Toplevel):
    def __init__(self, home):
        super().__init__(home)
        self.home = home
        self.parts = []
        self._committed_input = None
        self.bind("<Destroy>", self._destroyed, add=True)
        self.title("New dimensioned layout — FieldForge")
        self.geometry("900x710")
        self.minsize(760, 650)
        self.protocol("WM_DELETE_WINDOW", self.close)
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Build a layout from your dimensions", font=("TkDefaultFont", 18, "bold")).pack(anchor="w")
        ttk.Label(body, text="Add the parts you want to position. FieldForge draws their rectangular envelopes "
                  "and produces a parts table. No model or internet is needed.", wraplength=800).pack(anchor="w", pady=8)
        self.name = tk.StringVar()
        self.part_name = tk.StringVar()
        self.material = tk.StringVar()
        self.size = [tk.StringVar() for _ in range(3)]
        self.position = [tk.StringVar(value="0") for _ in range(3)]
        self.status = tk.StringVar(value="Enter a layout title and add at least one part.")
        ttk.Label(body, text="Layout title").pack(anchor="w")
        self.title_entry = ttk.Entry(body, textvariable=self.name)
        self.title_entry.pack(fill="x", pady=(2, 12))
        form = ttk.LabelFrame(body, text="Part details", padding=10)
        form.pack(fill="x")
        for col in range(3):
            form.columnconfigure(col, weight=1)
        ttk.Label(form, text="Part name").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.part_name).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Label(form, text="Material label").grid(row=0, column=1, sticky="w")
        ttk.Entry(form, textvariable=self.material).grid(row=1, column=1, columnspan=2, sticky="ew")
        for col, axis in enumerate("XYZ"):
            ttk.Label(form, text=f"Size {axis}").grid(row=2, column=col, sticky="w", pady=(8, 0))
            ttk.Entry(form, textvariable=self.size[col]).grid(row=3, column=col, sticky="ew", padx=(0, 8))
            ttk.Label(form, text=f"Position {axis}").grid(row=4, column=col, sticky="w", pady=(8, 0))
            ttk.Entry(form, textvariable=self.position[col]).grid(row=5, column=col, sticky="ew", padx=(0, 8))
        ttk.Label(form, text="Use mm, cm, m, in or ft (for example 24 in). A bare number means mm. "
                  "Position is the minimum corner; sizes must be positive.", wraplength=740).grid(
                      row=6, column=0, columnspan=3, sticky="w", pady=8)
        buttons = ttk.Frame(form)
        buttons.grid(row=7, column=0, columnspan=3, sticky="ew")
        ttk.Button(buttons, text="Add part", command=self.add).pack(side="left")
        ttk.Button(buttons, text="Update selected", command=self.update_part).pack(side="left", padx=6)
        ttk.Button(buttons, text="Remove selected", command=self.remove).pack(side="left")
        self.rows = ttk.Treeview(body, columns=("part", "material", "size", "position"), show="headings", height=6)
        for key, label, width in (("part", "Part", 150), ("material", "Material", 160),
                                  ("size", "XYZ size (mm)", 210), ("position", "XYZ position (mm)", 210)):
            self.rows.heading(key, text=label)
            self.rows.column(key, width=width, minwidth=80)
        self.rows.pack(fill="both", expand=True, pady=12)
        self.rows.bind("<<TreeviewSelect>>", self.select)
        footer = ttk.Frame(self, padding=(18, 8, 18, 18))
        footer.pack(side="bottom", fill="x", before=body)
        ttk.Label(footer, textvariable=self.status, wraplength=720).pack(fill="x")
        actions = ttk.Frame(footer)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Cancel", command=self.close).pack(side="left")
        self.create_button = ttk.Button(actions, text="Create drawings", command=self.create)
        self.create_button.pack(side="right")
        self.title_entry.focus_set()

    def _destroyed(self, event):
        if event.widget is self:
            if self.home.layout_form is self:
                self.home.layout_form = None
            release_tk_references(self)

    def _part(self):
        row = {"name": self.part_name.get(), "material": self.material.get(),
               "size": [v.get() for v in self.size], "position": [v.get() for v in self.position]}
        layout_part(**row)
        return row

    def _refresh(self):
        self.rows.delete(*self.rows.get_children())
        for index, row in enumerate(self.parts):
            part = layout_part(**row)
            self.rows.insert("", "end", iid=str(index), values=(part["name"], part["material"],
                " × ".join(str(v) for v in part["size_mm"]), ", ".join(str(v) for v in part["position_mm"])))
        self.status.set(f"{len(self.parts)} parts in this layout. Select a row to edit it.")

    def add(self):
        try:
            if len(self.parts) >= 60:
                raise ValueError("A layout supports up to 60 parts.")
            row = self._part()
            self.parts.append(row)
            self._committed_input = row
            self._refresh()
        except ValueError as exc:
            self.status.set(str(exc))

    def select(self, _event=None):
        selected = self.rows.selection()
        if selected:
            row = self.parts[int(selected[0])]
            self._committed_input = row
            self.part_name.set(row["name"])
            self.material.set(row["material"])
            for fields, key in ((self.size, "size"), (self.position, "position")):
                for variable, text in zip(fields, row[key]):
                    variable.set(text)

    def update_part(self):
        selected = self.rows.selection()
        if not selected:
            self.status.set("Select the part you want to update.")
            return
        try:
            row = self._part()
            self.parts[int(selected[0])] = row
            self._committed_input = row
            self._refresh()
        except ValueError as exc:
            self.status.set(str(exc))

    def remove(self):
        selected = self.rows.selection()
        if selected:
            del self.parts[int(selected[0])]
            self.part_name.set("")
            self.material.set("")
            for field in self.size:
                field.set("")
            for field in self.position:
                field.set("0")
            self._committed_input = None
            self._refresh()

    def create(self):
        try:
            if self.part_name.get() or self.material.get() or any(v.get() for v in self.size):
                if self._part() != self._committed_input:
                    self.status.set("Add this part or update the selected row before creating drawings.")
                    return
            value = create_layout(self.name.get(), self.parts)
            studio = self.home.open_maker("engineering")
            maker = studio.makers["engineering"]
            if maker.busy or maker._review_pending() or not maker._can_replace():
                self.status.set("Finish or keep the current engineering draft before replacing it.")
                return
            maker.history.detach()
            maker.show_blueprint(value)
            maker.load_request(value)
            maker.pages.select(maker.preview)
            maker.status.set("Your layout is ready. Save it, edit part measurements, or export the drawings and report.")
            self.home.layout_form = None
            self.destroy()
        except ValueError as exc:
            self.status.set(str(exc))

    def can_close(self):
        changed = bool(self.parts or self.name.get() or self.part_name.get() or self.material.get()
                       or any(v.get() for v in self.size) or any(v.get() != "0" for v in self.position))
        return not changed or messagebox.askyesno("Discard new layout?", "Discard the unsaved layout inputs?", parent=self)

    def close(self):
        if self.can_close():
            self.home.layout_form = None
            self.destroy()


class BlueprintHome(ttk.Frame):
    def __init__(self, parent, library):
        super().__init__(parent, padding=24)
        self.library = library
        self.studio = None
        self.layout_form = None
        ttk.Label(self, text="Blueprints", font=("TkDefaultFont", 24, "bold")).pack(anchor="w")
        ttk.Label(self, text="Create a dimensioned layout, plan a project, or design a software system.",
                  font=("TkDefaultFont", 12)).pack(anchor="w", pady=(4, 20))
        quick = ttk.LabelFrame(self, text="Start drawing — works without AI", padding=16)
        quick.pack(fill="x")
        ttk.Label(quick, text="Enter your parts, dimensions and positions in a form. Create assembly views, "
                  "individual part sheets, a materials table and a printable report.", wraplength=950).pack(anchor="w")
        self.new_button = ttk.Button(quick, text="Create layout from dimensions", command=self.new_layout)
        self.new_button.pack(anchor="w", pady=(12, 0))
        choices = ttk.Frame(self)
        choices.pack(fill="x", pady=20)
        self.maker_buttons = {}
        for col, (mode, title, description) in enumerate((
            ("engineering", "Engineering", "Edit dimensions and positions. Inspect geometry, requirements and drawing sheets."),
            ("project", "Projects and guides", "Plan phases, dependencies, resources and acceptance checks."),
            ("software", "Software architecture", "Inspect components, interfaces, data flows and implementation steps."),
        )):
            choices.columnconfigure(col, weight=1, uniform="maker")
            box = ttk.LabelFrame(choices, text=title, padding=14)
            box.grid(row=0, column=col, sticky="nsew", padx=(0, 10))
            ttk.Label(box, text=description, wraplength=270).pack(fill="x", expand=True, anchor="n")
            button = ttk.Button(box, text="Open " + title, command=lambda selected=mode: self.open_maker(selected))
            button.pack(fill="x", pady=(14, 0))
            self.maker_buttons[mode] = button
        ttk.Label(self, text="AI generation", font=("TkDefaultFont", 13, "bold")).pack(anchor="w")
        ttk.Label(self, text="Each maker can generate and revise a design with a local Ollama model. "
                  "Open a maker, choose Load models, and select a model you have installed. "
                  "No model is bundled. Manual layout creation, saved designs, editing and exports work without one.",
                  wraplength=960).pack(anchor="w", pady=(6, 14))
        ttk.Label(self, text="Drawings represent rectangular part envelopes. Structural analysis, joints and "
                  "fabrication-ready CAD are not implemented. Generated design quality has not been benchmarked.",
                  wraplength=960).pack(anchor="w")

    def open_maker(self, mode):
        if self.studio is None or not self.studio.winfo_exists():
            self.studio = BlueprintStudio(self, self.library)
        self.studio.pages.select(self.studio.makers[mode])
        self.studio.deiconify()
        self.studio.lift()
        return self.studio

    def new_layout(self):
        if self.layout_form is None or not self.layout_form.winfo_exists():
            self.layout_form = LayoutForm(self)
        self.layout_form.lift()
        return self.layout_form

    def can_close(self):
        if self.layout_form is not None and self.layout_form.winfo_exists() and not self.layout_form.can_close():
            return False
        return self.studio is None or not self.studio.winfo_exists() or self.studio.can_close()
