"""Small Tk-owned worker window shared by map acquisition and route planning."""
from __future__ import annotations

import queue
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from tkinter import ttk


class MapTaskWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='fieldforge-map-task')
        self._cancel = Event()
        self._future = self._poll_id = self._done = None
        self._disposed = self.busy = self._closing = False
        self._progress = queue.Queue(maxsize=1)
        self.status = tk.StringVar()
        self.progress_value = tk.DoubleVar(value=0)
        self._controls = []
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Destroy>', self._destroyed, add=True)

    def status_row(self, parent):
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(frame, textvariable=self.status, wraplength=850, justify='left')
        self.status_label.grid(row=0, column=0, columnspan=2, sticky='ew', pady=6)
        self.progress_bar = ttk.Progressbar(frame, variable=self.progress_value, maximum=100)
        self.progress_bar.grid(row=1, column=0, sticky='ew')
        self.cancel_button = ttk.Button(frame, text='Cancel operation', state='disabled', command=self.cancel)
        self.cancel_button.grid(row=1, column=1, padx=(8, 0))
        return frame

    def start_task(self, function, *args, done=None, progress=False, **kwargs):
        if self.busy or self._disposed:
            return False
        self.busy = True
        self._cancel = Event()
        self._progress = queue.Queue(maxsize=1)
        self._done = done
        self.progress_value.set(0)
        for widget, _state in self._controls:
            widget.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        if progress:
            kwargs['progress'] = _progress_callback(self._progress)
        self._future = self._worker.submit(function, *args, cancel=self._cancel, **kwargs)
        self._poll_id = self.after(40, self._poll)
        return True

    def _poll(self):
        if self._disposed:
            return
        self._poll_id = None
        try:
            current, total = self._progress.get_nowait()
        except queue.Empty:
            pass
        else:
            self.progress_value.set(100 * current / max(1, total))
            self.status.set(self.progress_message(current, total))
        if not self._future.done():
            self._poll_id = self.after(40, self._poll)
            return
        self.busy = False
        self.cancel_button.configure(state='disabled')
        for widget, state in self._controls:
            widget.configure(state=state)
        done, self._done = self._done, None
        try:
            result = self._future.result()
            if self._cancel.is_set():
                self.status.set(self.cancelled_message())
            elif not self._closing and done is not None:
                done(result)
        except Exception as exc:
            self.status.set(str(exc)[:1500])
        if self._closing:
            self.destroy()

    def progress_message(self, current, total):
        return f'Downloaded {current:,} of {total:,} bytes. Source data, not route-ready.'

    def cancelled_message(self):
        return 'Cancelled; no result displayed. A transfer that had already completed may remain in the selected folder.'

    def cancel(self):
        if self.busy:
            self._cancel.set()
            self.status.set('Cancelling… Waiting for the current network/disk operation to return.')

    def close(self):
        if self.busy:
            self._closing = True
            self.cancel()
        else:
            self.destroy()

    def _destroyed(self, event):
        if event.widget is self and not self._disposed:
            self._disposed = True
            self._cancel.set()
            if self._poll_id is not None:
                self.after_cancel(self._poll_id)
                self._poll_id = None
            self._done = None
            self._worker.shutdown(wait=False, cancel_futures=True)


def _progress_callback(q):
    # Worker captures only the queue, never a Tk object or a bound Tk method.
    def update(current, total):
        try:
            q.put_nowait((current, total))
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait((current, total))
            except queue.Full:
                pass
    return update
