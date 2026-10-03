# USA-first rollout: four additional prepared regional maps

Source snapshot reported by every new PBF: **2026-10-02T20:21:34Z**. USA coverage remains priority one; worldwide coverage remains phase two, as recorded in issue #9. Snapshot dates are not live-condition checks.

## Actual acquired and prepared data

The existing successful acquisition run was retrieved through GitHub Actions artifacts:
https://github.com/clryan86/FieldForge/actions/runs/37085818312
Commit: `0b0785f29f9a0f898d7754fd61b7eae0fbaa9147`.
Original artifact ZIP digests/CRC, source PBF SHA-256, publisher MD5 and extract polygon hashes were checked. Original PBF bytes remain inside each prepared pack.

| Region | Indexed source features | Address-tagged source objects | Prepared ZIP bytes |
| --- | ---: | ---: | ---: |
| New Jersey | 2,689,533 | 356,334 | 718,023,123 |
| Rhode Island | 534,797 | 54,012 | 181,939,843 |
| Hawaii | 456,789 | 19,869 | 121,015,716 |
| U.S. Virgin Islands | 68,392 | 1,042 | 16,060,822 |

Total newly prepared: **3,749,511** features and **431,257** address-tagged objects. These are source-object counts, not unique addresses or guarantees of complete state coverage. Extracts can contain adjoining geography. Relations/multipolygon assemblies are not drawn by the current visual index; original source relations are preserved in the PBF.

Each final ZIP was imported with the production importer, CRC/hash checked, and searched for actual recorded names and literal address fields with network sockets forbidden. Searches included Nassau Street, Providence, Honolulu and Charlotte Amalie. No private household records were used or changed.

All four road graph preparations refused unsupported restrictions rather than discard them: NJ 936081, RI 4139186, HI 1870945, USVI 13938835. **Every new region is view/search data, not driving directions.** Existing current Delaware/DC graphs also remain unavailable.

## Prepared pack checksums

```
f9f1870987f694bb9d4770a395775d97ea4f79746533bf920c54142e741660c3  FieldForge-USA-New-Jersey-2026-10-02.zip
9a5fb7c853a0341f5e6bc46d626cdcde49d7ed90b7cbbb78f6fabb998e7a0406  FieldForge-USA-Rhode-Island-2026-10-02.zip
b750f5ecd83e03b375b39acbe96d3434518fb4bb0c29bb19d01ab1e441895fd3  FieldForge-USA-Hawaii-2026-10-02.zip
e90ade7d5fffcfec551fdb4f0dded4e26eea5468006fd24c5ee5907cb7988493  FieldForge-USA-Us-Virgin-Islands-2026-10-02.zip
```

## Local software increment

A new prepared-ZIP import/export module and desktop Import prepared pack control avoid rebuilding the source on the recipient's computer. Fixed member names, bounds, source matching, hash verification, cancellation cleanup, exclusive new snapshot folders and separate map/road readiness are retained. There is no automatic download, household write or overwrite. ZIP export needs hard-link support for atomic no-clobber publication.

New Jersey exceeded the former 20-million-node preparation bound; the initial attempt stopped cleanly. Tested finite ceilings were raised to 50 million nodes, 5 million ways, 100 million references and 4 million indexed features; source/inflated byte and database caps remain unchanged. The successful New Jersey index is about 1.63 GB and the whole extracted pack about 1.79 GB. This is not country-scale benchmarking.

## Verification and repository boundary

Full local Linux/Python 3.13.5/Tk regression: **2,361 passed, 15 existing opt-in Pocket browser tests skipped**, including 47 new tests. Installed wheel: all 97 Python modules match tested source; actual data verification and prepared-pack import/search passed offline. Every one of 7,329 existing atlas PNG tiles decoded. Actual desktop import controls and New Jersey geometry were inspected, including the regional library at minimum 900x720 size. The incremental patch applied cleanly to the USA-first source checkpoint.

The prior mounted first-data archive was truncated. Its source was independently reconstructed from the complete previous installer archive and exact first-data source patch, matching all 96 recovered application modules. Original data was reacquired and hash-checked; national MBTiles reproduce prior hashes, and DE/DC were rebuilt from identical original PBFs. Their rebuilt index metadata/UUIDs differ, while source hashes and feature counts match. A fresh complete application archive replaces reliance on that truncated local copy.

**This commit records the rollout; it does not upload or merge the new application code/databases.** The current chat-delivered application source and `USA-WAVE2-CODE-CHANGES.patch` are ahead of this branch. The patch targets the USA-first chat checkpoint, not this branch's older application tree. No new remote application CI, Ruff, native Windows, mobile, physical GPS or navigation-validation pass is claimed.

The application archive retains six reference layers plus Delaware/DC. The four new prepared ZIPs are separate downloads imported through Maps -> Map tools -> U.S. installed street regions -> Import prepared pack. Do not extract the prepared ZIP before selecting it. Python 3.10+ and Tk remain required.

Detailed availability now covers source extracts for four states (DE/NJ/RI/HI), DC and USVI. The remaining 46 states, other territories, complete topographic/water/nautical collections and working cross-state navigation are still outstanding. Do not count national outlines or primary highways as all streets.

Source and rights:
https://download.geofabrik.de/north-america/us.html
https://www.openstreetmap.org/copyright
