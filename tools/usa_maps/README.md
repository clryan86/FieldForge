# USA-first map data tools

These developer tools acquire public regional OpenStreetMap source files and, with a compatible FieldForge regional backend, build prepared data ZIPs. They do not replace the desktop application or automatically install data on anyone's computer. USA coverage is first; worldwide coverage remains the next geographic phase (issue #9).

## Acquire one region

Python 3.10+ standard library only. Create a new output directory, then from this repository root:

```sh
mkdir usa-acquisition
python -m tools.usa_maps.acquire --output usa-acquisition --region vermont --max-mib 160
python -m tools.usa_maps.acquire --output usa-acquisition --region vermont --verify-only
```

Only the fixed public Geofabrik USA source paths in the code allowlist are requested. Both dated and latest source URLs are supported; a redirect cannot change the region, file kind, HTTPS host or path family. The original URL and final dated URL are both retained. Each source PBF is checked against the publisher's MD5, and all three acquired files receive SHA-256 records. The receipt includes source, rights, retrieval time and the provider's HTTP metadata. Retrieval time is not the underlying OSM snapshot date.

The source cap is 160 MiB by default, explicitly configurable up to 2 GiB. Metadata has smaller bounds. Transfers have time and disk-space checks. Four-region GitHub acquisition uses at most two concurrent jobs. No tile scraping, cloud geocoding, household files or precise device locations are involved.

Re-running a completed region verifies and reuses its **existing saved snapshot without downloading**. This does not check for updates or claim that the snapshot remains latest. To acquire a newer snapshot, choose a new output directory. Incomplete transfers are removed on ordinary errors; partial byte-range resume is not implemented.

## Prepare maps (separate backend required)

Preparation requires a FieldForge source build containing:

- `fieldforge.navigation.region_install`
- `fieldforge.navigation.regional_index`
- `fieldforge.navigation.pbf_stream`

The regional-installer / USA map-manager chat source deliveries provide those APIs. The older application tree on this branch and GitHub main does **not**. Place the compatible source root on `PYTHONPATH` alongside this repository, or use its installed package. This requirement is explicit; these tools do not silently find or download another application version.

```sh
mkdir usa-prepared
python -m tools.usa_maps.prepare --source-root usa-acquisition --output usa-prepared --regions vermont new-hampshire maine puerto-rico --try-roads
```

The actual source SHA-256 is rechecked. The backend builds a visual/search index and optionally tries a road graph. Unsupported road restrictions leave a usable visual map with the graph explicitly unavailable; restrictions are not silently discarded. The source PBF, acquisition evidence and ODbL notice stay with the data. Neither a prepared graph nor a successful path computation is validation of driving guidance.

Outputs are snapshot-keyed job directories containing `region.zip` and `prepared-job.json`. A repeated job verifies its ZIP, extracts it to a disposable checking directory, and uses the application's region verifier before reuse. An incomplete or corrupted existing job is refused rather than replaced. Retrying such a job needs a new output directory or separate manual diagnosis.

The ZIP uses the existing `fieldforge-region-install-v1` layout: `region.json`, `source.osm.pbf`, `map.ffmap`, `SOURCE-RIGHTS.txt`, and `roads.ffroute` only when available. This is the same fixed-member layout as the previously delivered prepared regional packs. The developer tool does not add executable files or private records to those ZIPs.

Use the last desktop build's **Import prepared pack...** control for the data ZIP; do not extract it first. Source acquisition ZIPs from GitHub Actions are different and are not prepared map ZIPs.

## Bounds and failure behavior

Preparation explicitly selects finite backend ceilings: 50 million source nodes, 5 million ways, 100 million references and 4 million indexed features. These are limits, not claims that every state or a country-wide source will fit.

Wave-six Alabama exposed a valid source entity with more than the older backend's 128-tag per-entity preview cap. `tag-limit-512.patch` raises only that finite per-entity cap to 512 and adds a regression proving >128 valid tags parse while the bound still rejects larger inputs when configured lower. Apply it only to the compatible map-manager source checkpoint; it is not a substitute for the full application source. A prepared ZIP is capped at 4 GiB compressed and 7 GiB expanded. New ZIP exports require filesystem hard-link support for no-clobber publication; unsupported filesystems fail explicitly.

The tool refuses linked output folders, unexpected ZIP members, changed source identities and hash mismatches. It uses exclusive per-job locks and new temporary folders and does not replace existing installations. The output directory is assumed not to be maliciously modified by other processes. A power failure can leave a lock or temporary directory; do not remove those while another build is active. This is not a signed publisher-authentication system or a sandbox for hostile files.

Map snapshots are public, unencrypted files outside household-database backups. Keep backups of installed map packs separately. Multipolygon assemblies, complete address coverage, current conditions and validated navigation are not established by this pipeline.

## Verification scope

`tests/test_usa_acquire.py` and `tests/test_usa_provider_dates.py` are 39 source-tool cases. GitHub's dedicated source checks execute them on Linux Python 3.10 and 3.12 and compile the tools. `tests/test_usa_prepare.py` adds 18 integration cases with the separately supplied regional backend; they were run locally, not represented as remote desktop integration. That file explicitly skips when the backend is absent.

The exact source archive from GitHub was also tested locally with the regional backend: **57 passed**, no skips. Cases include valid/invalid dated redirects, wrong regions, corrupt downloads, incomplete transfer cleanup, fixed archive paths, offline preparation, graph refusal, source-byte preservation, no-overwrite exports and verified completed-job reuse. There is no new full-application regression or native Windows/phone test claim in this source-only workstream.

Data loading results, per-pack hashes and remaining gaps are recorded separately in the wave-three delivery verification. A source URL in a catalog is not installed coverage; a prepared artifact in this conversation is not a file already installed on the user's device.

Sources and rights:
- https://download.geofabrik.de/north-america/us.html
- https://www.openstreetmap.org/copyright
