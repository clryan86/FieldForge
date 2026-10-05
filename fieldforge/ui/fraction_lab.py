"""Keyboard-operable fraction exploration, separate from saved practice."""

import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.knowledge.fraction_models import compare_fractions, fraction_scene


def draw_fraction(canvas, diagram, index=0):
    canvas.delete("all")
    for mark in fraction_scene(diagram, index, max(300, canvas.winfo_width())):
        if mark.kind == "text":
            canvas.create_text(*mark.coords, text=mark.text, fill="#18394a", font=("TkDefaultFont", 9))
        elif mark.kind == "line":
            canvas.create_line(*mark.coords, fill="#18394a")
        elif mark.kind == "point":
            canvas.create_oval(*mark.coords, fill="#18394a", outline="#18394a", tags=("fraction_point",))
        else:
            canvas.create_rectangle(*mark.coords, fill="#2c7f99" if mark.kind == "filled" else "white",
                                    outline="#18394a", tags=(mark.kind,))


class FractionLab(ttk.Frame):
    PRESETS = {
        "Equivalent amounts": ((1, 2, 2, 4), "Predict: change B from 2/4 to 3/6. Change both controls, then explain why the final endpoint matches A again."),
        "Size of one part": ((1, 3, 1, 6), "Keep B's selected parts at one. Predict what happens as its total equal parts increase. Keep the whole fixed."),
        "Compare different units": ((2, 3, 3, 4), "Which amount is larger? Read the common-piece explanation, then change B to 8/12 and predict whether the endpoints will match."),
    }

    def __init__(self, parent):
        super().__init__(parent, padding=10)
        self.preset = tk.StringVar(value=next(iter(self.PRESETS)))
        self.values = [tk.StringVar() for _ in range(4)]
        self.description = ttk.Label(self, text="Predict → change → explain. Both strips use the same unit whole.")
        self.description.pack(fill="x")
        presets = ttk.Frame(self)
        presets.pack(fill="x", pady=6)
        self.picker = ttk.Combobox(presets, textvariable=self.preset, state="readonly", values=list(self.PRESETS))
        self.picker.pack(side="left", fill="x", expand=True)
        self.picker.bind("<<ComboboxSelected>>", lambda _e: self.reset())
        self.reset_button = ttk.Button(presets, text="Reset example", command=self.reset)
        self.reset_button.pack(side="right", padx=(6, 0))
        self.challenge = ttk.Label(self, wraplength=550)
        self.challenge.pack(fill="x", pady=(0, 6))
        controls = ttk.Frame(self)
        controls.pack(fill="x")
        self.inputs = []
        for row in range(2):
            ttk.Label(controls, text="A" if row == 0 else "B").grid(row=row, column=0, padx=(0, 8))
            ttk.Label(controls, text="Selected parts").grid(row=row, column=1, sticky="w")
            numerator = ttk.Combobox(controls, textvariable=self.values[row * 2], state="readonly", width=4)
            numerator.grid(row=row, column=2, padx=(4, 12), pady=3)
            ttk.Label(controls, text="Total equal parts").grid(row=row, column=3, sticky="w")
            denominator = ttk.Combobox(controls, textvariable=self.values[row * 2 + 1], state="readonly",
                                       width=4, values=list(range(1, 13)))
            denominator.grid(row=row, column=4, padx=4)
            self.inputs.extend((numerator, denominator))
            for widget in (numerator, denominator):
                widget.bind("<<ComboboxSelected>>", lambda _e: self.changed())
        self.canvas = tk.Canvas(self, height=146, background="#f0f5f8", highlightthickness=0)
        self.canvas.pack(fill="x", pady=6)
        self.notice = ttk.Label(self, text="Explore 0 to 1, with 1–12 equal parts. Exploration is not saved; use Practice & explain to record your work.", wraplength=550)
        self.notice.pack(side="bottom", fill="x", pady=(8, 0))
        self.comparison = ScrolledText(self, wrap="word", height=4, padx=6, pady=6,
                                       state="disabled", font=("TkDefaultFont", 10))
        self.comparison.pack(fill="both", expand=True)
        self.model = None
        self.canvas.bind("<Configure>", lambda _e: self.draw())
        self.bind("<Configure>", self.resized)
        self.reset()

    def reset(self):
        values, text = self.PRESETS[self.preset.get()]
        for variable, value in zip(self.values, values):
            variable.set(str(value))
        self.challenge.configure(text=text)
        self.changed()

    def changed(self):
        try:
            values = [int(v.get()) for v in self.values]
            adjusted = []
            for i in (0, 2):
                n, d = values[i:i + 2]
                if not 1 <= d <= 12 or not 0 <= n <= 12:
                    raise ValueError("Choose from the listed part counts.")
                if n > d:
                    adjusted.append(f"{'A' if i == 0 else 'B'} selected parts changed from {n} to {d} to stay within one whole.")
                    values[i] = d
                    self.values[i].set(str(d))
                self.inputs[i].configure(values=list(range(d + 1)))
            result = compare_fractions(*values)
        except ValueError as exc:
            self.set_comparison(str(exc))
            return
        rows = [dict(label=label, selected=values[i], parts=values[i + 1]) for label, i in (("A", 0), ("B", 2))]
        self.model = dict(description="Both amounts use one unit whole.", steps=[
            dict(title="Compare two fractions", caption="The strips and number lines share the same unit whole.", rows=rows)])
        self.set_comparison((" ".join(adjusted) + "\n\n" if adjusted else "") + result)
        self.draw()

    def set_comparison(self, text):
        self.comparison.configure(state="normal")
        self.comparison.delete("1.0", "end")
        self.comparison.insert("1.0", text)
        self.comparison.configure(state="disabled")
        self.comparison.yview_moveto(0)

    def draw(self):
        if self.model:
            draw_fraction(self.canvas, self.model)

    def resized(self, event):
        if event.widget is self:
            for label in (self.description, self.challenge, self.notice):
                label.configure(wraplength=max(250, self.winfo_width() - 24))
