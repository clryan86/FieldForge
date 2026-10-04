# GPS and raster-map integration verification

This change integrates the combined receiver/map/place workspace into the main
FieldForge desktop, adds JPEG/WebP decoding to both MBTiles readers, and adds
an uncalibrated local-image reference viewer. Household database schemas and
backup formats are unchanged. External maps/images remain outside backups.

## Completed local checks

- Full source regression: **2,276 passed, 15 skipped, 2 warnings in 125.15s**.
  Linux, Python 3.12.3, Tk 8.6.14, Pillow 12.3.0, pypdf 6.19.0; real Tk under
  Xvfb with `FIELDFORGE_REQUIRE_GUI=1`. Third-party pytest plugin autoload was
  disabled. The 15 skips are the existing opt-in Pocket browser tests, which
  remain separately required in GitHub Actions. The two warnings are existing
  synthetic PDF fixture uses of deprecated pypdf `add_js`.
- Focused raster/desktop checks: **106 passed in 22.07s**. Real JPEG/WebP tiles
  pass through both readers at 256 and 512 pixels. Image tests exercise PNG,
  JPEG, WebP, TIFF, BMP, GIF, ICO, PPM, TGA, JPEG 2000 and AVIF. Tests also cover
  corrupt/mismatched/animated tiles, source-byte preservation, first-page
  behavior, resource bounds, pan/zoom, revocation and late-worker cancellation.
- The complete suite includes the five previously standalone/main-map
  integration checks, plus actual desktop close/cancel handling for unsaved GPS
  trips. No main-application integration test was skipped.
- Ruff passed. The repository does not have a formatter gate; existing files
  were not globally reformatted.
- Built a wheel and installed it in a separate directory. From `/tmp`, both
  packages resolved to that installation. All six source installation checks
  passed, including real PDF extraction, backup recovery, fictional map/place
  resources, JPEG/WebP decoding and the image-viewer window. This is source-mode
  Linux verification, not a Windows executable result.

## Required CI checks

Existing Python 3.10/3.12/3.13.16, Linux GUI, Windows source, Pocket browser,
Windows portable and source archive gates remain enabled. GUI jobs require a
working display for GPS tests. The installed-wheel job verifies bundled GPS
map/place resources away from source.

The Windows build now includes GPS resources, pySerial and Pillow with component
notices. The relocated executable diagnostic must open the combined workspace,
render the fictional map/catalogue and JPEG/WebP image references, then stop its
workers, without opening serial hardware or starting recording. Only the exact
bundled fictional MBTiles fixture may pass the archive's database-file exclusion;
arbitrary maps, altered fixtures and household databases remain rejected.

Windows executable results must be read from the Actions run for the published
commit. Local Linux results do not establish physical GPS accuracy, native mobile
support, map freshness or compatibility with every possible MBTiles/image file.

## Compatibility follow-up

The first GitHub run found Python 3.10's stricter fractional-second parser and a
wrong attribute in the new installed-wheel assertion. Timestamp validation now
uses a six-digit temporary value while preserving the exact original string;
the wheel assertion uses the GPS reader's `levels` field. The image viewer's
help/status labels also wrap to the available width at its minimum window size.
Focused GPX/image/installation regression after these fixes: **110 passed in
4.63s**, with Ruff and the corrected installed-wheel resource check passing.
The first run's Linux GUI and both browser jobs passed. Final platform/build
outcomes belong to the subsequent CI run for the updated commit.

## Windows build-input follow-up

The prior branch's Windows portable job (run 36965937481, job 110712768317)
failed before this integration because the installed Tcl `license.terms` was
absent. Matching upstream Tcl/Tk 8.6.15 notices are now retained under
`packaging/notices/`, with exact CPython source-dependency commit references and
SHA-256 hashes. The build reads the actual Tcl/Tk runtime versions and only uses
these fallback files when the version and hash match. Missing, modified or
unknown-version notices still block distribution. There is no build-time notice
download and no change to the project license.

Packaging/runtime unit checks: **30 passed**. Combined packaging, desktop and
image checks: **45 passed in 4.10s**. Unexpected error dialogs in the new desktop
tests fail immediately instead of awaiting an unattended modal response;
Windows CI prints individual test names for diagnosis. The preceding updated
run passed all three Python/wheel jobs, Linux GUI and both browser jobs; Windows
jobs were still running at this follow-up. Frozen-binary verification remains a
required gate and is not claimed by these local build-input tests.

## Windows compatibility repair — 2026-10-03

Run 37092436078 timed out on both Windows versions. Its logs showed a two-MiB
parameter value being used as a test label, overwhelming console output and
preventing usable failure reporting. Parameter IDs now use bounded size/hash
labels for long strings/bytes. All MBTiles collection lines are below 512
characters, including the same oversized tile input; no test payload was reduced.
Windows map/GPS tests run in a separate required job with a 15-minute limit,
while existing Windows workflows retain a 30-minute limit and both matrix
versions report independently.

Map-related fixes address the reported failures:

- `.gitattributes` preserves exact runtime-data and pinned-notice bytes on
  Windows. A checkout with `core.autocrlf=true` preserved all 13 files and the
  declared overview hash. This also protects the notice checksums during builds.
- GPX, image and place readers compare ctime before/after within the same file
  API. Path `stat` and descriptor `fstat` can give ctime different meanings on
  Windows; their cross-check still compares device, inode, size and mtime. Both
  full before/after checks remain, so descriptor changes and path replacement
  are rejected. Regression tests simulate differing clocks and changed files
  across all three readers. Upstream context:
  https://github.com/python/cpython/issues/157671
- Filename coverage uses spaces, Unicode and `#` on every platform; the literal
  `?` case runs on POSIX because Windows forbids that filename character.

Local verification: **311 focused reader checks passed**; the full Linux/Tk
suite passed **2,295 tests, 15 browser skips, 2 existing PDF deprecation warnings
in 131.03s**. Ruff and staged whitespace checks passed. Windows and frozen-app
results must come from the Actions run for this repair, not the earlier cancelled
runs or these local simulations.

## Windows source results and pySerial packaging follow-up

Run 37126817185 passed every source gate, including both Windows versions.
Windows map/GPS jobs each passed **929 tests with 4 platform-specific skips**
(105.45s on Python 3.13.16; 109.43s on 3.12). Both Windows local-data suites,
all three Linux Python/wheel jobs, Linux GUI and Chromium/WebKit also passed.

Both Windows executables compiled, then the portable job stopped because the
published pySerial 3.5 wheel contains no license file. Its exact upstream BSD
notice is now retained with an immutable source reference under
`packaging/notices/pyserial-3.5/`. This fallback requires both the installed
version and the notice SHA-256 to match. Installed license files take precedence;
missing, altered or unknown-version notices still stop the build. The bundle
includes notice provenance. Recorded-but-missing license paths no longer count
as a successful notice collection.

The focused packaging/runtime suite passed **37 tests** and Ruff passed.
Notice selection also passed against extracted, unmodified Windows x64 wheels
for Pillow 12.3.0 and PyInstaller 6.22.3, plus the universal pypdf 6.19.0 and
pySerial 3.5 wheels. This verifies build inputs without importing Windows native
libraries on Linux. Frozen executable verification remains required in the next
Actions run.

Run 37127830560 passed the added notice checks, all Linux jobs and both browser
jobs. Each Windows map job passed 935 tests, but the next Tk root after the
direct-destruction test failed to read installed Tcl/Tk scripts during fixture
setup; subsequent GUI tests passed. A similar intermittent initialization error
is reported at https://github.com/actions/setup-python/issues/1102. This does
not establish that the installed scripts were actually missing.

Both Windows test commands now use `--capture=sys` to keep native standard
handles stable while independent test interpreters are destroyed and recreated.
The previous default capture repeatedly duplicated/replaced native descriptors;
that interaction is the suspected cause, to be checked by the next Windows run.
Python output remains captured and native output goes to the job log. No Tk
error is retried, skipped or suppressed, and all GUI assertions remain required.
The matching local desktop/image/packaging checks passed **56 tests in 5.01s**
with this capture mode; Ruff and whitespace checks passed.

Run 37128237827 passed all ten source jobs. Both Windows map jobs passed
**936 tests with 4 platform-specific skips** (108.34s on 3.12, 101.63s on
3.13.16), including the previously failing fixture. The portable build compiled
both executables and collected component notices, then stopped in its isolation
script: copying `os.environ` into a plain dictionary had lost Windows' case-
insensitive lookup, so `SystemRoot` did not match the stored `SYSTEMROOT` key.

The verification environment now explicitly normalizes variable names and uses
a Windows-only system PATH. Regression cases cover upper/mixed/lowercase keys,
removal of Python/Tcl/Tk/virtualenv overrides, preservation of unrelated values
and the caller's mapping, and a missing/empty system root. This fixes the check
setup; successful frozen execution is still required before an archive is made.
