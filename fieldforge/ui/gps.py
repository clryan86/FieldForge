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
        self.portal_window = None

    def open_portal(self):
        if self.portal_window is not None and self.portal_window.winfo_exists():
            self.portal_window.lift()
            return self.portal_window
        from fieldforge.ui.online_maps import OnlineMapWindow

        def use_coordinate(point):
            from fieldforge.navigation.places import coordinate_text

            finder = self.open().live_map_frame.open_finder()
            finder.latitude.set(coordinate_text(point.latitude))
            finder.longitude.set(coordinate_text(point.longitude))
            finder.manual_status.set(f"Online match: {point.label}. {point.source}; {point.attribution}. "
                                     "Review these coordinates, then choose Show coordinate.")

        def open_asset(path, kind):
            view = self.open().live_map_frame
            if kind == "mbtiles":
                view.map_trust.set(True)
                view.start_map(path)
            else:
                image = view.open_image_reference()
                image.permission.set(True)
                image.open_path(path)

        self.portal_window = OnlineMapWindow(self.parent, use_coordinate=use_coordinate, open_asset=open_asset)
        return self.portal_window

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
        if self.portal_window is not None and self.portal_window.winfo_exists():
            self.portal_window.close()
        self.portal_window = None
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
    navigation.add_separator()
    navigation.add_command(label="Online map portal…", command=workspace.open_portal)
    menu_bar.insert_cascade(0, label="Navigation", menu=navigation)
    return workspace
