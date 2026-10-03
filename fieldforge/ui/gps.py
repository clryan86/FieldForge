"""Own the optional in-memory GPS workspace within the FieldForge desktop."""

from __future__ import annotations

import tkinter as tk

from fieldforge_gps.__main__ import GPSWindow


class GPSWorkspace:
    """Reuse one receiver workspace; leave source selection and recording explicit."""

    def __init__(self, parent):
        self.parent = parent
        self.window = None
        self.receiver = None

    def open(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.receiver.open_live_map()
            return self.receiver
        window = tk.Toplevel(self.parent)
        window.title("FieldForge · GPS receiver controls")
        window.geometry("960x740")
        window.minsize(880, 700)
        self.window = window
        try:
            self.receiver = GPSWindow(window)
            self.receiver.open_live_map()
        except Exception:
            self.close()
            raise

        def destroyed(event):
            if event.widget is window and self.window is window:
                self.window = self.receiver = None

        window.bind("<Destroy>", destroyed, add=True)
        window.protocol("WM_DELETE_WINDOW", self.request_close)
        return self.receiver

    def can_close(self):
        return self.receiver is None or self.receiver._closed or self.receiver.request_close()

    def request_close(self):
        if self.can_close():
            self.close()

    def close(self):
        receiver, window = self.receiver, self.window
        self.receiver = self.window = None
        if receiver is not None:
            receiver.close()
        if window is not None and window.winfo_exists():
            window.destroy()


def install_gps_menu(root, menu_bar):
    workspace = GPSWorkspace(root)
    navigation = tk.Menu(menu_bar, tearoff=False)
    navigation.add_command(label="Maps, GPS & places…", command=workspace.open)
    navigation.add_command(
        label="Open map image…",
        command=lambda: workspace.open().live_map_frame.open_image_reference(),
    )
    menu_bar.insert_cascade(0, label="Navigation", menu=navigation)
    return workspace
