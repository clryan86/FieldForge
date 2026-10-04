"""Bounded offline drawing geometry for a stored, planned route.

Input coordinates are GeoJSON order: longitude, latitude. Every rendered line
comes from an original adjacent pair; this module never connects sampled points
or interpolates across a polar gap. Projection and display clipping do not
modify the saved route. No I/O, location receiver or network is used here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fieldforge.navigation.map_view import MAX_LATITUDE, TILE_SIZE, Viewport, project

MAX_ROUTE_POINTS = 50_000
MAX_VISIBLE_SEGMENTS = 12_000
MAX_PATH_POINTS = 512

Point = tuple[float, float]
Segment = tuple[float, float, float, float]


@dataclass(frozen=True)
class RouteGeometry:
    """Projected adjacent segments in zoom-zero pixels, with polar gaps kept."""

    segments: tuple[tuple[int, Segment], ...]
    point_count: int
    polar_points: int
    start: tuple[float, float] | None  # Actual geometry endpoint, latitude first.
    end: tuple[float, float] | None


@dataclass(frozen=True)
class RouteDrawing:
    paths: tuple[tuple[Point, ...], ...]
    visible_segments: int
    limited: bool


def prepare_route(geometry) -> RouteGeometry:
    """Validate and project at most 50,000 lon/lat vertices once per selection.

    For each pair, choose the longitudinal continuation across the nearest world
    edge. A date-line crossing is therefore a short segment in adjacent world
    copies, not a chord across the middle of the world. At exactly 180 degrees the
    original projected direction is retained; no intermediate vertices are made.
    Polar vertices and both adjoining segments are omitted rather than clamped.
    """
    if not isinstance(geometry, (list, tuple)) or not 2 <= len(geometry) <= MAX_ROUTE_POINTS:
        raise ValueError(f"Route geometry must contain 2 to {MAX_ROUTE_POINTS:,} points.")
    segments = []
    previous = None
    polar = 0
    endpoints = [None, None]
    for index, point in enumerate(geometry):
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            raise ValueError("Route geometry must use [longitude, latitude] pairs.")
        longitude, latitude = point
        for value, maximum in ((longitude, 180), (latitude, 90)):
            if type(value) not in (int, float) or not -maximum <= value <= maximum:
                raise ValueError("Route coordinates must be finite WGS 84 numbers.")
        if abs(latitude) > MAX_LATITUDE:
            polar += 1
            previous = None
            continue
        current = project(latitude, longitude, 0)
        if index == 0:
            endpoints[0] = (latitude, longitude)
        if index == len(geometry) - 1:
            endpoints[1] = (latitude, longitude)
        if previous is not None:
            x0, y0 = previous
            x1, y1 = current
            delta = x1 - x0
            if delta > TILE_SIZE / 2:
                x1 -= TILE_SIZE
            elif delta < -TILE_SIZE / 2:
                x1 += TILE_SIZE
            segments.append((index, (x0, y0, x1, y1)))
        previous = current
    return RouteGeometry(tuple(segments), len(geometry), polar, *endpoints)


def clip_segment(segment: Segment, width: int, height: int) -> Segment | None:
    """Clip one screen segment to the closed viewport rectangle (Liang–Barsky).

    Coordinates on an edge remain on that edge; an entirely offscreen segment is
    discarded. The clipped points describe only the visible part of this segment.
    """
    if (len(segment) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in segment)
            or type(width) is not int or type(height) is not int or width < 1 or height < 1):
        raise ValueError("Clipping requires finite endpoints and positive integer dimensions.")
    x0, y0, x1, y1 = segment
    dx, dy = x1 - x0, y1 - y0
    if not math.isfinite(dx) or not math.isfinite(dy):
        raise ValueError("Segment extent exceeds the supported numeric range.")
    enter, leave = 0.0, 1.0
    for p, q in ((-dx, x0), (dx, width - x0), (-dy, y0), (dy, height - y0)):
        if p == 0:
            if q < 0:
                return None
        elif p < 0:
            enter = max(enter, q / p)
        else:
            leave = min(leave, q / p)
        if enter > leave:
            return None
    # Floating point intersections can be a tiny fraction outside an edge.
    def bounded(x, y):
        return max(0.0, min(float(width), x)), max(0.0, min(float(height), y))

    start = (x0, y0) if enter == 0 else (x0 + enter * dx, y0 + enter * dy)
    end = (x1, y1) if leave == 1 else (x0 + leave * dx, y0 + leave * dy)
    return (*bounded(*start), *bounded(*end))


def visible_route(route: RouteGeometry, view: Viewport, *, segment_limit=MAX_VISIBLE_SEGMENTS) -> RouteDrawing:
    """Return exact clipped paths for the visible horizontal world copies.

    Work is bounded by the validated 50,000-point input and at most 12,000 emitted
    segments. Each canvas path also has a bounded point count. If more geometry is
    visible, ``limited`` explicitly reports incomplete display; no shortcut lines
    are substituted. Joining is allowed only for consecutive original segments
    whose clipped endpoints are exactly equal, including across world wrapping.
    """
    if type(segment_limit) is not int or not 1 <= segment_limit <= MAX_VISIBLE_SEGMENTS:
        raise ValueError(f"Route display limit must be between 1 and {MAX_VISIBLE_SEGMENTS:,}.")
    left, top = view.origin
    scale = 1 << view.zoom
    world = TILE_SIZE * scale
    width, height = view.width, view.height
    paths = []
    previous_ends = {}
    previous_index = -1
    visible = 0
    for index, segment in route.segments:
        x0, y0, x1, y1 = segment
        x0, x1 = x0 * scale - left, x1 * scale - left
        y0, y1 = y0 * scale - top, y1 * scale - top
        if max(y0, y1) < 0 or min(y0, y1) > height:
            previous_ends = {}
            previous_index = index
            continue
        if index != previous_index + 1:
            previous_ends = {}
        # A segment is at most half a world wide. Only intersecting copies are
        # considered, even when the viewport straddles the date line or is
        # wider than a whole zoom-zero world.
        first = math.ceil(-max(x0, x1) / world)
        last = math.floor((width - min(x0, x1)) / world)
        current_ends = {}
        for copy in range(first, last + 1):
            clipped = clip_segment((x0 + copy * world, y0, x1 + copy * world, y1), width, height)
            if clipped is None:
                continue
            start, end = clipped[:2], clipped[2:]
            if start == end:
                continue
            if visible == segment_limit:
                return RouteDrawing(tuple(tuple(path) for path in paths), visible, True)
            path_index = previous_ends.get(start)
            if path_index is None or len(paths[path_index]) >= MAX_PATH_POINTS:
                path_index = len(paths)
                paths.append([start, end])
            else:
                paths[path_index].append(end)
            current_ends[end] = path_index
            visible += 1
        previous_ends, previous_index = current_ends, index
    return RouteDrawing(tuple(tuple(path) for path in paths), visible, False)
