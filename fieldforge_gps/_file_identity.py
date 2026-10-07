"""Compare path and descriptor metadata without mixing Windows clock meanings."""

import os

_WINDOWS = os.name == "nt"


def snapshot(info):
    """Keep every identity/change field for comparisons made through the same API."""
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def path_matches_descriptor(path_info, descriptor_info):
    """Check that a selected path and an opened handle refer to the same snapshot.

    Windows path stat can report creation time as ctime while fstat reports
    change time (https://github.com/python/cpython/issues/157671). Compare the
    portable fields across those APIs, keeping full snapshots for each API's
    before/after checks in the caller. POSIX still compares ctime here too.
    """
    path_snapshot = snapshot(path_info)
    descriptor_snapshot = snapshot(descriptor_info)
    if _WINDOWS:
        return path_snapshot[:-1] == descriptor_snapshot[:-1]
    return path_snapshot == descriptor_snapshot
