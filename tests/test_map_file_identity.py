"""Read real map-related files with Windows-style stat/fstat timestamp differences."""

import hashlib
import os
from functools import partial
from types import SimpleNamespace

import pytest
from test_raster_maps import encoded

from fieldforge_gps import _file_identity, gpx_review, places, raster


@pytest.fixture(params=["image", "gpx", "places"])
def local_reader(request, tmp_path):
    if request.param == "image":
        path = tmp_path / "reference.png"
        data = encoded("PNG", (64, 64))
        read = partial(raster.read_reference, path, consent=True)
    elif request.param == "gpx":
        path = tmp_path / "history.gpx"
        data = (
            b'<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="test">'
            b'<trk><trkseg><trkpt lat="10" lon="20"/></trkseg></trk></gpx>'
        )
        read = partial(gpx_review.read_gpx, path, consent=True, wgs84_confirmed=True)
    else:
        path = tmp_path / "places.csv"
        data = b"name,latitude,longitude\nFictional place,10,20\n"
        read = partial(places.read_catalog, path, consent=True, wgs84_confirmed=True)
    path.write_bytes(data)
    return path, data, read


@pytest.mark.parametrize("change", [None, "descriptor_ctime", "inode", "path_mtime"])
def test_file_identity_checks_separate_path_and_descriptor_clocks(
    local_reader, monkeypatch, change
):
    path, data, read = local_reader
    real_fstat = os.fstat
    before = path.stat()
    calls = 0

    def windows_fstat(fd):
        nonlocal calls
        calls += 1
        info = real_fstat(fd)
        fields = {
            key: getattr(info, key)
            for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode")
        }
        # The descriptor's change time can differ from the path's birth time
        # even when both describe an unchanged file on Windows.
        fields["st_ctime_ns"] += 1_000_000_000
        if change == "descriptor_ctime" and calls > 1:
            fields["st_ctime_ns"] += 1
        if change == "inode":
            fields["st_ino"] += 1
        if change == "path_mtime" and calls > 1:
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        return SimpleNamespace(**fields)

    with monkeypatch.context() as patch:
        patch.setattr(_file_identity, "_WINDOWS", True)
        patch.setattr(os, "fstat", windows_fstat)
        if change is None:
            document = read()
            digest = getattr(document, "sha256", getattr(document, "source_sha256", None))
            assert digest == hashlib.sha256(data).hexdigest()
        else:
            with pytest.raises(ValueError, match="changed"):
                read()
    assert path.read_bytes() == data
