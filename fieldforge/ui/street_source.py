"""Local small-PBF street preview inside Maps; independent of household data."""
from __future__ import annotations

import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from fieldforge.navigation.map_view import Viewport
from fieldforge.navigation.osm_source import (
    NOTICE,
    read_street_source,
    search_features,
)
from fieldforge.navigation.route_overlay import fit_route, route_segments
from fieldforge.ui.map_tasks import MapTaskWindow

MAX_DRAW_SEGMENTS = 20000
MAX_LABELS = 80
EXAMPLE_SHA256 = '40a25059d31a82521dcf49e3f1c9df385f1759b574d9bb1ca4ea37db91416992'

def _load_example(path, *, cancel=None, progress=None):
    result = read_street_source(path, cancel=cancel, progress=progress)
    if result.sha256 != EXAMPLE_SHA256:
        raise ValueError('The bundled historical example has changed. No example will be opened.')
    return result

class StreetSourceWindow(MapTaskWindow):

    def __init__(self, panel, *, heading="Street data • offline preview"):
        super().__init__(panel)
        self.title('FieldForge — Local street-source preview')
        self.geometry('1160x820')
        self.minsize(850, 670)
        self.source = None
        self.view = None
        self.matches = ()
        self.selected_id = None
        self._resize_id = None
        self._drag = None
        self.query = tk.StringVar()
        self.summary = tk.StringVar(value='No street source open. Reading a file does not install a routing graph.')
        self.credit = tk.StringVar(value='No internet or GPS requests. Source paths and map data stay on this computer.')
        self.pointer = tk.StringVar(value='Search by name and select a result; drag / arrow keys to pan.')
        self.example = Path(__file__).resolve().parents[2] / 'examples' / 'street-source' / 'historic-sample.osm.pbf'
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky='ew', padx=16, pady=(14, 6))
        ttk.Label(header, text=heading, font=('TkDefaultFont', 21, 'bold')).pack(side='left')
        self.notice = ttk.Label(self, text=NOTICE, wraplength=1090, justify='left')
        self.notice.grid(row=1, column=0, sticky='ew', padx=16, pady=(0, 8))
        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, sticky='ew', padx=16, pady=(0, 8))
        self.open_button = ttk.Button(actions, text='Open small .osm.pbf…', command=self.choose)
        self.open_button.pack(side='left')
        self.example_button = ttk.Button(actions, text='Historical street example', command=self.open_example, state='normal' if self.example.is_file() else 'disabled')
        self.example_button.pack(side='left', padx=7)
        self._controls += [(self.open_button, 'normal'), (self.example_button, str(self.example_button['state']))]
        self.fit_button = ttk.Button(actions, text='Fit source', command=self.fit)
        self.fit_button.pack(side='left', padx=(0, 5))
        ttk.Button(actions, text='−', width=3, command=lambda: self.zoom(-1)).pack(side='left')
        ttk.Button(actions, text='+', width=3, command=lambda: self.zoom(1)).pack(side='left', padx=5)
        ttk.Button(actions, text='Source details', command=self.source_details).pack(side='right')
        body = ttk.Panedwindow(self, orient='horizontal')
        body.grid(row=3, column=0, sticky='nsew', padx=16)
        left = ttk.Frame(body, width=315)
        right = ttk.Frame(body)
        body.add(left, weight=1)
        body.add(right, weight=3)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=2)
        left.rowconfigure(4, weight=1)
        ttk.Label(left, text='Search names, feature types, or OSM IDs').grid(row=0, column=0, sticky='w')
        entry = ttk.Entry(left, textvariable=self.query)
        entry.grid(row=1, column=0, sticky='ew', pady=(5, 7))
        entry.bind('<Return>', lambda _event: self.filter())
        listing = ttk.Frame(left)
        listing.grid(row=2, column=0, sticky='nsew')
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        self.results = ttk.Treeview(listing, columns=('name', 'kind'), show='headings', selectmode='browse')
        for key, name, width in (('name', 'Source name', 150), ('kind', 'Source tag', 140)):
            self.results.heading(key, text=name)
            self.results.column(key, width=width, minwidth=75)
        self.results.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(listing, command=self.results.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.results.configure(yscrollcommand=scroll.set)
        self.results.bind('<<TreeviewSelect>>', lambda _event: self.select())
        self.results.bind('<Double-1>', lambda _event: self.focus_selected())
        self.center_button = ttk.Button(left, text='Center on selected feature', command=self.focus_selected)
        self.center_button.grid(row=3, column=0, sticky='ew', pady=7)
        self.details = ScrolledText(left, height=9, wrap='word', state='disabled', width=30)
        self.details.grid(row=4, column=0, sticky='nsew')
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(right, bg='#f0f3ee', takefocus=True, highlightthickness=1, highlightbackground='#bdc5be')
        self.canvas.grid(row=0, column=0, sticky='nsew', padx=(8, 0))
        self.canvas.bind('<Configure>', self.resize)
        self.canvas.bind('<ButtonPress-1>', self.drag_start)
        self.canvas.bind('<B1-Motion>', self.drag_move)
        self.canvas.bind('<ButtonRelease-1>', self.drag_end)
        self.canvas.bind('<MouseWheel>', lambda e: self.zoom(1 if e.delta > 0 else -1) if e.delta else None)
        self.canvas.bind('<Button-4>', lambda _e: self.zoom(1))
        self.canvas.bind('<Button-5>', lambda _e: self.zoom(-1))
        self.canvas.bind('<KeyPress>', self.key)
        self.canvas.bind('<Motion>', self.motion)
        self.summary_label = ttk.Label(self, textvariable=self.summary, wraplength=1080, justify='left')
        self.summary_label.grid(row=4, column=0, sticky='ew', padx=16, pady=6)
        self.pointer_label = ttk.Label(self, textvariable=self.pointer, wraplength=1080)
        self.pointer_label.grid(row=5, column=0, sticky='ew', padx=16)
        self.credit_label = ttk.Label(self, textvariable=self.credit, wraplength=1080, justify='left')
        self.credit_label.grid(row=6, column=0, sticky='ew', padx=16, pady=5)
        self.status_row(self).grid(row=7, column=0, sticky='ew', padx=16, pady=(0, 12))
        self.query.trace_add('write', lambda *_args: self.filter())
        self.bind('<Configure>', self.wrap, add=True)
        self.bind('<Destroy>', self.cleanup, add=True)
        self.status.set('Local preview supports small extracts up to 32 MiB, with additional object limits. No file opened automatically.')
        self.canvas.create_text(25, 30, anchor='nw', text='Open a local OSM PBF street source.\n\nNo map server, network connection or GPS required.\nThe example is historical and is not travel guidance.', width=410)

    def progress_message(self, current, total):
        return f'Decoded {current:,} of {total:,} input bytes. Assembling preview; not route-ready.'

    def cancelled_message(self):
        return 'Cancelled. No source file or database was changed; any previous preview remains.'

    def choose(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self, title='Choose a trusted small OpenStreetMap PBF snapshot', filetypes=[('OSM PBF source', '*.pbf')])
        if path:
            self.open_path(path)

    def open_path(self, path, *, example=False):
        if self.busy:
            return False
        self.status.set('Reading a local source snapshot. No changes to files, household data or routing settings.')
        return self.start_task(_load_example if example else read_street_source, path, progress=True, done=self.loaded)

    def open_example(self):
        return self.open_path(self.example, example=True)

    def loaded(self, source):
        self.source = source
        self.selected_id = None
        self._text('Choose a feature to inspect its source tags. These tags do not establish access or road safety.')
        is_example = source.sha256 == EXAMPLE_SHA256
        date = 'Unknown snapshot date' if source.replication_timestamp is None else 'Source reports ' + datetime.fromtimestamp(source.replication_timestamp, timezone.utc).isoformat()
        prefix = 'HISTORICAL FORMAT SAMPLE — not current coverage. ' if is_example else ''
        self.credit.set(prefix + '© OpenStreetMap contributors • ODbL 1.0 • openstreetmap.org/copyright • ' + date)
        self.query.set('')
        self.filter()
        self.fit()
        self.status.set(f'Read {source.nodes:,} nodes, {source.ways:,} ways, {source.relations:,} relations. {source.missing_node_ways} ways omitted for missing nodes; {source.polar_features} polar features omitted. No routing graph was installed.')

    def filter(self):
        if not self.source or self._disposed:
            return
        try:
            self.matches, total = search_features(self.source, self.query.get())
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self.results.delete(*self.results.get_children())
        for feature in self.matches:
            self.results.insert('', 'end', iid=feature.id, values=(feature.name, feature.kind))
        if self.selected_id in [f.id for f in self.matches]:
            self.results.selection_set(self.selected_id)
        self.summary.set(f'{len(self.source.features):,} preview features • {len(self.matches)} of {total:,} search matches shown. {self.source.relations:,} relations NOT drawn; {self.source.restrictions} restriction relations NOT applied.')

    def _text(self, text):
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', text)
        self.details.configure(state='disabled')

    def selected(self):
        return next((f for f in self.source.features if f.id == self.selected_id), None) if self.source else None

    def select(self):
        selected = self.results.selection()
        if not selected:
            return
        self.selected_id = selected[0]
        feature = self.selected()
        if feature:
            self._text(feature.name + '\n' + feature.id + '\n\n' + '\n'.join((k + ': ' + v for k, v in feature.tags)) + '\n\nSource tags only. No assurance of access, safety, completeness or current conditions.')
            self.draw()

    def size(self):
        return (min(1800, max(50, self.canvas.winfo_width())), min(1000, max(50, self.canvas.winfo_height())))

    def fit(self):
        if not self.source:
            return
        coords = [p for f in self.source.features for p in f.geometry]
        if not coords:
            self.view = None
            self.canvas.delete('all')
            self.canvas.create_text(20, 25, anchor='nw', text='No supported geometry. Source may contain only relations or missing nodes.')
            return
        self.view = fit_route(coords, range(23), *self.size())
        self.draw()

    def focus_selected(self):
        feature = self.selected()
        if feature:
            self.view = fit_route(feature.geometry, range(19), *self.size())
            self.draw()

    def zoom(self, delta):
        if self.view:
            self.view = Viewport(self.view.latitude, self.view.longitude, max(0, min(22, self.view.zoom + delta)), *self.size())
            self.draw()

    def draw(self):
        if self._disposed or self.view is None or self.source is None:
            return
        self.canvas.delete('all')
        used, labels, omitted = (0, [], 0)
        features = sorted(self.source.features, key=lambda f: f.id == self.selected_id)
        for feature in features:
            selected = feature.id == self.selected_id
            color = '#9f4c16' if feature.kind.startswith('highway=') else '#647b69'
            if feature.kind.startswith(('waterway=', 'natural=water')):
                color = '#287fac'
            if selected:
                color = '#6336a2'
            if len(feature.geometry) == 1:
                lon, lat = feature.geometry[0]
                for x, y in self.view.locations(lat, lon):
                    self.canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline='white', tags=('feature', feature.id))
            else:
                try:
                    lines = route_segments(feature.geometry, self.view)
                except ValueError:
                    omitted += 1
                    continue
                for line in lines:
                    if used + len(line) > MAX_DRAW_SEGMENTS:
                        omitted += 1
                        continue
                    used += len(line)
                    self.canvas.create_line(*[v for p in line for v in p], fill=color, width=5 if selected else 2, tags=('feature', feature.id))
            if feature.name != feature.id and len(labels) < MAX_LABELS:
                lon, lat = feature.geometry[len(feature.geometry) // 2]
                visible = self.view.locations(lat, lon)
                if visible:
                    x, y = visible[0]
                    if selected or all((abs(x - a) > 95 or abs(y - b) > 18 for a, b in labels)):
                        self.canvas.create_text(x + 5, y - 9, text=feature.name[:65], anchor='sw', fill='#1c322d', font=('TkDefaultFont', 9), tags=('feature', feature.id))
                        labels.append((x, y))
        self.canvas.create_text(12, 12, anchor='nw', text='SOURCE GEOMETRY • NO ROUTING\nBlank space is not proof that nothing is there.', fill='#193a30', width=max(150, self.view.width - 30), tags='caption')
        if not omitted and self.status.get().startswith('Display budget reached:'):
            self.status.set('Preview redrawn within its display budget. Not navigation; no source changed.')
        if omitted:
            self.status.set(f'Display budget reached: {omitted} line pieces not drawn. Zoom/search a smaller extract. Data remains loaded.')

    def drag_start(self, event):
        self.canvas.focus_set()
        self._drag = (event.x, event.y)

    def drag_move(self, event):
        if self._drag and self.view:
            self.view = self.view.pan(self._drag[0] - event.x, self._drag[1] - event.y)
            self._drag = (event.x, event.y)
            self.draw()

    def drag_end(self, event):
        self._drag = None

    def key(self, event):
        if event.keysym in ('plus', 'equal', 'minus'):
            self.zoom(-1 if event.keysym == 'minus' else 1)
        elif self.view and event.keysym in ('Left', 'Right', 'Up', 'Down'):
            dx, dy = {'Left': (-80, 0), 'Right': (80, 0), 'Up': (0, -80), 'Down': (0, 80)}[event.keysym]
            self.view = self.view.pan(dx, dy)
            self.draw()

    def motion(self, event):
        if self.view:
            try:
                lat, lon = self.view.at_pixel(event.x, event.y)
                self.pointer.set(f'Map pointer: {lat:.6f}, {lon:.6f} • zoom {self.view.zoom} • not a GPS fix')
            except ValueError:
                self.pointer.set('Outside Mercator latitude coverage; no GPS fix.')

    def source_details(self):
        if not self.source:
            return
        source = self.source
        messagebox.showinfo('Source snapshot / limits', f'{source.source_name}\nSHA-256: {source.sha256}\n{source.bytes:,} bytes\n{source.nodes} nodes; {source.ways} ways; {source.relations} relations\n{source.omitted_ways} non-display ways; {source.missing_node_ways} ways with missing nodes.\n\n' + self.credit.get() + '\n\n' + NOTICE + '\n\nThe local fingerprint is not a publisher signature. Contributor metadata and contact tags are not indexed or displayed. Your original file is not modified.', parent=self)

    def resize(self, _event=None):
        if self._resize_id is not None:
            self.after_cancel(self._resize_id)
        self._resize_id = self.after(80, self._resized)

    def _resized(self):
        self._resize_id = None
        if self.view and (not self._disposed):
            self.view = Viewport(self.view.latitude, self.view.longitude, self.view.zoom, *self.size())
            self.draw()

    def wrap(self, event):
        if event.widget is self:
            for widget in (self.notice, self.summary_label, self.pointer_label, self.credit_label, self.status_label):
                widget.configure(wraplength=max(500, event.width - 40))

    def cleanup(self, event):
        if event.widget is self and self._resize_id is not None:
            self.after_cancel(self._resize_id)
            self._resize_id = None
