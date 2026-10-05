"""Run local Commons chat: python -m fieldforge.online.commons_preview --db chat.sqlite3.

This preview binds exclusively to 127.0.0.1. Do not forward it to a public host:
display names are unverified and there is no production account service.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from http.cookies import CookieError, SimpleCookie
from pathlib import Path

from fieldforge.online.chat_store import SESSION_SECONDS, ChatError, ChatStore
from fieldforge.online.community import CATEGORIES
from fieldforge.online.server import (
    PortalApplication,
    PortalConfig,
    PortalError,
    PortalHandler,
    PortalHTTPServer,
    PortalResponse,
    _check_request,
    _request_body,
)

COOKIE_NAME = "fieldforge_commons_preview"
API_ROOT = "/api/commons/"


def _cookie(token, *, clear=False):
    return (f"{COOKIE_NAME}={token}; Path=/api/commons; HttpOnly; SameSite=Strict; "
            f"Max-Age={0 if clear else SESSION_SECONDS}")


class PreviewHandler(PortalHandler):
    def _dispatch(self):
        if not self.path.startswith(API_ROOT):
            return super()._dispatch()
        app = self.server.app
        try:
            _check_request(app.config, self.server.server_address[1], self.path,
                           self.headers.get_all("Host", []), self.headers.get_all("Origin", []),
                           fetch_site=self.headers.get("Sec-Fetch-Site"),
                           transfer_encoding=bool(self.headers.get_all("Transfer-Encoding")))
            if (self.headers.get_all("X-FieldForge-Chat") != ["preview-v1"]
                    or self.command != "POST" or len(self.headers.get_all("Origin", [])) != 1):
                raise ChatError(403, "Use the local chat page to access this preview.")
            payload = _request_body(self.rfile, self.headers.get_all("Content-Length", []),
                                    self.headers.get_all("Content-Type", []))
            cookies = SimpleCookie()
            if len(self.headers.get_all("Cookie", [])) > 1:
                raise ChatError(400, "Invalid preview cookie.")
            cookies.load(self.headers.get("Cookie", ""))
            token = cookies[COOKIE_NAME].value if COOKIE_NAME in cookies else None
            response = app.chat_response(self.path, payload, token)
        except ChatError as exc:
            self.close_connection = True
            response = PortalResponse.error(PortalError(exc.status, "chat_error", str(exc)))
        except CookieError:
            self.close_connection = True
            response = PortalResponse.error(PortalError(400, "chat_error", "Invalid preview cookie."))
        except sqlite3.Error:
            self.close_connection = True
            response = PortalResponse.error(PortalError(503, "chat_error", "Chat storage is unavailable. Try again."))
        self._send(response)


class PreviewApplication(PortalApplication):
    def __init__(self, store):
        super().__init__(PortalConfig())
        self.store = store
        root = Path(__file__).parent
        for path, filename, mime in (
            ("/commons", "commons.html", "text/html; charset=utf-8"),
            ("/commons.js", "commons.js", "text/javascript; charset=utf-8"),
            ("/commons.css", "commons.css", "text/css; charset=utf-8"),
        ):
            self.assets[path] = ((root / filename).read_bytes(), mime)
        data, mime = self.assets["/commons"]
        options = "".join(f'<option value="{item.id}">{item.label}</option>' for item in CATEGORIES)
        self.assets["/commons"] = (data.replace(b"<!-- SKILL_OPTIONS -->", options.encode()), mime)
        page, mime = self.assets["/"]
        entry = (b'<section class="card connection-panel" aria-label="Commons chat preview">'
                 b'<h2>Try FieldForge Commons chat</h2><p>A working local chat preview with '
                 b'shared rooms and saved messages. Test with two separate browser profiles.</p>'
                 b'<a class="button" href="/commons">Open local chat preview</a>'
                 b'<p class="hint">Local preview only. Public accounts and membership are not active.</p></section>')
        page = page.replace(
            b'No account, profile photo, public directory, chat or encrypted messaging is active here.',
            b'Public accounts, profile photos, a public directory and encrypted messaging are not active. '
            b'Use the local chat preview button above to test shared rooms on this computer.')
        self.assets["/"] = (page.replace(b"<main>", b"<main>" + entry, 1), mime)

    def chat_response(self, path, payload, token):
        name = path.removeprefix(API_ROOT)
        schemas = {"join": {"name", "skill", "consent"}, "read": {"room"},
                   "send": {"room", "body", "request_id"}, "delete": {"message"},
                   "block": {"target", "blocked"}, "report": {"message", "reason"},
                   "export": set(), "leave": set()}
        if name not in schemas:
            raise ChatError(404, "Chat endpoint not found.")
        if set(payload) != schemas[name]:
            raise ChatError(400, "Unsupported chat request fields.")
        result = {"ok": True}
        cookie = None
        if name == "join":
            if payload["consent"] is not True:
                raise ChatError(400, "Confirm local message storage before joining.")
            token, viewer = self.store.join(payload["name"], payload["skill"], token)
            result = {"viewer": viewer}
            cookie = _cookie(token)
        elif name == "read":
            result = self.store.read(token, payload["room"])
        elif name == "send":
            result = self.store.send(token, **payload)
        elif name == "delete":
            self.store.delete(token, **payload)
        elif name == "block":
            self.store.block(token, **payload)
        elif name == "report":
            self.store.report(token, **payload)
        elif name == "export":
            result = self.store.export(token)
        elif name == "leave":
            self.store.leave(token)
            cookie = _cookie("", clear=True)
        response = PortalResponse.json(200, result)
        if cookie:
            response.extra_headers = (("Set-Cookie", cookie),)
        return response


def make_preview_server(database, port=8765):
    server = PortalHTTPServer(("127.0.0.1", port), PreviewApplication(ChatStore(database)))
    server.RequestHandlerClass = PreviewHandler
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="Local SQLite chat database (outside the source tree).")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--review-reports", action="store_true", help="Print local reports as JSON without starting a server.")
    args = parser.parse_args(argv)
    try:
        if not 0 <= args.port <= 65535:
            raise ValueError("Port must be between 0 and 65535.")
        if args.review_reports:
            if not args.db.is_file():
                raise ValueError("Choose an existing Commons preview database to review reports.")
            print(json.dumps(ChatStore(args.db).reports(), ensure_ascii=False, indent=2))
            return 0
        server = make_preview_server(args.db, args.port)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(2, f"Cannot start Commons preview: {exc}\n")
    print(f"Local Commons preview: http://127.0.0.1:{server.server_address[1]}/commons", flush=True)
    print("Local, unverified preview identities. Do not expose this server to the internet.", flush=True)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
