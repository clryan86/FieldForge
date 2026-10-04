"""Web Mercator display geometry; never substitutes roads, routes or polar points."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .mbtiles import MAX_CELLS, MAX_LAT
from .review_map import DISPLAY_POINTS, clip_line, sample_segments, wrap

TILE_SIZE = 256


def _number(v):
    return type(v) in (float, int) and math.isfinite(v)


def unit_xy(longitude, latitude):
    if (
        not _number(longitude)
        or not _number(latitude)
        or not -180 <= longitude <= 180
        or not -MAX_LAT <= latitude <= MAX_LAT
    ):
        raise ValueError(
            "Coordinates are outside Web Mercator; polar positions are not moved to its edge."
        )
    x = (longitude + 180) / 360
    y = (1 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2
    return x, max(0, min(1, y))  # Only floating-point noise at the mathematical extent.


def from_unit(x, y):
    if not _number(x) or not _number(y) or not 0 <= y <= 1:
        raise ValueError("Invalid normalized Mercator coordinates.")
    return wrap(x * 360 - 180), math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y))))


def _dimensions(width, height):
    if not all(type(v) is int and v >= 1 for v in (width, height)) or width > 2560 or height > 1600:
        raise ValueError("Map viewport must be at most 2560 × 1600 pixels; reduce the window size.")


@dataclass(frozen=True)
class MercatorView:
    longitude: float = 0
    latitude: float = 0
    level: int = 0

    def __post_init__(self):
        unit_xy(self.longitude, self.latitude)
        if self.longitude == 180 or type(self.level) is not int or not 0 <= self.level <= 22:
            raise ValueError("Invalid map center or zoom level.")

    @property
    def world_size(self):
        return TILE_SIZE * 2**self.level

    def position(self, longitude, latitude, width, height):
        try:
            x, y = unit_xy(longitude, latitude)
        except ValueError:
            return None
        cx, cy = unit_xy(self.longitude, self.latitude)
        dx = (x - cx + 0.5) % 1 - 0.5
        return width / 2 + dx * self.world_size, height / 2 + (y - cy) * self.world_size

    def pan(self, dx, dy, width, height):
        _dimensions(width, height)
        if not _number(dx) or not _number(dy):
            raise ValueError("Pan offsets must be finite.")
        x, y = unit_xy(self.longitude, self.latitude)
        lon, lat = from_unit(x - dx / self.world_size, max(0, min(1, y - dy / self.world_size)))
        return MercatorView(lon, lat, self.level)


def fit_mercator(points, width, height, levels):
    _dimensions(width, height)
    levels = tuple(levels)
    if not levels or any(type(z) is not int or not 0 <= z <= 22 for z in levels):
        raise ValueError("At least one supported zoom level is required.")
    xy = []
    for p in points:
        if -MAX_LAT <= p.latitude <= MAX_LAT:
            xy.append(unit_xy(p.longitude, p.latitude))
    if not xy:
        raise ValueError(
            "No selected track points are inside Web Mercator. Use World overview for polar tracks."
        )
    xs = sorted({x % 1 for x, _ in xy})
    gaps = [xs[(i + 1) % len(xs)] + (1 if i == len(xs) - 1 else 0) - x for i, x in enumerate(xs)]
    i = max(range(len(gaps)), key=gaps.__getitem__)
    span_x = max(0, 1 - gaps[i])
    south, north = max(y for _, y in xy), min(y for _, y in xy)
    longitude, latitude = from_unit(xs[(i + 1) % len(xs)] + span_x / 2, (south + north) / 2)
    fit_levels = [
        z
        for z in levels
        if span_x * TILE_SIZE * 2**z <= max(1, width - 64)
        and (south - north) * TILE_SIZE * 2**z <= max(1, height - 64)
    ]
    return MercatorView(longitude, latitude, max(fit_levels) if fit_levels else min(levels))


@dataclass(frozen=True)
class Cell:
    screen_x: float
    screen_y: float
    key: tuple[int, int, int] | None


def visible_cells(view: MercatorView, width, height):
    _dimensions(width, height)
    cx, cy = unit_xy(view.longitude, view.latitude)
    left, top = cx * view.world_size - width / 2, cy * view.world_size - height / 2
    cells = []
    n = 2**view.level
    for y in range(math.floor(top / TILE_SIZE), math.ceil((top + height) / TILE_SIZE)):
        for x in range(math.floor(left / TILE_SIZE), math.ceil((left + width) / TILE_SIZE)):
            key = (view.level, x % n, y) if 0 <= y < n else None
            cells.append(Cell(x * TILE_SIZE - left, y * TILE_SIZE - top, key))
    if len(cells) > MAX_CELLS:
        raise ValueError("Map viewport exceeds the 96-cell limit.")
    return tuple(cells)


def map_display_segments(segments, budget=DISPLAY_POINTS):
    """Split on every full-source polar point BEFORE simplifying the preview."""
    runs = []
    for segment in segments:
        run = []
        for point in segment:
            if -MAX_LAT <= point.latitude <= MAX_LAT:
                run.append(point)
            elif run:
                runs.append(tuple(run))
                run = []
        if run:
            runs.append(tuple(run))
    return sample_segments(tuple(runs), budget)


def project_mercator_paths(lonlat, view: MercatorView, width, height):
    """Clip connected paths; polar points break lines, including across simplification."""
    _dimensions(width, height)
    cx, cy = unit_xy(view.longitude, view.latitude)
    world = view.world_size
    copies = math.ceil(width / world / 2) + 1
    shifts = tuple(range(-copies, copies + 1))
    runs = {shift: [] for shift in shifts}
    paths = []

    def flush(shift):
        if runs[shift]:
            paths.append(tuple(runs[shift]))
            runs[shift] = []

    for a, b in zip(lonlat, lonlat[1:]):
        try:
            ax, ay = unit_xy(*a)
            bx, by = unit_xy(*b)
        except ValueError:
            for shift in shifts:
                flush(shift)
            continue
        ax = cx + ((ax - cx + 0.5) % 1 - 0.5)
        bx = ax + ((bx - (a[0] + 180) / 360 + 0.5) % 1 - 0.5)
        for shift in shifts:
            start = (width / 2 + (ax + shift - cx) * world, height / 2 + (ay - cy) * world)
            end = (width / 2 + (bx + shift - cx) * world, height / 2 + (by - cy) * world)
            clipped = clip_line(start, end, width, height)
            if clipped:
                run = runs[shift]
                if not run or any(abs(v - w) > 1e-7 for v, w in zip(run[-1], clipped[0])):
                    flush(shift)
                    runs[shift] = [clipped[0]]
                runs[shift].append(clipped[1])
            else:
                flush(shift)
    for shift in shifts:
        flush(shift)
    return tuple(paths)
