> Historical milestone notes. The workspace is now integrated into FieldForge.
> For current launch paths, PNG/JPEG/WebP MBTiles and image-file support, see
> [GPS workspace](../GPS_WORKSPACE.md). Older verification counts and standalone
> packaging boundaries below describe their original milestone.

# GPS Trips — capture/export behavior introduced in 0.2, retained in 0.3

This is an updated version of the separately runnable GPS Receiver source add-on,
not a competing replacement for the full FieldForge application. Extract into a
new folder. The main project, newer map packages, household database and existing
GPS add-on are not modified by extraction or normal startup.

## What is implemented

The Trips window adds Start, Pause, Resume, Finish, Discard, recorded-path
inspection, a bounded historical path sketch and explicit GPX track export.
The original receiver panel, strict NMEA parsing, manual waypoint export and
optional manual existing-map centering remain available.

The Trips sketch itself has no base map. Version 0.3 adds a separate read-only
saved-GPX reviewer with a coarse offline overview; see GPS_REVIEW.md. There is
still no new street coverage, road graph, route instruction, geocoder, map-follow
marker, native mobile integration or automatic recording. The NMEA example is
original fictional software-test input, not a physical trace or real travel advice.

## Use

Open `Start FieldForge Trips.cmd`, or run `python -m fieldforge_gps --trips` from
the extracted folder. Python 3.10+ with Tk is needed; the Windows command file is
a source launcher, not a bundled executable. pySerial remains an optional,
separately installed dependency for a local serial receiver. Recorded files and
the fictional example need no pySerial and no network.

For the fictional example, select the WGS84 and in-memory-history checkboxes,
then click **Load fictional example**. Its 30 dated positions form 3 segments.
One intentionally bad-checksum line and a later no-fix/time gap exercise breaks.
The persistent **RECORDED FILE — NOT LIVE** label is deliberate even when a file's
receiver timestamps happen to match today's date.

For serial input, connect an identified GPS receiver through **Receiver controls**.
In Trips, explicitly confirm both checkboxes and click **Start trip**. This begins
with the next new accepted RMC position; it does not copy a previously displayed
fix. A paused trip ignores new points. Resume explicitly starts another segment.
Finish prevents further capture. To switch sources or start a new trip, export
wanted history, then discard the old trip; source switching cannot silently
replace it. A disconnected serial trip remains historical data, not a current fix.

Unchecking WGS84 or history consent immediately pauses serial recording. Rechecking
does not resume it. The datum is an operator assertion, not an automated check or
coordinate conversion. An already requested recorded-file inspection is not a live
capture; revoking datum still blocks export. Disconnect cancels an unfinished file
read and discards its partial path.

Closing the Trips window does not end an active capture. The Receiver window
continues to show recording state and point/segment counts. Exit from the Receiver
window warns about active, pending or unsaved history. A matching exported
revision does not need another unsaved-history warning. A process crash cannot
show such a warning and loses unsaved history.

## Capture and interruption rules

The worker updates the recorder while holding the same lock used by the receiver
state machine, once per newly accepted dated RMC position. It does not poll a GUI
snapshot to collect points, so an invalid sentence between two good positions in
one serial read still creates an interruption. UI code never runs on the worker.
The recorder stores latitude, longitude and aware receiver UTC only. It does not
store raw sentences, serial identifiers, source filenames, altitude, speed or
an invented accuracy estimate in each point.

Serial history uses the existing receiver visibility checks: advancing dated
positions, receipt age below 5 seconds and receiver/system UTC difference no more
than 10 seconds. Observed invalid/no-fix conditions, stale or clock-mismatched
visibility, pauses, receipt-time discontinuities, or receiver timestamp gaps of
at least 5 seconds break continuity. Valid repeated epochs are ignored by the
session; conflicting same-epoch positions invalidate it. Unrecognized checksum-valid
sentences do not establish a new point. No missing positions are interpolated.

These are conservative application rules, not NMEA certification, spoofing
protection or a claim that every possible loss of reception is detectable. A
receiver that falsely reports plausible positions can pass. Jitter, missing
samples and unrecognized conditions can affect the resulting history. See the
Receiver document for its supported subset and 1980–2079 date window.

Capture is bounded at **50,000 points**, with no rolling overwrite or silent
replacement. At the limit the trip finishes with a visible partial-trip warning.
Higher-frequency receivers reach the limit sooner. No background autosave occurs.
The user must export/discard and explicitly start another trip to continue.

## Recorded input integrity

Recorded path inspection is separately requested and cannot be promoted to serial
mode. It uses the existing 8 MiB stable-regular-file reader and strict sentence
framing. The entire input is read and fingerprinted; public snapshots hide all
partial path points until validation completes. Detected modification, unreadable
input or cancellation discards the partial path. A complete file may contain
rejected sentences: these form gaps rather than fabricated positions.

The SHA-256 records the input bytes that were inspected; it is not proof of a
trusted author or a real physical receiver. The point cap can produce a deliberately
partial path from an otherwise fully fingerprinted file. The UI/export disclose
when the cap has been reached. Input files are opened read-only and not rewritten.

## Sketch and distance

The sketch is a relative, longitude-unwrapped, approximately equirectangular view.
It contains no roads, obstacles or terrain. North is up in this sketch. An open
circle marks a displayed segment start and a square its end. No line is drawn
between separate segments. A single point remains a point, not a fabricated line.

Rendering is capped at 5,000 displayed points and 1,000 displayed segments. A
caption discloses the shown/total counts. Within displayed segments, points may be
sampled for preview, preserving their endpoints. All captured points remain in
memory and in GPX export, subject to the separate 50,000-point capture limit.
Longitude unwrapping happens before point sampling to handle dateline crossings.
This schematic is not an authoritative world projection or a route to follow.

The displayed length sums approximate spherical point-to-point distances only
within segments, using radius 6,371,000 metres. It excludes gaps, height and road
shape. It is not a calibrated odometer, road distance, actual distance traveled,
arrival prediction or proof of safe passage. GPS noise can increase this sum.

## GPX and privacy

Export requires a paused or finished nonempty trip and an explicit WGS84 assertion.
The save action rechecks source identity and trip revision after its modal dialog.
The exporter validates coordinates, advancing UTC timestamps and segment/point
counts. It writes GPX 1.1 `trk`, `trkseg` and dated `trkpt` elements, not a route.
Rounded longitude output stays inside the GPX longitude interval. The same
rounding-edge correction is included in the original waypoint exporter.

Recorded exports carry **RECORDED — NOT LIVE** and the source fingerprint; serial
exports carry **CAPTURED HISTORY**. Both identify history rather than a current
location. There is no hostname, receiver port, local source pathname or household
record in export metadata. User-entered names are validated and XML-escaped.

GPX remains unencrypted private location history. Share it only deliberately.
The no-clobber writer creates a private temporary file in the chosen directory,
flushes it, and publishes a new name with a hard link. Existing files, directories
and symlinks are not replaced. Unsupported output filesystems fail without an
unsafe overwrite fallback. Ordinary publication errors clean up the temporary
file; an OS/process crash may leave one. This is not an encryption, secure-delete
or power-loss-durability guarantee. Use a trusted local destination directory.

**The older FieldForge Places importer deliberately refuses GPX tracks.** This
package does not change that importer. Single-waypoint export remains a separate
action in Receiver controls. Compatibility with third-party GPX applications is
not independently certified by these tests.

Discard drops workspace references to the trip; it is not secure erasure of RAM,
OS swap, crash dumps, backups or existing GPX copies. Default startup stores no
track. There is no application-created history database or telemetry.

## Development integration and verification

Nine production Python modules and a fictional package-data example are included.
The recorder and export modules can be reused without Tk. `Session` provides
`start_trip`, `pause_trip`, `resume_trip`, `finish_trip`, `discard_trip`,
`trip_summary` and `trip_snapshot`; recorded capture is explicitly selected with
`start_recording(..., collect_track=True, consent=True, wgs84_confirmed=True)`.
The summary avoids copying the full path on routine status polls. Snapshots are
immutable captures, not live position permissions. Session owns recorder locking.

`GPS-TRIPS-v0.1-to-v0.2.patch` is a developer change set for the previous standalone
GPS add-on, not a patch to apply blindly to FieldForge main. Run `git apply --check`
on a separate development copy first. It updates code, tests, launchers and
documentation, not old wheels or verification records; use this ZIP's current
`VERIFICATION.txt`. Do not overwrite a newer implementation or FieldForge's main
`pyproject.toml`. The wheel is likewise a source-package delivery,
not a FieldForge.exe update. Consult `VERIFICATION.txt` for exactly what was run.

The newer regional-index ZIP could be located but not materialized through Library
in this session; it was not reconciled, replaced or retested. GitHub PR #1 was read,
but no GitHub write/merge/release was performed. Physical GPS hardware, native
Windows/macOS/mobile execution and newest-map integration remain unverified.
No project-wide redistribution license is selected by this update.

## Primary references

Consulted October 2, 2026. GPX structure/datum/segment semantics follow the source
below; thresholds, privacy controls and the sketch are application design choices.

- GPX 1.1 schema documentation: https://www.topografix.com/GPX/1/1/
- Python filesystem operations (`os.link`, `os.fsync`): https://docs.python.org/3/library/os.html
- Python private temporary files (`mkstemp`): https://docs.python.org/3/library/tempfile.html

These are reference links, not network dependencies of the application.
