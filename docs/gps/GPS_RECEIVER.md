> Historical milestone notes. The workspace is now integrated into FieldForge.
> For current launch paths, PNG/JPEG/WebP MBTiles and image-file support, see
> [GPS workspace](../GPS_WORKSPACE.md). Older verification counts and standalone
> packaging boundaries below describe their original milestone.

# FieldForge GPS Receiver — retained in GPS Review 0.3

## What this adds

A separately launchable receiver workspace, strict parsing of a documented subset
of NMEA RMC/GGA sentences, optional local serial input, recorded-file inspection,
explicit GPX waypoint export and optional manual centering of an existing
FieldForge raster map. Version 0.2 also adds explicit in-memory trip capture and
recorded-path inspection in the Trips window; see GPS_TRIPS.md. It does not
download new maps or provide road directions. Version 0.3 adds a separate
read-only GPX review window with a bundled coarse overview; see GPS_REVIEW.md.

This is an additive development checkpoint. It is **not** a replacement for the
newer regional-index map build, a FieldForge.exe update, a signed installer, a
native phone app, a merged GitHub change or a verified physical GPS device test.

## Start on Windows

Extract this entire add-on into a **new folder**. Double-click
`Start FieldForge GPS.cmd`. Python 3.10 or later with Tk is required. The launcher
uses a `.venv` in that folder when present, then `py -3`, then `python`. It installs
nothing. A packaged FieldForge.exe does not supply Python to this source add-on.

On any supported desktop with Python and Tk:

```text
python -m fieldforge_gps
```

The first screen is disconnected. No port is selected or opened automatically,
no location is requested and no household database is opened.

For an offline software demonstration, open
`examples/SYNTHETIC-GPS-EXAMPLE.nmea` with **Open recorded NMEA**. The coordinates
are fictional test values, not a new map dataset or a physical receiver recording.
The banner always says **RECORDED FILE — NOT LIVE**. A recording is never treated
as the user's present position, even if its timestamps happen to match today.

## Connect a receiver deliberately

The receiver must expose a local serial device and emit the supported NMEA text
messages. USB/Bluetooth serial receivers may qualify; a phone's built-in location
service does not automatically become a serial port.

Use the port identified for **your GPS receiver**, such as `COM3` or
`/dev/ttyACM0`, and the baud rate configured on it. Never probe an unknown device.
Only 4800, 9600, 19200, 38400, 57600 and 115200 baud are accepted. The application
uses 8 data bits, no parity, one stop bit and no flow control. It sends no command
payloads. Opening a port can still change hardware control lines through its
operating-system driver; the code requests DTR/RTS off before opening.

Live serial input needs the optional **pySerial** package. Install it separately
in the Python environment used by the launcher, before offline deployment:

```text
python -m pip install "pyserial>=3.5,<4"
```

No installation is attempted by the app. Recorded-file inspection, parsing and
GPX export do not need pySerial. Network serial URLs, socket/rfc2217 transports,
relative device paths and automatic port scanning are not supported.

**Verify the receiver's coordinate datum is WGS84**, then select the checkbox.
RMC/GGA messages alone do not prove the receiver datum. The checkbox records only
the operator's assertion for the current session; it is not a datum conversion
or verification service. Recorded positions require the same assertion before
copy/export/map centering.

## What is accepted and what is hidden

A checksum-valid, supported **dated RMC** message establishes a candidate
position. GGA alone never establishes a dated position. RMC status V,
estimated/manual/simulator/unknown positioning modes, unsupported navigation
status, GGA no-fix or unsupported quality, or a malformed supported input clear
the displayed candidate rather than retaining an apparently current location.

The supported talkers are GP, GN, GL, GA, GB, BD, GQ and GI. The supported RMC modes
are absent/blank legacy mode, A, D, R, F and P; a supplied navigation-status field
must be S. Supported GGA qualities are 1, 2, 4 and 5. Other qualities are rejected
conservatively, including quality 3, which is outside this add-on’s supported subset. Only fields
used by this subset are interpreted; it is not a full NMEA implementation or
compliance certification.

For serial input, the most recent *advancing* receiver timestamp must have arrived
less than **5 seconds** ago, and receiver UTC must agree with the computer's aware
UTC clock within **10 seconds**. Otherwise the position is hidden. Check both
clocks if they disagree. There is no "trust stale coordinates" override. This
bounds freshness, not receiver accuracy, spoofing resistance or navigational
safety. A falsely timestamped receiver stream can still pass these checks.

Repeated or backwards RMC timestamps do not renew freshness. Conflicting positions
at the same receiver timestamp invalidate the candidate. A no-fix observation
cannot be undone by repeating the previous positive timestamp. GGA never repairs
a void RMC by itself. GGA no-fix ordering uses UTC time-of-day and a conservative
half-day window; unusual restarts or multi-receiver interleaving can require a
new session. Do not combine several receivers into one stream.

Two-digit RMC years are interpreted in the **1980–2079** window. GPS week rollover,
leap-second instants, unsupported timestamp precision and other datum conversions
are not repaired automatically. Course is course-over-ground, not a stationary
compass heading. HDOP is not converted into an accuracy radius. No promised
position accuracy, arrival time, safe crossing or route availability is given.

## Local recording limits

The reader accepts an ordinary, stable local file of at most **8 MiB**, streams it
in 4096-byte blocks. Ordinary Receiver inspection retains only the latest
candidate/diagnostics/counters. Explicit Trips inspection additionally retains a
bounded path in memory as described in GPS_TRIPS.md.
Symlinks, FIFOs, devices, directories, oversized inputs and detected changes while
reading are refused. Sentences are bounded to **512 bytes**; this accommodates
long vendor precision fields without unbounded buffering. Bad checksums, control
characters, impossible coordinates and unsupported field shapes are rejected.
An unterminated final record is rejected rather than guessed complete.

The file is read in a worker. A partial recording is never offered for export.
The exact bytes read receive a SHA-256 fingerprint; this identifies bytes, not
a trusted publisher. File stability checks are not protection against every
hostile concurrent filesystem change. Use trusted local files and maintained
Python/Tk/OS dependencies. The original recording is never edited.

## Export and map integration

**Export new GPX waypoint** saves one explicit captured position. It does not
record a track; that is a separate, explicit Trips action in version 0.2. Replayed points retain the RECORDED label, receiver UTC and source
fingerprint in the description; FieldForge's existing waypoint importer retains
that description as private notes. Serial exports also include receiver UTC.
The existing importer may omit the separate GPX time field, so the description
preserves the same time. No private source file path or device identifier is put
in the GPX. Coordinates remain private data; GPX is unencrypted.

Export rechecks the selected position after the save dialog closes. Existing
files or symlinks are never overwritten. A temporary file is flushed then linked
to a new destination atomically. This requires hard-link support on the output
filesystem; unsupported filesystems fail without an overwrite fallback. The
temporary file is removed on ordinary success or failure. A process/OS crash can
leave a temporary file. Save to a suitable local filesystem, then copy the
completed export to another device deliberately.

To use the optional local map with a **source** FieldForge build, copy only the
`fieldforge_gps` directory and `Start FieldForge GPS.cmd` alongside that build's
existing `fieldforge` directory. Do not replace the old project folder or copy
this add-on's packaging configuration over FieldForge's `pyproject.toml`.
Then use **Open FieldForge local map**, load an existing trusted PNG MBTiles pack,
and choose **Center map on displayed position**. No map downloads, route snapping,
GPS-follow marker or automatic recentering occur. The map window title identifies
a captured/recorded position and its receiver timestamp. Its center remains a
static, manually selected location, not a continuously live indicator.

The optional integration uses the existing MapsTab with `database=None`. It does
not load saved places or edit the household database. Web Mercator cannot display
polar positions beyond the viewer's existing limit; those center requests are
refused. Compatibility was tested against source baseline
`94dcdcecd93e928a65e9ed9b35c87962732fc3e2`. The latest regional-index ZIP could not
be materialized in this session, so compatibility with that exact full build is
not claimed. All newer maps remain untouched.

For developers, the parser and session modules are reusable without Tk. Each
connection creates a new Session; stop invalidates it immediately and old-worker
results cannot populate a new session. Callers using snapshot/export APIs must
obtain a fresh snapshot at the time of the user's explicit action. Snapshots are
immutable captures, not permanently valid location permissions.

## Testing and remaining work

See the accompanying verification report for actual run counts. Serial transport
and failure behavior are exercised with injected test receivers and an adapter
contract test; **no physical GPS receiver or native Windows/macOS device was
available**. These are not hardware-compatibility claims. Desktop controls and
existing-map centering are tested under Linux/Tk/Xvfb. Native phone integration,
full map-build reconciliation, real serial hardware trials and validated road
navigation remain outstanding.

No new project-wide code redistribution license is selected by this add-on.

## Primary technical references

Consulted October 2, 2026. These inform the supported subset, not a claim of full
standards compliance.

- Trimble RMC: https://receiverhelp.trimble.com/alloy-gnss/en-us/NMEA-0183messages_RMC.html
- Trimble GGA: https://receiverhelp.trimble.com/alloy-gnss/en-us/NMEA-0183messages_GGA.html
- NovAtel RMC and datum/mode notes: https://docs.novatel.com/OEM7/Content/Logs/GPRMC.htm
- pySerial local port API: https://pyserial.readthedocs.io/en/latest/pyserial_api.html
- GPX 1.1 schema: https://www.topografix.com/GPX/1/1/
