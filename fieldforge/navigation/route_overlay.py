"""Dateline-aware route display. It projects engine geometry, not new paths."""
from __future__ import annotations

import math

from fieldforge.navigation.map_view import MAX_LATITUDE, TILE_SIZE, Viewport, project, unproject


def fit_route(geometry, zooms, width, height):
    if not geometry or not zooms:
        raise ValueError('No geometry or installed map zoom is available.')
    if any((abs(p[1]) > MAX_LATITUDE for p in geometry)):
        raise ValueError('This route extends outside the map’s Mercator latitude coverage.')
    points = [project(lat, lon, 0) for lon, lat in geometry]
    xs = sorted((p[0] for p in points))
    gaps = [(xs[(i + 1) % len(xs)] + (256 if i == len(xs) - 1 else 0) - x, i) for i, x in enumerate(xs)]
    _, gap = max(gaps)
    left = xs[(gap + 1) % len(xs)]
    span = 256 - gaps[gap][0]
    ys = [p[1] for p in points]
    cy, cx = ((min(ys) + max(ys)) / 2, (left + span / 2) % 256)
    zoom = min(zooms)
    for candidate in sorted(zooms):
        if span * 2 ** candidate <= max(1, width - 90) and (max(ys) - min(ys)) * 2 ** candidate <= max(1, height - 90):
            zoom = candidate
    lat, lon = unproject(cx, cy, 0)
    return Viewport(lat, lon, zoom, width, height)

def _clip(x1, y1, x2, y2, w, h):
    lo, hi = (0.0, 1.0)
    dx, dy = (x2 - x1, y2 - y1)
    for p, q in ((-dx, x1), (dx, w - x1), (-dy, y1), (dy, h - y1)):
        if p == 0:
            if q < 0:
                return None
        else:
            u = q / p
            if p < 0:
                lo = max(lo, u)
            else:
                hi = min(hi, u)
            if lo > hi:
                return None
    return ((x1 + lo * dx, y1 + lo * dy), (x1 + hi * dx, y1 + hi * dy))

def route_segments(geometry, view: Viewport):
    """Clip unwrapped segments; never draw a long chord across the date line."""
    if any((abs(p[1]) > MAX_LATITUDE for p in geometry)):
        raise ValueError('Route lies outside this map projection.')
    size = TILE_SIZE * 2 ** view.zoom
    left, top = view.origin
    points = []
    for lon, lat in geometry:
        x, y = project(lat, lon, view.zoom)
        if points:
            x += round((points[-1][0] - x) / size) * size
        points.append((x, y))
    if len(points) < 2:
        return ()
    lo, hi = (min((p[0] for p in points)), max((p[0] for p in points)))
    first, last = (math.ceil((left - hi) / size), math.floor((left + view.width - lo) / size))
    if last - first > 16:
        raise ValueError('Route spans too many wrapped worlds to display.')
    lines = []
    count = 0
    for copy in range(first, last + 1):
        current = []
        for a, b in zip(points, points[1:]):
            segment = _clip(a[0] + copy * size - left, a[1] - top, b[0] + copy * size - left, b[1] - top, view.width, view.height)
            if segment is None:
                if current:
                    lines.append(tuple(current))
                    current = []
                continue
            start, end = segment
            if current and current[-1] != start:
                lines.append(tuple(current))
                current = []
            if not current:
                current.append(start)
            current.append(end)
            count += 1
            if count > 100000:
                raise ValueError('Route overlay exceeds its display segment limit.')
        if current:
            lines.append(tuple(current))
    return tuple(lines)
