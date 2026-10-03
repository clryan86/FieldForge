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
