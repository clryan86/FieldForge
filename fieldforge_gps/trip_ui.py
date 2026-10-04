"""Trip controls and historical-path preview; workers never access Tk objects."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .tk_cleanup import TkCleanupMixin
from .track_export import export_track
from .track_sketch import sketch


class TripWindow(TkCleanupMixin, tk.Toplevel):
    def __init__(self, gps):
        super().__init__(gps)
        self.gps = gps
        self.title("FieldForge · GPS Trips — historical paths, not navigation")
        self.geometry("1060x800")
        self.minsize(940, 750)
        self._after = None
        self._closed = False
        self._render_key = None
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Destroy>", self._destroyed, add=True)
        panel = ttk.Frame(self, padding=18)
        panel.pack(fill="both", expand=True)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(7, weight=1)
        ttk.Label(panel, text="FieldForge · GPS Trips", font=("TkDefaultFont", 22, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            panel,
            text="Opt-in history • memory only until export • no household database changes",
            font=("TkDefaultFont", 10),
        ).grid(row=1, column=0, sticky="w", pady=(6, 12))
        privacy = ttk.LabelFrame(panel, text="Choose deliberately", padding=10)
        privacy.grid(row=2, column=0, sticky="ew")
        self.datum_check = ttk.Checkbutton(
            privacy,
            text="I verified this receiver / recording uses WGS84 coordinates.",
            variable=gps.datum,
        )
        self.datum_check.pack(anchor="w")
        self.consent_check = ttk.Checkbutton(
            privacy,
            text="Keep a private trip in memory after I click Start or open a recorded path.",
            variable=gps.trip_consent,
        )
        self.consent_check.pack(anchor="w", pady=4)
        ttk.Label(
            privacy,
            text="Unchecking either box pauses live capture. Closing this window does not stop capture; use Pause or Finish.",
            wraplength=875,
        ).pack(anchor="w")
        actions = ttk.Frame(panel)
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 4))
        self.start_button = ttk.Button(actions, text="Start trip", command=self.start)
        self.pause_button = ttk.Button(actions, text="Pause", command=self.pause)
        self.resume_button = ttk.Button(actions, text="Resume", command=self.resume)
        self.finish_button = ttk.Button(actions, text="Finish trip", command=self.finish)
        self.discard_button = ttk.Button(actions, text="Discard from memory…", command=self.discard)
        for button in (
            self.start_button,
            self.pause_button,
            self.resume_button,
            self.finish_button,
            self.discard_button,
        ):
            button.pack(side="left", padx=(0, 8))
        self.receiver_button = ttk.Button(actions, text="Receiver controls", command=self.receiver)
        self.receiver_button.pack(side="right")
        inputs = ttk.Frame(panel)
        inputs.grid(row=4, column=0, sticky="ew", pady=6)
        self.file_button = ttk.Button(
            inputs, text="Open recorded path…", command=self.open_recording
        )
        self.file_button.pack(side="left", padx=(0, 8))
        self.example_button = ttk.Button(
            inputs, text="Load fictional example", command=self.example
        )
        self.example_button.pack(side="left")
        self.review_button = ttk.Button(
            inputs, text="Review saved GPX + map…", command=gps.open_review
        )
        self.review_button.pack(side="right")
        self.mode = tk.StringVar(value="NOT RECORDING")
        self.summary = tk.StringVar(value="No trip requested.")
        self.reason = tk.StringVar(value="Connect a local GPS receiver, or open a recorded path.")
        ttk.Label(panel, textvariable=self.mode, font=("TkDefaultFont", 13, "bold")).grid(
            row=5, column=0, sticky="w", pady=(10, 2)
        )
        details = ttk.Frame(panel)
        details.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(details, textvariable=self.summary).pack(anchor="w")
        self.reason_label = ttk.Label(details, textvariable=self.reason, wraplength=910)
        self.reason_label.pack(anchor="w", pady=(4, 0))
        drawing = ttk.LabelFrame(
            panel, text="Historical path sketch — NO BASE MAP; not a route to follow", padding=6
        )
        drawing.grid(row=7, column=0, sticky="nsew")
        self.canvas = tk.Canvas(drawing, background="white", highlightthickness=0, height=245)
        self.canvas.bind("<Configure>", self._resize)
        self.preview_notice = tk.StringVar(value="No captured history.")
        self.preview_label = ttk.Label(drawing, textvariable=self.preview_notice, wraplength=890)
        self.preview_label.pack(side="bottom", fill="x", pady=(4, 0))
        self.canvas.pack(fill="both", expand=True)
        footer = ttk.LabelFrame(
            panel,
            text="Explicit export — unencrypted private coordinates and receiver times",
            padding=10,
        )
        footer.grid(row=8, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(1, weight=1)
        ttk.Label(footer, text="Trip name").grid(row=0, column=0)
        self.name_entry = ttk.Entry(footer, textvariable=gps.trip_name)
        self.name_entry.grid(row=0, column=1, sticky="ew", padx=8)
        self.export_button = ttk.Button(footer, text="Export NEW GPX track…", command=self.export)
        self.export_button.grid(row=0, column=2)
        ttk.Label(
            footer,
            text="Pause or finish first. Existing files are not replaced. Gaps stay separate; no roads or turn instructions are added.",
            wraplength=900,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.poll()

    def _run(self, action):
        try:
            if self.gps.session is None:
                raise ValueError("Connect a serial receiver or open a recorded path first.")
            action(self.gps.session)
        except (ValueError, RuntimeError, OSError) as exc:
            messagebox.showerror("GPS trip", str(exc), parent=self)
        self.refresh()

    def start(self):
        self._run(
            lambda session: session.start_trip(
                consent=self.gps.trip_consent.get(), wgs84_confirmed=self.gps.datum.get()
            )
        )

    def pause(self):
        self._run(lambda session: session.pause_trip())

    def resume(self):
        self._run(
            lambda session: session.resume_trip(
                consent=self.gps.trip_consent.get(), wgs84_confirmed=self.gps.datum.get()
            )
        )

    def finish(self):
        self._run(lambda session: session.finish_trip())

    def discard(self):
        if not messagebox.askyesno(
            "Discard trip?",
            "Discard this trip from workspace memory?\nExported files are not deleted. Unsaved points cannot be recovered.",
            parent=self,
        ):
            return
        self._run(lambda session: session.discard_trip())
        self.gps._trip_exported_revision = None

    def receiver(self):
        self.gps.winfo_toplevel().deiconify()
        self.gps.winfo_toplevel().lift()

    def open_recording(self):
        if not self.gps.datum.get() or not self.gps.trip_consent.get():
            messagebox.showerror(
                "Recorded path", "Confirm WGS84 and private in-memory history first.", parent=self
            )
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="Inspect a recorded path — NOT LIVE",
            filetypes=[("NMEA recording", "*.nmea *.log *.txt"), ("All files", "*")],
        )
        if path:
            self.gps.load_recording(path, collect_track=True)
        self.refresh()

    def example(self):
        if self.gps.load_recording(
            Path(__file__).parent / "data" / "SYNTHETIC-TRIP.nmea", collect_track=True
        ):
            self.gps.trip_name.set("FICTIONAL SOFTWARE EXAMPLE")
        self.refresh()

    def export(self):
        try:
            session = self.gps.session
            if session is None:
                raise ValueError("No trip is available.")
            before = session.trip_summary()
            if before.state not in ("paused", "finished") or not before.point_count:
                raise ValueError("Pause or finish a nonempty trip before export.")
            if not self.gps.datum.get():
                raise ValueError("Confirm the recorded source uses WGS84 first.")
            path = filedialog.asksaveasfilename(
                parent=self,
                title="Export a NEW private GPX track",
                defaultextension=".gpx",
                filetypes=[("GPX track", "*.gpx")],
            )
            if not path:
                return
            # A dialog can run the Tk event loop. Bind export to the same source
            # and revision, and recheck consent/datum and state after it closes.
            if (
                self.gps.session is not session
                or session.trip_summary().revision != before.revision
            ):
                raise ValueError(
                    "The trip changed while choosing a file. Review it and export again."
                )
            trip = session.trip_snapshot()
            export_track(path, trip, self.gps.trip_name.get(), wgs84_confirmed=self.gps.datum.get())
            self.gps._trip_exported_revision = (id(session), trip.summary.revision)
            messagebox.showinfo(
                "GPX track saved",
                "Saved a new historical GPX track. Existing files and the household database were not changed.\n"
                "This file contains unencrypted private coordinates and receiver times. It is not a navigable route.\n"
                "The older FieldForge Places importer accepts waypoints, not tracks.",
                parent=self,
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("Track export", str(exc), parent=self)
        self.refresh()

    def _resize(self, event):
        self._render_key = None
        self.reason_label.configure(wraplength=max(450, event.width - 20))

    def refresh(self):
        if self._closed:
            return
        session = self.gps.session
        summary = session.trip_summary() if session is not None else None
        receiver = session.snapshot() if session is not None else None
        state = summary.state if summary else "idle"
        serial_running = receiver is not None and receiver.mode == "serial" and receiver.running
        permission = self.gps.datum.get() and self.gps.trip_consent.get()
        for button, enabled in (
            (self.start_button, serial_running and state == "idle" and permission),
            (self.pause_button, state == "recording" and summary.source == "serial"),
            (self.resume_button, serial_running and state == "paused" and permission),
            (self.finish_button, state in ("recording", "paused") and summary.source == "serial"),
            (self.discard_button, state not in ("idle", "reading")),
            (
                self.export_button,
                state in ("paused", "finished")
                and summary.point_count > 0
                and self.gps.datum.get(),
            ),
            (
                self.file_button,
                state == "idle" and permission and not (receiver and receiver.running),
            ),
            (
                self.example_button,
                state == "idle" and permission and not (receiver and receiver.running),
            ),
        ):
            button.configure(state="normal" if enabled else "disabled")
        if summary is not None and summary.state != "idle":
            prefix = (
                "RECORDED FILE — NOT LIVE"
                if summary.source == "recorded"
                else "SERIAL TRIP — CAPTURED HISTORY"
            )
            self.mode.set(prefix + " · " + state.upper())
            self.summary.set(
                f"{summary.point_count:,} / {summary.limit:,} points   ·   {summary.segment_count:,} segments   ·   "
                f"Approx. connected-point length: {summary.distance_m / 1000:.3f} km (gaps excluded)"
            )
            self.reason.set(summary.reason)
        else:
            self.mode.set("NOT RECORDING — no automatic location history")
            self.summary.set(
                "No captured trip. Start begins with the next accepted position, not an old displayed fix."
            )
            self.reason.set(
                summary.reason
                if summary
                else "Connect a local GPS receiver, or inspect the fictional example."
            )
        key = (
            id(session),
            summary.revision if summary else 0,
            self.canvas.winfo_width(),
            self.canvas.winfo_height(),
        )
        if key != self._render_key:
            self.draw(session.trip_snapshot() if session else None)
            self._render_key = key

    def draw(self, trip):
        canvas = self.canvas
        canvas.delete("all")
        width, height = max(100, canvas.winfo_width()), max(100, canvas.winfo_height())
        if trip is None or not trip.segments:
            canvas.create_text(
                width / 2,
                height / 2,
                text="No captured path\nNothing is saved automatically.",
                justify="center",
                font=("TkDefaultFont", 13),
            )
            self.preview_notice.set(
                "Path history is not a current GPS fix. No base map is included in this sketch."
            )
            return
        preview = sketch(trip, width, height)
        for index, segment in enumerate(preview.segments):
            coords = tuple(value for point in segment for value in point)
            if len(segment) > 1:
                canvas.create_line(*coords, width=2, tags=("segment", f"segment-{index}"))
            x, y = segment[0]
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill="white", width=2, tags=("start",))
            x, y = segment[-1]
            canvas.create_rectangle(x - 3, y - 3, x + 3, y + 3, tags=("end",))
        canvas.create_text(18, 14, text="N ↑", anchor="nw")
        canvas.create_text(width - 12, 14, text="HISTORY — NOT NAVIGATION", anchor="ne")
        self.preview_notice.set(
            f"Showing {preview.shown_points:,}/{preview.total_points:,} points in {preview.shown_segments:,}/{preview.total_segments:,} segments. "
            "Open circle = segment start; square = end. Gaps are not joined. Preview may be simplified; GPX retains all captured points."
        )

    def poll(self):
        if not self._closed:
            self.refresh()
            self._after = self.after(500, self.poll)

    def _destroyed(self, event):
        if event.widget is self:
            self._closed = True
            if self._after is not None:
                self.after_cancel(self._after)
                self._after = None

    def close(self):
        self._closed = True
        if self._after is not None:
            self.after_cancel(self._after)
            self._after = None
        self.destroy()
