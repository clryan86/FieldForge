"""Bounded, explicit USA OSM acquisition. No background schedule or map claims.

Only public Geofabrik extracts are requested. A receipt means source bytes were
checked, NOT that an app installed, indexed or routed the region. Reusing a saved
receipt reuses its snapshot; it does not claim the snapshot is the latest one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

BASE = "https://download.geofabrik.de/north-america/us/"
REGIONS = frozenset("""alabama alaska arizona arkansas california colorado connecticut
 delaware district-of-columbia florida georgia hawaii idaho illinois indiana iowa
 kansas kentucky louisiana maine maryland massachusetts michigan minnesota mississippi
 missouri montana nebraska nevada new-hampshire new-jersey new-mexico new-york
 north-carolina north-dakota ohio oklahoma oregon pennsylvania puerto-rico rhode-island
 south-carolina south-dakota tennessee texas us-virgin-islands utah vermont virginia
 washington west-virginia wisconsin wyoming""".split())
FORMAT = "fieldforge-usa-source-v1"
CHUNK = 1024 * 1024
DEFAULT_CAP = 160 * CHUNK
MAX_CAP = 2 * 1024**3
NOTICE = ("Original source only; not installed map coverage or driving directions. "
          "Extracts may include adjoining geography. Checksums detect changes, not "
          "publisher authenticity, completeness or current road conditions.")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _region(value):
    if not isinstance(value, str) or value not in REGIONS:
        raise ValueError("Choose a supported, explicitly named USA source region.")
    return value


def _safe_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "download.geofabrik.de"
            or parsed.query or parsed.fragment or not url.startswith(BASE)):
        raise ValueError("Only fixed public Geofabrik HTTPS source paths are allowed.")
    tail = url[len(BASE):]
    if not any(tail in (r + "-latest.osm.pbf", r + "-latest.osm.pbf.md5", r + ".poly")
               for r in REGIONS):
        raise ValueError("Unsupported public geographic source path.")
    return url


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _safe_url(newurl)
        # Redirects within the fixed region path cannot change the requested source.
        if newurl != req.full_url:
            raise ValueError("Source redirect changed the requested file.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_source(url):
    request = urllib.request.Request(_safe_url(url), headers={
        "User-Agent": "FieldForge-USA-map-acquisition/0.2",
        "Accept-Encoding": "identity",
    })
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _Redirect()).open(
        request, timeout=45)


def _directory(path):
    path = Path(path).expanduser().absolute()
    for ancestor in (path, *path.parents):
        info = ancestor.lstat()
        if (not stat.S_ISDIR(info.st_mode) or
                getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError("Choose an existing ordinary directory, not a linked folder.")
    return path


def _signature(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Expected an ordinary, unlinked local file.")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _hash(path):
    before = _signature(path)
    h = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(CHUNK):
            h.update(chunk)
    if _signature(path) != before:
        raise ValueError("Local source changed while checking.")
    return {"bytes": before[2], "sha256": h.hexdigest()}


def _unique(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("Duplicate receipt field.")
        out[k] = v
    return out


def _json_bytes(data):
    return (json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()


def _write_new(path, raw):
    with path.open('xb') as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())


def _download(url, path, cap, transport, deadline):
    _safe_url(url)
    h = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    count = 0
    with transport(url) as response, path.open('xb') as target:
        final_url = response.geturl()
        if _safe_url(final_url) != url:
            raise ValueError("Response changed the requested public file.")
        size_header = response.headers.get('Content-Length')
        expected = None
        if size_header is not None:
            if not re.fullmatch(r'[0-9]{1,15}', size_header):
                raise ValueError("Malformed source size header.")
            expected = int(size_header)
            if not 0 < expected <= cap:
                raise ValueError("Source exceeds the per-file download budget.")
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("Source operation exceeded its time budget.")
            chunk = response.read(CHUNK)
            if not chunk:
                break
            count += len(chunk)
            if count > cap:
                raise ValueError("Source exceeds the per-file download budget.")
            target.write(chunk)
            h.update(chunk)
            md5.update(chunk)
        target.flush()
        os.fsync(target.fileno())
        modified = response.headers.get('Last-Modified')
    if count == 0 or (expected is not None and count != expected):
        raise ValueError("Source was empty or incomplete.")
    return dict(bytes=count, sha256=h.hexdigest(), md5=md5.hexdigest(),
                url=url, http_last_modified=modified)


def verify_acquisition(folder, *, expected_region=None):
    """Verify preserved bytes without network or mutation; no latest-date claim."""
    folder = _directory(folder)
    receipt = folder / 'source-receipt.json'
    if _signature(receipt)[2] > 65536:
        raise ValueError("Receipt too large.")
    row = json.loads(receipt.read_text('utf-8'), object_pairs_hook=_unique)
    if (not isinstance(row, dict) or row.get('format') != FORMAT or row.get('status') != 'source-verified'
            or row.get('license') != 'ODbL-1.0' or row.get('notice') != NOTICE):
        raise ValueError("Unsupported acquisition receipt.")
    region = _region(row.get('region'))
    if expected_region is not None and region != _region(expected_region):
        raise ValueError("Wrong region receipt.")
    stamp = datetime.fromisoformat(row['downloaded_utc'])
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("Receipt requires a UTC acquisition time.")
    names = {region + '-latest.osm.pbf', region + '-latest.osm.pbf.md5', region + '.poly'}
    if not isinstance(row['files'], dict) or set(row['files']) != names or {p.name for p in folder.iterdir()} != names | {'source-receipt.json'}:
        raise ValueError("Unexpected/missing acquisition members.")
    for name in names:
        item = row['files'][name]
        if not isinstance(item, dict) or item.get('url') != BASE + name:
            raise ValueError("Receipt source URL mismatch.")
        if type(item.get('bytes')) is not int or not 0 < item['bytes'] <= MAX_CAP:
            raise ValueError("Invalid receipt size.")
        if not re.fullmatch(r'[0-9a-f]{64}', item.get('sha256', '')):
            raise ValueError("Invalid receipt digest.")
        if _hash(folder / name) != {k: item[k] for k in ('bytes', 'sha256')}:
            raise ValueError("Acquired file size or SHA-256 changed.")
    pbf = region + '-latest.osm.pbf'
    md5_text = (folder / (pbf + '.md5')).read_text('ascii').strip()
    match = re.fullmatch(r'([0-9a-fA-F]{32})\s+\*?' + re.escape(pbf), md5_text)
    if not match or match.group(1).lower() != row['files'][pbf]['md5']:
        raise ValueError("Publisher MD5 does not match acquired source.")
    return row


def acquire_region(root, region, *, cap=DEFAULT_CAP, transport=open_source):
    """Acquire one bounded region, or verify/reuse its completed saved snapshot.

    An existing invalid acquisition is refused, never silently replaced. A failed
    new transfer is removed. A publish lock serializes this pipeline's own writers;
    the output directory is assumed not to be maliciously modified concurrently.
    """
    root = _directory(root)
    region = _region(region)
    if type(cap) is not int or not 1 <= cap <= MAX_CAP:
        raise ValueError("Invalid byte budget.")
    target = root / region
    if target.exists() or target.is_symlink():
        return verify_acquisition(target, expected_region=region), True
    lock = root / ('.' + region + '.acquisition-lock')
    lock.mkdir(mode=0o700)
    stage = None
    try:
        if target.exists() or target.is_symlink():
            return verify_acquisition(target, expected_region=region), True
        if shutil.disk_usage(root).free < cap + 16 * CHUNK:
            raise ValueError("Insufficient free space for download budget and reserve.")
        stage = Path(tempfile.mkdtemp(prefix='.' + region + '-source-', dir=root))
        pbf = region + '-latest.osm.pbf'
        deadline = time.monotonic() + 600
        files = {}
        for name, bound in ((pbf + '.md5', 4096), (pbf, cap), (region + '.poly', CHUNK)):
            files[name] = _download(BASE + name, stage / name, bound, transport, deadline)
        row = dict(format=FORMAT, status='source-verified', region=region,
                   publisher='OpenStreetMap contributors; Geofabrik extract',
                   license='ODbL-1.0', rights_url='https://www.openstreetmap.org/copyright',
                   downloaded_utc=utc_now(), notice=NOTICE, files=files)
        _write_new(stage / 'source-receipt.json', _json_bytes(row))
        verify_acquisition(stage, expected_region=region)
        if target.exists() or target.is_symlink():
            raise FileExistsError("Acquisition target was created by another process.")
        stage.rename(target)
        stage = None
        return row, False
    finally:
        if stage is not None:
            shutil.rmtree(stage)
        lock.rmdir()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True, help='Existing download directory')
    p.add_argument('--region', choices=sorted(REGIONS), required=True)
    p.add_argument('--max-mib', type=int, default=160)
    p.add_argument('--verify-only', action='store_true')
    args = p.parse_args(argv)
    try:
        if args.verify_only:
            row = verify_acquisition(args.output / args.region, expected_region=args.region)
            reused = True
        else:
            row, reused = acquire_region(args.output, args.region, cap=args.max_mib * CHUNK)
        print(json.dumps({'reused_existing_snapshot': reused, 'receipt': row}, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('Source acquisition failed: ' + str(exc))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
