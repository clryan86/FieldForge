"""Legacy asset exports from the one primary FieldForge browser portal."""

from fieldforge.online.server import portal_assets

_assets, _policy = portal_assets()
HTML = _assets["/"][0].decode("utf-8")
SCRIPT = _assets["/portal.js"][0].decode("utf-8")
CSS = _assets["/portal.css"][0].decode("utf-8")

__all__ = ["HTML", "SCRIPT", "CSS"]
