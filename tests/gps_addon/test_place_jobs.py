import threading
import time

import pytest

from fieldforge_gps import place_jobs

from .test_places import CSV


@pytest.fixture
def worker():
    value = place_jobs.LatestPlaceWorker()
    yield value
    value.close()
    value._thread.join(2)
    assert not value._thread.is_alive()


def await_result(worker):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        result = worker.poll()
        if result:
            return result
        time.sleep(0.005)
    raise AssertionError("No worker result")


def test_read_then_search(worker, tmp_path):
    path = tmp_path / "file.csv"
    path.write_bytes(CSV)
    token = worker.submit("load", path)
    result = await_result(worker)
    assert result[0] == token and result[1] == "load" and result[3] is None
    doc = result[2]
    token = worker.submit("search", doc, "cafe")
    result = await_result(worker)
    assert result[0] == token and result[2].total == 1 and result[3] is None


def test_file_failure_does_not_publish_private_path(worker, tmp_path):
    worker.submit("load", tmp_path / "private-file-do-not-display.csv")
    result = await_result(worker)
    assert result[2] is None and "private-file" not in result[3]


def test_latest_request_wins_and_queue_bounded(worker, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def search(doc, query, **kwargs):
        if query == "first":
            started.set()
            release.wait(2)
        return query

    monkeypatch.setattr(place_jobs, "search_places", search)
    worker.submit("search", None, "first")
    assert started.wait(1)
    for index in range(30):
        worker.submit("search", None, f"new-{index}")
    assert worker._pending.qsize() <= 1
    release.set()
    assert await_result(worker)[2] == "new-29"


def test_cancel_active_work_does_not_publish(worker, monkeypatch):
    started = threading.Event()
    done = threading.Event()

    def search(*args, cancel, **kwargs):
        started.set()
        cancel.wait(2)
        done.set()
        return "obsolete"

    monkeypatch.setattr(place_jobs, "search_places", search)
    worker.submit("search", None, "x")
    assert started.wait(1)
    worker.cancel()
    assert done.wait(1)
    time.sleep(0.03)
    assert worker.poll() is None


def test_unknown_operation_and_unexpected_failure(worker, monkeypatch):
    worker.submit("unknown")
    assert "Unknown" in await_result(worker)[3]

    def error(*args, **kwargs):
        raise RuntimeError("PRIVATE DATA")

    monkeypatch.setattr(place_jobs, "search_places", error)
    worker.submit("search", None, "query")
    result = await_result(worker)
    assert "PRIVATE" not in result[3] and result[2] is None


def test_closed_worker_rejects_new_tasks(worker):
    worker.close()
    worker.close()
    with pytest.raises(ValueError, match="closed"):
        worker.submit("search", None, "x")
    assert worker.poll() is None
