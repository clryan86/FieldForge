"""Optional portal access with locally reusable maps, routes, and coordinates.

Constructing or reopening this workspace never connects to the network. A
worker owns each explicit service operation; only Tk callbacks publish results.
"""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import tempfile
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.navigation.places import PlaceStore, coordinate, coordinate_text
from fieldforge.online.client import PortalCancelled, PortalClient, PortalError, PortalOffline
from fieldforge.online.compat import Address, address_csv, save_new
from fieldforge.online.download_list import (
    download_maps,
    load_download_list,
    make_download_list,
    save_download_list,
)
from fieldforge.online.models import validate_portal_url
from fieldforge.online.storage import PortalLibrary
from fieldforge.ui.map_catalog_filters import CatalogFilters
from fieldforge.ui.map_download_list import MapDownloadListWindow
from fieldforge.ui.online_compat import OnlineMapWindow as OnlineMapWindow
from fieldforge.ui.portal_connection import confirm_connection, open_portal
from fieldforge_gps.tk_cleanup import TkCleanupMixin

HEALTH_CHECK_MS = 30_000
_NETWORK = {"connect", "health", "search", "catalog", "route", "download", "download_list"}
_WRITES = {"save_route", "export_gpx", "import_route", "save_place_csv", "save_download_list", "import_download_list"}
_ERRORS = (OSError, ValueError, sqlite3.Error, PortalError)


def _size(value):
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if amount < 1024 or unit == "GiB":
            return f"{amount:,.1f} {unit}" if unit != "B" else f"{amount:,.0f} B"
        amount /= 1024


def _route_summary(route):
    minutes = route["duration_s"] / 60
    duration = f"{minutes:,.0f} min" if minutes < 60 else f"{minutes / 60:,.1f} h"
    return f"{route['title']} · {route['distance_m'] / 1000:,.1f} km · estimated {duration}"


def _route_endpoints(route):
    return [f"{label}: latitude {coordinate_text(route[key]['latitude'])}, "
            f"longitude {coordinate_text(route[key]['longitude'])}"
            for label, key in (("Start", "start"), ("Destination", "end"))]


class OnlineMapsTab(TkCleanupMixin, ttk.Frame):
    def __init__(self, parent, database, *, on_open_map=None, on_center=None,
                 on_use_place=None, on_show_route=None, client_factory=PortalClient):
        super().__init__(parent, padding=12)
        self.database = Path(database).expanduser().resolve()
        self.settings_path = self.database.parent / "online-maps" / "settings.json"
        self.library = None
        self._storage_error = ""
        try:
            self.library = PortalLibrary(self.settings_path.parent)
        except (OSError, ValueError) as exc:
            self._storage_error = "Downloaded-file storage is unavailable: " + str(exc)
        self.client_factory = client_factory
        self.client = None
        self.connected = False
        self.capabilities = {}
        self.on_open_map = on_open_map
        self.on_center = on_center
        self.on_use_place = on_use_place
        self.on_show_route = on_show_route
        self.dialog = None
        self._map_windows = []
        self._fallback_map = None
        self._disposed = False
        self._generation = 0
        self._cancel = Event()
        self._future = None
        self._poll_id = None
        self._heartbeat_id = None
        self._operation = None
        self._choosing_file = False
        self._progress = queue.Queue(maxsize=1)
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fieldforge-portal")
        self.busy = False
        self._results = ()
        self._catalog = ()
        self._catalog_loaded = False
        self._download_list = None
        self._download_list_window = None
        self._confirming = False
        self._connection_url = ""
        self._routes = ()
        self._local_maps = ()
        self._saved_routes = ()
        self.selected_result = None
        self.current_route = None
        self._retained_route_reason = ""
        self._updating_route_endpoints = False
        self.portal_url = tk.StringVar(value=os.environ.get("FIELDFORGE_MAP_PORTAL", ""))
        self.query = tk.StringVar()
        self.latitude = tk.StringVar()
        self.longitude = tk.StringVar()
        self.start_lat = tk.StringVar()
        self.start_lon = tk.StringVar()
        self.end_lat = tk.StringVar()
        self.end_lon = tk.StringVar()
        self.connection_status = tk.StringVar(value="Offline · Connect to use a portal.")
        self.status = tk.StringVar(value="Saved maps, routes and selected coordinates work offline.")
        self.selected_info = tk.StringVar(value="Select a result to review its full address and coordinates.")
        self.map_info = tk.StringVar(value="Connect and refresh to see the portal's available maps.")
        self.route_info = tk.StringVar(value="Choose a route alternative or open a saved route.")
        self.transfer_info = tk.StringVar()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        ttk.Label(self, text="Online Maps & Offline Downloads",
                  font=("TkDefaultFont", 19, "bold")).grid(row=0, column=0, sticky="w")
        settings = ttk.Frame(self)
        settings.grid(row=1, column=0, sticky="ew", pady=(8, 5))
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text="FieldForge portal URL").grid(row=0, column=0, padx=(0, 8))
        self.url_entry = ttk.Entry(settings, textvariable=self.portal_url)
        self.url_entry.grid(row=0, column=1, sticky="ew")
        self.save_url_button = ttk.Button(settings, text="Save URL", command=self.save_settings)
        self.save_url_button.grid(row=0, column=2, padx=(8, 0))
        links = ttk.Frame(settings)
        links.grid(row=1, column=1, sticky="w", pady=(4, 0))
        self.portal_home_button = ttk.Button(links, text="Open portal home", command=self.open_portal_home)
        self.portal_home_button.pack(side="left")
        ttk.Button(links, text="Copy portal link", command=self.copy_portal_link).pack(side="left", padx=6)
        connection = ttk.Frame(self)
        connection.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        connection.columnconfigure(3, weight=1)
        self.connect_button = ttk.Button(connection, text="Connect", command=self.connect)
        self.connect_button.grid(row=0, column=0)
        self.disconnect_button = ttk.Button(connection, text="Disconnect", command=self.disconnect)
        self.disconnect_button.grid(row=0, column=1, padx=6)
        self.cancel_button = ttk.Button(connection, text="Cancel task", command=self.cancel_task)
        self.cancel_button.grid(row=0, column=2)
        self.connection_label = ttk.Label(connection, textvariable=self.connection_status,
                                          wraplength=610, justify="left")
        self.connection_label.grid(row=0, column=3, sticky="w", padx=(12, 0))
        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=3, column=0, sticky="nsew")
        self._build_addresses()
        self._build_maps()
        self._build_routes()
        self._route_endpoint_fields = (
            (self.start_lat, "start", "latitude"), (self.start_lon, "start", "longitude"),
            (self.end_lat, "end", "latitude"), (self.end_lon, "end", "longitude"),
        )
        self._route_endpoint_traces = [
            (value, value.trace_add("write", self._route_endpoints_changed))
            for value, _endpoint, _key in self._route_endpoint_fields
        ]
        footer = ttk.Frame(self, height=52)
        footer.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        footer.pack_propagate(False)
        self.footer = ttk.Label(footer, textvariable=self.status, justify="left", wraplength=920)
        self.footer.pack(fill="x", anchor="nw")
        self.bind("<Configure>", self._resize, add=True)
        self.bind("<Destroy>", self._destroyed, add=True)
        self._load_settings()
        self.refresh_local()
        self._buttons()

    @staticmethod
    def _tree(parent, columns, widths, *, height=6):
        box = ttk.Frame(parent)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        tree = ttk.Treeview(box, columns=tuple(columns), show="headings",
                            selectmode="browse", height=height)
        for (key, label), width in zip(columns.items(), widths):
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=55, stretch=True)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(box, orient="horizontal", command=tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        return box, tree

    def _build_addresses(self):
        panel = ttk.Frame(self.tabs, padding=10)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)
        self.tabs.add(panel, text="Address search")
        self.address_tab = panel
        self.address_notice = ttk.Label(panel, wraplength=900, justify="left", text=(
            "Search sends the address you enter to the connected portal. Choose the intended match, "
            "then reuse its WGS 84 coordinates. Latitude first; north/east positive."))
        self.address_notice.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        search = ttk.Frame(panel)
        search.columnconfigure(0, weight=1)
        search.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.search_entry = ttk.Entry(search, textvariable=self.query)
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_entry.bind("<Return>", lambda _event: self.search())
        self.search_button = ttk.Button(search, text="Search address", command=self.search)
        self.search_button.grid(row=0, column=1, padx=(8, 0))
        box, self.results_tree = self._tree(panel, {
            "label": "Address / place", "latitude": "Latitude", "longitude": "Longitude",
        }, (550, 140, 140), height=7)
        box.grid(row=2, column=0, sticky="nsew")
        self.results_tree.bind("<<TreeviewSelect>>", self.select_result)
        selected = ttk.Frame(panel, height=100)
        selected.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        selected.pack_propagate(False)
        self.selected_text = ScrolledText(selected, height=5, width=50, wrap="word", state="disabled")
        self.selected_text.pack(fill="both", expand=True)
        self.selected_info.trace_add("write", lambda *_: self._set_text(self.selected_text, self.selected_info.get()))
        self._set_text(self.selected_text, self.selected_info.get())
        actions = ttk.Frame(panel)
        actions.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.copy_button = ttk.Button(actions, text="Copy coordinates", command=self.copy_coordinates)
        self.save_place_button = ttk.Button(actions, text="Fill saved-place editor…", command=self.save_place)
        self.save_place_csv_button = ttk.Button(actions, text="Save place CSV…", command=self.save_place_csv)
        self.start_button = ttk.Button(actions, text="Use start", command=self.use_start)
        self.destination_button = ttk.Button(actions, text="Use destination", command=self.use_destination)
        self.center_button = ttk.Button(actions, text="Center offline map", command=self.center_map)
        for column, button in enumerate((self.copy_button, self.save_place_button, self.save_place_csv_button, self.start_button,
                                         self.destination_button, self.center_button)):
            button.grid(row=0, column=column, padx=(0, 6))

    def _build_maps(self):
        panel = ttk.Frame(self.tabs, padding=10)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)
        panel.rowconfigure(5, weight=1)
        self.tabs.add(panel, text="Map downloads")
        self.maps_tab = panel
        actions = ttk.Frame(panel)
        actions.columnconfigure(2, weight=1)
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        self.refresh_catalog_button = ttk.Button(actions, text="Refresh online catalog", command=self.refresh_catalog)
        self.refresh_catalog_button.grid(row=0, column=0)
        self.download_button = ttk.Button(actions, text="Download & open", command=self.download_selected)
        self.download_button.grid(row=0, column=1, padx=7)
        self.progress = ttk.Progressbar(actions, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=2, sticky="ew", padx=(5, 8))
        ttk.Label(actions, textvariable=self.transfer_info, width=22).grid(row=0, column=3)
        self.add_to_list_button = ttk.Button(actions, text="Add selected to list", command=self.add_to_download_list)
        self.add_to_list_button.grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.review_list_button = ttk.Button(actions, text="Review / import list…", command=self.review_download_list)
        self.review_list_button.grid(row=1, column=1, padx=7, pady=(5, 0))
        self.list_summary = tk.StringVar(value="0 maps selected · 0 B")
        ttk.Label(actions, textvariable=self.list_summary).grid(row=1, column=2, columnspan=2, sticky="w", pady=(5, 0))
        self.catalog_filters = CatalogFilters(panel, changed=self._render_catalog)
        self.catalog_filters.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        box, self.maps_tree = self._tree(panel, {
            "title": "Portal map", "size": "Download size", "format": "Format",
            "version": "Version", "license": "License",
        }, (310, 105, 85, 125, 180), height=4)
        self.map_tree = self.maps_tree
        box.grid(row=2, column=0, sticky="nsew")
        self.maps_tree.bind("<<TreeviewSelect>>", self.select_map)
        details = ttk.Frame(panel, height=84)
        details.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        details.pack_propagate(False)
        self.map_details = ScrolledText(details, height=4, width=50, wrap="word", state="disabled")
        self.map_details.pack(fill="both", expand=True)
        self.map_info.trace_add("write", lambda *_: self._set_text(self.map_details, self.map_info.get()))
        self._set_text(self.map_details, self.map_info.get())
        local = ttk.Frame(panel)
        local.grid(row=4, column=0, sticky="ew", pady=(3, 6))
        ttk.Label(local, text="Downloaded maps · available offline").pack(side="left")
        self.refresh_local_button = ttk.Button(local, text="Refresh local files", command=self.refresh_local)
        self.refresh_local_button.pack(side="right")
        self.open_map_button = ttk.Button(local, text="Open selected map", command=self.open_local_map)
        self.open_map_button.pack(side="right", padx=7)
        box, self.local_maps_tree = self._tree(panel, {
            "filename": "Local map file", "size": "Stored size",
        }, (630, 145), height=4)
        box.grid(row=5, column=0, sticky="nsew")
        self.local_maps_tree.bind("<<TreeviewSelect>>", lambda _event: self._buttons())
        self.local_maps_tree.bind("<Double-1>", lambda _event: self.open_local_map())

    def _build_routes(self):
        panel = ttk.Frame(self.tabs, padding=10)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)
        self.tabs.add(panel, text="Routes")
        self.routes_tab = panel
        endpoints = ttk.Frame(panel)
        endpoints.grid(row=0, column=0, sticky="ew")
        for row, (label, lat, lon) in enumerate((
                ("Start", self.start_lat, self.start_lon),
                ("Destination", self.end_lat, self.end_lon))):
            ttk.Label(endpoints, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
            ttk.Label(endpoints, text="Latitude").grid(row=row, column=1, padx=(0, 5))
            ttk.Entry(endpoints, textvariable=lat, width=20).grid(row=row, column=2, sticky="ew")
            ttk.Label(endpoints, text="Longitude").grid(row=row, column=3, padx=(14, 5))
            ttk.Entry(endpoints, textvariable=lon, width=20).grid(row=row, column=4, sticky="ew")
        endpoints.columnconfigure(2, weight=1)
        endpoints.columnconfigure(4, weight=1)
        route_actions = ttk.Frame(panel)
        route_actions.grid(row=1, column=0, sticky="ew", pady=(6, 8))
        self.route_button = ttk.Button(route_actions, text="Get route alternatives online", command=self.request_route)
        self.route_button.pack(side="left")
        self.route_notice = ttk.Label(route_actions, text=(
            "Saved directions work offline. New routes and rerouting need the portal."), wraplength=620)
        self.route_notice.pack(side="left", padx=10)
        body = ttk.Panedwindow(panel, orient="horizontal")
        body.grid(row=2, column=0, sticky="nsew")
        left, right = ttk.Frame(body), ttk.Frame(body, padding=(10, 0, 0, 0))
        body.add(left, weight=2)
        body.add(right, weight=3)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        left.rowconfigure(4, weight=1)
        ttk.Label(left, text="Returned alternatives · select one").grid(row=0, column=0, sticky="w")
        box, self.route_tree = self._tree(left, {"title": "Route", "distance": "km", "duration": "Est. min"},
                                         (230, 70, 80), height=3)
        box.grid(row=1, column=0, sticky="nsew", pady=(5, 0))
        self.route_tree.bind("<<TreeviewSelect>>", self.select_route)
        buttons = ttk.Frame(left)
        buttons.grid(row=2, column=0, sticky="ew", pady=6)
        self.save_route_button = ttk.Button(buttons, text="Save route offline", command=self.save_route)
        self.save_route_button.pack(side="left")
        self.export_gpx_button = ttk.Button(buttons, text="Export GPX…", command=self.export_gpx)
        self.export_gpx_button.pack(side="left", padx=6)
        ttk.Label(left, text="Saved routes · available offline").grid(row=3, column=0, sticky="w", pady=(3, 5))
        box, self.saved_routes_tree = self._tree(left, {"filename": "Saved route file"}, (380,), height=3)
        box.grid(row=4, column=0, sticky="nsew")
        self.saved_routes_tree.bind("<<TreeviewSelect>>", lambda _event: self._buttons())
        self.saved_routes_tree.bind("<Double-1>", lambda _event: self.open_saved_route())
        saved_buttons = ttk.Frame(left)
        saved_buttons.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        self.open_route_button = ttk.Button(saved_buttons, text="Open saved route", command=self.open_saved_route)
        self.open_route_button.grid(row=0, column=0, sticky="w")
        ttk.Button(saved_buttons, text="Refresh files", command=self.refresh_local).grid(row=0, column=1, padx=6)
        self.import_route_button = ttk.Button(saved_buttons, text="Import downloaded route…", command=self.import_route)
        self.import_route_button.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self.route_label = ttk.Label(right, textvariable=self.route_info, wraplength=460, justify="left")
        self.route_label.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        self.route_steps = ScrolledText(right, height=8, width=40, wrap="word", state="disabled")
        self.route_steps.grid(row=1, column=0, sticky="nsew")
        self.show_route_button = ttk.Button(right, text="Show route on offline map", command=self.show_route)
        self.show_route_button.grid(row=2, column=0, sticky="w", pady=(6, 0))
        right.bind("<Configure>", lambda event: self.route_label.configure(wraplength=max(190, event.width - 20)))

    def _resize(self, event):
        if event.widget is self:
            width = max(350, event.width - 60)
            for label in (self.footer, self.address_notice):
                label.configure(wraplength=width)
            self.connection_label.configure(wraplength=max(240, event.width - 340))
            self.route_notice.configure(wraplength=max(240, event.width - 340))

    @staticmethod
    def _set_text(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _load_settings(self):
        if self.library is None:
            return
        try:
            if not self.settings_path.exists():
                return
            with self.settings_path.open("rb") as source:
                raw = source.read(8193)
            if len(raw) > 8192:
                raise ValueError("Saved portal settings are too large.")
            settings = json.loads(raw)
            url = settings.get("portal_url", "")
            if not isinstance(url, str) or len(url) > 2048:
                raise ValueError("Saved portal URL is invalid.")
            url = validate_portal_url(url) if url else ""
            self.portal_url.set(url)
            self.status.set("Saved portal URL loaded. Connect when you want online services.")
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.status.set("Could not read portal settings: " + str(exc))

    def save_settings(self):
        if self.library is None:
            self.status.set(self._storage_error)
            return
        url = self.portal_url.get().strip()
        try:
            url = validate_portal_url(url) if url else ""
        except ValueError as exc:
            self.status.set("Portal URL was not saved: " + str(exc))
            return
        temporary = None
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.settings_path.parent,
                                              prefix=".settings-", suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                json.dump({"version": 1, "portal_url": url}, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.settings_path)
            temporary = None
            self.portal_url.set(url)
            self.status.set("Portal URL saved on this device. Startup stays disconnected.")
        except OSError as exc:
            self.status.set("Portal URL was not saved: " + str(exc))
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _available(self, capability):
        return self.connected and self.capabilities.get(capability) is True

    @staticmethod
    def _selected(tree, values):
        selection = tree.selection()
        if not selection:
            return None
        try:
            return values[int(selection[0])]
        except (ValueError, IndexError, TypeError):
            return None

    def _buttons(self):
        if self._disposed:
            return
        idle = not self.busy
        self.url_entry.configure(state="normal" if idle and not self.connected else "disabled")
        self.save_url_button.configure(state="normal" if idle else "disabled")
        self.connect_button.configure(state="normal" if idle and not self.connected else "disabled")
        self.disconnect_button.configure(state="normal" if self.connected or self._operation == "connect" else "disabled")
        self.cancel_button.configure(state="normal" if self.busy and self._operation not in _WRITES else "disabled")
        searchable = self._available("geocoding") and idle
        self.search_entry.configure(state="normal" if searchable else "disabled")
        self.search_button.configure(state="normal" if searchable else "disabled")
        for button in (self.copy_button, self.save_place_button, self.start_button,
                       self.destination_button, self.center_button):
            button.configure(state="normal" if self.selected_result is not None else "disabled")
        self.save_place_csv_button.configure(state="normal" if self.selected_result is not None and idle else "disabled")
        catalog = self._available("catalog") and idle
        self.portal_home_button.configure(state="normal" if self.connected else "disabled")
        self.refresh_catalog_button.configure(state="normal" if catalog else "disabled")
        self.download_button.configure(state="normal" if catalog and self.library is not None and self._selected(self.maps_tree, self._catalog) else "disabled")
        self.add_to_list_button.configure(state="normal" if idle and self._selected(self.maps_tree, self._catalog) else "disabled")
        if self._download_list_window is not None:
            self._download_list_window.update_state()
        self.open_map_button.configure(state="normal" if self._selected(self.local_maps_tree, self._local_maps) else "disabled")
        self.route_button.configure(state="normal" if self._available("routing") and idle else "disabled")
        for button in (self.save_route_button, self.export_gpx_button):
            button.configure(state="normal" if self.current_route is not None and self.library is not None and idle else "disabled")
        self.show_route_button.configure(state="normal" if self.current_route is not None and self.on_show_route is not None else "disabled")
        self.open_route_button.configure(state="normal" if idle and self._selected(self.saved_routes_tree, self._saved_routes) else "disabled")
        self.import_route_button.configure(state="normal" if idle and self.library is not None else "disabled")

    def _start(self, operation, function):
        if self._disposed or self.busy:
            return False
        self._generation += 1
        self._cancel = Event()
        self._operation = operation
        self.busy = True
        self._future = self._worker.submit(function, self._cancel)
        self._poll_id = self.after(40, self._poll, self._future, operation, self._generation)
        self._buttons()
        return True

    def _cancel_work(self):
        self._generation += 1
        self._cancel.set()
        if self._future is not None:
            self._future.cancel()
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
        self._poll_id = None
        self._future = None
        self._operation = None
        self.busy = False
        if not self._disposed:
            self.transfer_info.set("")
            self.progress.configure(value=0)

    def _offline(self):
        if self._heartbeat_id is not None:
            self.after_cancel(self._heartbeat_id)
            self._heartbeat_id = None
        client, self.client = self.client, None
        self.connected = False
        self.capabilities = {}
        if client is not None:
            client.disconnect()
        if not self._disposed:
            self.connection_status.set("Offline · Saved maps, routes and selected coordinates are available.")
            self._label_retained_route("Selected route remains available offline.")

    def _schedule_health(self, milliseconds=None):
        if self._heartbeat_id is not None:
            self.after_cancel(self._heartbeat_id)
            self._heartbeat_id = None
        if self.connected and not self._disposed:
            self._heartbeat_id = self.after(HEALTH_CHECK_MS if milliseconds is None else milliseconds,
                                           self._check_health)

    def _check_health(self):
        if self._heartbeat_id is not None:
            self.after_cancel(self._heartbeat_id)
            self._heartbeat_id = None
        if self._disposed or not self.connected:
            return
        if self.busy or self._choosing_file:
            self._schedule_health(5_000)
            return
        client = self.client
        self.connection_status.set("Online · Rechecking portal availability…")
        self._start("health", lambda cancel: client.connect(cancel=cancel))

    def connect(self):
        if self._disposed or self.busy or self.connected or self._confirming:
            return
        try:
            url = validate_portal_url(self.portal_url.get().strip())
            client = self.client_factory(url)
        except _ERRORS as exc:
            self.status.set("Could not connect: " + str(exc))
            return
        self._confirming = True
        try:
            accepted = confirm_connection(self, url)
        finally:
            self._confirming = False
        if self._disposed:
            return
        if not accepted:
            self.status.set("Stayed offline. No portal request was sent.")
            return
        self._connection_url = url
        self._catalog, self._catalog_loaded = (), False
        self._render_catalog()
        self.client = client
        self.status.set("Checking the configured portal and its available services…")
        self.connection_status.set("Connecting… Address search stays disabled until the portal responds.")
        self._start("connect", lambda cancel: client.connect(cancel=cancel))

    def open_portal_home(self):
        if self._disposed or not self.connected:
            return
        opened = open_portal(self._connection_url)
        self.status.set("Portal home opened in your browser. Save downloads, then disconnect when ready." if opened else
                        "Browser could not open. Use Copy portal link and paste it into your browser: " + self._connection_url)

    def copy_portal_link(self):
        if self._disposed:
            return
        try:
            url = self._connection_url if self.connected else validate_portal_url(self.portal_url.get().strip())
            self.clipboard_clear()
            self.clipboard_append(url)
            self.status.set("Portal link copied. Opening it in a browser uses your internet connection.")
        except (ValueError, tk.TclError) as exc:
            self.status.set("Could not copy portal link: " + str(exc))

    def disconnect(self):
        if self._disposed:
            return
        downloading_list = self._operation == "download_list"
        if self._operation in _NETWORK:
            self._cancel_work()
        self._offline()
        if downloading_list:
            self.refresh_local()
        self.status.set("Disconnected. Selected coordinates and downloaded files remain available offline.")
        self._buttons()

    def cancel_task(self):
        if self._disposed or not self.busy or self._operation in _WRITES:
            return
        connecting = self._operation in {"connect", "health"}
        routing = self._operation == "route"
        downloading_list = self._operation == "download_list"
        self._cancel_work()
        if connecting:
            self._offline()
        self.status.set("Task cancelled. Previously selected coordinates and saved files are unchanged.")
        if routing:
            self._label_retained_route("Previous selection retained; new route request cancelled.")
        if downloading_list:
            self.refresh_local()
            self.status.set("Download list stopped. Completed maps remain offline; retry the list to reuse verified files.")
        self._buttons()

    def _poll(self, future, operation, generation):
        self._poll_id = None
        if self._disposed or generation != self._generation:
            return
        if operation in {"download", "download_list"}:
            try:
                update = self._progress.get_nowait()
                token, done, total = update[:3]
                if token == generation:
                    self.transfer_info.set(f"{_size(done)} / {_size(total)}")
                    self.progress.configure(value=100 * done / total if total else 0)
                    if operation == "download_list" and len(update) == 4:
                        self.status.set(update[3])
            except queue.Empty:
                pass
        if not future.done():
            self._poll_id = self.after(40, self._poll, future, operation, generation)
            return
        self.busy = False
        self._future = None
        self._operation = None
        try:
            result = future.result()
            self._complete(operation, result)
        except PortalCancelled:
            self.status.set("Task cancelled. Previously selected coordinates and saved files are unchanged.")
            if operation in {"connect", "health"}:
                self._offline()
            elif operation == "route":
                self._label_retained_route("Previous selection retained; new route request cancelled.")
        except Exception as exc:
            if operation in {"connect", "health"} or isinstance(exc, (PortalOffline, ConnectionError, TimeoutError)):
                self._offline()
            elif operation in _NETWORK and self.client is not None and not self.client.connected:
                self._offline()
            if operation == "route":
                self._label_retained_route("Previous selection retained; new route request failed.")
            self.status.set("Could not complete " + operation.replace("_", " ") + ": " + str(exc))
            if operation == "download_list":
                self.refresh_local()
        self._buttons()

    def _complete(self, operation, result):
        if operation in {"connect", "health"}:
            if self.client is None or not self.client.connected:
                raise PortalOffline("The portal connection ended before its status could be applied.")
            self.connected = True
            self.capabilities = dict(result)
            services = [label for key, label in (("geocoding", "addresses"), ("routing", "routes"),
                                                 ("catalog", "map catalog")) if result.get(key) is True]
            self.connection_status.set(f"Online · {result.get('name', 'FieldForge portal')} · " +
                                       (", ".join(services) if services else "no services enabled") +
                                       " · checked every 30 s")
            if operation == "connect":
                self.open_portal_home()
            self._schedule_health()
        elif operation == "search":
            self._results = tuple(result)
            self.results_tree.delete(*self.results_tree.get_children())
            for index, item in enumerate(self._results):
                self.results_tree.insert("", "end", iid=str(index), values=(
                    item["label"], coordinate_text(item["latitude"]), coordinate_text(item["longitude"])))
            self.status.set(f"{len(self._results)} address matches. Select the intended result; no coordinates were chosen automatically.")
        elif operation == "catalog":
            self._catalog = tuple(result)
            self._catalog_loaded = True
            self._render_catalog(preserve_selection=False)
            self.status.set(f"{len(self._catalog)} downloadable maps supplied by this portal. Choose a pack to inspect its coverage.")
            if not self._catalog:
                self.map_info.set("The portal currently offers no map downloads. Previously downloaded maps remain below.")
        elif operation == "route":
            self._routes = tuple(result)
            self.current_route = None
            self._retained_route_reason = ""
            self._set_text(self.route_steps, "")
            self.route_info.set("Select a returned alternative to view its directions." if self._routes else
                                "No route alternatives returned. Previously saved routes remain available below.")
            self.route_tree.delete(*self.route_tree.get_children())
            for index, route in enumerate(self._routes):
                self.route_tree.insert("", "end", iid=str(index), values=(
                    route["title"], f"{route['distance_m']/1000:,.1f}", f"{route['duration_s']/60:,.0f}"))
            self.status.set(f"{len(self._routes)} route alternatives returned. Choose one to inspect its directions and save offline."
                            if self._routes else "No route alternatives returned for those coordinates. Saved files are unchanged.")
        elif operation == "download":
            self.progress.configure(value=100)
            self.transfer_info.set("Verified and saved")
            self.refresh_local()
            self.status.set(f"Downloaded and verified {Path(result).name}. Opening the local copy…")
            self._open_map_path(Path(result))
        elif operation == "download_list":
            self.progress.configure(value=100)
            self.transfer_info.set("List ready offline")
            self.refresh_local()
            self.status.set(f"{len(result)} selected maps verified and ready offline. Open them from Downloaded maps.")
        elif operation == "import_download_list":
            self._set_download_list(result)
            self.status.set("Download list imported locally. Review its portal and total size, then connect explicitly when ready.")
        elif operation == "save_download_list":
            self.status.set(f"Map list saved: {Path(result).name}. This file contains the selection and source details, not map bytes.")
        elif operation == "save_route":
            self.refresh_local()
            self.status.set(f"Route saved for offline use: {Path(result).name}.")
        elif operation == "open_route":
            self.route_tree.selection_remove(*self.route_tree.selection())
            self._show_route(result)
            self.status.set("Saved route opened from this device. Its geometry and source details are available offline.")
        elif operation == "import_route":
            path, route = result
            self.route_tree.selection_remove(*self.route_tree.selection())
            self._show_route(route)
            self.refresh_local()
            self.status.set(f"Imported {Path(path).name} for offline use. The original downloaded file is unchanged.")
        elif operation == "export_gpx":
            self.status.set(f"Planned-route GPX exported: {Path(result).name}.")
        elif operation == "save_place_csv":
            self.status.set(f"Place CSV saved for offline use: {Path(result).name}.")
        elif operation == "local_files":
            self._display_local(*result)

    def search(self):
        if self._disposed or self.busy or not self._available("geocoding"):
            return
        query = self.query.get().strip()
        if not query:
            self.status.set("Enter an address or place to search.")
            return
        client = self.client
        self.status.set("Looking up this address through the connected portal…")
        self._start("search", lambda cancel: client.search(query, cancel=cancel))

    def select_result(self, _event=None):
        result = self._selected(self.results_tree, self._results)
        if result is not None:
            self.selected_result = dict(result)
            self.latitude.set(coordinate_text(result["latitude"]))
            self.longitude.set(coordinate_text(result["longitude"]))
            self.selected_info.set(
                f"{result['label']}\nLatitude {self.latitude.get()} · Longitude {self.longitude.get()}\n"
                f"{result.get('source', '')} · {result.get('attribution', '')} · {result.get('license', '')}\n"
                f"Retrieved: {result.get('retrieved_at', '')}")
        self._buttons()

    def copy_coordinates(self):
        if self.selected_result is not None and not self._disposed:
            self.clipboard_clear()
            self.clipboard_append(f"{self.latitude.get()}, {self.longitude.get()}")
            self.status.set("Copied latitude, longitude. Selected coordinates remain available after disconnecting.")

    @staticmethod
    def place_initial(result):
        source = "\n".join(f"{label}: {result[key]}" for label, key in (
            ("Source", "source"), ("Attribution", "attribution"), ("License", "license"),
            ("Retrieved", "retrieved_at")) if result.get(key))
        return {"name": result["label"][:200], "latitude": result["latitude"],
                "longitude": result["longitude"], "kind": "waypoint",
                "notes": (result["label"] + "\n" + source)[:4000]}

    def save_place(self):
        if self._disposed or self.selected_result is None:
            return
        result = dict(self.selected_result)
        try:
            if self.on_use_place is not None:
                self.on_use_place(result)
            elif self.dialog is not None and self.dialog.winfo_exists():
                self.dialog.lift()
            else:
                from fieldforge.ui.places import PlaceEditor

                self.dialog = PlaceEditor(self, PlaceStore(self.database),
                                          initial=self.place_initial(result), finished=self._place_finished)
        except _ERRORS as exc:
            self.status.set("Could not open the place editor: " + str(exc))

    def _place_finished(self, changed=False):
        self.dialog = None
        self.status.set("Place saved locally for offline use." if changed else "Place editor closed.")

    def save_place_csv(self):
        if self._disposed or self.busy or self.selected_result is None:
            return
        result = dict(self.selected_result)
        self._choosing_file = True
        try:
            destination = filedialog.asksaveasfilename(
                parent=self, title="Save selected place for offline use", initialfile="fieldforge-place.csv",
                defaultextension=".csv", filetypes=[("Place CSV", "*.csv")])
        finally:
            self._choosing_file = False
        if not destination or self._disposed:
            return

        def save(_cancel):
            point = Address(label=result["label"], latitude=result["latitude"], longitude=result["longitude"],
                            source=result["source"], attribution=result["attribution"],
                            license=result.get("license", ""), retrieved_at=result.get("retrieved_at", ""))
            path = Path(destination)
            save_new(path, address_csv(point))
            return path

        self.status.set("Saving the selected coordinates and their source in a local CSV…")
        self._start("save_place_csv", save)

    def use_start(self):
        if self.selected_result is not None:
            self.start_lat.set(self.latitude.get())
            self.start_lon.set(self.longitude.get())
            self.status.set("Selected coordinates filled the route start. Open Routes to choose a destination.")

    def use_destination(self):
        if self.selected_result is not None:
            self.end_lat.set(self.latitude.get())
            self.end_lon.set(self.longitude.get())
            self.status.set("Selected coordinates filled the destination. Open Routes to request alternatives.")

    def center_map(self):
        if self._disposed or self.selected_result is None:
            return
        lat, lon = self.selected_result["latitude"], self.selected_result["longitude"]
        try:
            if self.on_center is not None:
                self.on_center(lat, lon)
            elif self._fallback_map is not None and self._fallback_map.winfo_exists():
                self._fallback_map.latitude.set(coordinate_text(lat))
                self._fallback_map.longitude.set(coordinate_text(lon))
                self._fallback_map.go()
            else:
                self.status.set("Open a downloaded MBTiles map first, then center it on the selected coordinates.")
        except _ERRORS as exc:
            self.status.set("Could not center the offline map: " + str(exc))

    def refresh_catalog(self):
        if self._disposed or self.busy or not self._available("catalog"):
            return
        client = self.client
        self.status.set("Reading the portal's map catalog…")
        self._start("catalog", lambda cancel: client.catalog(cancel=cancel))

    def _render_catalog(self, *, preserve_selection=True):
        if self._disposed:
            return
        previous = self.maps_tree.selection() if preserve_selection else ()
        visible = self.catalog_filters.apply(self._catalog, loaded=self._catalog_loaded)
        indexes = {item["id"]: index for index, item in enumerate(self._catalog)}
        self.maps_tree.delete(*self.maps_tree.get_children())
        for item in visible:
            self.maps_tree.insert("", "end", iid=str(indexes[item["id"]]), values=(
                item["title"], _size(item["bytes"]), item["format"], item["version"], item["license"]))
        if previous and self.maps_tree.exists(previous[0]):
            self.maps_tree.selection_set(previous[0])
        self.select_map()

    def select_map(self, _event=None):
        item = self._selected(self.maps_tree, self._catalog)
        if item is not None:
            coverage = item["coverage"]
            if not isinstance(coverage, str):
                coverage = json.dumps(coverage, ensure_ascii=False)
            self.map_info.set(f"{item['title']} · {_size(item['bytes'])} · version {item['version']}\n"
                              f"Coverage: {coverage}\n{item['attribution']} · License: {item['license']}")
        else:
            self.map_info.set("Select a visible map to inspect coverage and download details.")
        self._buttons()

    def download_selected(self):
        if self._disposed or self.busy or self.library is None or not self._available("catalog"):
            return
        asset = self._selected(self.maps_tree, self._catalog)
        if asset is None:
            return
        client = self.client
        token = self._generation + 1
        progress_queue = self._progress

        def progress(done, total):
            try:
                progress_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                progress_queue.put_nowait((token, done, total))
            except queue.Full:
                pass

        self.progress.configure(value=0)
        self.transfer_info.set("Starting…")
        self.status.set(f"Downloading {asset['title']}. It becomes available offline after checksum verification.")
        directory = self.library.maps_directory
        self._start("download", lambda cancel: client.download(asset, directory, cancel=cancel, progress=progress))

    def _set_download_list(self, document):
        self._download_list = document
        maps = document["maps"] if document else []
        self.list_summary.set(f"{len(maps)} maps selected · {_size(document['total_bytes'] if document else 0)}")
        if self._download_list_window is not None:
            self._download_list_window.render()
        self._buttons()

    def add_to_download_list(self):
        if self._disposed or self.busy or self._choosing_file:
            return
        asset = self._selected(self.maps_tree, self._catalog)
        if asset is None:
            return
        try:
            document = self._download_list or make_download_list(self._connection_url, [])
            if document["portal"] != self._connection_url:
                raise ValueError("This list belongs to another portal. Save and clear it before adding maps from here.")
            by_id = {item["id"]: item for item in document["maps"]}
            if asset["id"] in by_id and by_id[asset["id"]] != asset:
                raise ValueError("This map changed. Remove its old selection before adding the new version.")
            by_id[asset["id"]] = asset
            self._set_download_list(make_download_list(document["portal"], list(by_id.values())))
            self.status.set("Map added to the download list. Review its total size before starting; no file was downloaded.")
        except ValueError as exc:
            self.status.set(str(exc))

    def remove_from_download_list(self, selected):
        if self._disposed or self.busy or self._choosing_file or self._download_list is None:
            return
        document = self._download_list
        self._set_download_list(make_download_list(document["portal"], [item for item in document["maps"] if item["id"] not in selected]))

    def clear_download_list(self):
        if not self._disposed and not self.busy and not self._choosing_file:
            self._set_download_list(None)

    def review_download_list(self):
        if self._disposed:
            return
        if self._download_list_window is None:
            self._download_list_window = MapDownloadListWindow(self, _size)
        self._download_list_window.deiconify()
        self._download_list_window.lift()

    def copy_download_list_portal(self):
        if self._disposed or self._download_list is None:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self._download_list["portal"])
            self.status.set("Required portal copied. Paste it into the portal URL field, then choose Connect when ready.")
        except tk.TclError as exc:
            self.status.set("Could not copy the required portal: " + str(exc))

    def import_download_list(self):
        if self._disposed or self.busy or self._choosing_file:
            return
        self._choosing_file = True
        try:
            source = filedialog.askopenfilename(parent=self._download_list_window or self,
                                               title="Import a FieldForge map download list",
                                               filetypes=(("Map download list", "*.json"),))
        finally:
            self._choosing_file = False
        if source and not self._disposed:
            self._start("import_download_list", lambda _cancel: load_download_list(source))

    def export_download_list(self):
        if self._disposed or self.busy or self._choosing_file or not self._download_list or not self._download_list["maps"]:
            return
        document = self._download_list
        self._choosing_file = True
        try:
            destination = filedialog.asksaveasfilename(parent=self._download_list_window or self,
                                                      title="Save map download list (new file)",
                                                      initialfile="fieldforge-map-list.json", defaultextension=".json",
                                                      filetypes=(("Map download list", "*.json"),))
        finally:
            self._choosing_file = False
        if destination and not self._disposed:
            self._start("save_download_list", lambda _cancel: save_download_list(document, destination))

    def download_list(self):
        if (self._disposed or self.busy or self._choosing_file or self.library is None
                or not self._available("catalog") or not self._download_list or not self._download_list["maps"]):
            return
        if self._connection_url != self._download_list["portal"]:
            self.status.set("Connect explicitly to the portal named in the download list before starting it.")
            return
        client, document, directory = self.client, self._download_list, self.library.maps_directory
        token, progress_queue = self._generation + 1, self._progress

        def progress(done, total, detail):
            try:
                progress_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                progress_queue.put_nowait((token, done, total, detail))
            except queue.Full:
                pass

        self.progress.configure(value=0)
        self.transfer_info.set("Checking selection…")
        self.status.set(f"Preparing {len(document['maps'])} selected maps · {_size(document['total_bytes'])} total file size.")
        self._start("download_list", lambda cancel: download_maps(client, document, directory, cancel=cancel, progress=progress))

    def refresh_local(self):
        if self._disposed or self.busy:
            return
        if self.library is None:
            self.status.set(self._storage_error)
            return
        library = self.library

        def read(cancel):
            maps = tuple(library.maps())
            if cancel.is_set():
                raise PortalCancelled("Local file refresh cancelled.")
            routes = tuple(library.routes())
            if cancel.is_set():
                raise PortalCancelled("Local file refresh cancelled.")
            map_rows = [(path.name, _size(path.stat().st_size)) for path in maps]
            return maps, routes, map_rows

        self._start("local_files", read)

    def _display_local(self, maps, routes, map_rows):
        selected_map = self._selected(self.local_maps_tree, self._local_maps)
        selected_route = self._selected(self.saved_routes_tree, self._saved_routes)
        self._local_maps, self._saved_routes = maps, routes
        self.local_maps_tree.delete(*self.local_maps_tree.get_children())
        self.saved_routes_tree.delete(*self.saved_routes_tree.get_children())
        for index, row in enumerate(map_rows):
            self.local_maps_tree.insert("", "end", iid=str(index), values=row)
            if maps[index] == selected_map:
                self.local_maps_tree.selection_set(str(index))
        for index, path in enumerate(routes):
            self.saved_routes_tree.insert("", "end", iid=str(index), values=(path.name,))
            if path == selected_route:
                self.saved_routes_tree.selection_set(str(index))
        self._buttons()

    def open_local_map(self):
        if self._disposed:
            return
        path = self._selected(self.local_maps_tree, self._local_maps)
        if path is None:
            return
        self._open_map_path(path)

    def _open_map_path(self, path):
        window = None
        try:
            if self.on_open_map is not None:
                self.on_open_map(path)
                return
            window = tk.Toplevel(self)
            window.title("FieldForge · Downloaded map")
            window.geometry("1080x740")
            window.minsize(960, 680)
            if path.suffix.lower() == ".mbtiles":
                from fieldforge.ui.maps import MapsTab

                frame = MapsTab(window, self.database)
                frame.pack(fill="both", expand=True)
                frame.open_path(path)
                self._fallback_map = frame
            else:
                from fieldforge_gps.image_map_ui import ImageMapFrame

                frame = ImageMapFrame(window)
                frame.permission.set(True)
                frame.open_path(path)
            self._map_windows.append(window)
        except _ERRORS as exc:
            if window is not None and window.winfo_exists():
                window.destroy()
            self.status.set("Could not open the downloaded map: " + str(exc))

    def request_route(self):
        if self._disposed or self.busy or not self._available("routing"):
            return
        try:
            start = (coordinate(self.start_lat.get(), latitude=True), coordinate(self.start_lon.get(), latitude=False))
            end = (coordinate(self.end_lat.get(), latitude=True), coordinate(self.end_lon.get(), latitude=False))
        except ValueError as exc:
            self.status.set("Check the route coordinates: " + str(exc))
            self._label_retained_route("Previous selection retained; new coordinates need review.")
            return
        client = self.client
        self.status.set("Requesting route alternatives for these coordinates…")
        self._label_retained_route("Previous selection shown while the new route request runs.")
        self._start("route", lambda cancel: client.routes(start, end, cancel=cancel))

    def select_route(self, _event=None):
        route = self._selected(self.route_tree, self._routes)
        if route is not None:
            self._show_route(route)
        self._buttons()

    def _show_route(self, route):
        self.current_route = route
        self._retained_route_reason = ""
        self._updating_route_endpoints = True
        try:
            for value, endpoint, key in self._route_endpoint_fields:
                value.set(coordinate_text(route[endpoint][key]))
        finally:
            self._updating_route_endpoints = False
        self._update_route_info()
        lines = [*_route_endpoints(route), "", f"Mode: {route['mode']}", f"Created: {route['created_at']}",
                 f"Source: {route['source']}", f"{route['attribution']} · {route['license']}", "",
                 "This plan describes the requested route. Conditions and travel times can change.", ""]
        if not route["steps"]:
            lines.append("This route has no supplied turn instructions.")
        for index, step in enumerate(route["steps"], 1):
            lines.append(f"{index}. {step['instruction']}\n   {step['distance_m']:,.0f} m · "
                         f"{coordinate_text(step['latitude'])}, {coordinate_text(step['longitude'])}\n")
        lines.extend(["", f"{len(route['geometry']):,} route geometry points included in this plan."])
        self.route_steps.configure(state="normal")
        self.route_steps.delete("1.0", "end")
        self.route_steps.insert("1.0", "\n".join(lines))
        self.route_steps.configure(state="disabled")

    def _route_endpoints_changed(self, *_args):
        if not self._disposed and not self._updating_route_endpoints:
            self._update_route_info()

    def _update_route_info(self):
        route = self.current_route
        if route is None:
            return
        try:
            matches = all(coordinate(value.get(), latitude=key == "latitude") == route[endpoint][key]
                          for value, endpoint, key in self._route_endpoint_fields)
        except ValueError:
            matches = False
        lines = [_route_summary(route), *_route_endpoints(route)]
        if not route["steps"]:
            lines.append("No turn instructions supplied; route geometry is available.")
        if not matches:
            lines.append("Selected plan uses previous coordinates")
        if self._retained_route_reason:
            lines.append(self._retained_route_reason)
        self.route_info.set("\n".join(lines))

    def _label_retained_route(self, reason):
        if self.current_route is not None:
            self._retained_route_reason = reason
            self._update_route_info()

    def save_route(self):
        if self._disposed or self.busy or self.library is None or self.current_route is None:
            return
        route, library = self.current_route, self.library
        self.status.set("Saving the selected route and directions for offline use…")
        self._start("save_route", lambda _cancel: library.save_route(route))

    def show_route(self):
        if self._disposed or self.current_route is None or self.on_show_route is None:
            return
        try:
            self.on_show_route(self.current_route)
        except _ERRORS as exc:
            self.status.set("Could not show the saved route on a map: " + str(exc))

    def open_saved_route(self):
        path = self._selected(self.saved_routes_tree, self._saved_routes)
        if path is not None:
            self.open_route_path(path)

    def open_route_path(self, path):
        if self._disposed or self.busy or self.library is None:
            return
        library = self.library
        self.status.set("Opening saved route from this device…")
        self._start("open_route", lambda _cancel: library.load_route(path))

    def import_route(self):
        if self._disposed or self.busy or self.library is None:
            return
        self._choosing_file = True
        try:
            source = filedialog.askopenfilename(parent=self, title="Import downloaded FieldForge route",
                                                filetypes=[("FieldForge route JSON", "*.json")])
        finally:
            self._choosing_file = False
        if source:
            self.import_route_path(Path(source))

    def import_route_path(self, source):
        if self._disposed or self.busy or self.library is None:
            return
        library = self.library
        source = Path(source)

        def import_and_read(_cancel):
            path = library.import_route(source)
            return path, library.load_route(path)

        self.status.set("Importing the downloaded route into this device's offline routes…")
        self._start("import_route", import_and_read)

    def export_gpx(self):
        if self._disposed or self.busy or self.library is None or self.current_route is None:
            return
        self._choosing_file = True
        try:
            destination = filedialog.asksaveasfilename(parent=self, title="Export planned route GPX",
                                                       defaultextension=".gpx", filetypes=[("GPX route", "*.gpx")])
        finally:
            self._choosing_file = False
        if destination:
            route, library = self.current_route, self.library
            self.status.set("Exporting planned-route geometry to GPX…")
            self._start("export_gpx", lambda _cancel: library.export_gpx(route, Path(destination)))

    def can_close(self):
        if self._choosing_file:
            self.status.set("Finish choosing the local file before closing.")
            return False
        if self.dialog is not None and self.dialog.winfo_exists():
            self.dialog.close()
            if self.dialog is not None:
                return False
        if self.busy and self._operation in _WRITES:
            self.status.set("Finish the local file save, import or export before closing.")
            return False
        return True

    def close(self):
        if self._disposed:
            return
        self._disposed = True
        if self._download_list_window is not None:
            self._download_list_window.destroy()
        self.catalog_filters.close()
        # These variables belong to this tab. Remove the detail-panel traces as
        # well as the endpoint traces before any callback can retain a closed UI.
        for value in tuple(self.__dict__.values()):
            if isinstance(value, tk.Variable):
                for modes, callback in value.trace_info():
                    value.trace_remove(modes, callback)
        self._route_endpoint_traces.clear()
        self._route_endpoint_fields = ()
        self.on_open_map = self.on_center = self.on_use_place = self.on_show_route = None
        self._cancel_work()
        self._offline()
        self._worker.shutdown(wait=False, cancel_futures=True)
        for window in self._map_windows:
            if window.winfo_exists():
                window.destroy()
        self._map_windows.clear()

    def destroy(self):
        try:
            self.close()
        finally:
            super().destroy()

    def _destroyed(self, event):
        if event.widget is self:
            self.close()
