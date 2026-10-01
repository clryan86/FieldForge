# Offline asset verification quick start

Run the additive verifier with Python 3.10 or later; no third-party runtime dependency is required:

```sh
python fieldforge/knowledge/asset_audit.py snapshot /path/to/content --output baseline.json
python fieldforge/knowledge/asset_audit.py verify /path/to/content baseline.json --output health.html
python fieldforge/knowledge/asset_audit.py verify /path/to/content baseline.json --format json --output health.json
python -m pytest -q tests/test_asset_audit.py
```

Select a dedicated content directory. Snapshot inventories every regular file below it, including hidden files, and labels source/rights/review metadata as unrecorded or unreviewed. Do not accidentally select private household or profile directories. Outputs must be new filenames outside the content directory. Output publication requires a writable directory supporting hard links; unsupported filesystems fail closed without overwriting anything.

The report distinguishes verified, missing, changed, unsafe, unreadable, and not-checked files, with independent metadata alerts. It includes relative filenames and supplied metadata, not file contents or the absolute content root. Review filenames before sharing a report. HTML search and filters work offline and do not fetch source URLs or execute the listed files.

Default hashing limits are 2 GiB per file and 8 GiB total; use --max-file-bytes and --max-total-bytes to change them. Oversized files are not checked, never passed. Manifests are limited to 16 MiB and 10,000 assets. Paths cannot traverse parents, be absolute, or refer through symbolic links/reparse points. Use a stable, trusted filesystem; these checks are not a hostile-filesystem sandbox.

Verify exits 0 for matching files without metadata alerts; 1 for matching files with metadata gaps; 2 for failed or incomplete verification; and 3 for invalid input/output failure. Keyboard interruption exits 130. Snapshot returns 0 only after creating a complete baseline; argument usage errors use argparse's exit code 2.

A snapshot records current bytes. It cannot tell whether a file was already wrong or malicious. An unsigned manifest and matching checksums do not prove publisher identity, expert review, content accuracy, permission to redistribute, subject completeness, or device playback support. No repairs, downloads, database changes, desktop-interface integration, or default-branch changes are included. Native mobile and full-application integration tests remain pending.
