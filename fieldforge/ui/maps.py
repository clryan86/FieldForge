"""Offline raster/vector MBTiles viewer with an explicitly selected planned route.

Tk owns rendering; workers only read bounded local data. External map files and
selected routes are never imported into the household database or snapshots.
No GPS, network, route calculation, downloads or automatic place writes.
"""

from __future__ import annotations

import base64
import sqlite3
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.navigation.map_view import MAX_LATITUDE, TILE_SIZE, Viewport
from fieldforge.navigation.mbtiles import (
    NOTICE,
    MapCancelled,
    MapPack,
    inspect_pack,
    read_frame,
    read_markers,
)
from fieldforge.navigation.places import coordinate, coordinate_text
from fieldforge.navigation.route_view import prepare_route, visible_route
from fieldforge.online.models import validate_route

_ERRORS = (OSError, ValueError, sqlite3.Error)


def _read_view(pack, view, database, cancel):
    frame = read_frame(pack, view, cancel=cancel)
    markers, problem = (), ""
    if database is not None:
        try:
            markers = read_markers(database)
        except _ERRORS as exc:
            problem = "Saved places unavailable: " + str(exc)
    if cancel.is_set():
        raise MapCancelled("Map request cancelled.")
    return frame, markers, problem


class MapsTab(ttk.Frame):
    def __init__(self, parent, database):
        super().__init__(parent, padding=16)
        self.database = database
        self.pack_info: MapPack | None = None
        self.view: Viewport | None = None
        self.frame = None
        self.markers = ()
        self.route = None
        self._route_geometry = None
        self._route_drawing = self._route_drawing_view = None
        self._images = []
        self._disposed = False
        self._generation = 0
        self._cancel = Event()
        self._future: Future | None = None
        self._poll_id = self._resize_id = None
        self._drag = None
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-map")
        self.busy = False
        self.source = tk.StringVar(value="No map open. Choose a trusted, locally stored MBTiles pack.")
        self.status = tk.StringVar(value="No maps are bundled or downloaded automatically. Your location is not requested.")
        self.pointer = tk.StringVar(value="Pointer coordinates appear only over a loaded map view.")
        self.attribution = tk.StringVar(value="Source attribution will appear here. Map accuracy and reuse rights are not verified.")
        self.zoom_choice = tk.StringVar()
        self.latitude = tk.StringVar()
        self.longitude = tk.StringVar()
        self.overlay = tk.BooleanVar(value=False)
        self.place_choice = tk.StringVar()
        self.route_status = tk.StringVar(value="No planned route selected.")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(6, weight=1)
        self.bind("<Destroy>", self._destroyed, add=True)
        ttk.Label(self, text="Offline Maps", font=("TkDefaultFont", 21, "bold")).grid(row=0, column=0, sticky="w")
        self.notice = ttk.Label(self, text=NOTICE, wraplength=1100, justify="left")
        self.notice.grid(row=1, column=0, sticky="ew", pady=(6, 10))
        files = ttk.Frame(self)
        files.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.open_button = ttk.Button(files, text="Open local map…", command=self.choose)
        self.open_button.pack(side="left")
        self.close_button = ttk.Button(files, text="Close map", command=self.close_map)
        self.close_button.pack(side="left", padx=6)
        self.info_button = ttk.Button(files, text="Map details / rights…", command=self.details)
        self.info_button.pack(side="left")
        self.source_label = ttk.Label(files, textvariable=self.source, wraplength=540, justify="left")
        self.source_label.pack(side="left", fill="x", expand=True, padx=(12, 0))
        nav = ttk.Frame(self)
        nav.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self.minus = ttk.Button(nav, text="−", width=3, command=lambda: self.change_zoom(-1))
        self.minus.pack(side="left")
        self.zoom_picker = ttk.Combobox(nav, textvariable=self.zoom_choice, values=(), width=4, state="readonly")
        self.zoom_picker.pack(side="left", padx=4)
        self.zoom_picker.bind("<<ComboboxSelected>>", lambda _: self.set_zoom())
        self.plus = ttk.Button(nav, text="+", width=3, command=lambda: self.change_zoom(1))
        self.plus.pack(side="left")
        self.home_button = ttk.Button(nav, text="Pack start", command=self.home)
        self.home_button.pack(side="left", padx=(8, 12))
        ttk.Label(nav, text="Center latitude").pack(side="left")
        self.lat_entry = ttk.Entry(nav, textvariable=self.latitude, width=13)
        self.lat_entry.pack(side="left", padx=4)
        ttk.Label(nav, text="Longitude").pack(side="left")
        self.lon_entry = ttk.Entry(nav, textvariable=self.longitude, width=13)
        self.lon_entry.pack(side="left", padx=4)
        self.go_button = ttk.Button(nav, text="Go", command=self.go)
        self.go_button.pack(side="left")
        self.lat_entry.bind("<Return>", lambda _: self.go())
        self.lon_entry.bind("<Return>", lambda _: self.go())
        self.reload_button = ttk.Button(nav, text="Refresh view", command=self.request_view)
        self.reload_button.pack(side="right")
        privacy = ttk.Frame(self)
        privacy.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        self.overlay_box = ttk.Checkbutton(privacy, text="Show saved places (private)", variable=self.overlay,
                                          command=self.request_view)
        self.overlay_box.pack(side="left")
        self.place_picker = ttk.Combobox(privacy, textvariable=self.place_choice, values=(), state="readonly", width=32)
        self.place_picker.pack(side="left", fill="x", expand=True, padx=8)
        self.center_button = ttk.Button(privacy, text="Center on chosen place", command=self.center_place)
        self.center_button.pack(side="left")
        route_bar = ttk.Frame(self)
        route_bar.grid(row=5, column=0, sticky="ew", pady=(0, 6))
        route_bar.columnconfigure(0, weight=1)
        self.route_label = ttk.Label(route_bar, textvariable=self.route_status, width=1, anchor="w")
        self.route_label.grid(row=0, column=0, sticky="ew")
        self.route_start_button = ttk.Button(route_bar, text="Route start", command=self.center_route)
        self.route_start_button.grid(row=0, column=1, padx=(6, 0))
        self.route_details_button = ttk.Button(route_bar, text="Route details…", command=self.route_details)
        self.route_details_button.grid(row=0, column=2, padx=6)
        self.clear_route_button = ttk.Button(route_bar, text="Clear route", command=self.clear_route)
        self.clear_route_button.grid(row=0, column=3)
        self.canvas = tk.Canvas(self, bg="#e3e8e5", highlightthickness=1, highlightbackground="#adbcb2", takefocus=True)
        self.canvas.grid(row=6, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self.resize)
        self.canvas.bind("<ButtonPress-1>", self.drag_start)
        self.canvas.bind("<B1-Motion>", self.drag_move)
        self.canvas.bind("<ButtonRelease-1>", self.drag_end)
        self.canvas.bind("<Motion>", self.motion)
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<Button-4>", lambda _: self.change_zoom(1))
        self.canvas.bind("<Button-5>", lambda _: self.change_zoom(-1))
        self.canvas.bind("<KeyPress>", self.key)
        # Stable-height status rows prevent wrapped loading/cursor text from
        # resizing the canvas and creating an endless tile-reload feedback loop.
        def fixed_label(row, height, variable):
            box = ttk.Frame(self, height=height)
            box.grid(row=row, column=0, sticky="ew", pady=(4, 0))
            box.pack_propagate(False)
            label = ttk.Label(box, textvariable=variable, wraplength=1100, justify="left")
            label.pack(anchor="nw", fill="x")
            return label

        self.pointer_label = fixed_label(7, 38, self.pointer)
        self.credit_label = fixed_label(8, 44, self.attribution)
        self.footer = fixed_label(9, 58, self.status)
        self.bind("<Configure>", self._wrap, add=True)
        self._blank("Open a local MBTiles pack to begin.\n\nRaster tiles and basic vector previews work offline. Publisher styles and labels are not applied to vector packs.\nNo internet, GPS or automatic download.\nDrag to pan; use + / − or the wheel to zoom.\nArrow keys pan when the map has focus.")
        self._buttons()

    def _wrap(self, event):
        if event.widget is self:
            for label in (self.notice, self.pointer_label, self.credit_label, self.footer):
                label.configure(wraplength=max(400, event.width - 40))
            self.source_label.configure(wraplength=max(230, event.width - 435))

    def _buttons(self):
        ready = self.pack_info is not None and self.view is not None
        for button in (self.close_button, self.info_button, self.home_button, self.go_button, self.reload_button,
                       self.lat_entry, self.lon_entry, self.overlay_box):
            button.configure(state="normal" if ready else "disabled")
        self.zoom_picker.configure(state="readonly" if ready else "disabled")
        self.minus.configure(state="normal" if ready and self.view.zoom > self.pack_info.zooms[0] else "disabled")
        self.plus.configure(state="normal" if ready and self.view.zoom < self.pack_info.zooms[-1] else "disabled")
        self.place_picker.configure(state="readonly" if ready and self.overlay.get() and self.markers else "disabled")
        self.center_button.configure(state="normal" if ready and self.overlay.get() and self.markers else "disabled")
        for button in (self.clear_route_button, self.route_details_button):
            button.configure(state="normal" if self.route is not None else "disabled")
        self.route_start_button.configure(state="normal" if ready and self._route_geometry is not None
                                          and self._route_geometry.start is not None else "disabled")
        self._update_route_label()

    def _update_route_label(self):
        if self.route is None:
            self.route_status.set("No planned route selected.")
            return
        title = self.route["title"]
        title = title[:44] + ("…" if len(title) > 44 else "")
        if self.pack_info is None or self.view is None:
            note = "open a local map"
        elif self.frame is None:
            note = "map loading" if self.busy else "map view unavailable"
        elif self._route_drawing is not None and self._route_drawing.limited:
            note = "display limit reached — zoom in"
        elif self._route_geometry.polar_points:
            note = f"{self._route_geometry.polar_points} polar point(s) hidden"
        elif self._route_drawing is not None and not self._route_drawing.visible_segments:
            endpoints = (self._route_geometry.start, self._route_geometry.end)
            visible = any(point is not None and self.view.locations(*point) for point in endpoints)
            note = "S start · E end" if visible else "outside this view — Route start"
        else:
            note = "S start · E end · planned only"
        # Put display limitations before the title so they remain visible even
        # in the minimum-width window with a long provider-supplied title.
        self.route_status.set(f"Planned route · {note} · {title} · {self.route['distance_m'] / 1000:.1f} km")

    def show_route(self, route):
        """Show a supplied plan using local geometry only.

        Validation finishes before replacing the current selection. The copied
        route remains selected across close/open, missing tiles and map errors;
        only clear_route removes it. With a map open, center on the actual first
        geometry vertex at the existing zoom. With no map, retain it and prompt
        for a local pack; the next opened map centers there. Nothing is saved,
        transmitted or added to receiver history by this method.
        """
        if self._disposed:
            return
        checked = validate_route(route)
        geometry = prepare_route(checked["geometry"])
        self.route, self._route_geometry = checked, geometry
        self._route_drawing = self._route_drawing_view = None
        if self.pack_info is None or self.view is None:
            self.status.set("Planned route ready. Open a local MBTiles pack to view it offline. "
                            "Showing a route keeps this selection for the session; use Save route to keep it after restarting.")
            if not self.busy:
                self._blank("Planned route ready.\nOpen a local MBTiles map to show it.\n"
                            "This is a stored plan, with no live guidance or location receiver.")
        elif geometry.start is not None:
            self.center_route()
        else:
            if self.frame is not None:
                self._draw_route(self.frame.view)
            self.status.set("Planned route selected. Its start is outside the Web Mercator latitude extent. "
                            "Polar vertices and adjoining segments are hidden; the original geometry is unchanged.")
        self._buttons()

    def clear_route(self):
        """Remove the session overlay without deleting or rewriting a saved plan."""
        self.route = self._route_geometry = None
        self._route_drawing = self._route_drawing_view = None
        self.canvas.delete("planned-route")
        if self.pack_info is None and not self.busy:
            self._blank("No map open.\nChoose Open local map… to read a compatible raster or vector MBTiles file.")
        self.status.set("Planned route overlay cleared. No saved route file was deleted or changed.")
        self._buttons()

    def center_route(self):
        if self._route_geometry is None or self.pack_info is None or self.view is None:
            return
        if self._route_geometry.start is None:
            self.status.set("The actual route start is outside the Web Mercator latitude extent; "
                            "no replacement start is invented.")
            return
        self._set_view(*self._route_geometry.start, self.view.zoom)

    def _draw_route(self, view):
        self.canvas.delete("planned-route")
        if self._route_geometry is None:
            return
        if self._route_drawing_view != view:
            self._route_drawing = visible_route(self._route_geometry, view)
            self._route_drawing_view = view
        for path in self._route_drawing.paths:
            coordinates = tuple(value for point in path for value in point)
            tags = ("mapcontent", "planned-route", "route-line")
            self.canvas.create_line(*coordinates, fill="white", width=6, capstyle="round",
                                    joinstyle="round", smooth=False, tags=tags)
            self.canvas.create_line(*coordinates, fill="#057fa3", width=3, capstyle="round",
                                    joinstyle="round", smooth=False, tags=tags)
        for label, point, color, tag in (("S", self._route_geometry.start, "#185b42", "route-start"),
                                         ("E", self._route_geometry.end, "#234f92", "route-end")):
            if point is None:
                continue
            for x, y in view.locations(*point):
                tags = ("mapcontent", "planned-route", tag)
                self.canvas.create_oval(x - 10, y - 10, x + 10, y + 10, fill=color,
                                        outline="white", width=2, tags=tags)
                self.canvas.create_text(x, y, text=label, fill="white",
                                        font=("TkDefaultFont", 10, "bold"), tags=tags)

    def _blank(self, text):
        self.canvas.delete("all")
        self._images.clear()
        self.frame = None
        self._drag = None
        self.canvas.create_text(max(1, self.canvas.winfo_width()) / 2, max(1, self.canvas.winfo_height()) / 2,
                                text=text, width=max(250, self.canvas.winfo_width() - 60), justify="center",
                                font=("TkDefaultFont", 13), fill="#2b4938", tags="placeholder")

    def _stop_request(self):
        self._generation += 1
        self._cancel.set()
        if self._future is not None:
            self._future.cancel()
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        self.busy = False

    def _start(self, operation, function, *args):
        self._stop_request()
        self._cancel = Event()
        self.busy = True
        self._future = self._worker.submit(function, *args, cancel=self._cancel)
        self._poll_id = self.after(40, self._poll, self._future, operation, self._generation)

    def choose(self):
        path = filedialog.askopenfilename(parent=self, title="Open a trusted MBTiles pack",
                                          filetypes=[("MBTiles map", "*.mbtiles")])
        if path:
            if messagebox.askyesno("Open a trusted offline map?", "Only open a map pack you trust and have permission to use. "
                                   "This build supports flat, indexed PNG/JPEG/WebP raster MBTiles and PBF vector MBTiles with a basic preview style. Publisher styles, sprites, fonts and labels are not applied. "
                                   "No malware, accuracy or route-safety check is performed. The file stays external to your database backups. Continue?",
                                   parent=self):
                self.open_path(path)

    def open_path(self, path):
        """Called after the file picker/trust confirmation; tests use synthetic trusted packs."""
        if self._disposed:
            return
        self.close_map()
        self.source.set("Opening local map…")
        self.status.set("Reading map metadata and observed zoom levels; nothing is downloaded or copied into your database.")
        self._blank("Opening trusted map pack…")
        self._start("open", inspect_pack, path)

    def close_map(self):
        self._stop_request()
        self.pack_info = self.view = None
        self.markers = ()
        self.overlay.set(False)
        self.place_picker.configure(values=())
        self.place_choice.set("")
        self.zoom_picker.configure(values=())
        self.zoom_choice.set("")
        self.latitude.set("")
        self.longitude.set("")
        self.source.set("No map open.")
        self.attribution.set("Map packs are separate files. Database backups do not contain them.")
        self.pointer.set("No map coordinates available.")
        self.status.set("Closed map view. No map file or saved-place record was deleted or changed."
                        + (" Planned route retained; open a local map to show it again." if self.route else ""))
        self._blank("No map open.\nChoose Open local map… to read a compatible raster or vector MBTiles file.")
        self._buttons()

    def _dimensions(self):
        return max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())

    def _set_view(self, latitude, longitude, zoom):
        try:
            self.view = Viewport(latitude, longitude, zoom, *self._dimensions())
            self.latitude.set(coordinate_text(latitude))
            self.longitude.set(coordinate_text(longitude))
            self.zoom_choice.set(str(zoom))
            self.request_view()
        except ValueError as exc:
            self._stop_request()
            self._blank(str(exc))
            self.status.set(str(exc))

    def request_view(self):
        if self._disposed or self.pack_info is None or self.view is None:
            return
        self.markers = ()
        self.place_picker.configure(values=())
        self._blank("Loading local tiles…\nNo remote fallback is used.")
        self.pointer.set("Pointer coordinates unavailable while tiles load.")
        self.status.set("Reading the current viewport. Superseded requests are discarded.")
        self._buttons()
        self._start("frame", _read_view, self.pack_info, self.view, self.database if self.overlay.get() else None)
        self._update_route_label()

    def _poll(self, future, operation, generation):
        if self._disposed or generation != self._generation:
            return
        self._poll_id = None
        if not future.done():
            self._poll_id = self.after(40, self._poll, future, operation, generation)
            return
        self.busy = False
        try:
            value = future.result()
            if operation == "open":
                self.pack_info = value
                self.zoom_picker.configure(values=tuple(str(z) for z in value.zooms))
                tile_format = dict(value.metadata).get("format", "unknown").lower()
                kind = "vector preview" if tile_format == "pbf" else "raster"
                self.source.set(f"{value.name[:120]} · {kind} · stored zooms {', '.join(map(str, value.zooms))}")
                attribution = dict(value.metadata).get("attribution", "Not supplied — verify source and rights")
                compact = " ".join(attribution.split())
                self.attribution.set("Attribution (pack-supplied): " + compact[:200]
                                     + ("… [full text in Map details]" if len(compact) > 200 else ""))
                if self._route_geometry is not None and self._route_geometry.start is not None:
                    self._set_view(*self._route_geometry.start, value.zoom)
                else:
                    self.home()
                return
            frame, markers, problem = value
            if frame.view != self.view:
                return
            self.markers = markers if self.overlay.get() else ()
            self._draw(frame, problem)
        except Exception as exc:
            self.markers = ()
            self.place_picker.configure(values=())
            self.place_choice.set("")
            self._blank("Map view unavailable.\n" + str(exc))
            if operation == "open":
                self.pack_info = self.view = None
                self.source.set("Map could not be opened; no previous map is displayed.")
            self.status.set("Map operation failed: " + str(exc))
        self._buttons()

    def _draw(self, frame, marker_error=""):
        self.canvas.delete("all")
        self._images.clear()
        shown = missing = bad = outside = 0
        cache = {}
        for tile in frame.tiles:
            x, y = tile.slot.left, tile.slot.top
            issue = tile.issue
            if tile.data is not None:
                key = (tile.slot.column, tile.slot.row)
                try:
                    if key not in cache:
                        photo = tk.PhotoImage(master=self.canvas, data=base64.b64encode(tile.data), format="png")
                        if photo.width() != tile.pixels or photo.height() != tile.pixels:
                            raise tk.TclError("Decoded tile dimensions differ")
                        if tile.pixels == 512:
                            photo = photo.subsample(2, 2)
                        cache[key] = photo
                        self._images.append(photo)
                    self.canvas.create_image(x, y, anchor="nw", image=cache[key], tags="mapcontent")
                    shown += 1
                    continue
                except tk.TclError:
                    issue = "PNG could not be decoded"
            if issue == "Tile not installed":
                missing += 1
            elif issue == "Outside projection":
                outside += 1
            else:
                bad += 1
            fill = "#d9e0dc" if issue == "Outside projection" else "#f0eee6"
            self.canvas.create_rectangle(x, y, x + TILE_SIZE, y + TILE_SIZE, fill=fill, outline="#aab8ac", tags="mapcontent")
            self.canvas.create_text(x + 128, y + 128, text=issue + f"\nZ{frame.view.zoom} X{tile.slot.column} Y{tile.slot.row}",
                                    width=225, fill="#4d5c51", justify="center", tags="mapcontent")
        self._draw_route(frame.view)
        choices, visible, polar = [], 0, 0
        for marker in self.markers:
            caption = f"{marker.id} — {marker.name}"
            choices.append(caption)
            if abs(marker.latitude) > MAX_LATITUDE:
                polar += 1
                continue
            positions = frame.view.locations(marker.latitude, marker.longitude)
            if positions:
                visible += 1
            for x, y in positions:
                self.canvas.create_oval(x - 6, y - 6, x + 6, y + 6, fill="#a73b47", outline="white", width=2,
                                        tags=("mapcontent", "private-marker"))
                self.canvas.create_text(x + 10, y - 12, anchor="w", text=marker.name[:70], fill="#621f2c",
                                        font=("TkDefaultFont", 10, "bold"), tags=("mapcontent", "private-marker"))
        self.place_picker.configure(values=choices)
        if self.place_choice.get() not in choices:
            self.place_choice.set(choices[0] if choices else "")
        self.frame = frame
        self.pointer.set(f"View center: latitude {frame.view.latitude:.7f}, longitude {frame.view.longitude:.7f} · zoom {frame.view.zoom}. "
                         "North is up. Displayed precision is not surveyed accuracy.")
        overlay = (f" · {visible} saved places visible; {polar} outside projection" if self.overlay.get() else " · Private-place overlay off")
        self.status.set(f"Visible cells: {shown} shown, {missing} not installed, {bad} unreadable, {outside} outside projection"
                        + overlay + (". " + marker_error if marker_error else ". No coverage or route-safety guarantee."))
        self._update_route_label()

    def home(self):
        if self.pack_info:
            p = self.pack_info
            self._set_view(p.latitude, p.longitude, p.zoom)

    def go(self):
        if self.pack_info and self.view:
            try:
                lat = coordinate(self.latitude.get(), latitude=True)
                lon = coordinate(self.longitude.get(), latitude=False)
                if abs(lat) > MAX_LATITUDE:
                    raise ValueError("This projection cannot show polar coordinates beyond ±85.05112878°.")
                self._set_view(lat, lon, self.view.zoom)
            except ValueError as exc:
                self.status.set("Center not changed: " + str(exc))

    def center_place(self):
        if not self.overlay.get() or self.view is None:
            return
        marker = next((m for m in self.markers if f"{m.id} — {m.name}" == self.place_choice.get()), None)
        if marker is not None:
            if abs(marker.latitude) > MAX_LATITUDE:
                self.status.set("That saved place is outside the Web Mercator latitude extent; no position was invented.")
            else:
                self._set_view(marker.latitude, marker.longitude, self.view.zoom)

    def change_zoom(self, direction):
        if self.pack_info and self.view and self._drag is None:
            index = self.pack_info.zooms.index(self.view.zoom)
            index = max(0, min(len(self.pack_info.zooms) - 1, index + direction))
            zoom = self.pack_info.zooms[index]
            if zoom != self.view.zoom:
                self._set_view(self.view.latitude, self.view.longitude, zoom)
        return "break"

    def set_zoom(self):
        if self.view and self.pack_info:
            try:
                zoom = int(self.zoom_choice.get())
                if zoom not in self.pack_info.zooms:
                    raise ValueError()
                self._set_view(self.view.latitude, self.view.longitude, zoom)
            except ValueError:
                self.status.set("Choose a zoom level actually present in the map pack.")

    def wheel(self, event):
        return self.change_zoom(1 if event.delta > 0 else -1) if event.delta else "break"

    def key(self, event):
        if self.view is None or self._drag is not None:
            return None
        moves = {"Left": (-128, 0), "Right": (128, 0), "Up": (0, -128), "Down": (0, 128)}
        if event.keysym in moves:
            self.view = self.view.pan(*moves[event.keysym])
            self._set_view(self.view.latitude, self.view.longitude, self.view.zoom)
        elif event.keysym in ("plus", "equal", "minus"):
            self.change_zoom(-1 if event.keysym == "minus" else 1)
        else:
            return None
        return "break"

    def drag_start(self, event):
        self.canvas.focus_set()
        if self.frame is not None and not self.busy:
            self._drag = (event.x, event.y, event.x, event.y)
            self.pointer.set("Panning preview — release to read the new viewport.")

    def drag_move(self, event):
        if self._drag is not None:
            x, y, last_x, last_y = self._drag
            self.canvas.move("mapcontent", event.x - last_x, event.y - last_y)
            self._drag = x, y, event.x, event.y

    def drag_end(self, event):
        if self._drag is not None and self.view is not None:
            x, y, _, _ = self._drag
            self._drag = None
            moved = self.view.pan(x - event.x, y - event.y)
            self._set_view(moved.latitude, moved.longitude, moved.zoom)

    def motion(self, event):
        if self.frame is not None and self._drag is None:
            try:
                latitude, longitude = self.frame.view.at_pixel(event.x, event.y)
                self.pointer.set(f"Pointer: latitude {latitude:.7f}, longitude {longitude:.7f} · WGS 84. "
                                 "Calculated map position, NOT GPS or a surveyed location.")
            except ValueError:
                self.pointer.set("Pointer is outside the Web Mercator projection. No location inferred.")

    def resize(self, _event=None):
        if self._disposed:
            return
        if self._resize_id is not None:
            self.after_cancel(self._resize_id)
        self._resize_id = self.after(120, self._resized)

    def _resized(self):
        self._resize_id = None
        if self._disposed:
            return
        if self.view is not None:
            if (self.view.width, self.view.height) != self._dimensions():
                self._set_view(self.view.latitude, self.view.longitude, self.view.zoom)
        elif not self.busy:
            self.canvas.coords("placeholder", self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)

    def details(self):
        if self.pack_info is None:
            return None
        pack = self.pack_info
        window = tk.Toplevel(self)
        window.title("FieldForge — Map source and limitations")
        window.geometry("820x680")
        text = ScrolledText(window, wrap="word", padx=16, pady=16, font=("TkDefaultFont", 11))
        text.pack(fill="both", expand=True)
        text.insert("1.0", f"EXTERNAL MAP FILE\n{pack.path}\n{pack.signature[2]:,} bytes\n\n"
                    "This file is not copied into FieldForge. Back it up separately with any licenses/source files. "
                    "Metadata below is supplied by the pack, not independently checked or fetched. HTML/URLs remain inert text.\n\n"
                    + "\n\n".join(f"{key}:\n{value}" for key, value in pack.metadata)
                    + "\n\nLIMITS\n" + "\n".join(pack.warnings)
                    + "\n\nFlat/indexed raster MBTiles and gzip-compressed PBF vector MBTiles with a basic preview style; publisher styles, fonts, sprites and labels are not applied. Normalized/views are unsupported. "
                    "The file signature detects ordinary changes, not malicious tampering or full integrity. "
                    "Only open trusted data with an up-to-date Python/Tk/SQLite installation.\n\n" + NOTICE)
        text.configure(state="disabled")
        return window

    def route_details(self):
        if self.route is None:
            return None
        route = self.route
        window = tk.Toplevel(self)
        window.title("FieldForge — Planned route details")
        window.geometry("820x650")
        text = ScrolledText(window, wrap="word", padx=16, pady=16, font=("TkDefaultFont", 11))
        text.pack(fill="both", expand=True)
        first, last = route["geometry"][0], route["geometry"][-1]
        polar = self._route_geometry.polar_points
        text.insert("1.0", f"PLANNED ROUTE\n{route['title']}\n\n"
                    "Supplied planned geometry, not a recorded journey. No live guidance, receiver history, "
                    "rerouting or current road-condition check is performed. The cyan line follows the supplied "
                    "geometry. S and E mark its actual first and last vertices; provider-snapped endpoints "
                    "can differ from the requested coordinates. Showing a route keeps the selection for this session. "
                    "Use Save route in Online Maps & Offline Downloads to keep it after restarting.\n\n"
                    f"Mode: {route['mode']}\nDistance supplied: {route['distance_m']:,.1f} m\n"
                    f"Duration supplied: {route['duration_s']:,.1f} seconds\n"
                    f"Provider plan timestamp: {route['created_at']}\n"
                    f"Route geometry: {len(route['geometry']):,} longitude/latitude vertices\n"
                    f"Turn instructions: {len(route['steps']):,}\n\n"
                    f"Requested start: latitude {route['start']['latitude']:.7f}, longitude {route['start']['longitude']:.7f}\n"
                    f"Requested end: latitude {route['end']['latitude']:.7f}, longitude {route['end']['longitude']:.7f}\n"
                    f"Geometry start: latitude {first[1]:.7f}, longitude {first[0]:.7f}\n"
                    f"Geometry end: latitude {last[1]:.7f}, longitude {last[0]:.7f}\n\n"
                    f"SOURCE\n{route['source']}\n\nATTRIBUTION\n{route['attribution']}\n\nLICENSE\n{route['license']}\n\n"
                    "DISPLAY LIMITS\n"
                    f"{polar:,} polar vertices outside ±85.05112878° and their adjoining segments are hidden; "
                    "no substitute points are invented. The date line wraps horizontally. The display clips "
                    "individual segments to the viewport without simplifying the path. At most 12,000 visible "
                    "segments are drawn at once; a message identifies that limit so you can zoom in.\n\n"
                    "Source text and URLs are displayed as inert text. The supplied attribution and rights "
                    "are retained without independent verification. Clearing this overlay or closing a map "
                    "does not delete the separately saved route. No map file is downloaded when viewing a route.")
        text.configure(state="disabled")
        return window

    def _destroyed(self, event):
        if event.widget is self and not self._disposed:
            self._disposed = True
            self._stop_request()
            if self._resize_id is not None:
                self.after_cancel(self._resize_id)
                self._resize_id = None
            self._worker.shutdown(wait=False, cancel_futures=True)
            self._images.clear()
