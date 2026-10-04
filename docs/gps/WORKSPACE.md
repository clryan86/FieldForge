# FieldForge GPS workspace

In the main desktop, open **Navigation → Maps, GPS & places…**.
For source installations, open **Start FieldForge Workspace.cmd** on Windows, or run
`python -B -m fieldforge_gps --workspace` from the extracted source folder.
The map and receiver controls open together. Neither connects a receiver,
imports personal files, enables a live layer, or starts recording automatically.
The old `--live-map` option opens the same combined workspace.

## Places, receiver positions, and saved trips

Use **Find places / coordinates…** to open a supported local CSV or Point
GeoJSON file, search its names and regions, and choose a reference point.
The same window accepts manually entered latitude and longitude. See
[PLACES.md](PLACES.md) for the exact formats and limits.

With a compatible receiver connected through **Receiver controls…**, enable
**Show live position** to display accepted fresh serial fixes. **Center live fix**
centers once; **Follow receiver** keeps the receiver in view. The receiver's
freshness checks and explicit WGS84 confirmation still apply. See
[LIVE_MAP.md](LIVE_MAP.md).

| Action | Result in the combined workspace |
| --- | --- |
| Open the finder, load a catalogue, or search | Following and the map center stay unchanged. |
| Show a valid place or manual coordinate | The map centers there and following pauses; the live layer stays enabled if it was enabled. |
| Enter an invalid or unsupported coordinate | The previous view, reference marker, and follow setting are preserved. |
| Re-enable Follow receiver | The map returns to an eligible fresh fix; the reference marker remains as a separate point. |
| Clear the place marker | Its marker and label disappear immediately; map tiles, GPS and GPX history remain available. |
| Revoke place-file permission or close the finder | The catalogue and its FILE PLACE marker clear; a manually entered marker is retained. |
| Lose a GPS fix or disconnect | The live marker disappears and following pauses; the reference marker remains. |
| Close the map workspace | Map and place workers stop. An independently active receiver and its trip remain in receiver controls. |
| Reopen the map workspace | Place data and live-display permission start cleared. |

**FILE PLACE** and **MANUAL COORDINATE** are purple reference markers.
**SERIAL FIX** is a teal crosshair/diamond reported by a receiver.
GPX tracks and selected points remain historical. The three layers do not
prove that a path is accessible or that a reference point is a current position.
Showing any layer does not start trip recording.

## Practice without hardware

1. Open the workspace and finder. Confirm the two place-file checkboxes.
2. Load fictional places, search for `springs`, and select North District.
3. Show the selected place. Then use the map's separate permission checkbox
   and **Load fictional test map** to try the local PNG tile layer.
4. Show South District to move the map. Clear its marker to remove the reference.
5. Use **Show GPX controls** for historical tracks and their separate permissions.

The examples are software fixtures. They are not real destinations or maps.
The source application performs no map downloads and needs your own trusted,
permitted files for local detail. The inherited coarse land outline has unknown
original data vintage. No new real geographic dataset was added in this update.

## Packaging and integration

The workspace is included in the main `fieldforge` package and Windows build.
The source entry points are `fieldforge-workspace` and `fieldforge-gps`;
`python -m fieldforge_gps --workspace` also works. The Navigation menu owns the
receiver and its windows, and main-app exit checks unsaved trip history.
See [current integration and image support](../GPS_WORKSPACE.md).

The `gps` extra installs the serial adapter. The `maps` extra installs Pillow
for JPEG/WebP MBTiles and local image references. The fictional examples and
source notices are packaged together. Physical receiver accuracy and native
mobile operation are not established by software regression tests. Source/data
notices under `sources/` are retained; no whole-project license is selected here.
