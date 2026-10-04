> Historical milestone notes. The workspace is now integrated into FieldForge.
> For current launch paths, PNG/JPEG/WebP MBTiles and image-file support, see
> [GPS workspace](../GPS_WORKSPACE.md). Older verification counts and standalone
> packaging boundaries below describe their original milestone.

# FieldForge GPS + Live Map 0.6

This development add-on connects the existing local serial receiver workspace to
the existing offline map viewer. It does not replace the whole FieldForge app.

Version 0.6 includes offline place search in the same map window. Selecting a
place or manual coordinate pauses following; invalid inputs preserve it. See
[WORKSPACE.md](WORKSPACE.md) for the combined workflow.

## Open it

Extract the entire archive into a new folder. On Windows, open **Start FieldForge
Live Map.cmd**. On Linux/macOS, run `sh "Start FieldForge Live Map.sh"`. The source
command is `python -B -m fieldforge_gps --live-map`. Both a receiver control window
and a map window open; neither connects a device or shows a live position by default.

Python 3.10+ with Tk is required. The source launcher requires no package install.
Reading GPX retains the existing Expat 2.6+ requirement. Serial input additionally
requires a compatible local receiver and optional pySerial 3.5; it is not bundled
or installed automatically. The serial adapter accepts only user-selected local
ports, such as COM3 or /dev/ttyACM0, not network transport URLs. See GPS_RECEIVER.md.
The package has been tested here on Linux/Python 3.12/Tk 9.0, not physical GPS
hardware, Windows, macOS, Android, or iPhone.

## Show your receiver position

1. In **Receiver controls**, enter your GPS port and its configured baud rate.
   Confirm you have checked its WGS84 datum, then choose **Connect selected GPS**.
   Confirm your system UTC and receiver UTC are correct. They are not changed by
   this application. Opening a serial port can affect driver control lines.
2. In the map window, check **Show live position**. A fresh accepted serial RMC fix
   can appear as a teal diamond/crosshair. It is receiver-reported, not an
   independently verified location or a certified accuracy estimate.
3. Use **Center live fix** for one-time centering, or **Follow receiver** for
   automatic recentering. Follow starts with an explicit center. Subsequent
   recentering uses a central-half dead zone and a one-second minimum interval;
   it waits for any pending map read. The marker itself updates on the UI poll.
4. To view local imagery, check the separate map trust/permission box and open
   your own supported PNG MBTiles file. With no local map selected, the existing
   low-resolution world-outline overview is used. Missing/unreadable tiles remain
   labeled; there is no download or fallback to online maps.

The map polls every 200 ms while the UI event loop is responsive. The existing
Session freshness gate hides a fix at a receipt age of five seconds, after a
receiver/system UTC mismatch over ten seconds, on rejected/no-fix input, or on
disconnect. These are software policy thresholds, not guarantees of GPS accuracy
or integrity. No dead reckoning, animation, road snapping, heading arrow, accuracy
circle, speed-based prediction, or interpolation of missing positions is added.

Manual drag or arrow-key panning stops following. Click the canvas to focus it
before using arrow keys. Pack-start, map replacement/closure and historical-track
centering also stop following. Zoom does not turn following off. Losing an eligible
fix stops following; a later good fix does not silently re-enable it. Re-enable
Follow explicitly. Replacing the input, including switching to another serial
session, clears map-display consent and following. Removing WGS84 confirmation
also turns off live display; rechecking it does not restore permission automatically.

## Separate permissions and layers

* **Show live position** does not start/stop trip recording or write coordinates.
  With this box off, the map does not request receiver snapshots. The separately
  connected receiver control window may still display its own input.
* The **Follow receiver** setting changes the in-memory view, not a recorded trip.
* **Show GPX controls** reveals the retained saved-trip controls. Their WGS84 and
  private-history confirmations are separate from receiver/map permissions.
  GPX lines and their file-point markers are historical even when a serial marker
  is also visible. Hiding the controls does not clear already loaded history.
* Closing the live map stops its timers and clears displayed receiver text, but
  leaves the explicitly connected receiver and any separately started trip alone.
  Close/disconnect the receiver window to stop the source. Unsaved trip exit
  confirmation remains in that window. This is not secure memory erasure.

Recorded NMEA files never enter the live layer, regardless of the file timestamp.
They can still be inspected/exported using the older receiver/trip tools. The
application cannot authenticate a serial device or detect every recording/spoof
sent through a physical port. No source authenticity is claimed.

Polar positions are not clamped to Mercator's edge. The local-map live marker is
hidden outside the projection; World overview can display the actual latitude.
The existing supported MBTiles subset is unchanged; see LOCAL_MAPS.md.

## Test material versus real-world capability

The included grid map, GPX and NMEA examples are fictional software fixtures.
The new preview image uses an injected test serial stream and is visibly labeled
as a synthetic test. That injection exists in the verification script, not as a
live-mode demo button. A preview is not evidence of a working physical receiver.
The production launcher does not inject a source or automatically load fixtures.

No new real-world street, regional, marine, terrain or world-map dataset is bundled
by this increment. There is still no geocoding, destination search, route engine,
alternate-route computation or turn-by-turn guidance in this GPS add-on. The
separate prepared-road-path FieldForge work is not integrated by this archive.
Do not use it as the sole basis for navigation or emergency decisions.

## Technical references

References checked October 2, 2026. URLs are documentation only, never fetched by
the application. Existing licensing/source notices for bundled overview data remain.

- GPSD project's NMEA field reference: https://gpsd.io/NMEA.html
- pySerial API, including timeouts and DTR/RTS control-line caveats:
  https://pyserial.readthedocs.io/en/latest/pyserial_api.html

## Verify or install locally

From the extracted source folder with development test dependencies already present:

```text
python -B -m pytest -q -ra
```

The GUI tests require an actual display; on Linux the development run used Xvfb.
Five inherited tests require the separate FieldForge main package and are skipped
when that package is not installed. They are not counted as passing integration.

Optional local wheel installation (never needed for the source launcher):

```text
python -m pip install --no-index --no-deps dist/fieldforge_gps-0.5.0-py3-none-any.whl
fieldforge-live-map
```

Read VERIFICATION.txt and the logs in verification/ for the actual observed run.
The patch is against the recovered GPS 0.4 archive, not against FieldForge main.
No GitHub upload, merge, installed-app update, or persistent Library replacement
is performed by extracting or running this source add-on.
