"""Pure map geometry and the bundled coarse overview; no online tile services.

Equirectangular display, not a navigational chart. File segments remain separate.
The overview's source vintage is unknown; no road or current-condition claim.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

OVERVIEW_SHA256 = "6828fc5d0dcf72838e2ad20f2a1a477444e30f4ded9a2de1937e2d72a86d620b"
MIN_SPAN = 0.001
DISPLAY_POINTS = 8_000


def wrap(longitude: float) -> float:
    return (longitude + 180) % 360 - 180


def _finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True)
class View:
    longitude: float = 0.0
    latitude: float = 0.0
    span: float = 360.0

    def __post_init__(self):
        if not all(_finite(x) for x in (self.longitude, self.latitude, self.span)):
            raise ValueError("Map view coordinates and span must be finite.")
        if (
            not -180 <= self.longitude < 180
            or not -90 <= self.latitude <= 90
            or not MIN_SPAN <= self.span <= 360
        ):
            raise ValueError("Map view is outside the supported range.")

    def scale(self, width: int, height: int) -> float:
        if not all(_finite(x) and 1 <= x <= 100_000 for x in (width, height)):
            raise ValueError("Map dimensions must be finite and between 1 and 100,000 pixels.")
        return min(width / 360, height / 180) * 360 / self.span

    def position(self, longitude, latitude, width, height):
        scale = self.scale(width, height)
        return (
            width / 2 + wrap(longitude - self.longitude) * scale,
            height / 2 - (latitude - self.latitude) * scale,
        )

    def zoom(self, factor: float):
        if not _finite(factor) or factor <= 0:
            raise ValueError("Zoom factor must be positive and finite.")
        return View(self.longitude, self.latitude, max(MIN_SPAN, min(360, self.span / factor)))

    def pan(self, dx: float, dy: float, width: int, height: int):
        if not _finite(dx) or not _finite(dy):
            raise ValueError("Pan movement must be finite.")
        scale = self.scale(width, height)
        return View(
            wrap(self.longitude - dx / scale),
            max(-90, min(90, self.latitude + dy / scale)),
            self.span,
        )


def fit_points(points, width: int, height: int) -> View:
    """Smallest longitude arc; points on either side of the date line fit together."""
    points = tuple(points)
    if not points:
        return View()
    lons = sorted({point.longitude % 360 for point in points})
    gaps = [
        (lons[(i + 1) % len(lons)] + (360 if i == len(lons) - 1 else 0) - v)
        for i, v in enumerate(lons)
    ]
    index = max(range(len(gaps)), key=gaps.__getitem__)
    arc = 360 - gaps[index]
    longitude = wrap(lons[(index + 1) % len(lons)] + arc / 2)
    south, north = min(p.latitude for p in points), max(p.latitude for p in points)
    base = View().scale(width, height)
    span = max(
        MIN_SPAN,
        arc * base * 360 / max(1, width - 64),
        (north - south) * base * 360 / max(1, height - 64),
    )
    return View(longitude, (south + north) / 2, min(360, max(MIN_SPAN, span * 1.15)))


def clip_line(a, b, width, height):
    """Liang-Barsky clipping keeps large off-screen coordinates away from Tk."""
    x0, y0 = a
    dx, dy = b[0] - x0, b[1] - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0), (dx, width - x0), (-dy, y0), (dy, height - y0)):
        if p == 0:
            if q < 0:
                return None
        else:
            ratio = q / p
            if p < 0:
                t0 = max(t0, ratio)
            else:
                t1 = min(t1, ratio)
            if t0 > t1:
                return None
    return (
        (max(0, min(width, x0 + t0 * dx)), max(0, min(height, y0 + t0 * dy))),
        (max(0, min(width, x0 + t1 * dx)), max(0, min(height, y0 + t1 * dy))),
    )


def project_paths(lonlat, view: View, width: int, height: int):
    """Split at the map edge instead of drawing spurious cross-world chords.

    Each pair is interpreted along its shorter longitudinal separation. No call
    joins distinct input segments, and clipping does not add geographic samples.
    """
    scale = view.scale(width, height)
    paths = []
    runs = [[], [], []]
    for a, b in zip(lonlat, lonlat[1:]):
        lon0 = view.longitude + wrap(a[0] - view.longitude)
        lon1 = lon0 + wrap(b[0] - a[0])
        for i, shift in enumerate((-360, 0, 360)):
            start = (
                width / 2 + (lon0 + shift - view.longitude) * scale,
                height / 2 - (a[1] - view.latitude) * scale,
            )
            end = (
                width / 2 + (lon1 + shift - view.longitude) * scale,
                height / 2 - (b[1] - view.latitude) * scale,
            )
            clipped = clip_line(start, end, width, height)
            run = runs[i]
            if clipped is not None:
                same = (
                    run
                    and abs(run[-1][0] - clipped[0][0]) < 1e-7
                    and abs(run[-1][1] - clipped[0][1]) < 1e-7
                )
                if not same:
                    if run:
                        paths.append(tuple(run))
                    runs[i] = [clipped[0]]
                runs[i].append(clipped[1])
            elif run:
                paths.append(tuple(run))
                runs[i] = []
    paths.extend(tuple(run) for run in runs if run)
    return tuple(paths)


def sample_segments(segments, budget: int = DISPLAY_POINTS):
    """Bound display cost; retain ends of each shown segment and never join gaps.

    When even segment endpoints exceed the budget, omit whole trailing segments
    and disclose shown/total counts. Full source data remains in the document.
    """
    if type(budget) is not int or not 1 <= budget <= DISPLAY_POINTS:
        raise ValueError("Invalid display point budget.")
    total = sum(map(len, segments))
    stride = max(1, math.ceil(total / budget))
    shown = []
    remaining = budget
    for segment in segments:
        if not segment:
            continue
        required = min(2, len(segment))
        if remaining < required:
            break
        indices = list(range(0, len(segment), stride))
        if indices[-1] != len(segment) - 1:
            indices.append(len(segment) - 1)
        if len(indices) > remaining:
            indices = (
                [round(i * (len(segment) - 1) / (remaining - 1)) for i in range(remaining)]
                if remaining > 1
                else [0]
            )
        shown.append(tuple(segment[i] for i in indices))
        remaining -= len(indices)
    return tuple(shown)


def connected_length_m(segments) -> float:
    """Approximate spherical point-to-point length excluding file-defined gaps."""
    total = 0.0
    for segment in segments:
        for a, b in zip(segment, segment[1:]):
            p, q = math.radians(a.latitude), math.radians(b.latitude)
            dl = math.radians(wrap(b.longitude - a.longitude))
            h = math.sin((q - p) / 2) ** 2 + math.cos(p) * math.cos(q) * math.sin(dl / 2) ** 2
            total += 12_742_000 * math.asin(math.sqrt(max(0, min(1, h))))
    return total


def load_overview():
    """Check packaged data integrity; never substitutes downloaded content."""
    data = (Path(__file__).parent / "data" / "overview.json").read_bytes()
    if hashlib.sha256(data).hexdigest() != OVERVIEW_SHA256:
        raise ValueError("Bundled coastline overview failed its integrity check.")
    document = json.loads(data)
    return tuple(tuple(tuple(point) for point in ring) for ring in document["rings"])
