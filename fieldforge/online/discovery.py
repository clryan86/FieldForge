"""Filter the in-memory map catalog without making requests or changing entries."""

import unicodedata


def _value(item, key, default=""):
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def _fold(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value)).lower()
                   if not unicodedata.category(c).startswith("M"))


def filter_maps(items, query="", kind="all", order="title"):
    """Return original native assets or compatibility MapItems in display order."""
    if not isinstance(query, str) or len(query) > 300 or kind not in {"all", "mbtiles", "image"}:
        raise ValueError("Use a map filter of at most 300 characters and a supported format.")
    if order not in {"title", "smallest", "largest"}:
        raise ValueError("Choose title, smallest or largest map order.")
    terms, selected = _fold(query).split(), []
    for item in items:
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
