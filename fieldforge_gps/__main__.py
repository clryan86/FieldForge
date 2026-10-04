"""Run with ``python -m fieldforge_gps``. Uses no household database."""

from __future__ import annotations

import argparse
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .export import export_waypoint
from .session import BAUD_RATES, Session
from .tk_cleanup import TkCleanupMixin

NOTICE = (
    "Local receiver workspace • no internet or database changes. Trip history is opt-in.\n"
    "Receiver positions are not independently verified. This is not turn-by-turn navigation."
)


class GPSWindow(TkCleanupMixin, ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=20)
        self.session: Session | None = None
        self._closed = False
        self._after = None
        self.map_window = None
        self.map_tab = None
        self.trip_window = None
        self.review_window = None
        self.live_map_window = None
        self.live_map_frame = None
        self._trip_exported_revision = None
        self.pack(fill="both", expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(8, weight=1)
        self.port = tk.StringVar(value="")
        self.baud = tk.StringVar(value="9600")
        self.datum = tk.BooleanVar(value=False)
        self.trip_consent = tk.BooleanVar(value=False)
        self.trip_name = tk.StringVar(value="My trip")
        self.trip_status = tk.StringVar(value="Trip: not recording; nothing saved automatically.")
        self.datum.trace_add("write", self._permission_changed)
        self.trip_consent.trace_add("write", self._permission_changed)
        self.mode = tk.StringVar(value="DISCONNECTED — no location requested")
        self.status = tk.StringVar(
            value="Connect a GPS receiver or inspect a local NMEA recording."
        )
        self.coords = tk.StringVar(value="No current position")
        self.detail = tk.StringVar(value="Nothing has been read or saved.")
        self.counts = tk.StringVar(value="")
        self.name = tk.StringVar(value="GPS waypoint")
        ttk.Label(self, text="FieldForge · GPS Receiver", font=("TkDefaultFont", 23, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        header_actions = ttk.Frame(self)
        header_actions.grid(row=0, column=0, sticky="e")
        self.live_map_button = ttk.Button(
            header_actions, text="Maps / GPS / places…", command=self.open_live_map
        )
        self.live_map_button.pack(side="left", padx=(0, 8))
        self.trips_button = ttk.Button(
            header_actions, text="Trips / recorded paths…", command=self.open_trips
        )
        self.trips_button.pack(side="left")
        self.notice = ttk.Label(self, text=NOTICE, wraplength=840, justify="left")
        self.notice.grid(row=1, column=0, sticky="ew", pady=(8, 16))
        source = ttk.LabelFrame(self, text="Choose input explicitly", padding=12)
        source.grid(row=2, column=0, sticky="ew")
        source.columnconfigure(1, weight=1)
        ttk.Label(source, text="Local port").grid(row=0, column=0, sticky="w")
        self.port_entry = ttk.Entry(source, textvariable=self.port, width=26)
        self.port_entry.grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Label(source, text="Baud").grid(row=0, column=2)
        self.baud_entry = ttk.Combobox(
            source, textvariable=self.baud, values=BAUD_RATES, state="readonly", width=8
        )
        self.baud_entry.grid(row=0, column=3, padx=(8, 0))
        ttk.Label(
            source,
            text="Examples: COM3 on Windows; /dev/ttyACM0 on Linux. Use only a GPS receiver.",
            wraplength=780,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 4))
        ttk.Checkbutton(
            source,
            variable=self.datum,
            text="I verified that this receiver / recording uses WGS84 coordinates.",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=4)
        ttk.Label(
            source,
            text="Opening a serial port may toggle device control lines. No GPS commands are sent.",
            wraplength=780,
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=4)
        actions = ttk.Frame(source)
        actions.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self.connect_button = ttk.Button(actions, text="Connect selected GPS", command=self.connect)
        self.connect_button.pack(side="left")
        self.record_button = ttk.Button(
            actions, text="Open recorded NMEA…", command=self.choose_recording
        )
        self.record_button.pack(side="left", padx=8)
        self.stop_button = ttk.Button(actions, text="Disconnect / clear", command=self.disconnect)
        self.stop_button.pack(side="left")
        ttk.Label(self, textvariable=self.mode, font=("TkDefaultFont", 13, "bold")).grid(
            row=3, column=0, sticky="w", pady=(20, 4)
        )
        ttk.Label(self, textvariable=self.coords, font=("TkDefaultFont", 20, "bold")).grid(
            row=4, column=0, sticky="w", pady=6
        )
        self.status_label = ttk.Label(self, textvariable=self.status, wraplength=840)
        self.status_label.grid(row=5, column=0, sticky="ew", pady=6)
        self.detail_label = ttk.Label(
            self, textvariable=self.detail, wraplength=840, justify="left"
        )
        self.detail_label.grid(row=6, column=0, sticky="ew", pady=6)
        ttk.Label(self, textvariable=self.counts).grid(row=7, column=0, sticky="w", pady=6)
        ttk.Label(self, textvariable=self.trip_status).grid(row=8, column=0, sticky="sw")
        export = ttk.LabelFrame(
            self, text="Manual waypoint export — separate from opt-in trip history", padding=12
        )
        export.grid(row=9, column=0, sticky="ew", pady=(14, 0))
        export.columnconfigure(1, weight=1)
        ttk.Label(export, text="Waypoint name").grid(row=0, column=0)
        ttk.Entry(export, textvariable=self.name).grid(row=0, column=1, sticky="ew", padx=8)
        self.export_button = ttk.Button(
            export, text="Export new GPX waypoint…", command=self.export
        )
        self.export_button.grid(row=0, column=2)
        lower = ttk.Frame(export)
        lower.grid(row=1, column=0, columnspan=3, sticky="w", pady=(12, 0))
        self.copy_button = ttk.Button(
            lower, text="Copy displayed coordinates", command=self.copy_coordinates
        )
        self.copy_button.pack(side="left")
        self.map_button = ttk.Button(lower, text="Open FieldForge local map", command=self.open_map)
        self.map_button.pack(side="left", padx=8)
        self.center_button = ttk.Button(
            lower, text="Center map on displayed position", command=self.center_map
        )
        self.center_button.pack(side="left")
        self.bind("<Configure>", self._resize, add=True)
        self.bind("<Destroy>", self._destroyed, add=True)
        self.poll()

    def _resize(self, event):
        if event.widget is self:
            for label in (self.notice, self.status_label, self.detail_label):
                label.configure(wraplength=max(500, event.width - 45))

    def _permission_changed(self, *_):
        if (not self.datum.get() or not self.trip_consent.get()) and self.session is not None:
            summary = self.session.trip_summary()
            if summary.source == "serial" and summary.state == "recording":
                self.session.pause_trip()
        self._refresh_live_map()

    def _refresh_live_map(self):
        if self.live_map_frame is not None and not self.live_map_frame._closed:
            self.live_map_frame.refresh_live()

    def open_live_map(self):
        if self.live_map_window is not None and self.live_map_window.winfo_exists():
            self.live_map_window.deiconify()
            self.live_map_window.lift()
            return self.live_map_frame
        from .live_map_ui import LiveMapFrame

        self.live_map_window = tk.Toplevel(self)
        self.live_map_window.title("FieldForge · Maps, GPS & offline places — not route guidance")
        self.live_map_window.geometry("1200x900")
        self.live_map_window.minsize(1020, 800)
        self.live_map_frame = LiveMapFrame(self.live_map_window, self)

        def close_map_window():
            self.live_map_frame.close()
            self.live_map_window.destroy()
            self.live_map_frame = None
            self.live_map_window = None

        self.live_map_window.protocol("WM_DELETE_WINDOW", close_map_window)
        return self.live_map_frame

    def open_trips(self):
        if self.trip_window is not None and self.trip_window.winfo_exists():
            self.trip_window.lift()
            return
        from .trip_ui import TripWindow

        self.trip_window = TripWindow(self)

    def open_review(self):
        if self.review_window is not None and self.review_window.winfo_exists():
            self.review_window.lift()
            return
        from .review_ui import open_review

        self.review_window = open_review(self)

    def _can_change_source(self):
        if self.session is not None:
            summary = self.session.trip_summary()
            if summary.state != "idle":
                messagebox.showerror(
                    "Preserve current trip",
                    "Open Trips to finish and export any wanted history, then Discard it before changing input. "
                    "The existing trip has not been replaced.",
                    parent=self,
                )
                return False
            if self.session.snapshot().running:
                messagebox.showerror(
                    "Input already active",
                    "Disconnect the current input before opening another.",
                    parent=self,
                )
                return False
        return True

    def request_close(self):
        if self.session is not None:
            summary = self.session.trip_summary()
            saved = self._trip_exported_revision == (id(self.session), summary.revision)
            if summary.state in ("recording", "reading") or (summary.point_count and not saved):
                return messagebox.askyesno(
                    "Exit GPS workspace?",
                    "Trip history is held only in memory. Exiting discards any unsaved points.\n"
                    "Choose No, then Pause/Finish and Export in Trips to keep a copy.\nExit and discard?",
                    parent=self,
                )
        return True

    def _replace(self, session):
        if self.session is not None:
            self.session.stop()
        self.session = session
        self._trip_exported_revision = None
        self._refresh_live_map()

    def connect(self):
        if not self._can_change_source():
            return
        session = Session("serial")
        try:
            session.start_serial(
                self.port.get().strip(), int(self.baud.get()), wgs84_confirmed=self.datum.get()
            )
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("GPS connection", str(exc), parent=self)
            return
        self._replace(session)

    def choose_recording(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Open recorded NMEA — NOT live",
            filetypes=[("NMEA recording", "*.nmea *.log *.txt"), ("All files", "*")],
        )
        if path:
            self.load_recording(path)

    def load_recording(self, path, *, collect_track=False):
        if not self._can_change_source():
            return False
        session = Session("recorded")
        try:
            session.start_recording(
                path,
                collect_track=collect_track,
                wgs84_confirmed=self.datum.get(),
                consent=self.trip_consent.get(),
            )
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Recorded path", str(exc), parent=self)
            return False
        self._replace(session)
        return True

    def disconnect(self):
        if self.session is not None:
            self.session.stop()
        # Clear synchronously, rather than waiting for the next polling tick.
        self.coords.set("No current position")
        self.mode.set("DISCONNECTED — no current location")
        self.status.set("Disconnected; no current position.")
        for button in (self.copy_button, self.export_button, self.center_button):
            button.configure(state="disabled")
        self._refresh_live_map()

    def current(self):
        if not self.datum.get():
            raise ValueError("Confirm the receiver / recording WGS84 datum first.")
        snapshot = self.session.snapshot() if self.session is not None else None
        if snapshot is None or snapshot.position is None:
            raise ValueError("No accepted current or recorded position is available.")
        return snapshot

    def copy_coordinates(self):
        try:
            snapshot = self.current()
        except ValueError as exc:
            messagebox.showerror("Copy coordinates", str(exc), parent=self)
            return
        p = snapshot.position
        # This action is explicit. Include source/time so recorded data cannot
        # silently masquerade as the user's current position in the clipboard.
        label = "RECORDED — NOT LIVE" if snapshot.mode == "recorded" else "Receiver-reported"
        self.clipboard_clear()
        self.clipboard_append(
            f"{label}: {p.latitude:.8f}, {p.longitude:.8f}; receiver UTC {p.timestamp.isoformat()}"
        )

    def export(self):
        try:
            self.current()
            path = filedialog.asksaveasfilename(
                parent=self,
                title="Export a NEW private GPX waypoint",
                defaultextension=".gpx",
                filetypes=[("GPX", "*.gpx")],
            )
            if not path:
                return
            # Re-check freshness after the modal dialog; never save an old
            # snapshot captured before the user chose a destination.
            snapshot = self.current()
            export_waypoint(path, snapshot, self.name.get(), wgs84_confirmed=self.datum.get())
            messagebox.showinfo(
                "GPX saved",
                "New waypoint saved. Existing files and your FieldForge database were not changed.\n"
                "The GPX contains private coordinates; share it deliberately.",
                parent=self,
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("GPX export", str(exc), parent=self)

    def open_map(self):
        if self.map_window is not None and self.map_window.winfo_exists():
            self.map_window.lift()
            return
        try:
            from fieldforge.ui.maps import MapsTab
        except ImportError:
            messagebox.showinfo(
                "Optional FieldForge map",
                "Run this add-on beside a FieldForge source build with Maps.\n"
                "The receiver workspace itself does not bundle maps.",
                parent=self,
            )
            return
        self.map_window = tk.Toplevel(self)
        self.map_window.title("FieldForge · Local map — manual position centering only")
        self.map_window.geometry("1150x820")
        try:
            self.map_tab = MapsTab(self.map_window, None)
            self.map_tab.pack(fill="both", expand=True)
        except Exception:
            self.map_window.destroy()
            self.map_window = self.map_tab = None
            messagebox.showerror(
                "Optional FieldForge map",
                "This FieldForge map version is not compatible with the add-on.",
                parent=self,
            )

    def center_map(self):
        try:
            snapshot = self.current()
            if (
                self.map_window is None
                or not self.map_window.winfo_exists()
                or self.map_tab.pack_info is None
            ):
                raise ValueError("Open a trusted local map pack in the map window first.")
            p = snapshot.position
            from fieldforge.navigation.map_view import MAX_LATITUDE

            if abs(p.latitude) > MAX_LATITUDE:
                raise ValueError(
                    "This map projection cannot show polar positions; the map was not changed."
                )
            self.map_tab.latitude.set(str(p.latitude))
            self.map_tab.longitude.set(str(p.longitude))
            self.map_tab.go()
            label = (
                "RECORDED position — NOT live"
                if snapshot.mode == "recorded"
                else "Captured receiver position — NOT auto-follow"
            )
            self.map_window.title("FieldForge · " + label + " · " + p.timestamp.isoformat())
        except (ValueError, AttributeError, tk.TclError) as exc:
            messagebox.showerror("Center map", str(exc), parent=self)

    def poll(self):
        if self._closed:
            return
        snapshot = self.session.snapshot() if self.session is not None else None
        ready = snapshot is not None and snapshot.position is not None and self.datum.get()
        for button in (self.copy_button, self.export_button, self.center_button):
            button.configure(state="normal" if ready else "disabled")
        trip = self.session.trip_summary() if self.session is not None else None
        if trip is not None and trip.state != "idle":
            self.trip_status.set(
                f"Trip: {trip.state.upper()} · {trip.point_count:,} points · {trip.segment_count:,} segments · history, not a current fix"
            )
        else:
            self.trip_status.set("Trip: not recording; nothing saved automatically.")
        running = snapshot is not None and snapshot.running
        for button in (self.connect_button, self.record_button):
            button.configure(
                state="disabled" if running or (trip and trip.state != "idle") else "normal"
            )
        if snapshot is not None:
            self.mode.set(
                "RECORDED FILE — NOT LIVE"
                if snapshot.mode == "recorded"
                else (
                    "LOCAL SERIAL INPUT — receiver claims only"
                    if running
                    else "DISCONNECTED — no active serial input"
                )
            )
            self.status.set(snapshot.status)
            p = snapshot.position
            self.coords.set(
                f"Latitude {p.latitude:.8f}     Longitude {p.longitude:.8f}"
                if p
                else "No current position"
            )
            if p:
                self.detail.set(
                    f"Receiver UTC: {p.timestamp.isoformat()}\n"
                    f"{p.talker} RMC · Speed: {p.speed_knots if p.speed_knots is not None else 'not supplied'} knots · "
                    f"Course over ground: {p.course_true if p.course_true is not None else 'not supplied'}° true\n"
                    "Course is not a stationary compass heading. No accuracy estimate is asserted."
                )
            else:
                self.detail.set(
                    "A valid, dated RMC position is required. GGA alone does not establish a dated position."
                )
            self.counts.set(
                f"Parsed RMC/GGA: {snapshot.accepted}   Rejected: {snapshot.rejected}   "
                f"Other sentences: {snapshot.ignored}   Duplicate/backward epochs: {snapshot.duplicates}"
            )
        self._after = self.after(200, self.poll)

    def _destroyed(self, event):
        if event.widget is self:
            self.close()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.live_map_frame is not None:
            self.live_map_frame.close()
        if self._after is not None:
            self.after_cancel(self._after)
            self._after = None
        if self.session is not None:
            self.session.stop()
        if self.trip_window is not None and self.trip_window.winfo_exists():
            self.trip_window.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="FieldForge offline maps, place search, GPS receiver and saved trips."
    )
    parser.add_argument(
        "--trips",
        action="store_true",
        help="Open the opt-in trips workspace; does not connect or record.",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="Open standalone read-only GPX review; no receiver is connected.",
    )
    parser.add_argument(
        "--workspace",
        "--live-map",
        dest="live_map",
        action="store_true",
        help="Open maps, offline places and opt-in live GPS; does not connect or record automatically.",
    )
    args = parser.parse_args(argv)
    if args.review:
        from .review_ui import main as review_main

        review_main()
        return
    root = tk.Tk()
    root.title("FieldForge GPS Receiver")
    root.geometry("960x740")
    root.minsize(880, 700)
    window = GPSWindow(root)

    if args.trips:
        window.open_trips()
    if args.live_map:
        window.open_live_map()

    def close():
        if not window.request_close():
            return
        window.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


if __name__ == "__main__":
    main()
