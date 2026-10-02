"""Web Mercator viewport geometry; no maps, GPS, routes or unit inference.

Tile placements use XYZ (north-origin) rows; the MBTiles reader performs the
separate TMS row conversion. Each logical tile occupies 256 screen pixels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

TILE_SIZE = 256
MAX_LATITUDE = math.degrees(math.atan(math.sinh(math.pi)))
MAX_VISIBLE_TILES = 96


def _zoom(value: int) -> None:
    if type(value) is not int or not 0 <= value <= 22:
        raise ValueError("Map zoom must be an integer from 0 to 22.")


def _number(value: float) -> None:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Map coordinates must be finite numbers, not booleans.")


def project(latitude: float, longitude: float, zoom: int) -> tuple[float, float]:
    _zoom(zoom)
    _number(latitude)
    _number(longitude)
    if not -MAX_LATITUDE <= latitude <= MAX_LATITUDE or not -180 <= longitude <= 180:
        raise ValueError("Map latitude must be within ±85.05112878°, longitude within ±180°. Polar places are not projected.")
    size = TILE_SIZE * (1 << zoom)
    x = (longitude + 180) / 360 * size
    y = (1 - math.asinh(math.tan(math.radians(latitude))) / math.pi) * size / 2
    return x % size, max(0.0, min(float(size), y))


def unproject(x: float, y: float, zoom: int) -> tuple[float, float]:
    _zoom(zoom)
    _number(x)
    _number(y)
    size = TILE_SIZE * (1 << zoom)
    if not 0 <= y <= size:
        raise ValueError("Pointer is outside the Web Mercator latitude extent.")
    latitude = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / size))))
    return latitude, (x % size) / size * 360 - 180


@dataclass(frozen=True)
class TileSlot:
    column: int
    row: int
    left: float
    top: float


@dataclass(frozen=True)
class Viewport:
    latitude: float
    longitude: float
    zoom: int
    width: int
    height: int

    def __post_init__(self) -> None:
        project(self.latitude, self.longitude, self.zoom)
        for value, maximum in ((self.width, 2560), (self.height, 1600)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Map viewport supports up to 2560 × 1600 pixels; make the window smaller.")
        if len(self.slots()) > MAX_VISIBLE_TILES:
            raise ValueError("Too many visible tiles; make the map window smaller.")

    @property
    def origin(self) -> tuple[float, float]:
        x, y = project(self.latitude, self.longitude, self.zoom)
        return x - self.width / 2, y - self.height / 2

    def slots(self) -> tuple[TileSlot, ...]:
        left, top = self.origin
        return tuple(TileSlot(x % (1 << self.zoom), y, x * TILE_SIZE - left, y * TILE_SIZE - top)
                     for y in range(math.floor(top / TILE_SIZE), math.ceil((top + self.height) / TILE_SIZE))
                     for x in range(math.floor(left / TILE_SIZE), math.ceil((left + self.width) / TILE_SIZE)))

    def at_pixel(self, x: float, y: float) -> tuple[float, float]:
        left, top = self.origin
        return unproject(left + x, top + y, self.zoom)

    def pan(self, dx: float, dy: float) -> Viewport:
        """Move the view center in world-pixel coordinates; positive dx pans east."""
        _number(dx)
        _number(dy)
        x, y = project(self.latitude, self.longitude, self.zoom)
        size = TILE_SIZE * (1 << self.zoom)
        latitude, longitude = unproject(x + dx, max(0, min(size, y + dy)), self.zoom)
        return Viewport(latitude, longitude, self.zoom, self.width, self.height)

    def locations(self, latitude: float, longitude: float) -> tuple[tuple[float, float], ...]:
        """Visible copies of one place, including horizontal wrapping at the date line."""
        x, y = project(latitude, longitude, self.zoom)
        left, top = self.origin
        y -= top
        if not 0 <= y <= self.height:
            return ()
        size = TILE_SIZE * (1 << self.zoom)
        first = math.ceil((left - x) / size)
        last = math.floor((left + self.width - x) / size)
        return tuple((x + copy * size - left, y) for copy in range(first, last + 1))
