"""Release owned Tk references during UI-thread destruction, not worker-thread GC."""

from __future__ import annotations

import tkinter as tk


class TkCleanupMixin:
    """For these windows, direct Variable attributes are owned, not shared.

    Tk destroys widgets and commands but Python widget/Variable reference cycles
    can otherwise survive until cyclic GC runs in a parser thread. Removing traces
    and releasing the window's Tk references here keeps their finalizers on the
    thread that destroys the window. No global GC setting or private Tk internals
    are changed. Destroyed window controls are deliberately no longer usable.
    """

    def destroy(self):
        if self.__dict__.get("_tk_destroyed", False):
            return
        self._tk_destroyed = True
        variables = [value for value in self.__dict__.values() if isinstance(value, tk.Variable)]
        for variable in variables:
            for modes, callback in variable.trace_info():
                variable.trace_remove(modes, callback)
        try:
            super().destroy()
        finally:
            # Destroy has already detached children from their parents. Also drop
            # attribute references (including master) that would retain cycles.
            for name, value in tuple(self.__dict__.items()):
                if isinstance(value, (tk.Variable, tk.Misc)):
                    setattr(self, name, None)
