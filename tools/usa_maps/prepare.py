"""Build reusable FieldForge prepared map ZIPs from checked acquisitions.

Requires a FieldForge source build providing navigation.region_install. That
backend is not bundled here, and the older GitHub main does not provide it.
The output is a regional data pack, not a replacement desktop application.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .acquire import (
    _directory, _hash, _json_bytes, _region, _signature, _unique, _write_new,
    utc_now, verify_acquisition,
)

MAX_PACK = 4 * 1024**3
MAX_EXPANDED = 7 * 1024**3
FORMAT = 'fieldforge-prepared-job-v1'
MEMBERS = {'region.json', 'source.osm.pbf', 'map.ffmap', 'roads.ffroute', 'SOURCE-RIGHTS.txt'}


def backend():
    try:
        from fieldforge.navigation import region_install
        from fieldforge.navigation.pbf_stream import IndexLimits
    except ImportError as exc:
        raise ValueError('Preparation requires the FieldForge regional-installer source build; '
                         'this tool does not replace or install the desktop app.') from exc
    return region_install, IndexLimits


def _zip_inventory(archive):
    entries = archive.infolist()
    names = [i.filename for i in entries]
    if not 4 <= len(entries) <= 5 or len(names) != len(set(names)) or not set(names) <= MEMBERS:
        raise ValueError('Prepared ZIP has an unsupported or duplicate member list.')
    if not {'region.json', 'source.osm.pbf', 'map.ffmap', 'SOURCE-RIGHTS.txt'} <= set(names):
        raise ValueError('Prepared ZIP is missing required files.')
    total = 0
    for i in entries:
        mode = i.external_attr >> 16
        if (i.is_dir() or i.flag_bits & 1 or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                or i.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                or i.file_size < 1):
            raise ValueError('Prepared ZIP contains unsupported member metadata.')
        total += i.file_size
        if total > MAX_EXPANDED:
            raise ValueError('Prepared ZIP exceeds expanded byte budget.')
    if archive.getinfo('region.json').file_size > 65536:
        raise ValueError('Prepared manifest exceeds its size budget.')
    meta = json.loads(archive.read('region.json'), object_pairs_hook=_unique)
    if not isinstance(meta, dict) or not re.fullmatch('[0-9a-f]{32}', meta.get('id', '')):
        raise ValueError('Invalid prepared region identity.')
    return entries, meta


def verify_pack(path, workspace, *, expected_source=None):
    """Extract only fixed members into a disposable folder; then use app verifier."""
    ri, _ = backend()
    path, workspace = Path(path), _directory(workspace)
    before = _signature(path)
    if not 1 <= before[2] <= MAX_PACK:
        raise ValueError('Prepared ZIP exceeds its compressed byte budget.')
    if expected_source is not None and not re.fullmatch('[0-9a-f]{64}', expected_source):
        raise ValueError('Invalid expected source digest.')
    with zipfile.ZipFile(path) as archive:
        entries, meta = _zip_inventory(archive)
        needed = sum(i.file_size for i in entries)
        if shutil.disk_usage(workspace).free < needed + 16*1024**2:
            raise ValueError('Not enough free space to verify the prepared pack.')
        with tempfile.TemporaryDirectory(prefix='.verify-pack-', dir=workspace) as temp:
            folder = Path(temp) / ('region-' + meta['id'])
            folder.mkdir(mode=0o700)
            for entry in entries:
                count = 0
                with archive.open(entry) as source, (folder / entry.filename).open('xb') as target:
                    while chunk := source.read(1024**2):
                        count += len(chunk)
                        if count > entry.file_size:
                            raise ValueError('Expanded member exceeds its stated size.')
                        target.write(chunk)
                if count != entry.file_size:
                    raise ValueError('Truncated prepared member.')
            checked = ri.verify_region(folder)
            if (expected_source is not None and
                    checked.manifest['files']['source']['sha256'] != expected_source):
                raise ValueError('Prepared pack is from a different source snapshot.')
            result = checked.manifest
    if _signature(path) != before:
        raise ValueError('Prepared ZIP changed during verification.')
    return result


def export_region(folder, target):
    """No-clobber ZIP publication; refuses filesystems without hard-link support."""
    ri, _ = backend()
    checked = ri.verify_region(folder)
    target = Path(target).absolute()
    _directory(target.parent)
    if target.suffix.casefold() != '.zip' or target.exists() or target.is_symlink():
        raise ValueError('Choose a new .zip output filename.')
    members = ['region.json'] + [ri.FILES[k] for k in checked.manifest['files']]
    before = {n: _signature(checked.folder / n) for n in members}
    fd, name = tempfile.mkstemp(prefix='.pack-', suffix='.part', dir=target.parent)
    os.close(fd)
    pending = Path(name)
    try:
        with zipfile.ZipFile(pending, 'w', compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as archive:
            for name in sorted(members):
                archive.write(checked.folder / name, name)
        if any(_signature(checked.folder / n) != before[n] for n in members):
            raise ValueError('Region changed while exporting.')
        if pending.stat().st_size > MAX_PACK:
            raise ValueError('Prepared ZIP exceeds its compressed byte budget.')
        with pending.open('r+b') as handle:
            os.fsync(handle.fileno())
        os.link(pending, target)
    finally:
        pending.unlink(missing_ok=True)
    return target


def prepare_one(acquisition, output, *, try_roads=False, progress=None):
    """Resume only verified completed packs; fail without replacing previous jobs."""
    row = verify_acquisition(acquisition)
    output = _directory(output)
    region = row['region']
    source = Path(acquisition) / (region + '-latest.osm.pbf')
    digest = row['files'][source.name]['sha256']
    key = region + '-' + digest[:16] + ('-roads' if try_roads else '-map')
    final = output / key
    if final.exists() or final.is_symlink():
        _directory(final)
        receipt = final / 'prepared-job.json'
        if _signature(receipt)[2] > 65536:
            raise ValueError('Prepared-job receipt too large.')
        saved = json.loads(receipt.read_text('utf-8'), object_pairs_hook=_unique)
        if (not isinstance(saved, dict) or saved.get('format') != FORMAT or
                saved.get('source_sha256') != digest or saved.get('region') != region or
                set(p.name for p in final.iterdir()) != {'region.zip', 'prepared-job.json'} or
                saved.get('pack') != _hash(final / 'region.zip')):
            raise ValueError('Existing job failed verification; choose a new output directory.')
        manifest = verify_pack(final / 'region.zip', output, expected_source=digest)
        return final / 'region.zip', manifest, True
    lock = output / ('.' + key + '.lock')
    lock.mkdir(mode=0o700)
    stage = None
    try:
        ri, limits_type = backend()
        stage = Path(tempfile.mkdtemp(prefix='.build-region-', dir=output))
        work = stage / 'working'
        work.mkdir()
        # Explicit ceilings identical to the tested wave-two source build. These
        # are operating limits, not evidence of whole-country performance.
        limits = limits_type(nodes=50000000, ways=5000000, references=100000000,
                             features=4000000)
        built = ri.install_region(source, work, region.replace('-', ' ').title() + ' - OSM source',
                                  try_roads=try_roads, expected_sha256=digest,
                                  limits=limits, progress=progress)
        # Preserve provider evidence inside the permitted rights member, not an
        # unrecognized extra file. Source bytes and index geometry stay unchanged.
        rights = built.folder / ri.FILES['rights']
        with rights.open('ab') as handle:
            handle.write(b'\nACQUISITION RECEIPT (checksums are not signatures)\n')
            handle.write(_json_bytes(row))
        meta = built.manifest
        meta['files']['rights'] = _hash(rights)
        stamp = meta['source']['replication_timestamp']
        if stamp is not None:
            meta['label'] = region.replace('-', ' ').title() + ' - OSM ' + datetime.fromtimestamp(
                stamp, timezone.utc).date().isoformat()
        (built.folder / 'region.json').write_bytes(_json_bytes(meta))
        target = export_region(built.folder, stage / 'region.zip')
        checked = verify_pack(target, stage, expected_source=digest)
        shutil.rmtree(work)
        _write_new(stage / 'prepared-job.json', _json_bytes(dict(
            format=FORMAT, region=region, source_sha256=digest, prepared_utc=utc_now(),
            pack=_hash(target), map_state='prepared', roads=checked['roads'])))
        if final.exists() or final.is_symlink():
            raise FileExistsError('Another process published this preparation job.')
        stage.rename(final)
        stage = None
        return final / 'region.zip', checked, False
    finally:
        if stage is not None:
            shutil.rmtree(stage)
        lock.rmdir()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True, help='Existing output directory')
    p.add_argument('--regions', nargs='+', required=True)
    p.add_argument('--try-roads', action='store_true')
    args = p.parse_args(argv)
    failures = 0
    for region in args.regions:
        try:
            _region(region)
            pack, meta, reused = prepare_one(args.source_root / region, args.output,
                                             try_roads=args.try_roads)
            print(json.dumps({'region': region, 'pack': str(pack), 'reused': reused,
                              'features': meta['map']['features'], 'roads': meta['roads']}), flush=True)
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
            failures += 1
            print(json.dumps({'region': region, 'failed': str(exc)}), flush=True)
    return 2 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
