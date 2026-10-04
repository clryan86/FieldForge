"""Tk preview of FieldForge's own limited SVG output, without a browser dependency."""

from __future__ import annotations

import re
import tkinter as tk
import xml.etree.ElementTree as ET
from tkinter import ttk

from fieldforge.blueprints.render import drawings
from fieldforge.ui.blueprint_geometry import GeometryInspector


class DrawingPreview(ttk.Frame):
    def __init__(self, parent, configure_clearance=None, *, notice_text=None):
        super().__init__(parent)
        self.images = {}
        self.highlighted = set()
        self.selection = tk.StringVar()
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=4)
        self.choices = ttk.Combobox(toolbar, textvariable=self.selection, state="readonly")
        self.choices.pack(side="left", fill="x", expand=True)
        self.choices.bind("<<ComboboxSelected>>", self.redraw)
        ttk.Label(toolbar, text="Zoom").pack(side="left", padx=(12, 4))
        self.zoom = tk.StringVar(value="Fit width")
        zoom = ttk.Combobox(toolbar, textvariable=self.zoom, state="readonly", width=10,
                            values=("Fit width", "100%", "150%", "200%"))
        zoom.pack(side="left")
        zoom.bind("<<ComboboxSelected>>", self.redraw)
        self.notice = ttk.Label(self, text=notice_text or "Drawings are illustrative. The Blueprint and checks tab contains "
                                "the complete text equivalent; exported SVGs retain full vector detail.", wraplength=900)
        self.notice.pack(fill="x", pady=4)
        self.bind("<Configure>", lambda event: self.notice.configure(wraplength=max(200, event.width - 16)))
        self.pages = ttk.Notebook(self)
        self.pages.pack(fill="both", expand=True)
        frame = self.sheet = ttk.Frame(self.pages)
        self.pages.add(frame, text="Sheets")
        self.inspector = GeometryInspector(self.pages, self.highlight_parts, configure_clearance)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(frame, background="#102239", highlightthickness=0, takefocus=True)
        scroll = ttk.Scrollbar(frame, command=self.canvas.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self.redraw)
        self.canvas.bind("<Down>", lambda e: self.canvas.yview_scroll(1, "units"))
        self.canvas.bind("<Up>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Next>", lambda e: self.canvas.yview_scroll(1, "pages"))
        self.canvas.bind("<Prior>", lambda e: self.canvas.yview_scroll(-1, "pages"))
        self.canvas.bind("<Left>", lambda e: self.canvas.xview_scroll(-1, "units"))
        self.canvas.bind("<Right>", lambda e: self.canvas.xview_scroll(1, "units"))
        self.canvas.bind("<Home>", self.reset_view)

    def reset_view(self, _event=None):
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def show(self, blueprint):
        self.images = drawings(blueprint)
        self.highlighted.clear()
        if blueprint["request"]["mode"] == "engineering":
            self.inspector.show(blueprint["design"]["parts"])
            if str(self.inspector) not in self.pages.tabs():
                self.pages.add(self.inspector, text="Geometry inspector")
        elif str(self.inspector) in self.pages.tabs():
            self.pages.forget(self.inspector)
        self.choices.configure(values=list(self.images))
        self.selection.set(next(iter(self.images)))
        self.reset_view()
        self.redraw()

    def highlight_parts(self, ids):
        self.highlighted = set(ids)
        if ids:
            self.selection.set("isometric.svg")
        self.pages.select(self.sheet)
        self.reset_view()
        self.redraw()

    def redraw(self, _event=None):
        self.canvas.delete("all")
        if not self.images:
            return
        # Parse only generated SVG; this is intentionally not an arbitrary SVG loader.
        root = ET.fromstring(self.images[self.selection.get()])
        _, _, width, height = map(float, root.attrib["viewBox"].split())
        scale = (max(0.1, (self.canvas.winfo_width() - 10) / width)
                 if self.zoom.get() == "Fit width" else float(self.zoom.get().rstrip("%")) / 100)
        self.canvas.configure(scrollregion=(0, 0, width * scale, height * scale))
        light = root.attrib.get("data-font") == "mono"
        self.canvas.configure(background="#ffffff" if light else "#102239")
        ink = "#18344c" if light else "#eff6ff"
        outline = "#426986" if light else "#91caff"
        # Draw selected envelopes last so other parts cannot hide the highlight.
        elements = sorted(root, key=lambda element: element.attrib.get("data-part") in self.highlighted)
        for element in elements:
            tag = element.tag.rsplit("}", 1)[-1]
            a = element.attrib
            selected = a.get("data-part") in self.highlighted
            colour = "#b04400" if selected else outline
            line_width = 3 if selected else 1
            if tag == "rect" and a.get("class") == "part":
                x, y, w, h = (float(a.get(key, 0)) for key in ("x", "y", "width", "height"))
                self.canvas.create_rectangle(x * scale, y * scale, (x + w) * scale,
                                             (y + h) * scale, fill="#dceaf3" if light else "#28496a",
                                             outline=colour, width=line_width)
            elif tag == "polygon" and a.get("class") == "part":
                coordinates = [float(v) * scale for v in re.split(r"[ ,]+", a["points"].strip())]
                self.canvas.create_polygon(*coordinates, fill="", outline=colour, width=line_width)
            elif tag == "line":
                coordinates = [float(a[key]) * scale for key in ("x1", "y1", "x2", "y2")]
                self.canvas.create_line(*coordinates, fill=a.get("stroke", outline))
            elif tag == "text":
                size = re.search(r"font-size:(\d+)px", a.get("style", ""))
                pixels = int(size[1]) if size else 14
                anchor = {"middle": "s", "end": "se"}.get(a.get("text-anchor"), "sw")
                self.canvas.create_text(float(a["x"]) * scale, float(a["y"]) * scale,
                                        text=element.text or "", anchor=anchor, fill=a.get("fill", ink),
                                        font=("TkFixedFont" if light else "TkDefaultFont",
                                              -max(1, round(pixels * scale))))
            elif tag == "path" and a.get("class") == "line":
                segments = re.findall(r"([MLh])(-?[\d.]+)(?: (-?[\d.]+))?", a["d"])
                coordinates = []
                for command, x, y in segments:
                    if command == "h":
                        coordinates.extend((coordinates[-2] + float(x) * scale, coordinates[-1]))
                    else:
                        coordinates.extend((float(x) * scale, float(y) * scale))
                if len(coordinates) >= 4:
                    self.canvas.create_line(*coordinates,
                                            fill="#87b8d8", arrow="last" if "marker-end" in a else "none")
