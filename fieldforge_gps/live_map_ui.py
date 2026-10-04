"""Opt-in serial receiver overlay on the cumulative, read-only local map viewer.

A receiver workspace owns the Session. This view never starts a source, records a
trip, writes a coordinate, extrapolates a position, or accesses the household DB.
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from .live_map import POLL_MS, RECENTER_SECONDS, centered, live_status, outside_follow_box
from .mercator import MercatorView
from .places_map_ui import PlacesMapReviewFrame


class LiveMapFrame(PlacesMapReviewFrame):
    def __init__(self, parent, gps, *, clock=time.monotonic):
        # Parent constructors call overridable methods. Guards below keep their
        # initialization separate from the live layer, which begins disabled.
        self._live_ready = False
        self._live_after = None
        self._refreshing_live = False
        self._source = gps.session
        self._gps = gps
        self._live_clock = clock
        self._last_center = float("-inf")
        self._follow_note = ""
        super().__init__(parent)
        self.title_label.configure(text="FieldForge · Maps + GPS + Places")
        self.source_label.configure(text="OFFLINE WORKSPACE")
        self.banner_label.configure(
            text="Receiver fixes are not route guidance. Saved GPX tracks remain historical."
        )
        self.point_detail.set(
            "No recorded GPX point selected. The live receiver layer is separate."
        )
        # Keep historical controls available, but collapsed by default so the
        # live map is usable on a laptop-sized screen.
        self._history_widgets = []
        for child in self.grid_slaves():
            row = int(child.grid_info()["row"])
            if row in (2, 3, 4, 5, 9):
                self._history_widgets.append(child)
            if row >= 2:
                child.grid_configure(row=row + 1)
        self.rowconfigure(8, weight=0)
        self.rowconfigure(9, weight=1, minsize=180)
        for child in self._history_widgets:
            child.grid_remove()
        self._history_visible = False
        panel = ttk.LabelFrame(
            self, text="Live receiver layer — opt-in; no automatic recording", padding=(10, 6)
        )
        panel.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        actions = ttk.Frame(panel)
        actions.pack(fill="x")
        self.receiver_button = ttk.Button(
            actions, text="Receiver controls…", command=self.receiver_controls
        )
        self.receiver_button.pack(side="left", padx=(0, 10))
        self.show_live = tk.BooleanVar(value=False)
        self.follow_live = tk.BooleanVar(value=False)
        self.show_live_check = ttk.Checkbutton(
            actions, text="Show live position", variable=self.show_live
        )
        self.show_live_check.pack(side="left", padx=(0, 12))
        self.follow_check = ttk.Checkbutton(
            actions, text="Follow receiver", variable=self.follow_live
        )
        self.follow_check.pack(side="left", padx=(0, 10))
        self.center_live_button = ttk.Button(
            actions, text="Center live fix", command=self.center_live
        )
        self.center_live_button.pack(side="left")
        self.history_button = ttk.Button(
            actions, text="Show GPX controls", command=self.toggle_history
        )
        self.history_button.pack(side="right", padx=(10, 0))
        self.live_notice = tk.StringVar(value="Live layer OFF.")
        status_box = ttk.Frame(panel, height=57)
        status_box.pack(fill="x", pady=(5, 0))
        status_box.pack_propagate(False)
        self.live_label = ttk.Label(
            status_box, textvariable=self.live_notice, wraplength=960, anchor="nw"
        )
        self.live_label.pack(fill="both", expand=True)
        self.show_live.trace_add("write", self._live_permission_changed)
        self.follow_live.trace_add("write", self._follow_changed)
        for key, dx, dy in (
            ("Left", 100, 0),
            ("Right", -100, 0),
            ("Up", 0, 100),
            ("Down", 0, -100),
        ):
            self.canvas.bind("<" + key + ">", lambda event, dx=dx, dy=dy: self.pan(dx, dy))
        self._live_ready = True
        self.refresh_live()
        self._poll_live()

    def receiver_controls(self):
        if self._gps is not None and not self._gps._closed:
            window = self._gps.winfo_toplevel()
            window.deiconify()
            window.lift()

    def toggle_history(self):
        self._history_visible = not self._history_visible
        for child in self._history_widgets:
            child.grid() if self._history_visible else child.grid_remove()
        self.history_button.configure(
            text="Hide GPX controls" if self._history_visible else "Show GPX controls"
        )
        self.request_draw()

    def _live_permission_changed(self, *_):
        if not self.show_live.get():
            self.follow_live.set(False)
            self._follow_note = ""
            self.canvas.delete("live-overlay")
        self.refresh_live()

    def _follow_changed(self, *_):
        if self._refreshing_live:
            return
        if self.follow_live.get():
            if not self.center_live():
                self.follow_live.set(False)
        else:
            self._follow_note = "Follow is off; use Center live fix or enable Follow receiver."
        self.refresh_live()

    def _read_live(self):
        gps = self._gps
        present = gps is not None and not gps._closed
        session = gps.session if present else None
        datum = present and gps.datum.get()
        # Every source replacement (even serial -> serial) needs fresh consent.
        if session is not self._source:
            self._source = session
            self.show_live.set(False)
            self.follow_live.set(False)
            self._follow_note = (
                "Input changed. Enable the live layer again after checking the new source."
            )
        if not datum and self.show_live.get():
            self.show_live.set(False)
            self.follow_live.set(False)
            self._follow_note = (
                "WGS84 confirmation is absent. Live display and following were turned off."
            )
        # Never retain a Snapshot or Observation on the widget. Ask Session anew
        # at each draw/tick; even a previously accepted fix can become stale.
        return live_status(
            session.snapshot() if session is not None and self.show_live.get() and datum else None,
            consent=self.show_live.get(),
            wgs84_confirmed=bool(datum),
            mercator=isinstance(self.view, MercatorView),
        )

    def _move_to(self, point):
        view = centered(self.view, point)
        self._last_center = self._live_clock()
        if view != self.view:
            self.view = view
            self._drag = None
            self._map_buttons()
            # Clear imagery immediately on a view change, not one idle callback
            # later. Otherwise an overlay can briefly be drawn over old tiles.
            self.draw()
        return True

    def center_live(self):
        if self._closed or not self._live_ready:
            return False
        state = self._read_live()
        if state.position is None:
            self.live_notice.set(state.message)
            self.refresh_live(allow_recenter=False)
            return False
        self._follow_note = ""
        self._move_to(state.position)
        return True

    def _pause_follow(
        self, message="Follow paused after manual map movement. Enable it again to resume."
    ):
        if self._live_ready and self.follow_live.get():
            self.follow_live.set(False)
            self._follow_note = message

    def refresh_live(self, *, allow_recenter=True):
        if self._closed or not self._live_ready or self._refreshing_live:
            return
        self._refreshing_live = True
        try:
            state = self._read_live()
            point = state.position
            self.center_live_button.configure(state="normal" if point is not None else "disabled")
            self.follow_check.configure(state="normal" if point is not None else "disabled")
            if point is None and self.follow_live.get():
                self.follow_live.set(False)
                self._follow_note = "Follow paused: no eligible fresh fix. Enable it again after the receiver recovers."
            width, height = self._dimensions()
            if (
                point is not None
                and self.follow_live.get()
                and allow_recenter
                and self._live_clock() - self._last_center >= RECENTER_SECONDS
                and self._map_task is None
                and outside_follow_box(self.view, point, width, height)
            ):
                self._move_to(point)
            if (
                self.map_pack
                and self._frame_key != self._viewport_key()
                and self.canvas.find_withtag("map-tile")
            ):
                self.draw()  # Never put a new-frame marker over an old-frame tile.
            self._render_live(state, width, height)
        finally:
            self._refreshing_live = False

    def _render_live(self, state, width, height):
        canvas = self.canvas
        canvas.delete("live-overlay")
        point = state.position
        message = state.message
        if point is not None:
            xy = self.view.position(point.longitude, point.latitude, width, height)
            visible = xy is not None and 10 <= xy[0] <= width - 10 and 43 <= xy[1] <= height - 10
            if visible:
                x, y = xy
                # A crosshair/diamond, not the circle/square used for GPX history.
                canvas.create_polygon(
                    x,
                    y - 9,
                    x + 9,
                    y,
                    x,
                    y + 9,
                    x - 9,
                    y,
                    fill="#146b70",
                    outline="white",
                    width=2,
                    tags=("live-overlay", "live-position"),
                )
                canvas.create_line(
                    x - 14,
                    y,
                    x + 14,
                    y,
                    fill="#146b70",
                    width=2,
                    tags=("live-overlay", "live-crosshair"),
                )
                canvas.create_line(
                    x,
                    y - 14,
                    x,
                    y + 14,
                    fill="#146b70",
                    width=2,
                    tags=("live-overlay", "live-crosshair"),
                )
                anchor = "sw" if x < width - 175 else "se"
                label_x = x + 15 if anchor == "sw" else x - 15
                canvas.create_text(
                    label_x,
                    y - 15,
                    text="SERIAL FIX",
                    anchor=anchor,
                    fill="#124f55",
                    font=("TkDefaultFont", 10, "bold"),
                    tags=("live-overlay", "live-fix-label"),
                )
            else:
                message += " Fix is off-screen; use Center live fix."
            mode = "FOLLOW ON" if self.follow_live.get() else "FOLLOW OFF"
            message = (
                f"{mode} · {point.latitude:.6f}, {point.longitude:.6f} · receiver UTC {point.timestamp.isoformat()}\n"
                + message
            )
        if self._follow_note and not self.follow_live.get():
            message += " " + self._follow_note
        self.live_notice.set(message)
        # Cover the inherited history-only banner so the simultaneous layers
        # cannot be mislabeled. The history controls retain their own labels.
        canvas.create_rectangle(0, 0, width, 33, fill="#f7f8f8", outline="", tags="live-overlay")
        canvas.create_text(
            12,
            16,
            text="N ↑",
            anchor="w",
            fill="#253f56",
            font=("TkDefaultFont", 11, "bold"),
            tags="live-overlay",
        )
        banner = "SERIAL FIX — RECEIVER-REPORTED" if point is not None else "NO LIVE POSITION"
        canvas.create_text(
            width - 12,
            16,
            text=banner + " / GPX IS HISTORY / NOT ROUTE GUIDANCE",
            anchor="e",
            fill="#253f56",
            font=("TkDefaultFont", 10, "bold"),
            tags=("live-overlay", "live-banner"),
        )
        if not self._points:
            self.render_notice.set(
                "No GPX history displayed. The live layer is separately controlled; no trip recording is started here."
            )
            self.point_detail.set(
                "No recorded GPX point selected. The live receiver layer is separate."
            )

    def draw(self):
        super().draw()
        self.refresh_live(allow_recenter=False)

    def _poll_live(self):
        if not self._closed:
            self.refresh_live()
            self._live_after = self.after(POLL_MS, self._poll_live)

    def _resize(self, event):
        super()._resize(event)
        if self._live_ready:
            self.live_label.configure(wraplength=max(400, event.width - 20))

    def _start_drag(self, event):
        self.canvas.focus_set()
        self._pause_follow()
        super()._start_drag(event)

    def pan(self, dx, dy):
        self._pause_follow()
        try:
            self.view = self.view.pan(dx, dy, *self._dimensions())
        except ValueError as exc:
            self.map_status.set(str(exc))
        self.request_draw()

    def pack_start(self):
        self._pause_follow()
        super().pack_start()

    def fit(self):
        self._pause_follow(
            "Follow paused for historical GPX review; file tracks are not live positions."
        )
        super().fit()

    def center_point(self):
        self._pause_follow("Follow paused to inspect a historical GPX point.")
        return super().center_point()

    def show_place(self, place, origin):
        # Validate and accept the user's reference point first. A rejected point
        # must not change the viewport, marker, or follow state.
        super().show_place(place, origin)
        self._pause_follow(
            "Follow paused to inspect a place or coordinate. Enable it again to return to the receiver."
        )
        # Replace old imagery/overlays synchronously. The existing tile worker
        # will fill the new frame; no marker may sit over the previous viewport.
        self.draw()

    def close_map(self):
        self._pause_follow("Follow paused because the map layer changed.")
        super().close_map()
        if self._live_ready:
            self.refresh_live(allow_recenter=False)

    def destroy(self):
        self.close()
        super().destroy()

    def close(self):
        if self._closed:
            return
        self._live_ready = False
        self._refreshing_live = True
        self.show_live.set(False)
        self.follow_live.set(False)
        self.live_notice.set("Live map closed. No current position.")
        try:
            self.canvas.delete("live-overlay")
        except tk.TclError:
            pass  # Also safe when a direct Tcl destroy has removed children.
        if self._live_after is not None:
            self.after_cancel(self._live_after)
            self._live_after = None
        self._source = None
        self._gps = None
        self._history_widgets = []
        super().close()


def main():
    from .__main__ import main as receiver_main

    receiver_main(["--live-map"])


if __name__ == "__main__":
    main()
