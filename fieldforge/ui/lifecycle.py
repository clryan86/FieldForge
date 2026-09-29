"""Release custom Tk references on the UI thread during widget destruction."""

from __future__ import annotations

import tkinter as tk


def release_tk_references(widget: tk.Misc) -> None:
    """Drop owned variables/child references before a worker can collect a cycle.

    Call from the widget's own Destroy event after cancelling UI callbacks. Keep
    the standard master attribute: Tkinter still needs it to complete destroy().
    The closed widget must not be used again after this cleanup.
    """
    for name, value in tuple(vars(widget).items()):
        if name != "master" and isinstance(value, (tk.Misc, tk.Variable)):
            setattr(widget, name, None)
