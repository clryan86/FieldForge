"""Bounded relative path sketch; deliberately not a road map or route planner."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .tracks import TripSnapshot

PREVIEW_POINTS = 5000
PREVIEW_SEGMENTS = 1000


def _even_indices(length: int, count: int) -> tuple[int, ...]:
    if count >= length:
        return tuple(range(length))
    if count == 1:
        return (0,)
    return tuple(i * (length - 1) // (count - 1) for i in range(count))


@dataclass(frozen=True)
class Sketch:
    segments: tuple[tuple[tuple[float, float], ...], ...]
    shown_points: int
    total_points: int
    shown_segments: int
    total_segments: int


def sketch(trip: TripSnapshot, width: int, height: int) -> Sketch:
    """Fit a sampled, longitude-unwrapped, equirectangular sketch to a canvas.

    Segments never connect to each other. Rendering is capped independently of
    capture; GPX keeps all captured points. The sketch has no map, terrain,
    obstacle, speed, access-right or accuracy information.
    """
    if type(width) is not int or type(height) is not int or width < 100 or height < 100:
        raise ValueError("Sketch needs a canvas of at least 100 by 100 pixels.")
    selected = [trip.segments[i] for i in _even_indices(len(trip.segments), PREVIEW_SEGMENTS)]
    selected = [segment for segment in selected if segment]
    if not selected:
        return Sketch((), 0, trip.summary.point_count, 0, len(trip.segments))
    quota = max(2, PREVIEW_POINTS // len(selected))
    # Unwrap every source point before sampling so repeated dateline crossings
    # are not converted into an unintended long jump by preview decimation.
    anchor = selected[0][0].longitude
    mean_latitude = (
        min(p.latitude for s in selected for p in s) + max(p.latitude for s in selected for p in s)
    ) / 2
    x_scale = max(0.001, math.cos(math.radians(mean_latitude)))
    paths = []
    for segment in selected:
        keep = set(_even_indices(len(segment), quota))
        last_lon = anchor
        unwrapped = anchor
        path = []
        for index, point in enumerate(segment):
            unwrapped += (point.longitude - last_lon + 180) % 360 - 180
            last_lon = point.longitude
            if index in keep:
                path.append((unwrapped * x_scale, -point.latitude))
        paths.append(path)
    xs = [x for path in paths for x, _ in path]
    ys = [y for path in paths for _, y in path]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    span_x, span_y = max(xmax - xmin, 1e-6), max(ymax - ymin, 1e-6)
    scale = min((width - 90) / span_x, (height - 90) / span_y)
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    fitted = tuple(
        tuple((width / 2 + (x - cx) * scale, height / 2 + (y - cy) * scale) for x, y in path)
        for path in paths
    )
    return Sketch(
        fitted, sum(len(p) for p in paths), trip.summary.point_count, len(paths), len(trip.segments)
    )
