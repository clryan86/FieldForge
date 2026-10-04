"""Optional online preparation window. Local map/GPS readers remain offline."""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from fieldforge.navigation.places import coordinate, coordinate_text
from fieldforge.online.compat import Cancelled, PortalSession, address_csv, route_gpx, save_new
from fieldforge.online.models import validate_portal_url
from fieldforge.ui.map_catalog_filters import CatalogFilters
from fieldforge.ui.portal_connection import confirm_connection, open_portal
from fieldforge_gps.tk_cleanup import TkCleanupMixin


def _worker(pending, completed, stop):
    while not stop.is_set():
        try:
            token, kind, action, args = pending.get(timeout=.1)
        except queue.Empty:
            continue
        try:
            result, error = action(*args), None
        except Cancelled:
            result, error = None, "Online operation cancelled."
        except (ValueError, FileExistsError) as exc:
            result, error = None, str(exc)
        except Exception:
            result, error = None, "The online operation failed. Reconnect or choose a different destination."
        if not stop.is_set():
            completed.put((token, kind, result, error))
        del action, args, result, error


def _connect(session, url):
    return session.connect(url, consent=True)


class OnlineMapWindow(TkCleanupMixin, tk.Toplevel):
    def __init__(self, parent, *, use_coordinate=None, open_asset=None):
        super().__init__(parent)
        self.title("FieldForge · Online preparation / offline files")
        self.geometry("1010x780")
        self.minsize(860, 690)
        self._closed = False
        self._busy = False
        self._choosing_file = False
        self._saving = False
        self._token = 0
        self._after = None
        self._route_endpoint_traces = []
        self._route_request = None
        self._planned_endpoints = None
        self.session = None
        self.results = ()
        self.items = ()
        self._catalog_loaded = False
        self._confirming = False
        self._connection_url = ""
        self.selected = None
        self.planned_route = None
        self.downloaded = None
        self._download_item = None
        self.use_coordinate = use_coordinate
        self.open_asset = open_asset
        self.return_grab = None
        self._pending, self._completed = queue.Queue(maxsize=1), queue.Queue()
        self._stop = threading.Event()
        self.worker = threading.Thread(target=_worker, args=(self._pending, self._completed, self._stop),
                                       name="FieldForge-portal", daemon=True)
        self.worker.start()
        self.url = tk.StringVar(value=os.environ.get("FIELDFORGE_MAP_PORTAL", ""))
        self.consent = tk.BooleanVar(value=False)
        self.query = tk.StringVar()
        self.status = tk.StringVar(value="Offline. Enter your portal URL and choose Connect to enable online tools.")
        self.detail = tk.StringVar(value="Select a possible address match before using its coordinates.")
        self.map_detail = tk.StringVar(value="Map files stay external to household backups. Keep their source notes.")
        self.route_detail = tk.StringVar(value="Saved driving-route geometry; no offline rerouting or live road conditions.")
        self.route_fields = {key: tk.StringVar() for key in ("start_lat", "start_lon", "end_lat", "end_lon")}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text="Prepare online. Use offline.", font=("TkDefaultFont", 19, "bold"),
                  padding=(18, 14)).grid(row=0, column=0, sticky="w")
        connection = ttk.Frame(self, padding=(18, 0, 18, 10))
        connection.grid(row=1, column=0, sticky="ew")
        connection.columnconfigure(1, weight=1)
        ttk.Label(connection, text="Portal URL").grid(row=0, column=0, padx=(0, 8))
        self.url_entry = ttk.Entry(connection, textvariable=self.url)
        self.url_entry.grid(row=0, column=1, sticky="ew")
        self.connect_button = ttk.Button(connection, text="Connect", command=self.connect)
        self.connect_button.grid(row=0, column=2, padx=8)
        self.offline_button = ttk.Button(connection, text="Go offline / cancel", command=self.disconnect)
        self.offline_button.grid(row=0, column=3)
        ttk.Checkbutton(connection, variable=self.consent, command=self._permission,
                        text="Send entered address searches and route coordinates to this portal and its providers.").grid(
                            row=1, column=0, columnspan=4, sticky="w", pady=10)
        self.portal_home_button = ttk.Button(connection, text="Open portal home", command=self.open_portal_home)
        self.portal_home_button.grid(row=2, column=1, sticky="w")
        ttk.Button(connection, text="Copy portal link", command=self.copy_portal_link).grid(row=2, column=2, columnspan=2)
        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=2, column=0, sticky="nsew", padx=18)
        addresses, maps, routes = [ttk.Frame(self.tabs, padding=14) for _ in range(3)]
        for frame, label in ((addresses, "Address search"), (maps, "Download maps"), (routes, "Plan & save route")):
            self.tabs.add(frame, text=label)
            frame.columnconfigure(0, weight=1)
        search_row = ttk.Frame(addresses)
        search_row.grid(row=0, column=0, sticky="ew")
        search_row.columnconfigure(0, weight=1)
        self.search_entry = ttk.Entry(search_row, textvariable=self.query)
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_entry.bind("<Return>", lambda _: self.search())
        self.search_button = ttk.Button(search_row, text="Search address", command=self.search)
        self.search_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(addresses, text="Include city and country. Search runs only when requested; possible matches are not a GPS fix.",
                  wraplength=760).grid(row=1, column=0, sticky="w", pady=8)
        addresses.rowconfigure(2, weight=1)
        self.table = ttk.Treeview(addresses, columns=("label", "lat", "lon"), show="headings", height=7)
        for key, label, width in (("label", "Possible address match", 510), ("lat", "Latitude", 120), ("lon", "Longitude", 120)):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=80)
        self.table.grid(row=2, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(addresses, command=self.table.yview)
        scroll.grid(row=2, column=1, sticky="ns")
        self.table.configure(yscrollcommand=scroll.set)
        self.table.bind("<<TreeviewSelect>>", self._selected)
        ttk.Label(addresses, textvariable=self.detail, wraplength=760).grid(row=3, column=0, sticky="ew", pady=10)
        actions = ttk.Frame(addresses)
        actions.grid(row=4, column=0, sticky="w")
        self.apply_button = ttk.Button(actions, text="Use coordinates", command=self.apply)
        self.copy_button = ttk.Button(actions, text="Copy lat, lon", command=self.copy)
        self.save_place_button = ttk.Button(actions, text="Save place CSV…", command=self.save_place)
        self.start_button = ttk.Button(actions, text="Use as start", command=lambda: self.route_point("start"))
        self.end_button = ttk.Button(actions, text="Use as destination", command=lambda: self.route_point("end"))
        for button in (self.apply_button, self.copy_button, self.save_place_button, self.start_button, self.end_button):
            button.pack(side="left", padx=(0, 7))
        self.refresh_button = ttk.Button(maps, text="Load / refresh catalogue", command=self.catalogue)
        self.refresh_button.grid(row=0, column=0, sticky="w")
        # This compatibility protocol exposes coverage labels, not numeric bounds.
        self.catalog_filters = CatalogFilters(maps, changed=self._render_catalog, point_filter=False)
        self.catalog_filters.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        maps.rowconfigure(2, weight=1)
        self.map_table = ttk.Treeview(maps, columns=("title", "coverage", "size"), show="headings", height=8)
        for key, label, width in (("title", "Map pack", 300), ("coverage", "Coverage", 300), ("size", "MiB", 100)):
            self.map_table.heading(key, text=label)
            self.map_table.column(key, width=width, minwidth=70)
        self.map_table.grid(row=2, column=0, sticky="nsew", pady=10)
        scroll = ttk.Scrollbar(maps, command=self.map_table.yview)
        scroll.grid(row=2, column=1, sticky="ns", pady=10)
        self.map_table.configure(yscrollcommand=scroll.set)
        self.map_table.bind("<<TreeviewSelect>>", self._map_selected)
        ttk.Label(maps, textvariable=self.map_detail, wraplength=760).grid(row=3, column=0, sticky="ew", pady=8)
        map_actions = ttk.Frame(maps)
        map_actions.grid(row=4, column=0, sticky="w")
        self.download_button = ttk.Button(map_actions, text="Download selected map…", command=self.download)
        self.download_button.pack(side="left")
        self.open_button = ttk.Button(map_actions, text="Open downloaded map", command=self.open_download)
        self.open_button.pack(side="left", padx=10)
        ttk.Label(routes, text="Driving route · latitude first, longitude second · WGS84 decimal degrees",
                  wraplength=760).grid(row=0, column=0, sticky="w")
        route_box = ttk.Frame(routes)
        route_box.grid(row=1, column=0, sticky="ew", pady=16)
        self.route_entries = []
        for index, (key, label) in enumerate((("start_lat", "Start latitude"), ("start_lon", "Start longitude"),
                                            ("end_lat", "Destination latitude"), ("end_lon", "Destination longitude"))):
            row, col = divmod(index, 2)
            ttk.Label(route_box, text=label).grid(row=row*2, column=col, sticky="w", padx=(0, 18))
            entry = ttk.Entry(route_box, textvariable=self.route_fields[key], width=28)
            entry.grid(row=row*2+1, column=col, sticky="ew", padx=(0, 18), pady=(3, 12))
            self.route_entries.append(entry)
            route_box.columnconfigure(col, weight=1)
        self.plan_button = ttk.Button(routes, text="Request driving route", command=self.plan_route)
        self.plan_button.grid(row=2, column=0, sticky="w")
        ttk.Label(routes, textvariable=self.route_detail, wraplength=760).grid(row=3, column=0, sticky="ew", pady=16)
        self.save_route_button = ttk.Button(routes, text="Save planned route GPX…", command=self.save_route)
        self.save_route_button.grid(row=4, column=0, sticky="w")
        ttk.Label(routes, text="Open the saved GPX with the workspace's GPX controls. Download a map of its area separately. "
                  "A planned route is not a recorded trip and does not establish safe access.", wraplength=760).grid(
                      row=5, column=0, sticky="ew", pady=16)
        ttk.Label(self, textvariable=self.status, padding=18, wraplength=820).grid(row=3, column=0, sticky="ew")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Destroy>", lambda event: self._dispose() if event.widget is self else None, add=True)
        self._route_endpoint_traces = [
            (value, value.trace_add("write", self._route_endpoints_changed))
            for value in self.route_fields.values()
        ]
        self._buttons()
        self._after = self.after(40, self._poll)

    def _online(self):
        return self.session is not None and self.session.ready and not self.session.cancel.is_set()

    def _buttons(self):
        if self._closed:
            return
        online = self._online() and not self._busy
        caps = self.session.capabilities if self.session else {}
        for widget in (self.search_entry, self.search_button):
            widget.configure(state="normal" if online and caps.get("geocoding") else "disabled")
        self.plan_button.configure(state="normal" if online and caps.get("routing") else "disabled")
        self.portal_home_button.configure(state="normal" if self._online() else "disabled")
        self.refresh_button.configure(state="normal" if online else "disabled")
        self.download_button.configure(state="normal" if online and self._map_item() else "disabled")
        self.connect_button.configure(state="disabled" if self._online() or self._busy else "normal")
        self.url_entry.configure(state="disabled" if self._online() or self._busy else "normal")
        self.offline_button.configure(state="normal" if self._online() or self._busy else "disabled")
        for button in (self.copy_button, self.save_place_button, self.start_button, self.end_button):
            button.configure(state="normal" if self.selected else "disabled")
        self.apply_button.configure(state="normal" if self.selected and self.use_coordinate else "disabled")
        self.save_route_button.configure(state="normal" if self.planned_route else "disabled")
        self.open_button.configure(state="normal" if self.downloaded and self.open_asset else "disabled")

    def _submit(self, kind, action, *args):
        if self._closed or self._busy:
            return False
        self._token += 1
        self._busy = True
        self._pending.put_nowait((self._token, kind, action, args))
        self.status.set({"connect": "Connecting to the selected portal…", "search": "Searching the entered address…",
                         "maps": "Loading published map catalogue…", "route": "Requesting driving route…",
                         "download": "Downloading and verifying map; Go offline cancels unfinished work…"}[kind])
        self._buttons()
        return True

    def connect(self):
        if self._closed or self._busy or self._online() or self._confirming:
            return False
        if not self.consent.get():
            self.status.set("Choose to send searches to this portal before connecting.")
            return False
        try:
            url = validate_portal_url(self.url.get().strip())
        except ValueError as exc:
            self.status.set(str(exc))
            return False
        self._confirming = True
        try:
            accepted = confirm_connection(self, url)
        finally:
            self._confirming = False
        if self._closed:
            return False
        if not accepted:
            self.status.set("Stayed offline. No portal request was sent.")
            return False
        self._connection_url = url
        self.items, self._catalog_loaded = (), False
        self._render_catalog()
        self.session = PortalSession()
        return self._submit("connect", _connect, self.session, url)

    def open_portal_home(self):
        if self._closed or not self._online():
            return
        if not open_portal(self._connection_url):
            self.status.set("Browser could not open. Use Copy portal link: " + self._connection_url)

    def copy_portal_link(self):
        if self._closed:
            return
        try:
            url = self._connection_url if self._online() else validate_portal_url(self.url.get().strip())
            self.clipboard_clear()
            self.clipboard_append(url)
            self.status.set("Portal link copied. Opening it in a browser uses your internet connection.")
        except (ValueError, tk.TclError) as exc:
            self.status.set(str(exc))

    def _permission(self):
        if not self.consent.get():
            self.disconnect()

    def disconnect(self):
        if self._closed:
            return
        if self.session:
            self.session.disconnect()
        self._token += 1
        self._busy = False
        self._route_request = None
        try:
            self._pending.get_nowait()
        except queue.Empty:
            pass
        self.status.set("Offline. Saved files and selected coordinates remain available. Reconnect explicitly when wanted.")
        self._buttons()

    def search(self):
        if self._online() and self.session.capabilities.get("geocoding") and self.query.get().strip():
            return self._submit("search", self.session.search, self.query.get())
        return False

    def catalogue(self):
        if self._online():
            return self._submit("maps", self.session.maps)
        return False

    def _selected(self, _event=None):
        selected = self.table.selection()
        if selected and int(selected[0]) < len(self.results):
            self.selected = self.results[int(selected[0])]
            point = self.selected
            self.detail.set(f"{point.label}\nLatitude {coordinate_text(point.latitude)}, longitude {coordinate_text(point.longitude)}. "
                            f"{point.source} · {point.attribution}")
        self._buttons()

    def apply(self):
        if self.selected and self.use_coordinate:
            try:
                self.use_coordinate(self.selected)
                self.status.set("Coordinates filled in. Review the fields and save explicitly.")
            except (ValueError, tk.TclError) as exc:
                self.status.set(str(exc))

    def copy(self):
        if self.selected:
            self.clipboard_clear()
            self.clipboard_append(f"{coordinate_text(self.selected.latitude)}, {coordinate_text(self.selected.longitude)}")
            self.status.set("Latitude, longitude copied by your request.")

    def save_place(self):
        if self._closed or not self.selected:
            return
        value = self.selected
        try:
            content = address_csv(value)
        except ValueError as exc:
            self.status.set("Could not save place CSV: " + str(exc))
            return
        self._choosing_file = True
        try:
            path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="fieldforge-place.csv")
        finally:
            self._choosing_file = False
        if path and not self._closed:
            self._save(path, content)

    def _save(self, path, content):
        self._saving = True
        try:
            save_new(path, content)
            self.status.set(f"Saved for offline use: {Path(path).name}")
        except (OSError, ValueError):
            self.status.set("Could not save. Choose a writable folder and a new filename; existing files are not overwritten.")
        finally:
            self._saving = False

    def route_point(self, prefix):
        if self.selected:
            self.route_fields[prefix + "_lat"].set(coordinate_text(self.selected.latitude))
            self.route_fields[prefix + "_lon"].set(coordinate_text(self.selected.longitude))
            self.status.set("Selected coordinate filled into the route form.")

    def plan_route(self):
        if not self._online() or not self.session.capabilities.get("routing"):
            return False
        try:
            values = {key: coordinate(var.get(), latitude=key.endswith("lat")) for key, var in self.route_fields.items()}
        except ValueError as exc:
            self.status.set(str(exc))
            return False
        start = values["start_lat"], values["start_lon"]
        end = values["end_lat"], values["end_lon"]
        submitted = self._submit("route", self.session.route, start, end)
        if submitted:
            # Retain the requested endpoints with this operation token. A
            # router's snapped geometry is not evidence of the entered points.
            self._route_request = (self._token, start, end)
        return submitted

    def _route_endpoints_changed(self, *_args):
        if not self._closed:
            self._update_route_detail()

    def _update_route_detail(self):
        route = self.planned_route
        if route is None:
            return
        lines = [f"PLANNED driving route: {route['distance_m']/1000:.1f} km, "
                 f"{route['duration_s']/60:.0f} minutes estimated. Requested {route['created_at']}"]
        if self._planned_endpoints is not None:
            start, end = self._planned_endpoints
            for label, point in (("Requested start", start), ("Requested destination", end)):
                lines.append(f"{label}: latitude {coordinate_text(point[0])}, longitude {coordinate_text(point[1])}")
            try:
                form = tuple(coordinate(self.route_fields[key].get(), latitude=key.endswith("lat"))
                             for key in ("start_lat", "start_lon", "end_lat", "end_lon"))
                matches = form == (*start, *end)
            except ValueError:
                matches = False
            if not matches:
                lines.append("Selected plan uses previous coordinates")
        lines.extend([f"{route['source']} · {route['attribution']}",
                      "Not a recorded trip or current road-condition report."])
        self.route_detail.set("\n".join(lines))

    def save_route(self):
        if self._closed or self.planned_route is None:
            return
        value = self.planned_route
        try:
            content = route_gpx(value)
        except ValueError as exc:
            self.status.set("Could not save planned route GPX: " + str(exc))
            return
        self._choosing_file = True
        try:
            path = filedialog.asksaveasfilename(parent=self, defaultextension=".gpx", initialfile="fieldforge-planned-route.gpx")
        finally:
            self._choosing_file = False
        if path and not self._closed:
            self._save(path, content)

    def _map_item(self):
        selected = self.map_table.selection()
        return self.items[int(selected[0])] if selected and int(selected[0]) < len(self.items) else None

    def _render_catalog(self, *, preserve_selection=True):
        if self._closed:
            return
        previous = self.map_table.selection() if preserve_selection else ()
        visible = self.catalog_filters.apply(self.items, loaded=self._catalog_loaded)
        indexes = {item.id: index for index, item in enumerate(self.items)}
        self.map_table.delete(*self.map_table.get_children())
        for item in visible:
            self.map_table.insert("", "end", iid=str(indexes[item.id]), values=(item.title, item.coverage, f"{item.size/1024**2:.1f}"))
        if previous and self.map_table.exists(previous[0]):
            self.map_table.selection_set(previous[0])
        self._map_selected()

    def _map_selected(self, _event=None):
        item = self._map_item()
        if item:
            self.map_detail.set(f"{item.title} · {item.coverage} · {item.kind} · updated {item.updated}\n"
                                f"{item.source} · {item.attribution}\n{item.license}")
        else:
            self.map_detail.set("Select a visible map to inspect coverage and download details.")
        self._buttons()

    def download(self):
        item = self._map_item()
        if not item or not self._online() or self._busy:
            return False
        session = self.session
        self._choosing_file = True
        try:
            path = filedialog.asksaveasfilename(parent=self, initialfile=item.filename,
                                               defaultextension=Path(item.filename).suffix)
        finally:
            self._choosing_file = False
        if not path or self._closed or not self._online() or self.session is not session:
            return False
        self._download_item = item
        return self._submit("download", session.download, item, path)

    def open_download(self):
        if self.downloaded and self.open_asset:
            try:
                self.open_asset(*self.downloaded)
            except (ValueError, OSError, tk.TclError) as exc:
                self.status.set(str(exc))

    def _poll(self):
        if self._closed:
            return
        while True:
            try:
                token, kind, value, error = self._completed.get_nowait()
            except queue.Empty:
                break
            if token != self._token:
                continue
            self._busy = False
            if error:
                self.disconnect()
                self.status.set("Offline — " + error)
            elif kind == "connect":
                providers = " · ".join(p["name"] for p in value.get("providers", {}).values())
                missing = [label for key, label in (("geocoding", "address search"), ("routing", "routes"))
                           if not self.session.capabilities.get(key)]
                self.status.set("Connected. " + providers + (" Not configured: " + ", ".join(missing) if missing else ""))
                self.open_portal_home()
            elif kind == "search":
                self.table.delete(*self.table.get_children())
                self.results = value
                for index, point in enumerate(value):
                    self.table.insert("", "end", iid=str(index), values=(point.label, point.latitude, point.longitude))
                self.status.set(f"{len(value)} possible matches. Select one explicitly." if value else "No matches. Try city and country.")
            elif kind == "maps":
                self.items = value
                self._catalog_loaded = True
                self._render_catalog(preserve_selection=False)
                self.status.set(f"{len(value)} published map packs." if value else "This portal has no published maps yet.")
            elif kind == "route":
                self.planned_route = value
                request = self._route_request
                self._planned_endpoints = request[1:] if request is not None and request[0] == token else None
                self._route_request = None
                self._update_route_detail()
                self.status.set("Route ready. Save GPX for offline review.")
            elif kind == "download":
                self.downloaded = (value, self._download_item.kind)
                self.status.set(f"Verified and saved {value.name} with its source note. Ready offline.")
            self._buttons()
        self._after = self.after(40, self._poll)

    def _dispose(self):
        if self._closed:
            return
        self._closed = True
        self.catalog_filters.close()
        for value, token in self._route_endpoint_traces:
            try:
                value.trace_remove("write", token)
            except tk.TclError:
                pass
        self._route_endpoint_traces.clear()
        if self.session:
            self.session.disconnect()
        self._token += 1
        self._busy = False
        self._stop.set()
        try:
            self._pending.get_nowait()
        except queue.Empty:
            pass
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def can_close(self):
        if self._closed:
            return True
        if self._saving or self._choosing_file:
            self.status.set("Finish the local file save or file picker before closing this window.")
            self.lift()
            return False
        return True

    def close(self):
        if self.can_close():
            self.destroy()

    def destroy(self):
        if self.__dict__.get("_tk_destroyed", False):
            return
        self._dispose()
        return_grab = self.return_grab
        try:
            super().destroy()
        finally:
            # These owned Tk references are nested, so the mixin cannot release
            # them itself. Finalize them here on the UI thread before worker GC.
            self.route_fields.clear()
            self.route_entries.clear()
            self.use_coordinate = self.open_asset = None
        if return_grab is not None:
            try:
                if return_grab.winfo_exists():
                    return_grab.grab_set()
            except tk.TclError:
                pass
