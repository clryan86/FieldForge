"""Saved-track review over explicitly selected offline map tiles.

The receiver and household database are not accessed. PNG decoding stays on Tk's
thread; a single non-Tk worker reads selected files and accepts only current work.
"""

from __future__ import annotations

import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from .map_jobs import LatestMapReader
from .mbtiles import MAX_LAT
from .mercator import (
    MercatorView,
    fit_mercator,
    map_display_segments,
    project_mercator_paths,
    visible_cells,
)
from .review_map import View
from .review_ui import ReviewFrame


class LocalMapReviewFrame(ReviewFrame):
    def __init__(self, parent):
        self.map_pack = None
        self._map_reader = None
        self._map_after = None
        self._map_loading = False
        self._frame_key = self._requested_key = None
        self._tiles = {}
        self._images = {}
        self._decode_errors = set()
        self._map_task = None
        self._map_cells = ()
        super().__init__(parent)
        self._coarse_base_text = self.base_label.cget("text")
        # Insert a map control panel without changing the inherited GPX controls.
        for child in self.grid_slaves():
            row = int(child.grid_info()["row"])
            if row >= 6:
                child.grid_configure(row=row + 1)
        self.rowconfigure(7, weight=0)
        self.rowconfigure(8, weight=1)
        panel = ttk.LabelFrame(
            self, text="Local map layer — optional, read-only, no downloads", padding=(10, 5)
        )
        panel.grid(row=6, column=0, sticky="ew", pady=(7, 0))
        self.map_trust = tk.BooleanVar(value=False)
        self.map_status = tk.StringVar(
            value="No local map selected. Bundled coastline overview only."
        )
        self.map_trust_check = ttk.Checkbutton(
            panel,
            text="I trust the local map file and have permission to use it. Unchecking closes the map.",
            variable=self.map_trust,
        )
        self.map_trust_check.pack(anchor="w")
        actions = ttk.Frame(panel)
        actions.pack(fill="x", pady=4)
        self.open_map_button = ttk.Button(
            actions, text="Open local MBTiles…", command=self.choose_map
        )
        self.demo_map_button = ttk.Button(
            actions, text="Load fictional test map", command=self.example_map
        )
        self.close_map_button = ttk.Button(actions, text="Close map", command=self.close_map)
        self.pack_start_button = ttk.Button(actions, text="Pack start", command=self.pack_start)
        self.map_details_button = ttk.Button(
            actions, text="Map details / rights", command=self.map_details
        )
        for button in (
            self.open_map_button,
            self.demo_map_button,
            self.close_map_button,
            self.pack_start_button,
            self.map_details_button,
        ):
            button.pack(side="left", padx=(0, 6))
        ttk.Label(actions, text="Zoom").pack(side="left", padx=(5, 3))
        self.map_zoom = ttk.Combobox(actions, state="disabled", width=4)
        self.map_zoom.pack(side="left")
        self.map_zoom.bind("<<ComboboxSelected>>", self._choose_zoom)
        # Reserve message space: changing text height must not resize the canvas,
        # which would otherwise request a new tile frame and change the text again.
        status_box = ttk.Frame(panel, height=54)
        status_box.pack(fill="x")
        status_box.pack_propagate(False)
        self.map_status_label = ttk.Label(
            status_box, textvariable=self.map_status, wraplength=950, anchor="nw"
        )
        self.map_status_label.pack(fill="both", expand=True)
        footer = self.render_label.master
        self.render_label.destroy()
        render_box = ttk.Frame(footer, height=54)
        render_box.pack(fill="x", before=self.base_label)
        render_box.pack_propagate(False)
        self.render_label = ttk.Label(
            render_box, textvariable=self.render_notice, wraplength=950, anchor="nw"
        )
        self.render_label.pack(fill="both", expand=True)
        self.map_trust.trace_add("write", self._map_permission_changed)
        self.world_button.configure(text="World overview / close map")
        self._map_reader = LatestMapReader()
        self._map_buttons()
        self._poll_maps()

    def _map_buttons(self):
        permitted = self.map_trust.get()
        for button in (self.open_map_button, self.demo_map_button):
            button.configure(state="normal" if permitted else "disabled")
        for button in (self.pack_start_button, self.map_details_button):
            button.configure(state="normal" if self.map_pack else "disabled")
        self.close_map_button.configure(
            state="normal" if self.map_pack or self._map_loading else "disabled"
        )
        self.map_zoom.configure(
            state="readonly" if self.map_pack else "disabled",
            values=self.map_pack.levels if self.map_pack else (),
        )
        self.map_zoom.set(
            str(self.view.level) if self.map_pack and isinstance(self.view, MercatorView) else ""
        )

    def _map_permission_changed(self, *_):
        if not self.map_trust.get():
            self.close_map()
        self._map_buttons()

    def choose_map(self):
        if not self.map_trust.get():
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="Open a trusted, closed local map pack",
            filetypes=[("PNG/JPEG/WebP MBTiles", "*.mbtiles")],
        )
        if path:
            self.start_map(path)  # Trust is checked again after the modal dialog.

    def example_map(self):
        return self.start_map(Path(__file__).parent / "data" / "FICTIONAL-MAP.mbtiles")

    def start_map(self, path):
        if self._closed or not self.map_trust.get():
            if not self._closed:
                self.map_status.set("Confirm map trust and permission first. Nothing was read.")
            return False
        self.close_map()
        self._map_loading = True
        token = self._map_reader.submit("open", path)
        self._map_task = (token, "open", None)
        self.map_status.set("Reading selected local map. Previous map cleared; no network request.")
        self._map_buttons()
        return True

    def close_map(self):
        if self._map_reader:
            self._map_reader.cancel()
        self.map_pack = None
        self._map_task = None
        self._map_loading = False
        self._frame_key = self._requested_key = None
        self._tiles = {}
        self._images = {}
        self._decode_errors = set()
        self._map_cells = ()
        self.view = View()
        if hasattr(self, "map_status"):
            self.map_status.set("Local map closed. Its file is unchanged; GPX review is separate.")
            self.base_label.configure(text=self._coarse_base_text)
            self._map_buttons()
        self._drag = None
        self.request_draw()

    def _poll_maps(self):
        if self._closed:
            return
        result = self._map_reader.poll()
        if result and self._map_task and result[0] == self._map_task[0] and self.map_trust.get():
            _, kind, value, error = result
            task = self._map_task
            self._map_task = None
            self._map_loading = False
            if error:
                self.close_map()
                self.map_status.set("Local map unavailable: " + error)
            elif kind == "open":
                self.map_pack = value
                self.view = MercatorView(*value.start)
                self._frame_key = self._requested_key = None
                self.map_status.set(f"Opened {value.name[:120]}. {value.start_notice}")
                self.base_label.configure(
                    text="Local raster map · Web Mercator; no polar coverage, routes, or current-condition checks.\n"
                    "Attribution / source (pack-supplied, unverified): "
                    + dict(value.metadata).get("attribution", "not supplied")[:400]
                    + " · Full metadata: Map details / rights."
                )
                if self._points:
                    self.fit()
                self._map_buttons()
                self.request_draw()
            elif kind == "tiles" and self.map_pack and task[2] == self._viewport_key():
                self._tiles = {tile.key: tile for tile in value}
                self._images = {}
                self._decode_errors = set()
                self._frame_key = task[2]
                self.request_draw()
        self._map_after = self.after(40, self._poll_maps)

    def _viewport_key(self):
        return (self.map_pack.identity, self.view, *self._dimensions()) if self.map_pack else None

    def pack_start(self):
        if self.map_pack:
            self.view = MercatorView(*self.map_pack.start)
            self._map_buttons()
            self.request_draw()

    def _choose_zoom(self, _event=None):
        if self.map_pack:
            try:
                level = int(self.map_zoom.get())
                if level not in self.map_pack.levels:
                    raise ValueError
            except ValueError:
                self._map_buttons()
                return
            self.view = MercatorView(self.view.longitude, self.view.latitude, level)
            self.request_draw()

    def fit(self):
        if not self.map_pack:
            return super().fit()
        if self._points:
            try:
                self.view = fit_mercator(
                    (p for _, _, p in self._points), *self._dimensions(), self.map_pack.levels
                )
            except ValueError as exc:
                self.map_status.set(str(exc))
            self._map_buttons()
            self.request_draw()

    def center_point(self):
        if not self.map_pack:
            return super().center_point()
        if self.inspect_point():
            point = self._points[self._selection][2]
            if not -MAX_LAT <= point.latitude <= MAX_LAT:
                self.map_status.set(
                    "Selected file point is outside Web Mercator. It was not moved to the map edge; use World overview."
                )
                return False
            self.view = MercatorView(point.longitude, point.latitude, self.view.level)
            self.request_draw()
            return True
        return False

    def zoom(self, factor):
        if not self.map_pack:
            return super().zoom(factor)
        if type(factor) not in (int, float) or not math.isfinite(factor) or factor <= 0:
            raise ValueError("Zoom factor must be positive and finite.")
        levels = self.map_pack.levels
        index = levels.index(self.view.level)
        step = 1 if factor > 1 else -1 if factor < 1 else 0
        level = levels[max(0, min(len(levels) - 1, index + step))]
        self.view = MercatorView(self.view.longitude, self.view.latitude, level)
        self._map_buttons()
        self.request_draw()

    def world(self):
        self.close_map()
        super().world()

    def clear(self):
        view = self.view
        super().clear()
        if self.map_pack:
            self.view = view
            self.request_draw()

    def _resize(self, event):
        super()._resize(event)
        if hasattr(self, "map_status_label"):
            self.map_status_label.configure(wraplength=max(400, event.width - 20))

    def _move_drag(self, event):
        try:
            super()._move_drag(event)
        except ValueError as exc:
            if self.map_pack:
                self.map_status.set(str(exc))
                self.request_draw()
            else:
                raise

    def draw(self):
        if not self.map_pack or not isinstance(self.view, MercatorView):
            return super().draw()
        if self._draw_after is not None:
            self.after_cancel(self._draw_after)
            self._draw_after = None
        if self._closed:
            return
        canvas = self.canvas
        canvas.delete("all")
        width, height = self._dimensions()
        try:
            cells = visible_cells(self.view, width, height)
        except ValueError as exc:
            # Cancel outstanding work as the previous coordinate frame is no longer displayed.
            self._map_reader.cancel()
            self._map_task = None
            self._requested_key = None
            self._images = {}
            self.map_status.set(str(exc))
            canvas.create_text(
                width / 2,
                height / 2,
                text=str(exc),
                width=max(100, width - 40),
                tags="viewport-error",
            )
            return
        self._map_cells = cells
        key = self._viewport_key()
        ready = self._frame_key == key
        if not ready and self._requested_key != key:
            self._images = {}
            self._tiles = {}
            self._decode_errors = set()
            self._frame_key = None
            wanted = tuple(dict.fromkeys(c.key for c in cells if c.key is not None))
            token = self._map_reader.submit("tiles", self.map_pack, wanted)
            self._map_task = (token, "tiles", key)
            self._requested_key = key
        counts = {"ready": 0, "missing": 0, "bad": 0, "outside": 0, "loading": 0}
        for cell in cells:
            x, y = cell.screen_x, cell.screen_y
            tile = self._tiles.get(cell.key) if ready else None
            state = "outside" if cell.key is None else tile.state if tile else "loading"
            photo = None
            if state == "ready":
                if cell.key not in self._images and cell.key not in self._decode_errors:
                    try:
                        photo = tk.PhotoImage(master=self, data=tile.data, format="png")
                        if photo.width() == 512:
                            photo = photo.subsample(2, 2)
                        if photo.width() != 256 or photo.height() != 256:
                            raise tk.TclError("Unsupported tile dimensions")
                        self._images[cell.key] = photo
                    except tk.TclError:
                        self._decode_errors.add(cell.key)
                photo = self._images.get(cell.key)
                if photo is None:
                    state = "bad"
            counts[state] += 1
            if state == "ready":
                canvas.create_image(x, y, image=photo, anchor="nw", tags="map-tile")
            else:
                message = {
                    "missing": "TILE NOT INSTALLED",
                    "bad": "UNREADABLE TILE",
                    "outside": "OUTSIDE PROJECTION",
                    "loading": "READING LOCAL MAP…",
                }[state]
                fill = {
                    "missing": "#ece8df",
                    "bad": "#f4dfdf",
                    "outside": "#d9dde0",
                    "loading": "#eef1f3",
                }[state]
                canvas.create_rectangle(
                    x,
                    y,
                    x + 256,
                    y + 256,
                    fill=fill,
                    outline="#b9c4c7",
                    tags=("tile-placeholder", state + "-tile"),
                )
                canvas.create_text(
                    x + 128,
                    y + 128,
                    text=message,
                    width=230,
                    fill="#4d555a",
                    font=("TkDefaultFont", 9, "bold"),
                    tags=state + "-label",
                )
        if ready:
            self._draw_history(width, height)
            self.map_status.set(
                f"{self.map_pack.name[:110]} · z{self.view.level} · visible cells: {counts['ready']} displayed, "
                f"{counts['missing']} missing, {counts['bad']} unreadable, {counts['outside']} outside projection. "
                "No other zoom or online fallback; dates and accuracy unverified."
            )
        else:
            self.map_status.set(
                f"Reading local tiles at z{self.view.level}. Old imagery cleared; no partial frame accepted."
            )
            self.render_notice.set(
                "Historical track overlay waits for the current local-map frame. GPX data remains in memory."
            )
        canvas.create_rectangle(0, 0, width, 33, fill="#f7f8f8", outline="", tags="map-header")
        canvas.create_text(
            12, 16, text="N ↑", anchor="w", fill="#253f56", font=("TkDefaultFont", 11, "bold")
        )
        canvas.create_text(
            width - 12,
            16,
            text="GPX HISTORY — NOT LIVE / NOT NAVIGATION",
            anchor="e",
            fill="#253f56",
            font=("TkDefaultFont", 10, "bold"),
        )

    def _draw_history(self, width, height):
        canvas = self.canvas
        track = self.document.tracks[self.track_box.current()] if self.document else None
        display = map_display_segments(track.segments) if track else ()
        for segment_id, segment in enumerate(display):
            coords = tuple((p.longitude, p.latitude) for p in segment)
            for path in project_mercator_paths(coords, self.view, width, height):
                values = [v for p in path for v in p]
                canvas.create_line(*values, fill="white", width=5, tags="track-halo")
                canvas.create_line(
                    *values,
                    fill="#a14918",
                    width=2.5,
                    tags=("track-line", f"review-segment-{segment_id}"),
                )
            for point, tag, shape in (
                (segment[0], "segment-start", "oval"),
                (segment[-1], "segment-end", "rectangle"),
            ):
                xy = self.view.position(point.longitude, point.latitude, width, height)
                if xy and 0 <= xy[0] <= width and 0 <= xy[1] <= height:
                    x, y = xy
                    getattr(canvas, "create_" + shape)(
                        x - 4,
                        y - 4,
                        x + 4,
                        y + 4,
                        outline="#8b4319",
                        fill="white",
                        width=2,
                        tags=tag,
                    )
        if self._points:
            point = self._points[self._selection][2]
            xy = self.view.position(point.longitude, point.latitude, width, height)
            if xy and 0 <= xy[0] <= width and 0 <= xy[1] <= height:
                x, y = xy
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
            shown = sum(map(len, display))
            polar = sum(not -MAX_LAT <= p.latitude <= MAX_LAT for _, _, p in self._points)
            detail = " SIMPLIFIED PREVIEW." if shown < track.point_count else ""
            self.render_notice.set(
                f"Display samples {shown:,}/{track.point_count:,} points in {len(display):,} display runs ({len(track.segments):,} original file segments); "
                f"{polar:,} full-track points outside projection; others may be off-screen. Circle=run start; square=run end. Gaps are not joined.{detail}"
            )
        else:
            self.render_notice.set(
                "Local map only. No saved track displayed and no live location requested."
            )

    def map_details(self):
        if not self.map_pack:
            return None
        window = tk.Toplevel(self)
        window.title("Local map metadata — unverified pack-supplied text")
        window.geometry("800x520")
        text = tk.Text(window, wrap="word", padx=12, pady=12)
        scrollbar = ttk.Scrollbar(window, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        header = (
            "LOCAL FILE — READ ONLY\nMetadata does not prove accuracy, freshness, rights, or authenticity.\n"
            "URLs and HTML below are inert text, not opened or executed. Missing rights are not assumed.\n"
            f"Observed zoom levels: {self.map_pack.levels}\n{self.map_pack.start_notice}\n\n"
        )
        text.insert("1.0", header + "\n\n".join(f"{k}\n{v}" for k, v in self.map_pack.metadata))
        text.configure(state="disabled")
        return window

    def close(self):
        if self._closed:
            return
        if self._map_reader:
            self._map_reader.close()
        if self._map_after is not None:
            self.after_cancel(self._map_after)
            self._map_after = None
        self._images = {}
        self._tiles = {}
        self.map_pack = None
        self._map_task = None
        super().close()


def main():
    from .places_map_ui import main as places_main

    places_main()


if __name__ == "__main__":
    main()
