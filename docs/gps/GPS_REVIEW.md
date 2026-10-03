> Historical milestone notes. The workspace is now integrated into FieldForge.
> For current launch paths, PNG/JPEG/WebP MBTiles and image-file support, see
> [GPS workspace](../GPS_WORKSPACE.md). Older verification counts and standalone
> packaging boundaries below describe their original milestone.

> Version 0.4 note: launchers now open the cumulative local-map viewer.
> The original coarse-only behavior below remains available without a selected map.
> See LOCAL_MAPS.md for raster-map permissions, supported formats, and limitations.

# Saved GPX review — GPS add-on 0.3

The new reviewer reads saved trip history without taking ownership of a receiver
Session. It can be launched alone (`python -B -m fieldforge_gps --review`) or from
**Review saved GPX + map** in Trips. It is a separate source add-on, not a new
FieldForge executable, a regional-map replacement or a mobile application.

## Use and privacy

Select the WGS84 and private-history checkboxes before opening a local file. WGS84
is the user's assertion, not an automatic datum detector or a coordinate
transformation. Selecting a file is a read request; there is no file discovery,
automatic import, telemetry, online map fetch or history database.

A completed review is immutable. A new file replaces the view only after it has
been read and checked successfully. Malformed files, cancellations, ordinary
source-file change detection and exceeded limits leave the previous review
unchanged. Clear, or revoke either checkbox, to drop the review and cancel a
pending import. Rechecking permission does not reopen a file. Clear and close
are not secure RAM, operating-system swap, clipboard or disk erasure.

The reviewer does not save or edit GPX files. Their original metadata and
extensions remain in the original files even when not displayed. Use the Trips
exporter to create a new GPX from captured receiver history; use **Open saved
GPX** to reopen it here. There is no implicit GPX-to-Places conversion, active-trip
merge or promotion from a recorded file to a live position.

## Supported input and refusal rules

The reader supports UTF-8 (including a UTF-8 BOM), namespaced GPX 1.1 documents
with `version="1.1"` and a `creator` attribute. A namespace prefix is allowed.
Track names, direct `trk/trkseg/trkpt` structure, latitude/longitude, optional
point elevation and optional point time are inspected. Track and point order
and all nonempty file-defined segments are preserved.

Latitude must be a finite decimal in [-90,90]; longitude must be a finite decimal
in [-180,180). Exponent notation is not accepted for GPX decimal fields. Missing
coordinates, duplicate interpreted fields, nested markup in a plain-text field,
and misplaced native track structure reject the entire file. Bad points are not
silently skipped and neighboring points are not connected around them.

Supplied times accept the documented ISO calendar-date/time subset, with optional
fractional seconds and optional `Z` or signed time-zone offset. Missing times stay
missing. Naive times are displayed as **timezone not supplied; NOT assumed UTC**.
The original valid time string is retained, including its fractional precision.
Time-zone offsets are bounded to 14 hours, as supported by this reader. Leap
seconds, 24:00, expanded years and other date/time forms outside this subset are
refused. Times and elevation are file values, not independently verified sensor
measurements. No speed, ETA or present-position claim is derived from them.

GPX 1.0, unnamespaced XML and non-UTF-8 encodings are not accepted. Root routes and
waypoints are counted but not rendered or converted into tracks. Empty tracks and
segments are counted and omitted from the drawable view. Other metadata,
extensions, fix-quality fields, accuracy fields, speed fields and links are not
interpreted. No links, external schema references or processing instructions are
executed. DTD/entity declarations and XML processing instructions are rejected.
This is not a full XML Schema validator or a certification of source authenticity.

Bounds: 16 MiB source bytes, 50,000 track points, 200 tracks, 10,000 segments,
250,000 XML elements, 32 nesting levels, 16,384 characters of direct element text,
64 attributes per element, and 160 characters per track name. Names are displayed
as plain text; control and bidirectional-formatting characters are removed from
the label, not rewritten in the file. The GPX reader refuses an Expat version
older than 2.6.0; this minimum check is not a substitute for security updates.

## File and worker behavior

The reader checks a selected regular file before and after reading. It refuses
leaf symlinks, directories, device files and pipes. The open file descriptor and
final selected pathname are compared using ordinary device/inode/size/mtime/ctime
signatures. Reads are bounded even if the file grows. These checks do not provide
a tamper-proof filesystem snapshot, trusted authorship or protection from an
adversary controlling the filesystem. The displayed SHA-256 identifies exactly
the bytes inspected, not who created them or whether the trip was real.

Parsing occurs in one bounded worker. Workers never call Tk. Only a completed
result crosses a queue into the main UI loop; cancellation and current permission
are rechecked before publication. A cancelled worker must finish before another
read starts, preventing a buildup of concurrent parsers. Closing the window
signals cancellation and drops displayed history. Destruction explicitly removes
owned variable traces and releases window references on the UI thread, rather
than leaving their finalizers to cyclic garbage collection in a parser thread.
Unresponsive storage may still
delay an underlying operating-system read; use local files, not network shares.

## Offline map and display limits

The bundled JSON overview is derived from the installed pyogrio
`naturalearth_lowres` fixture. Its original observation/release vintage was not
established; it was not newly downloaded or verified as current. Administrative
polygons were dissolved into land outlines. All resulting rings were retained,
with coordinates rounded to six decimals. The runtime only needs the resulting
JSON, not pyogrio, pyshp or Shapely. Provenance, input hashes, development-library
versions and a rebuild script are provided in `sources/` and `tools/`.

The overview contains 128 rings and 5,165 vertices. This is coarse geographic
orientation: small islands and local detail may be absent or inaccurate. It is
not street coverage, bathymetry, terrain, a navigational chart or an assertion
about territorial boundaries. The application checks the JSON hash before use;
a missing or changed overview is reported, with no online fallback.

The canvas uses an equirectangular display with north up. It is not conformal or
equidistant; screen distances and shapes are distorted. Fit uses the smallest
longitude arc. Edges crossing the date line are split at the map edge rather than
joined through the center of the world. At close zoom a notice says that local
road and terrain detail is not loaded. Pan and zoom never download content.

The display uses at most 8,000 track points. Display sampling retains the ends of
shown segments. If even segment endpoints exceed the budget, whole trailing
segments are omitted from the preview. The displayed/total point and segment
counts disclose that limitation. Some prepared points can also be off-screen.
Point inspection still accesses the complete accepted document, not the sampled
preview. No separate segments are joined. Only gaps explicitly present in the
GPX are known; undocumented gaps cannot be reconstructed.

Connected-point length sums approximate spherical separations within segments,
excluding gaps and elevation. It is not road distance, an odometer measurement,
actual distance traveled or evidence that a path is safe or accessible. File
points and the selected-point marker remain labeled historical, not live.

## Reproduce tests

From this source folder, with pytest and a working Tk display:

```sh
python -m pytest -o addopts= -q -ra tests/gps_addon
```

The observed Linux run used:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 xvfb-run -a python -m pytest -o addopts= -q -ra tests/gps_addon
```

The GUI test harness creates a separate Tcl interpreter for each test. Its
autouse fixture collects destroyed test-interpreter cycles on the test/UI thread
before and after each GUI test. It does not change production GC behavior, extend
existing test deadlines, or suppress warnings. Final runs used `-W error`.

Five inherited tests need the separately installed main FieldForge map/Places
modules. They skip when that source is absent; see the actual report. No main
program tests or the newer regional-index regression are claimed for this update.

The included wheel can be installed into a fresh target without dependency/index
access, then checked outside the source tree with the installed-smoke script.
That script uses fictional data, temporary outputs and a temporary sentinel
household database. Pillow is needed only for its screenshot capture, not by the
application. See `VERIFICATION.txt` and `verification/installed-review-smoke.json`.

## Primary references

GPX schema and format semantics:
https://www.topografix.com/GPX/1/1/

Python XML security considerations:
https://docs.python.org/3/library/xml.html#xml-vulnerabilities

Python Expat handlers and parser-version behavior:
https://docs.python.org/3/library/pyexpat.html

Natural Earth dataset terms (public-domain map data, not a license for FieldForge):
https://www.naturalearthdata.com/about/terms-of-use/

Reference links are documentation only; the application does not open them.
