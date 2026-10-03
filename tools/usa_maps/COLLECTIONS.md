# Offline map collection receipts

`catalog.py` verifies explicitly chosen prepared regional ZIPs, then writes one portable JSON receipt. This is a developer/data-management tool, not a replacement desktop application or an automatic USA installer. No network calls or household database reads are made. USA coverage remains first, with worldwide coverage next.

## Usage

Use Python 3.10+ and the same compatible FieldForge regional backend required by `prepare.py`. The older application tree on this branch does not contain that backend; use the regional-installer/map-manager source delivery with its large-map verification patch. Create an ordinary temporary workspace with enough free space to expand the largest selected pack, then run:

```sh
python -m tools.usa_maps.catalog --pack /maps/FieldForge-USA-North-Dakota-2026-10-02.zip --pack /maps/FieldForge-USA-South-Dakota-2026-10-02.zip --workspace /maps/verification-work --output /maps/checked-collection.json
```

Repeat `--pack` for up to 128 explicitly selected ZIPs. Only prepared region ZIPs are accepted; GitHub's outer source-artifact ZIPs are different. Verification extracts fixed permitted members into disposable folders, runs the application's region/index verifier, and checks the source identity and content hashes. Inputs and existing installations are never overwritten.

The resulting receipt records each filename, ZIP SHA-256/byte size, source digest, source snapshot time (or null when unknown), license, expanded bytes, source-object counts and separate road-preparation state. Filenames are basenames; local directory paths, household records and address queries are not copied into the receipt. Labels remain source-supplied information.

A downloaded/checked pack is not necessarily installed on any device. Every row says `status: verified-download`, `installed_on_device: not-checked`, and `validated_navigation: false`. A positive road-preparation state is not a claim of validated driving directions. Counts are source objects, not unique addresses or completeness measurements.

## Failures and limits

Any invalid ZIP, changed input, duplicate filename (case-insensitive), duplicate region ID, or duplicated source snapshot fails the collection rather than inflating totals. It does not automatically choose among map versions. The input count, compressed and expanded byte limits remain finite. Linked input/output folders and linked files are rejected.

Only a new `.json` output is allowed. Publication uses a flushed temporary file and a no-clobber hard link, so unsupported filesystems fail rather than overwrite existing data. Interrupted/failed validation publishes no completed receipt. Ordinary publication failures remove the temporary file. This is not protection against malicious concurrent modification of the workspace, a signed publisher manifest, or a replacement for backups. A receipt reflects the checked snapshot; rerun with a new output filename to check later changes.

Keep the original data ZIPs: the JSON contains no maps and cannot install maps by itself. Installed maps also remain separate from household-database backups.

## Testing

`tests/test_usa_catalog.py` contains 22 wrapper tests plus one actual prepared-pack integration test with explicitly fictional source data. The latter requires the regional backend and skips in the older GitHub source tree; that skip is not counted as integration success. The previously tested acquisition and preparation tools remain independently exercised. The new real-data delivery is verified separately with actual source files and offline queries.
