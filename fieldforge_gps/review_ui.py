"""Read-only saved-trip viewer. Parsing runs off Tk; no receiver Session is used."""

from __future__ import annotations

import queue
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from .gpx_review import read_gpx
from .review_map import (
    View,
    connected_length_m,
    fit_points,
    load_overview,
    project_paths,
    sample_segments,
)
from .tk_cleanup import TkCleanupMixin

BANNER = "GPX FILE — NOT LIVE · READ-ONLY REVIEW"


def _read_worker(path, cancel, output):
    """A worker owns no Tk objects. A single result is published only at completion."""
    try:
        result = read_gpx(path, consent=True, wgs84_confirmed=True, cancel=cancel)
        output.put((result, None))
    except (ValueError, OSError, RuntimeError) as exc:
        output.put((None, str(exc)))
    except Exception:
        # Keep an unexpected parser failure from leaving controls permanently busy.
        # Do not expose private paths or file contents in a traceback in the UI.
        output.put((None, "Unexpected GPX reader failure. Previous review was not replaced."))


class ReviewFrame(TkCleanupMixin, ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        self.pack(fill="both", expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(7, weight=1)
        self.document = None
        self.view = View()
        self._points = ()
        self._display = ()
        self._selection = 0
        self._closed = False
        self._after = None
        self._draw_after = None
        self._drag = None
        self._busy = False
        self._cancel = None
        self._queue = None
        self._thread = None
        self._overview_error = ""
        try:
            self._overview = load_overview()
        except (ValueError, OSError) as exc:
            self._overview = ()
            self._overview_error = str(exc)
        self.consent = tk.BooleanVar(value=False)
        self.datum = tk.BooleanVar(value=False)
        self.status = tk.StringVar(
            value="Choose a saved GPX file. Nothing is opened or recorded automatically."
        )
        self.counts = tk.StringVar(value="No saved track selected.")
        self.render_notice = tk.StringVar(
            value="No track displayed. Coastline overview only; no street or terrain coverage."
        )
        self.point_detail = tk.StringVar(
            value="No recorded point selected. This workspace never displays a live position."
        )
        self.provenance = tk.StringVar(value="No private history loaded.")
        self.point_number = tk.StringVar(value="1")
        style = ttk.Style(self)
        style.configure("Review.Title.TLabel", font=("TkDefaultFont", 23, "bold"))
        style.configure(
            "Review.Banner.TLabel", font=("TkDefaultFont", 11, "bold"), foreground="#8b4d16"
        )
        title = ttk.Frame(self)
        title.grid(row=0, column=0, sticky="ew")
        self.title_label = ttk.Label(
            title, text="FieldForge · Saved trips", style="Review.Title.TLabel"
        )
        self.title_label.pack(side="left")
        self.source_label = ttk.Label(
            title, text="OFFLINE / GPX REVIEW", font=("TkDefaultFont", 9, "bold")
        )
        self.source_label.pack(side="right")
        self.banner_label = ttk.Label(self, text=BANNER, style="Review.Banner.TLabel")
        self.banner_label.grid(row=1, column=0, sticky="w", pady=(5, 10))
        permissions = ttk.Frame(self)
        permissions.grid(row=2, column=0, sticky="ew")
        self.datum_check = ttk.Checkbutton(
            permissions, text="The selected GPX file uses WGS84 coordinates.", variable=self.datum
        )
        self.datum_check.pack(anchor="w")
        self.consent_check = ttk.Checkbutton(
            permissions,
            text="Inspect private history in memory only. Clearing either box clears this review, not the source file.",
            variable=self.consent,
        )
        self.consent_check.pack(anchor="w", pady=(2, 4))
        actions = ttk.Frame(self)
        actions.grid(row=3, column=0, sticky="ew", pady=(3, 6))
        self.open_button = ttk.Button(actions, text="Open saved GPX…", command=self.choose_file)
        self.example_button = ttk.Button(
            actions, text="Load fictional example", command=self.example
        )
        self.cancel_button = ttk.Button(actions, text="Cancel read", command=self.cancel_read)
        self.clear_button = ttk.Button(actions, text="Clear review", command=self.clear)
        for button in (
            self.open_button,
            self.example_button,
            self.cancel_button,
            self.clear_button,
        ):
            button.pack(side="left", padx=(0, 8))
        self.status_label = ttk.Label(self, textvariable=self.status, wraplength=920)
        self.status_label.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        selection = ttk.LabelFrame(
            self,
            text="Select a recorded track — file-defined segments remain separate",
            padding=(10, 7),
        )
        selection.grid(row=5, column=0, sticky="ew")
        selection.columnconfigure(0, weight=1)
        self.track_box = ttk.Combobox(selection, state="disabled")
        self.track_box.grid(row=0, column=0, sticky="ew")
        self.track_box.bind("<<ComboboxSelected>>", self._track_selected)
        self.counts_label = ttk.Label(selection, textvariable=self.counts, wraplength=910)
        self.counts_label.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        toolbar = ttk.Frame(self)
        toolbar.grid(row=6, column=0, sticky="ew", pady=7)
        self.fit_button = ttk.Button(toolbar, text="Fit selected track", command=self.fit)
        self.world_button = ttk.Button(toolbar, text="World overview", command=self.world)
        self.plus_button = ttk.Button(toolbar, text="Zoom +", command=lambda: self.zoom(2))
        self.minus_button = ttk.Button(toolbar, text="Zoom −", command=lambda: self.zoom(0.5))
        for button in (self.fit_button, self.world_button, self.plus_button, self.minus_button):
            button.pack(side="left", padx=(0, 7))
        ttk.Label(toolbar, text="Drag to pan · wheel to zoom · north is up").pack(side="right")
        self.canvas = tk.Canvas(
            self,
            background="#f0f5f6",
            highlightthickness=1,
            highlightbackground="#a6b8bf",
            height=330,
        )
        self.canvas.grid(row=7, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._move_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda event: setattr(self, "_drag", None))
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda event: self.zoom(1.3))
        self.canvas.bind("<Button-5>", lambda event: self.zoom(1 / 1.3))
        inspect = ttk.Frame(self)
        inspect.grid(row=8, column=0, sticky="ew", pady=(7, 2))
        inspect.columnconfigure(4, weight=1)
        ttk.Label(inspect, text="Recorded point").grid(row=0, column=0)
        self.point_spin = ttk.Spinbox(
            inspect,
            from_=1,
            to=1,
            width=8,
            textvariable=self.point_number,
            command=self.inspect_point,
        )
        self.point_spin.grid(row=0, column=1, padx=7)
        self.point_spin.bind("<Return>", lambda event: self.inspect_point())
        self.inspect_button = ttk.Button(inspect, text="Inspect", command=self.inspect_point)
        self.inspect_button.grid(row=0, column=2, padx=(0, 7))
        self.center_button = ttk.Button(
            inspect, text="Center on file point", command=self.center_point
        )
        self.center_button.grid(row=0, column=3)
        self.point_label = ttk.Label(inspect, textvariable=self.point_detail, wraplength=920)
        self.point_label.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(5, 0))
        footer = ttk.Frame(self)
        footer.grid(row=9, column=0, sticky="ew", pady=(5, 0))
        self.render_label = ttk.Label(footer, textvariable=self.render_notice, wraplength=920)
        self.render_label.pack(anchor="w", fill="x")
        self.base_label = ttk.Label(
            footer,
            text="Natural Earth-derived, low-resolution land outlines · source vintage unknown · no roads, terrain, or turn instructions.\nEquirectangular display: shapes/distances are distorted. A recorded track is not evidence of a safe or accessible route.",
            wraplength=920,
        )
        self.base_label.pack(anchor="w", fill="x", pady=(4, 3))
        self.provenance_label = ttk.Label(
            footer, textvariable=self.provenance, font=("TkDefaultFont", 8), wraplength=920
        )
        self.provenance_label.pack(anchor="w", fill="x")
        self.datum.trace_add("write", self._permission_changed)
        self.consent.trace_add("write", self._permission_changed)
        self.bind("<Destroy>", self._destroyed, add=True)
        self._buttons()
        self._poll()
        self.request_draw()

    def _permission_changed(self, *_):
        if not self.consent.get() or not self.datum.get():
            self.clear()
        self._buttons()

    def _buttons(self):
        permitted = self.consent.get() and self.datum.get()
        for button in (self.open_button, self.example_button):
            button.configure(state="normal" if permitted and not self._busy else "disabled")
        self.cancel_button.configure(state="normal" if self._busy else "disabled")
        self.track_box.configure(state="readonly" if self.document else "disabled")
        for button in (self.fit_button, self.point_spin, self.inspect_button, self.center_button):
            button.configure(state="normal" if self._points else "disabled")

    def choose_file(self):
        if not self.consent.get() or not self.datum.get():
            self.status.set("Confirm WGS84 and private-history inspection before opening a file.")
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="Review a saved GPX track — NOT LIVE",
            filetypes=[("GPX tracks", "*.gpx"), ("All files", "*")],
        )
        if path:
            self.start_read(path)  # Rechecks permission after the modal dialog.

    def example(self):
        self.start_read(Path(__file__).parent / "data" / "FICTIONAL-REVIEW.gpx")

    def start_read(self, path):
        if self._closed:
            return False
        if not self.consent.get() or not self.datum.get():
            self.status.set("Confirm WGS84 and private-history inspection first. Nothing was read.")
            return False
        if self._busy:
            self.status.set(
                "A file is already being checked. Cancel it or let it finish before another read."
            )
            return False
        self._busy = True
        self._cancel = threading.Event()
        self._queue = queue.Queue(maxsize=1)
        self.status.set(
            "Checking selected GPX file — NOT LIVE. Previous review stays visible until success."
        )
        self._thread = threading.Thread(
            target=_read_worker,
            args=(path, self._cancel, self._queue),
            name="FieldForge-GPX-review",
            daemon=True,
        )
        self._thread.start()
        self._buttons()
        return True

    def cancel_read(self):
        if self._busy:
            self._cancel.set()
            self.status.set(
                "Cancelling read. Previous review is unchanged; no partial track will be displayed."
            )

    def clear(self):
        self.cancel_read()
        self.document = None
        self._points = self._display = ()
        self._selection = 0
        self.track_box.configure(values=())
        self.track_box.set("")
        self.point_number.set("1")
        self.point_spin.configure(to=1)
        self.counts.set("No saved track selected.")
        self.point_detail.set(
            "No recorded point selected. This workspace never displays a live position."
        )
        self.provenance.set(
            "Review cleared from memory; original GPX and exported files were not changed. Not secure erasure."
        )
        self.status.set("Review cleared. No saved files or live receiver settings were changed.")
        self.view = View()
        self._buttons()
        self.request_draw()

    def _poll(self):
        if self._closed:
            return
        if self._busy:
            try:
                result, error = self._queue.get_nowait()
            except queue.Empty:
                pass
            else:
                cancelled = self._cancel.is_set() or not self.datum.get() or not self.consent.get()
                self._busy = False
                self._thread = self._queue = self._cancel = None
                if cancelled:
                    self.status.set("GPX read cancelled. No partial import was displayed.")
                elif error:
                    self.status.set("GPX not loaded: " + error)
                else:
                    self._publish(result)
                self._buttons()
        self._after = self.after(40, self._poll)

    def _publish(self, document):
        self.document = document
        self.track_box.configure(
            values=tuple(f"{i}. {track.name}" for i, track in enumerate(document.tracks, 1))
        )
        self.track_box.current(0)
        self.provenance.set(
            f"Source SHA-256: {document.source_sha256} · {document.source_bytes:,} bytes · not a proof of authenticity"
        )
        self.status.set(
            f"GPX FILE — NOT LIVE. Loaded {len(document.tracks):,} tracks / {document.point_count:,} points. "
            f"Not displayed: {document.ignored_waypoints:,} waypoints, {document.ignored_routes:,} routes, "
            f"{document.empty_tracks:,} empty tracks, {document.empty_segments:,} empty segments."
        )
        self._track_selected()

    def _track_selected(self, event=None):
        if not self.document:
            return
        index = self.track_box.current()
        if not 0 <= index < len(self.document.tracks):
            return
        track = self.document.tracks[index]
        self._points = tuple(
            (s, i, point)
            for s, segment in enumerate(track.segments, 1)
            for i, point in enumerate(segment, 1)
        )
        self._display = sample_segments(track.segments)
        self._selection = 0
        self.point_number.set("1")
        self.point_spin.configure(to=len(self._points))
        self.counts.set(
            f"{track.point_count:,} points · {len(track.segments):,} file segments · "
            f"Approx. connected-point length: {connected_length_m(track.segments) / 1000:,.3f} km (file gaps excluded; not road distance)"
        )
        self.inspect_point()
        self._buttons()
        self.fit()

    def inspect_point(self):
        if not self._points:
            return False
        try:
            value = self.point_number.get()
            if not re.fullmatch(r"[0-9]{1,5}", value):
                raise ValueError
            index = int(value) - 1
            if not 0 <= index < len(self._points):
                raise ValueError
        except ValueError:
            self.point_detail.set(
                f"Enter a recorded point number between 1 and {len(self._points):,}. Selection is unchanged."
            )
            return False
        self._selection = index
        segment, inside, point = self._points[index]
        elevation = (
            "not supplied" if point.elevation_m is None else f"{point.elevation_m:g} m (file value)"
        )
        time_text = point.time_text or "not supplied"
        if point.time_text and not re.search(r"(?:Z|[+-][0-9]{2}:[0-9]{2})$", point.time_text):
            time_text += " (timezone not supplied; NOT assumed UTC)"
        self.point_detail.set(
            f"FILE POINT {index + 1:,} · segment {segment:,}, point {inside:,} · latitude {point.latitude:.8f} · longitude {point.longitude:.8f}\n"
            f"Elevation: {elevation} · Time: {time_text} · recorded data, NOT current position"
        )
        self.request_draw()
        return True

    def center_point(self):
        if self.inspect_point():
            point = self._points[self._selection][2]
            self.view = View(point.longitude, point.latitude, self.view.span)
            self.request_draw()

    def _dimensions(self):
        return max(100, self.canvas.winfo_width()), max(100, self.canvas.winfo_height())

    def fit(self):
        if self._points:
            self.view = fit_points((p for _, _, p in self._points), *self._dimensions())
            self.request_draw()

    def world(self):
        self.view = View()
        self.request_draw()

    def zoom(self, factor):
        self.view = self.view.zoom(factor)
        self.request_draw()

    def _wheel(self, event):
        if event.delta:
            self.zoom(1.3 if event.delta > 0 else 1 / 1.3)

    def _start_drag(self, event):
        self._drag = (event.x, event.y, self.view)

    def _move_drag(self, event):
        if self._drag:
            x, y, original = self._drag
            self.view = original.pan(event.x - x, event.y - y, *self._dimensions())
            self.request_draw()

    def _resize(self, event):
        for label in (
            self.status_label,
            self.counts_label,
            self.point_label,
            self.render_label,
            self.base_label,
            self.provenance_label,
        ):
            label.configure(wraplength=max(400, event.width - 10))
        self.request_draw()

    def request_draw(self):
        if not self._closed and self._draw_after is None:
            self._draw_after = self.after(20, self.draw)

    def draw(self):
        if self._draw_after is not None:
            self.after_cancel(self._draw_after)
            self._draw_after = None
        if self._closed:
            return
        canvas = self.canvas
        canvas.delete("all")
        width, height = self._dimensions()
        scale = self.view.scale(width, height)
        for lat in range(-90, 91, 30):
            y = height / 2 - (lat - self.view.latitude) * scale
            if 0 <= y <= height:
                canvas.create_line(0, y, width, y, fill="#d5e1e4", tags="graticule")
                canvas.create_text(
                    5, y + 3, text=f"{lat}°", anchor="nw", fill="#657d84", font=("TkDefaultFont", 8)
                )
        for lon in range(-180, 180, 30):
            x, _ = self.view.position(lon, 0, width, height)
            if 0 <= x <= width:
                canvas.create_line(x, 0, x, height, fill="#d5e1e4", tags="graticule")
                canvas.create_text(
                    x + 3,
                    height - 5,
                    text=f"{lon}°",
                    anchor="sw",
                    fill="#657d84",
                    font=("TkDefaultFont", 8),
                )
        for ring in self._overview:
            for path in project_paths(ring, self.view, width, height):
                canvas.create_line(
                    *[v for p in path for v in p], fill="#608476", width=1.2, tags="coastline"
                )
        for segment_id, segment in enumerate(self._display):
            coords = tuple((p.longitude, p.latitude) for p in segment)
            for path in project_paths(coords, self.view, width, height):
                canvas.create_line(
                    *[v for p in path for v in p],
                    fill="#b65c24",
                    width=2.5,
                    tags=("track-line", f"review-segment-{segment_id}"),
                )
            x, y = self.view.position(segment[0].longitude, segment[0].latitude, width, height)
            if 0 <= x <= width and 0 <= y <= height:
                canvas.create_oval(
                    x - 4,
                    y - 4,
                    x + 4,
                    y + 4,
                    outline="#8b4319",
                    fill="white",
                    width=2,
                    tags="segment-start",
                )
            x, y = self.view.position(segment[-1].longitude, segment[-1].latitude, width, height)
            if 0 <= x <= width and 0 <= y <= height:
                canvas.create_rectangle(
                    x - 3, y - 3, x + 3, y + 3, outline="#8b4319", width=2, tags="segment-end"
                )
        if self._points:
            point = self._points[self._selection][2]
            x, y = self.view.position(point.longitude, point.latitude, width, height)
            if 0 <= x <= width and 0 <= y <= height:
                canvas.create_oval(
                    x - 8,
                    y - 8,
                    x + 8,
                    y + 8,
                    outline="#253f56",
                    width=2,
                    tags="selected-file-point",
                )
                canvas.create_text(
                    x + 12,
                    y - 12,
                    text=f"FILE POINT {self._selection + 1}",
                    anchor="sw",
                    fill="#253f56",
                    font=("TkDefaultFont", 9, "bold"),
                    tags="file-point-label",
                )
            track = self.document.tracks[self.track_box.current()]
            shown = sum(map(len, self._display))
            detail = (
                " SIMPLIFIED PREVIEW; original file unchanged." if shown < track.point_count else ""
            )
            self.render_notice.set(
                f"Display uses {shown:,}/{track.point_count:,} points in {len(self._display):,}/{len(track.segments):,} segments; some may be off-screen. "
                f"Circle = segment start; square = end. Gaps are not joined.{detail}"
            )
        else:
            self.render_notice.set(
                "No track displayed. Coastline overview only; no street or terrain coverage."
            )
        canvas.create_text(
            12, 12, text="N ↑", anchor="nw", fill="#253f56", font=("TkDefaultFont", 11, "bold")
        )
        canvas.create_text(
            width - 12,
            12,
            text="HISTORY — NOT NAVIGATION",
            anchor="ne",
            fill="#253f56",
            font=("TkDefaultFont", 10, "bold"),
        )
        if self._overview_error:
            canvas.create_text(
                width / 2,
                height - 28,
                text="COASTLINE LAYER UNAVAILABLE — " + self._overview_error,
                width=width - 40,
                fill="#8b4319",
            )
        elif self.view.span < 20:
            canvas.create_text(
                width / 2,
                height - 20,
                text="Zoomed detail: coarse outline only. No local road / terrain detail loaded.",
                fill="#253f56",
            )

    def _destroyed(self, event):
        if event.widget is self:
            self.close()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._cancel:
            self._cancel.set()
        for after in (self._after, self._draw_after):
            if after is not None:
                self.after_cancel(after)
        self._after = self._draw_after = None
        self.document = None
        self._points = self._display = ()
        self._queue = None
        # Drop displayed private text too; this is not secure memory erasure.
        try:
            self.point_detail.set("")
            self.provenance.set("")
            self.counts.set("")
        except tk.TclError:
            pass


def open_review(parent):
    """Open an independent viewer: no receiver object, database or track mutation."""
    window = tk.Toplevel(parent)
    window.title("FieldForge · Saved GPX review — NOT LIVE")
    window.geometry("1120x860")
    window.minsize(980, 820)
    from .places_map_ui import PlacesMapReviewFrame

    window.geometry("1200x990")
    window.minsize(1020, 930)
    frame = PlacesMapReviewFrame(window)
    window.review = frame

    def close():
        frame.close()
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    return window


def main():
    from .local_map_ui import main as local_main

    local_main()


if __name__ == "__main__":
    main()
