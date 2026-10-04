import threading
import time

import pytest

from fieldforge_gps import map_jobs


def wait_result(reader):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        value = reader.poll()
        if value:
            return value
        time.sleep(0.005)
    raise AssertionError("No map job result")


def test_only_latest_request_published_single_worker(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = []
    thread_ids = []

    def inspect(path, **kwargs):
        calls.append(path)
        thread_ids.append(threading.get_ident())
        if path == "old":
            entered.set()
            release.wait(2)
        return path

    monkeypatch.setattr(map_jobs, "inspect_pack", inspect)
    r = map_jobs.LatestMapReader()
    try:
        r.submit("open", "old")
        assert entered.wait(1)
        r.submit("open", "skipped")
        token = r.submit("open", "new")
        release.set()
        value = wait_result(r)
        assert value == (token, "open", "new", None)
        assert calls == ["old", "new"]
        assert len(set(thread_ids)) == 1 and thread_ids[0] != threading.get_ident()
    finally:
        r.close()
        release.set()
        r._thread.join(2)
    assert not r._thread.is_alive()


def test_cancel_discards_even_successful_late_result(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def inspect(*args, **kwargs):
        entered.set()
        release.wait(2)
        return "late"

    monkeypatch.setattr(map_jobs, "inspect_pack", inspect)
    r = map_jobs.LatestMapReader()
    r.submit("open", "path")
    assert entered.wait(1)
    r.cancel()
    release.set()
    time.sleep(0.05)
    assert r.poll() is None
    r.close()
    r._thread.join(2)


def test_worker_exception_is_reported_without_sensitive_traceback(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("secret /private/path")

    monkeypatch.setattr(map_jobs, "inspect_pack", fail)
    r = map_jobs.LatestMapReader()
    try:
        r.submit("open", "path")
        value = wait_result(r)
        assert value[2] is None and "Unexpected" in value[3] and "secret" not in value[3]
    finally:
        r.close()
        r._thread.join(2)


def test_closed_reader_cannot_accept_jobs():
    r = map_jobs.LatestMapReader()
    r.close()
    with pytest.raises(ValueError, match="closed"):
        r.submit("open", "path")
    assert r.poll() is None
    r._thread.join(2)
