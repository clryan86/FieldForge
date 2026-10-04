"""Compatibility entry points for the unified FieldForge map portal.

``python -m fieldforge.map_portal --config portal.json [--port 8765]`` runs
exactly the same server as ``python -m fieldforge.online.server``. Existing WSGI
hosts may keep ``create_app(config_path)``. Both legacy inline catalogs and the
new immutable catalog configuration use the same providers, validation, security
headers and browser UI. Legacy providers must explicitly include their license.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler

from fieldforge.online.models import validate_coordinates
from fieldforge.online.server import (
    Busy,
    PortalApplication,
    PortalConfig,
    PortalError,
    PortalResponse,
    WSGIApplication,
    _legacy_route,
    load_config,
    main,
    portal_assets,
)

__all__ = ["Busy", "Portal", "Provider", "QuietHandler", "create_app", "main"]


class Provider:
    """Original provider facade backed by the unified application's transport."""

    def __init__(self, config, kind):
        if kind not in {"geocoder", "router"}:
            raise ValueError("Provider kind must be geocoder or router.")
        self._app = PortalApplication(PortalConfig.from_dict({"version": 1, kind: config}))
        self.kind = kind
        self._kind = "geocoding" if kind == "geocoder" else "routing"

    @classmethod
    def _from_app(cls, app, kind):
        value = cls.__new__(cls)
        value._app, value._kind = app, kind
        value.kind = "geocoder" if kind == "geocoding" else "router"
        return value

    @property
    def config(self):
        return getattr(self._app.config, self._kind)

    @property
    def lock(self):
        return self._app._gates[self._kind].lock

    @property
    def url(self):
        return self.config.url

    @property
    def name(self):
        return self.config.name or self.config.source

    @property
    def attribution(self):
        return self.config.attribution

    @property
    def license(self):
        return self.config.license

    def search(self, query):
        if self._kind != "geocoding":
            raise ValueError("Address search requires a geocoder provider.")
        return self._app.search(query)["results"]

    def route(self, start, end):
        if self._kind != "routing":
            raise ValueError("Route planning requires a routing provider.")
        start, end = (dict(zip(("latitude", "longitude"), validate_coordinates(pair))) for pair in (start, end))
        routes = self._app.routes(start, end)["routes"]
        if not routes:
            raise PortalError(404, "no_route", "No driving route was returned for those coordinates.")
        return _legacy_route(routes[0])


class Portal(WSGIApplication):
    """Legacy WSGI constructor; source catalogs remain read-only and in place."""

    def __init__(self, config, *, folder=None):
        if not isinstance(config, PortalConfig):
            config = PortalConfig.from_dict(config)
        if folder is not None and config.legacy_maps is not None:
            config = replace(config, legacy_root=Path(folder).expanduser().resolve())
        super().__init__(config)

    @property
    def name(self):
        return self.app.config.name

    @property
    def geocoder(self):
        return Provider._from_app(self.app, "geocoding") if self.app.config.geocoding is not None else None

    @property
    def router(self):
        return Provider._from_app(self.app, "routing") if self.app.config.routing is not None else None

    @staticmethod
    def reply(start_response, status, payload, *, content_type="application/json; charset=utf-8", extra=()):
        """Preserve the original small response helper using shared headers."""
        code = int(status.split(" ", 1)[0])
        response = PortalResponse(code, payload, content_type) if isinstance(payload, bytes) else PortalResponse.json(code, payload)
        response.content_type = content_type
        response.extra_headers = tuple(extra)
        start_response(status, response.headers(portal_assets()[1]))
        return response


def create_app(config_path):
    return Portal(load_config(config_path))


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        return  # Request paths can contain provider queries in local test fixtures.


if __name__ == "__main__":
    raise SystemExit(main())
