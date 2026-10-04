"""One worker plus one replaceable queued request. Workers own no Tk objects."""

from __future__ import annotations

import queue
import threading

from .mbtiles import inspect_pack, read_tiles


def _worker(pending, completed, stop):
    while not stop.is_set():
        try:
            token, kind, args, cancel = pending.get(timeout=0.1)
        except queue.Empty:
            continue
        if stop.is_set():
            break
        try:
            if kind == "open":
                result = inspect_pack(*args, consent=True, cancel=cancel)
            elif kind == "tiles":
                result = read_tiles(*args, cancel=cancel)
            elif kind == "image_open":
                from .raster import read_reference

                result = read_reference(*args, consent=True, cancel=cancel)
            elif kind == "image_render":
                from .raster import render_reference

                result = render_reference(*args, cancel=cancel)
            else:
                raise ValueError("Unknown map operation.")
            error = None
        except (ValueError, OSError) as exc:
            result, error = None, str(exc)
        except Exception:
            result, error = None, "Unexpected local map-reader failure. No partial map accepted."
        if stop.is_set():
            break
        try:
            completed.get_nowait()
        except queue.Empty:
            pass
        completed.put_nowait((token, kind, result, error))
        del args, result, error, cancel


class LatestMapReader:
    def __init__(self):
        self._pending = queue.Queue(maxsize=1)
        self._completed = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._cancel = None
        self.token = 0
        self._thread = threading.Thread(
            target=_worker,
            args=(self._pending, self._completed, self._stop),
            name="FieldForge-local-map",
            daemon=True,
        )
        self._thread.start()

    def submit(self, kind, *args):
        if self._stop.is_set():
            raise ValueError("Map reader is closed.")
        self.cancel()
        self._cancel = threading.Event()
        self._pending.put_nowait((self.token, kind, args, self._cancel))
        return self.token

    def cancel(self):
        self.token += 1
        if self._cancel:
            self._cancel.set()
        for channel in (self._pending, self._completed):
            try:
                channel.get_nowait()
            except queue.Empty:
                pass

    def poll(self):
        try:
            result = self._completed.get_nowait()
        except queue.Empty:
            return None
        return result if result[0] == self.token and not self._stop.is_set() else None

    def close(self):
        self.cancel()
        self._stop.set()
