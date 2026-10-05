"""Disk-backed regional viewer using bounded background search/viewport queries."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tkinter import TclError, filedialog, messagebox, ttk

from fieldforge.navigation.map_view import Viewport
from fieldforge.navigation.osm_source import StreetSource
from fieldforge.navigation.regional_index import (
    NOTICE,
    import_archive,
    feature_coordinate,
    inspect_index,
    prepare_index,
    search_index,
    viewport_index,
)
from fieldforge.ui.street_source import StreetSourceWindow


def _page(index, query, view, *, cancel=None):
    return index, query, view, search_index(index, query, cancel=cancel), viewport_index(
        index, view, cancel=cancel)


class RegionalIndexWindow(StreetSourceWindow):
    def __init__(self, panel):
        self.index = None
        self._refresh_id = None
        self._pending_refresh = False
        self._task_kind = None
        self._selected_feature = None
        self._selected_coordinate = None
        self._viewport_features = ()
        self.page_limited = False
        super().__init__(panel, heading='Regional maps • prepared local index')
        self.title('FieldForge — Prepared regional map')
        self.notice.configure(text=NOTICE)
        self.open_button.configure(text='Open index…')
        self.example_button.destroy()
        self._controls = [entry for entry in self._controls if entry[0] is not self.example_button]
        actions = self.open_button.master
        self.import_button = ttk.Button(actions, text='Import package ZIP…', command=self.choose_import)
        self.import_button.pack(side='left', padx=5)
        self._controls.append((self.import_button, 'normal'))
        self.prepare_button = ttk.Button(actions, text='Prepare PBF…', command=self.choose_prepare)
        self.prepare_button.pack(side='left', padx=5)
        self._controls.append((self.prepare_button, 'normal'))
        left = self.details.master
        left.rowconfigure(4, weight=0)
        left.rowconfigure(5, weight=1)
        self.copy_button = ttk.Button(left, text='Copy lat, lon', command=self.copy_coordinates,
                                      state='disabled')
        self.copy_button.grid(row=4, column=0, sticky='ew', pady=(4, 0))
        self.details.grid_configure(row=5)
        self._controls.append((self.copy_button, 'disabled'))
        self.summary.set('No prepared map open. Your PBF source and household data are not modified.')
        self.status.set('Prepare a local source once, then reopen its .ffmap for offline search and display.')
        self.credit.set('No network or GPS access. A prepared index is visual/search data, NOT a routing graph.')
        self.canvas.delete('all')
        self.canvas.create_text(25, 30, anchor='nw', width=420,
                                text='Open a prepared .ffmap or choose Prepare PBF.\n\n'
                                     'Source nodes are held on disk during preparation.\n'
                                     'Only a bounded set of visible features is loaded for display.')
        self.bind('<Destroy>', self._index_cleanup, add=True)

    def choose(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self, title='Open a trusted prepared regional index',
                                         filetypes=[('FieldForge regional index', '*.ffmap')])
        if path:
            self.open_path(path)

    def open_path(self, path, *, example=False):
        if self.busy:
            return False
        self._pending_refresh = False
        self._task_kind = 'open'
        self.status.set('Checking regional index structure. Current map stays until this succeeds.')
        return self.start_task(inspect_index, path,
                               done=self.loaded_index, progress=True)

    def choose_prepare(self):
        if self.busy:
            return
        source = filedialog.askopenfilename(parent=self, title='Select a trusted local OSM PBF snapshot',
                                           filetypes=[('OSM PBF', '*.pbf')])
        if not source:
            return
        target = filedialog.asksaveasfilename(parent=self, title='Create a NEW prepared index',
                                             defaultextension='.ffmap',
                                             filetypes=[('FieldForge regional index', '*.ffmap')])
        if not target:
            return
        if not messagebox.askyesno('Prepare local map on disk?',
                'This creates a new .ffmap without changing your source or household data. '
                'It may take time and substantial disk space. Up to two 4 GiB temporary '
                'databases plus SQLite temporary space may be used. Existing files cannot '
                'be replaced. Preparation does not make the map route-ready.\n\nContinue?', parent=self):
            return
        self.prepare(source, target)

    def choose_import(self):
        if self.busy:
            return
        archive = filedialog.askopenfilename(parent=self, title='Choose a regional map ZIP package',
                                            filetypes=[('Regional map package', '*.zip')])
        if not archive:
            return
        suggested = Path(archive).stem + '.ffmap'
        target = filedialog.asksaveasfilename(parent=self, title='Save the extracted regional index as a new file',
                                              initialfile=suggested, defaultextension='.ffmap',
                                              filetypes=[('FieldForge regional index', '*.ffmap')])
        if not target:
            return
        if not messagebox.askyesno('Import local map package?',
                'FieldForge will read only the single map.ffmap from this ZIP, validate it, '
                'and create a new .ffmap copy. The ZIP and its source PBF remain unchanged. '
                'The archive limit is 2 GiB, the index limit is 4 GiB, and extra free space '
                'is needed while copying and validating. Existing files cannot be replaced. '
                'This index is not a routing graph. Continue?', parent=self):
            return
        self.import_package(archive, target)

    def import_package(self, archive, target):
        if self.busy:
            return False
        self._pending_refresh = False
        self._task_kind = 'import'
        self.status.set('Validating the ZIP and copying only its map.ffmap index. The archive remains unchanged.')
        return self.start_task(import_archive, archive, target, done=self.loaded_index, progress=True)

    def prepare(self, source, target, *, expected_sha256=None):
        if self.busy:
            return False
        self._pending_refresh = False
        self._task_kind = 'prepare'
        self.status.set('Preparing a new regional index on disk. Current map and source are unchanged.')
        return self.start_task(prepare_index, source, target, expected_sha256=expected_sha256,
                               done=self.loaded_index, progress=True)

    def loaded_index(self, index):
        self.index = index
        meta = index.metadata
        self.source = StreetSource(meta['source_name'], meta['source_sha256'], meta['source_bytes'],
                                   meta['nodes'], meta['ways'], meta['relations'], meta['restrictions'],
                                   meta['omitted_ways'], meta['missing_node_ways'], meta['polar_features'],
                                   meta['replication_timestamp'], (), notice=NOTICE)
        self.selected_id = None
        self._selected_feature = None
        self.matches = ()
        self.query.set('')
        self._text('Search names, feature tags, and explicit address tags when present. Results are source features, not verified geocoding or entrances. No GPS fix is available here.')
        date = ('Unknown snapshot date' if meta['replication_timestamp'] is None else
                'Source reports ' + datetime.fromtimestamp(meta['replication_timestamp'], timezone.utc).isoformat())
        self.credit.set('© OpenStreetMap contributors • ODbL 1.0 • openstreetmap.org/copyright • ' + date)
        self.status.set(f'Prepared index open: {meta["features"]:,} indexed features. No routing graph installed.')
        self.fit()

    def fit(self):
        if self.index is None:
            return
        bounds = self.index.metadata['bounds']
        if bounds is None:
            self.view = Viewport(0, 0, 1, *self.size())
        else:
            # Extent is an ordinary non-wrapping box. Do not use a shortest-arc
            # route fit on worldwide extrema: that can select the wrong hemisphere.
            import math

            from fieldforge.navigation.map_view import project, unproject
            w, s, e, n = bounds
            _, y1 = project(n, 0, 0)
            _, y2 = project(s, 0, 0)
            lat, _ = unproject(128, (y1 + y2) / 2, 0)
            width, height = self.size()
            scale = max((e - w) / 360 * 256 / max(1, width - 90),
                        (y2 - y1) / max(1, height - 90), 2**-18)
            zoom = max(0, min(18, math.floor(-math.log2(scale))))
            self.view = Viewport(lat, (w + e) / 2, zoom, width, height)
        self.draw()

    def filter(self):
        if self._disposed:
            return
        self.matches = ()
        self.selected_id = None
        self._selected_feature = None
        self._selected_coordinate = None
        self._set_copy_enabled(False)
        self.results.delete(*self.results.get_children())
        self._text('Searching the local index… Previous search results have been cleared.')
        self._schedule()

    def draw(self):
        if self._disposed or not self.index or not self.view:
            return
        self.canvas.delete('all')
        self.canvas.create_text(14, 15, anchor='nw', text='Loading this indexed area…\nNot navigation.', tags='caption')
        self._schedule()

    def _schedule(self):
        if self._disposed or not self.index or not self.view:
            return
        self._pending_refresh = True
        if self._refresh_id is not None:
            self.after_cancel(self._refresh_id)
        # Input changes cancel only queries, never a prepare/open operation.
        if self.busy and self._task_kind == 'query':
            self._cancel.set()
        self._refresh_id = self.after(160, self._refresh)

    def _refresh(self):
        self._refresh_id = None
        if self._disposed or self._closing or not self._pending_refresh:
            return
        if self.busy:
            return
        self._pending_refresh = False
        self._task_kind = 'query'
        self.start_task(_page, self.index, self.query.get(), self.view, done=self.loaded_page)

    def _poll(self):
        super()._poll()
        if not self._disposed and not self.busy and self._pending_refresh and self._refresh_id is None:
            self._refresh_id = self.after(1, self._refresh)

    def loaded_page(self, payload):
        index, query, view, matches, page = payload
        if index is not self.index or query != self.query.get() or view != self.view:
            self._schedule()
            return
        self.matches = matches.features
        self._viewport_features = page.features
        features = list(page.features)
        if self._selected_feature is not None and self._selected_feature.id not in {f.id for f in features}:
            features.append(self._selected_feature)
        self.source = replace(self.source, features=tuple(features))
        self.page_limited = page.limited
        self.results.delete(*self.results.get_children())
        for feature in self.matches:
            self.results.insert('', 'end', iid=feature.id, values=(feature.name, feature.kind))
        if self.selected_id in {f.id for f in self.matches}:
            self.results.selection_set(self.selected_id)
        self.summary.set(f'{self.index.metadata["features"]:,} indexed features • '
                         f'{len(page.features):,} in this view' + (' (LIMITED: zoom in)' if page.limited else '') +
                         f' • {len(matches.features):,} search results' + (' (more not shown)' if matches.limited else '') +
                         '. Relations/turn restrictions are NOT drawn or applied.')
        self.status.set('Read-only regional index. No original PBF needed to reopen; not route-ready.')
        self._render()

    def _render(self):
        StreetSourceWindow.draw(self)
        self.canvas.itemconfigure('caption', text='PREPARED SOURCE GEOMETRY • NOT NAVIGATION\n' +
                                  ('VIEW LIMITED — zoom in to inspect more features.' if self.page_limited else
                                   'Blank space is not proof that nothing is there.'))

    def selected(self):
        return self._selected_feature

    def _set_copy_enabled(self, enabled):
        state = 'normal' if enabled else 'disabled'
        self.copy_button.configure(state=state)
        self._controls = [(widget, state if widget is self.copy_button else saved)
                          for widget, saved in self._controls]

    def copy_coordinates(self):
        if self._selected_coordinate is None:
            return
        latitude, longitude, is_source_point = self._selected_coordinate
        value = f'{latitude:.7f}, {longitude:.7f}'
        try:
            self.clipboard_clear()
            self.clipboard_append(value)
        except TclError:
            self.status.set('Clipboard unavailable. Coordinates: ' + value)
            return
        kind = 'source point' if is_source_point else 'approximate feature-bounds center'
        self.status.set(f'Copied {kind} (latitude, longitude): {value}. Not a verified entrance.')

    def select(self):
        selection = self.results.selection()
        if not selection:
            return
        feature = next((f for f in self.matches if f.id == selection[0]), None)
        if feature is None:
            return
        self.selected_id, self._selected_feature = feature.id, feature
        self._selected_coordinate = feature_coordinate(feature)
        self._set_copy_enabled(self._selected_coordinate is not None)
        coordinate_text = ''
        if self._selected_coordinate is not None:
            latitude, longitude, is_source_point = self._selected_coordinate
            kind = ('Source point coordinate' if is_source_point else
                    'Approximate feature-bounds center; not an entrance')
            coordinate_text = f'{kind} (latitude, longitude): {latitude:.7f}, {longitude:.7f}\n\n'
        self._text(feature.name + '\n' + feature.id + '\n\n' + coordinate_text +
                   '\n'.join(k + ': ' + v for k, v in feature.tags) +
                   '\n\nSource tags do not verify an address, access, or current road conditions.')
        if self.source is not None:
            features = {f.id: f for f in self._viewport_features}
            features[feature.id] = feature
            self.source = replace(self.source, features=tuple(features.values()))
            self._render()

    def source_details(self):
        if not self.index:
            return
        meta = self.index.metadata
        messagebox.showinfo('Prepared index / source provenance',
            f'{self.index.path}\n\nSource: {meta["source_name"]}\n'
            f'Source SHA-256: {meta["source_sha256"]}\n'
            f'{meta["nodes"]:,} nodes; {meta["ways"]:,} ways; {meta["relations"]:,} relations\n'
            f'{meta["features"]:,} indexed features\n'
            f'{meta["missing_node_ways"]:,} ways missing nodes; '
            f'{meta["polar_features"]:,} polar and {meta["dateline_features"]:,} date-line features omitted\n'
            f'{meta["restrictions"]:,} restrictions counted, NOT applied\n\n'
            + self.credit.get() + '\n\n' + NOTICE + '\n\n'
            'The source checksum is not a publisher signature or an index signature. '
            'This external map is NOT included in household database backups. Copy it separately. '
            'Unencrypted. Search/contact or household data are not written here.', parent=self)

    def progress_message(self, current, total):
        if self._task_kind == 'prepare':
            stage = 'Decoding source to disk' if current <= 70 else 'Assembling spatial/search index'
            return f'{stage}: {current}% of preparation stages. No route graph is built.'
        if self._task_kind == 'import':
            return f'Validating package: copied {current:,} of {total:,} index bytes. No route graph is built.'
        return 'Checking prepared index structure and counts…'

    def cancelled_message(self):
        return ('Cancelled. A preparation already published may remain as a complete index; '
                'unpublished temporary files are removed. Sources and household data are unchanged.')

    def cancel(self):
        self._pending_refresh = False
        if self._refresh_id is not None:
            self.after_cancel(self._refresh_id)
            self._refresh_id = None
        super().cancel()

    def _index_cleanup(self, event):
        if event.widget is self and self._refresh_id is not None:
            self.after_cancel(self._refresh_id)
            self._refresh_id = None
