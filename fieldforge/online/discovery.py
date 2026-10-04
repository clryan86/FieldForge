"""Filter the in-memory map catalog without making requests or changing entries."""

import unicodedata

from fieldforge.navigation.places import coordinate
from fieldforge.online.models import number, validate_coordinates


def filter_point(latitude, longitude):
    """Blank fields disable point filtering; a half-filled pair never means zero."""
    if not latitude.strip() and not longitude.strip():
        return None
    if not latitude.strip() or not longitude.strip():
        raise ValueError("Enter both latitude and longitude, or clear both to show all maps.")
    return coordinate(latitude, latitude=True), coordinate(longitude, latitude=False)


def coverage_bounds(item):
    """Return declared numeric bounds only; never infer an extent from a label."""
    coverage = _value(item, "coverage")
    if not isinstance(coverage, (tuple, list)) or len(coverage) != 4:
        return None
    try:
        west, south, east, north = (
            number(value, "Coverage bound", -limit, limit)
            for value, limit in zip(coverage, (180, 90, 180, 90))
        )
    except ValueError:
        return None
    return (west, south, east, north) if south <= north else None


def _contains(bounds, point):
    if bounds is None:
        return False
    west, south, east, north = bounds
    latitude, longitude = point
    # +180 and -180 describe the same meridian, including zero-width bounds.
    longitudes = (longitude, -longitude) if abs(longitude) == 180 else (longitude,)
    return south <= latitude <= north and any(
        west <= lon <= east if west <= east else lon >= west or lon <= east
        for lon in longitudes
    )


def _value(item, key, default=""):
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def _fold(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value)).lower()
                   if not unicodedata.category(c).startswith("M"))


def filter_maps(items, query="", kind="all", order="title", *, point=None):
    """Return original native assets or compatibility MapItems in display order."""
    if not isinstance(query, str) or len(query) > 300 or kind not in {"all", "mbtiles", "image"}:
        raise ValueError("Use a map filter of at most 300 characters and a supported format.")
    if order not in {"title", "smallest", "largest"}:
        raise ValueError("Choose title, smallest or largest map order.")
    if point is not None:
        point = validate_coordinates(point)
    terms, selected = _fold(query).split(), []
    for item in items:
        if point is not None and not _contains(coverage_bounds(item), point):
            continue
        format_ = _value(item, "format", _value(item, "kind"))
        family = "mbtiles" if format_ == "mbtiles" else "image"
        if kind != "all" and family != kind:
            continue
        haystack = _fold(" ".join(str(_value(item, key)) for key in ("title", "coverage", "filename", "source")) + " " + format_)
        if all(term in haystack for term in terms):
            selected.append(item)
    def key(item):
        size = _value(item, "bytes", _value(item, "size", 0))
        return (size if order == "smallest" else -size if order == "largest" else 0,
                _fold(_value(item, "title")), _value(item, "id"))
    return tuple(sorted(selected, key=key))
