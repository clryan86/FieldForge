"""Verify explicit prepared ZIPs and write an offline download-collection receipt.

This records checked files in a chosen folder, not installed/device coverage.
No map downloads, household access, extraction into app folders or routing occurs.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

from .acquire import _directory, _hash, _json_bytes, _signature, utc_now
from .prepare import verify_pack

FORMAT = 'fieldforge-map-collection-v1'
MAX_PACKS = 128
NOTICE = ('Verified downloaded ZIPs, not an installation audit or complete geographic coverage. '
          'Counts describe source objects, not unique addresses. A prepared road model is '
          'not validated driving directions. Checksums are unsigned integrity checks. '
          'Keep the listed ZIPs; this JSON does not contain maps.')


def build_catalog(paths: Iterable[Path], workspace: Path) -> dict:
    """Fully verify each selected ZIP; fail on duplicates or any changed input."""
    workspace = _directory(workspace)
    selected = []
    for path in paths:
        if len(selected) >= MAX_PACKS:
            raise ValueError('Select at most 128 prepared map ZIPs per collection.')
        selected.append(Path(path).absolute())
    if not selected:
        raise ValueError('Select at least one prepared map ZIP.')
    rows, names, identities, sources, fingerprints = [], set(), set(), set(), []
    for path in selected:
        _directory(path.parent)
        if path.suffix.casefold() != '.zip':
            raise ValueError('Select prepared .zip files, not source artifacts or map folders.')
        if any(ord(c) < 32 or ord(c) == 127 for c in path.name):
            raise ValueError('Control characters are not allowed in pack filenames.')
        # Case-insensitive uniqueness keeps the receipt portable to Windows.
        if path.name.casefold() in names:
            raise ValueError('Duplicate pack filename in collection.')
        names.add(path.name.casefold())
        before = _signature(path)
        meta = verify_pack(path, workspace)
        identity = meta['id']
        source = meta['files']['source']['sha256']
        if identity in identities or source in sources:
            raise ValueError('Duplicate region identity or source snapshot in collection.')
        identities.add(identity)
        sources.add(source)
        digest = _hash(path)
        if _signature(path) != before:
            raise ValueError('Map ZIP changed during collection verification.')
        fingerprints.append((path, before))
        rows.append(dict(
            filename=path.name, **digest, region_id=identity,
            label=meta['label'], source_name=meta['source']['name'],
            source_sha256=source,
            replication_timestamp=meta['source']['replication_timestamp'],
            expanded_bytes=sum(item['bytes'] for item in meta['files'].values())
                           + _manifest_size(path),
            map_features=meta['map']['features'],
            address_tagged_objects=meta['map']['address_features'],
            missing_node_ways=meta['map']['missing_node_ways'],
            road_preparation=meta['roads'], license=meta['license'],
            status='verified-download', installed_on_device='not-checked',
            validated_navigation=False))
    if any(_signature(path) != before for path, before in fingerprints):
        raise ValueError('A previously checked map ZIP changed while checking the collection.')
    rows.sort(key=lambda row: row['filename'].casefold())
    return dict(format=FORMAT, checked_utc=utc_now(), notice=NOTICE, packs=rows,
                totals=dict(packs=len(rows),
                            download_bytes=sum(row['bytes'] for row in rows),
                            expanded_bytes=sum(row['expanded_bytes'] for row in rows),
                            map_features=sum(row['map_features'] for row in rows),
                            address_tagged_objects=sum(row['address_tagged_objects'] for row in rows)))


def _manifest_size(path: Path) -> int:
    # verify_pack already validated the fixed member list and its declared sizes.
    with zipfile.ZipFile(path) as archive:
        return archive.getinfo('region.json').file_size


def write_catalog(paths: Iterable[Path], workspace: Path, output: Path) -> dict:
    """Publish a new JSON atomically; never overwrite an existing file or link."""
    output = Path(output).absolute()
    _directory(output.parent)
    if output.suffix.casefold() != '.json' or output.exists() or output.is_symlink():
        raise ValueError('Choose a new .json filename for the collection receipt.')
    result = build_catalog(paths, workspace)
    fd, name = tempfile.mkstemp(prefix='.map-collection-', suffix='.part', dir=output.parent)
    pending = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_json_bytes(result))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, output)
    finally:
        pending.unlink(missing_ok=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', type=Path, action='append', required=True,
                        help='Prepared ZIP to check. Repeat for additional maps.')
    parser.add_argument('--workspace', type=Path, required=True,
                        help='Existing ordinary folder with temporary verification space.')
    parser.add_argument('--output', type=Path, required=True, help='New collection JSON filename.')
    args = parser.parse_args(argv)
    try:
        report = write_catalog(args.pack, args.workspace, args.output)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}))
        return 2
    print(json.dumps({'status': 'verified-downloads-not-installations', 'totals': report['totals']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
