"""Read-only image-map reference viewer with explicit loading, pan and zoom."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk

from .map_jobs import LatestMapReader
from .tk_cleanup import TkCleanupMixin


class ImageMapFrame(TkCleanupMixin, ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=12)
        self.pack(fill="both", expand=True)
        self._closed = False
        self.document = None
        self._photo = None
        self._job = None
        self._after = None
        self._draw_after = None
        self._drag = None
        self.center = (0, 0)
        self.scale = 1.0
        self.worker = LatestMapReader()
        self.permission = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="No image open. Nothing is read automatically.")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        ttk.Label(self, text="Map image reference", font=("TkDefaultFont", 20, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self,
            text="UNCALIBRATED IMAGE — no GPS overlay, coordinates, bearings or scale in ground units",
            foreground="#8b4d16",
        ).grid(row=1, column=0, sticky="w", pady=(4, 8))
        controls = ttk.Frame(self)
        controls.grid(row=2, column=0, sticky="ew")
        ttk.Checkbutton(
            controls,
            text="I trust this local image and have permission to use it.",
            variable=self.permission,
        ).pack(anchor="w")
        actions = ttk.Frame(controls)
        actions.pack(fill="x", pady=6)
        self.open_button = ttk.Button(actions, text="Open map image…", command=self.choose)
        self.clear_button = ttk.Button(actions, text="Clear / cancel", command=self.clear)
        self.fit_button = ttk.Button(actions, text="Fit image", command=self.fit)
        self.plus_button = ttk.Button(actions, text="Zoom +", command=lambda: self.zoom(1.5))
        self.minus_button = ttk.Button(actions, text="Zoom −", command=lambda: self.zoom(1 / 1.5))
        self.actual_button = ttk.Button(actions, text="100% pixels", command=self.actual_size)
        for button in (
            self.open_button,
            self.clear_button,
            self.fit_button,
            self.plus_button,
            self.minus_button,
            self.actual_button,
        ):
            button.pack(side="left", padx=(0, 7))
        status_box = ttk.Frame(self, height=54)
        status_box.grid(row=3, column=0, sticky="ew", pady=(0, 5))
        status_box.pack_propagate(False)
        self.status_label = ttk.Label(
            status_box, textvariable=self.status, wraplength=960, anchor="nw"
        )
        self.status_label.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self, background="#ebede9", highlightthickness=1)
        self.canvas.grid(row=4, column=0, sticky="nsew")
        ttk.Label(
            self,
            text="Drag or arrow keys to pan; mouse wheel to zoom. First page/frame only; stored pixel orientation. "
            "GeoTIFF/world-file calibration and EXIF GPS are not interpreted.",
            wraplength=960,
        ).grid(row=5, column=0, sticky="ew", pady=(7, 0))
        self.canvas.bind("<Configure>", lambda _e: self.request_draw())
        self.canvas.bind("<ButtonPress-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind(
            "<MouseWheel>", lambda event: self.zoom(1.5 if event.delta > 0 else 1 / 1.5)
        )
        self.canvas.bind("<Button-4>", lambda _e: self.zoom(1.5))
        self.canvas.bind("<Button-5>", lambda _e: self.zoom(1 / 1.5))
        for key, dx, dy in (
            ("Left", -100, 0),
            ("Right", 100, 0),
            ("Up", 0, -100),
            ("Down", 0, 100),
        ):
            self.canvas.bind("<" + key + ">", lambda _e, dx=dx, dy=dy: self.pan(dx, dy))
        self.permission.trace_add("write", self.permission_changed)
        self._buttons()
        self.poll()

    def _buttons(self):
        self.open_button.configure(state="normal" if self.permission.get() else "disabled")
        for button in (self.fit_button, self.plus_button, self.minus_button, self.actual_button):
            button.configure(state="normal" if self.document is not None else "disabled")

    def permission_changed(self, *_):
        if not self.permission.get():
            self.clear()
        self._buttons()

    def choose(self):
        if not self.permission.get():
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="Open a trusted local map image",
            filetypes=[
                (
                    "Map images",
                    "*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp *.gif *.jp2 *.avif *.tga *.ppm *.ico",
                ),
                ("All files", "*"),
            ],
        )
        if path:
            self.open_path(path)

    def open_path(self, path):
        if self._closed or not self.permission.get():
            return False
        self.clear()
        self._job = (self.worker.submit("image_open", path), "image_open")
        self.status.set("Reading selected image locally. The old image is cleared.")
        return True

    def clear(self):
        self.worker.cancel()
        self._job = None
        self.document = self._photo = self._drag = None
        self.canvas.delete("all")
        if self._draw_after is not None:
            self.after_cancel(self._draw_after)
            self._draw_after = None
        self.status.set("No image open. Image files are unchanged; nothing was exported.")
        self._buttons()

    def dimensions(self):
        return max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())

    def fit(self):
        if self.document is None:
            return
        width, height = self.dimensions()
        self.center = (self.document.width / 2, self.document.height / 2)
        self.scale = max(0.001, min(8, width / self.document.width, height / self.document.height))
        self.request_draw()

    def actual_size(self):
        if self.document is not None:
            self.scale = 1.0
            self.request_draw()

    def zoom(self, factor):
        if self.document is not None:
            self.scale = max(0.001, min(8, self.scale * factor))
            self.request_draw()

    def pan(self, dx, dy):
        if self.document is not None:
            self.center = (
                max(0, min(self.document.width, self.center[0] + dx / self.scale)),
                max(0, min(self.document.height, self.center[1] + dy / self.scale)),
            )
            self.request_draw()

    def start_drag(self, event):
        self.canvas.focus_set()
        self._drag = (event.x, event.y)

    def drag(self, event):
        if self._drag is not None:
            self.pan(self._drag[0] - event.x, self._drag[1] - event.y)
            self._drag = (event.x, event.y)

    def request_draw(self):
        if not self._closed and self.document is not None and self._draw_after is None:
            self._draw_after = self.after_idle(self.draw)

    def draw(self):
        self._draw_after = None
        if self._closed or self.document is None:
            return
        self._photo = None
        self.canvas.delete("all")
        self._job = (
            self.worker.submit(
                "image_render", self.document, self.center, self.scale, self.dimensions()
            ),
            "image_render",
        )
        self.status.set("Rendering image viewport…")

    def poll(self):
        if self._closed:
            return
        result = self.worker.poll()
        if result is not None and self._job == result[:2] and self.permission.get():
            _, kind, value, error = result
            self._job = None
            if error:
                self.status.set(error)
            elif kind == "image_open":
                self.document = value
                self._buttons()
                self.fit()
            elif kind == "image_render":
                try:
                    self._photo = tk.PhotoImage(master=self.canvas, data=value, format="png")
                    self.canvas.create_image(
                        0, 0, image=self._photo, anchor="nw", tags="reference-image"
                    )
                    doc = self.document
                    self.status.set(
                        f"{doc.name} · {doc.format} · {doc.width:,} × {doc.height:,} pixels · "
                        f"{self.scale * 100:.1f}% pixel zoom. First page/frame only. Uncalibrated reference."
                    )
                except tk.TclError:
                    self.status.set("The decoded image viewport could not be displayed.")
        self._after = self.after(60, self.poll)

    def close(self):
        if self._closed:
            return
        self.clear()
        self._closed = True
        self.worker.close()
        if self._after is not None:
            self.after_cancel(self._after)
            self._after = None

    def destroy(self):
        self.close()
        super().destroy()


def open_image_map(parent):
    window = tk.Toplevel(parent)
    window.title("FieldForge · Map image reference — uncalibrated")
    window.geometry("1080x780")
    window.minsize(940, 640)
    frame = ImageMapFrame(window)
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    return window, frame
