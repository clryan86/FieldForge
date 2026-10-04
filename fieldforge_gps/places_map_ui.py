"""Place centering layered over the cumulative offline map / GPX viewer."""

from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from tkinter import ttk

from .local_map_ui import LocalMapReviewFrame
from .mbtiles import MAX_LAT
from .mercator import MercatorView
from .places import Place, clean_text, coordinate
from .review_map import View, wrap


class PlacesMapReviewFrame(LocalMapReviewFrame):
    def __init__(self, parent):
        self._place_marker = None
        self._finder_window = None
        self.finder = None
        self._image_window = None
        self._image_frame = None
        super().__init__(parent)
        panel = self.map_trust_check.master
        box = ttk.Frame(panel)
        box.pack(fill="x", before=self.map_trust_check, pady=(0, 5))
        self.find_places_button = ttk.Button(
            box, text="Find places / coordinates…", command=self.open_finder
        )
        self.find_places_button.pack(side="left")
        self.clear_place_button = ttk.Button(
            box, text="Clear place marker", command=self.clear_place_marker
        )
        self.clear_place_button.pack(side="left", padx=7)
        self.image_button = ttk.Button(
            box, text="Open map image…", command=self.open_image_reference
        )
        self.image_button.pack(side="left", padx=(0, 7))
        ttk.Label(box, text="Local files only · no bundled real place index").pack(side="left")
        self.place_notice = tk.StringVar(
            value="No place marker. Place-file search is separate from GPX history and live receiver tools."
        )
        status = ttk.Frame(panel, height=38)
        status.pack(fill="x", before=self.map_trust_check)
        status.pack_propagate(False)
        label = ttk.Label(status, textvariable=self.place_notice, wraplength=960, anchor="nw")
        label.pack(fill="both", expand=True)
        status.bind(
            "<Configure>", lambda event: label.configure(wraplength=max(200, event.width - 4))
        )
        self.clear_place_button.configure(state="disabled")

    def open_image_reference(self):
        if self._closed:
            return None
        if self._image_window is not None and self._image_window.winfo_exists():
            self._image_window.deiconify()
            self._image_window.lift()
            return self._image_frame
        from .image_map_ui import open_image_map

        self._image_window, self._image_frame = open_image_map(self)
        return self._image_frame

    def open_finder(self):
        if self._closed:
            return None
        if self._finder_window is not None and self._finder_window.winfo_exists():
            self._finder_window.lift()
            return self.finder
        from .place_search_ui import PlaceSearchFrame

        window = tk.Toplevel(self)
        window.title("FieldForge · Offline place search — reference points, not navigation")
        window.geometry("1000x760")
        window.minsize(920, 700)
        self._finder_window = window
        self.finder = PlaceSearchFrame(window, self)

        def close():
            self.close_finder()

        def destroyed(event):
            if event.widget is window and self._finder_window is window:
                self.finder = self._finder_window = None

        window.bind("<Destroy>", destroyed, add=True)
        window.protocol("WM_DELETE_WINDOW", close)
        return self.finder

    def close_finder(self):
        finder, window = self.finder, self._finder_window
        self.finder = self._finder_window = None
        if finder is not None:
            finder.close()
        if window is not None:
            window.destroy()

    def show_place(self, place: Place, origin: str):
        if self._closed:
            raise ValueError("Map workspace is closed.")
        if not isinstance(place, Place) or origin not in ("FILE PLACE", "MANUAL COORDINATE"):
            raise ValueError("Unsupported place marker.")
        lat, lon = coordinate(place.latitude, "latitude"), coordinate(place.longitude, "longitude")
        place = replace(place, name=clean_text(place.name, "Place name", required=True))
        if self._map_loading:
            raise ValueError("Finish or cancel the map read before centering a place.")
        if self.map_pack:
            if not -MAX_LAT <= lat <= MAX_LAT:
                raise ValueError(
                    "Place is outside Web Mercator. Close the local map for the world overview; the coordinate was not clamped."
                )
            self.view = MercatorView(wrap(lon), lat, self.view.level)
        else:
            self.view = View(wrap(lon), lat, min(self.view.span, 45))
        self._place_marker = (place, origin)
        self.place_notice.set(
            f"{origin}: {place.name[:110]} · lat {lat:.6f}, lon {lon:.6f}. "
            "Reference point only; no live GPS, route, verified address, or coverage guarantee."
        )
        self.clear_place_button.configure(state="normal")
        self._drag = None
        self._map_buttons()
        self.request_draw()

    def clear_place_marker(self, *, file_only=False):
        if file_only and self._place_marker and self._place_marker[1] != "FILE PLACE":
            return
        self._place_marker = None
        if hasattr(self, "place_notice"):
            self.place_notice.set("No place marker. Loaded maps and GPX history are unchanged.")
            self.clear_place_button.configure(state="disabled")
        if not self._closed:
            self.canvas.delete("place-marker", "place-marker-label")
            self.request_draw()

    def draw(self):
        super().draw()
        if self._closed or self._place_marker is None:
            return
        if self.map_pack and self._frame_key != self._viewport_key():
            return  # Never draw over stale map imagery or a failed viewport.
        place, origin = self._place_marker
        width, height = self._dimensions()
        point = self.view.position(place.longitude, place.latitude, width, height)
        if point is None or not (12 <= point[0] <= width - 12 and 45 <= point[1] <= height - 12):
            return
        x, y = point
        self.canvas.create_polygon(
            x,
            y - 10,
            x + 10,
            y,
            x,
            y + 10,
            x - 10,
            y,
            fill="#76509b",
            outline="white",
            width=2,
            tags="place-marker",
        )
        left = x > width / 2
        text = f"{origin}\n{place.name[:70]}"
        self.canvas.create_text(
            x - 15 if left else x + 15,
            y + 14,
            text=text,
            anchor="ne" if left else "nw",
            width=min(280, max(90, width / 2 - 30)),
            font=("TkDefaultFont", 10, "bold"),
            fill="#4e2f71",
            tags="place-marker-label",
        )

    def destroy(self):
        # Parent-window destruction must stop both workers before child teardown.
        self.close()
        super().destroy()

    def close(self):
        if self._closed:
            return
        self.close_finder()
        if self._image_frame is not None:
            self._image_frame.close()
        if self._image_window is not None and self._image_window.winfo_exists():
            self._image_window.destroy()
        self._image_window = self._image_frame = None
        self._place_marker = None
        if hasattr(self, "place_notice"):
            self.place_notice.set("")
        super().close()


def main():
    root = tk.Tk()
    root.title("FieldForge · Offline places, local maps & saved trips — NOT NAVIGATION")
    root.geometry("1240x1040")
    root.minsize(1020, 930)
    frame = PlacesMapReviewFrame(root)

    def close():
        frame.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


if __name__ == "__main__":
    main()
