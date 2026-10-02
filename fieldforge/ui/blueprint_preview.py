"""Tk preview of FieldForge's own limited SVG output, without a browser dependency."""

from __future__ import annotations

import re
import tkinter as tk
import xml.etree.ElementTree as ET
from tkinter import ttk

from fieldforge.blueprints.render import drawings


class DrawingPreview(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.images = {}
        self.selection = tk.StringVar()
        self.choices = ttk.Combobox(self, textvariable=self.selection, state="readonly")
        self.choices.pack(fill="x", pady=4)
        self.choices.bind("<<ComboboxSelected>>", self.redraw)
        ttk.Label(self, text="Drawings are illustrative. The Blueprint and checks tab contains "
                  "the complete text equivalent; exported SVGs retain full vector detail.",
                  wraplength=900).pack(fill="x", pady=4)
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(frame, background="#102239", highlightthickness=0, takefocus=True)
        scroll = ttk.Scrollbar(frame, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self.redraw)
        self.canvas.bind("<Down>", lambda e: self.canvas.yview_scroll(1, "units"))
        self.canvas.bind("<Up>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Next>", lambda e: self.canvas.yview_scroll(1, "pages"))
        self.canvas.bind("<Prior>", lambda e: self.canvas.yview_scroll(-1, "pages"))

    def show(self, blueprint):
        self.images = drawings(blueprint)
        self.choices.configure(values=list(self.images))
        self.selection.set(next(iter(self.images)))
        self.redraw()

    def redraw(self, _event=None):
        self.canvas.delete("all")
        if not self.images:
            return
        # Parse only generated SVG; this is intentionally not an arbitrary SVG loader.
        root = ET.fromstring(self.images[self.selection.get()])
        _, _, width, height = map(float, root.attrib["viewBox"].split())
        scale = max(0.35, (self.canvas.winfo_width() - 10) / width)
        self.canvas.configure(scrollregion=(0, 0, width * scale, height * scale))
        for element in root:
            tag = element.tag.rsplit("}", 1)[-1]
            a = element.attrib
            if tag == "rect" and a.get("class") == "part":
                x, y, w, h = (float(a.get(key, 0)) for key in ("x", "y", "width", "height"))
                self.canvas.create_rectangle(x * scale, y * scale, (x + w) * scale,
                                             (y + h) * scale, fill="#28496a", outline="#91caff")
            elif tag == "text":
                size = re.search(r"font-size:(\d+)px", a.get("style", ""))
                pixels = int(size[1]) if size else 14
                self.canvas.create_text(float(a["x"]) * scale, float(a["y"]) * scale,
                                        text=element.text or "", anchor="sw", fill="#eff6ff",
                                        font=("TkDefaultFont", -max(8, int(pixels * scale))))
            elif tag == "path" and a.get("class") == "line":
                segments = re.findall(r"([MLh])([\d.]+)(?: ([\d.]+))?", a["d"])
                coordinates = []
                for command, x, y in segments:
                    if command == "h":
                        coordinates.extend((coordinates[-2] + float(x) * scale, coordinates[-1]))
                    else:
                        coordinates.extend((float(x) * scale, float(y) * scale))
                if len(coordinates) >= 4:
                    self.canvas.create_line(*coordinates,
                                            fill="#87b8d8", arrow="last" if "marker-end" in a else "none")
