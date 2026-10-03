"""One non-Tk worker with one replaceable pending place operation."""

from __future__ import annotations

import queue
import threading

from .places import read_catalog, search_places


def _worker(pending, completed, stop):
    while not stop.is_set():
        try:
            token, kind, args, cancel = pending.get(timeout=0.1)
        except queue.Empty:
            continue
        if stop.is_set():
            break
        try:
            if kind == "load":
                result = read_catalog(*args, consent=True, wgs84_confirmed=True, cancel=cancel)
            elif kind == "search":
                result = search_places(*args, cancel=cancel)
            else:
                raise ValueError("Unknown place operation.")
            error = None
        except ValueError as exc:
            result, error = None, str(exc)
        except OSError:
            result, error = (
                None,
                "Place file could not be read. Check the selected local file and permissions.",
            )
        except Exception:
            result, error = None, "Unexpected place operation failure. No partial results accepted."
        if not stop.is_set() and not cancel.is_set():
            try:
                completed.get_nowait()
            except queue.Empty:
                pass
            completed.put_nowait((token, kind, result, error))
        # Do not retain private catalogue arguments while waiting for another job.
        del args, result, error, cancel


class LatestPlaceWorker:
    def __init__(self):
        self._pending = queue.Queue(maxsize=1)
        self._completed = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._cancel = None
        self.token = 0
        self._thread = threading.Thread(
            target=_worker,
            args=(self._pending, self._completed, self._stop),
            name="FieldForge-place-search",
            daemon=True,
        )
        self._thread.start()

    def submit(self, kind, *args):
        if self._stop.is_set():
            raise ValueError("Place worker is closed.")
        self.cancel()
        self._cancel = threading.Event()
        self._pending.put_nowait((self.token, kind, args, self._cancel))
        return self.token

    def cancel(self):
        self.token += 1
        if self._cancel is not None:
            self._cancel.set()
        for channel in (self._pending, self._completed):
            try:
                channel.get_nowait()
            except queue.Empty:
                pass

    def poll(self):
        try:
            item = self._completed.get_nowait()
        except queue.Empty:
            return None
        return item if item[0] == self.token and not self._stop.is_set() else None

    def close(self):
        self.cancel()
        self._stop.set()
