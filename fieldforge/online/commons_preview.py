"""Run local Commons chat: python -m fieldforge.online.commons_preview --db chat.sqlite3.

This preview binds exclusively to 127.0.0.1. Do not forward it to a public host:
local accounts are not verified identities and there is no production account service.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from http.cookies import CookieError, SimpleCookie
from pathlib import Path

from fieldforge.online.account_lifecycle import AccountLifecycleStore
from fieldforge.online.chat_store import SESSION_SECONDS, ChatError
from fieldforge.online.community import CATEGORIES
from fieldforge.online.owner import OwnerStore
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
PHOTO_REQUEST_BYTES = ((1024 * 1024 + 2) // 3) * 4 + 256


def _cookie(token):
    return (f"{COOKIE_NAME}={token}; Path=/api/commons; HttpOnly; SameSite=Strict; "
            f"Max-Age={SESSION_SECONDS}")


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
            # Preserve small API limits while allowing bounded photo bytes and a fully
            # JSON-escaped, 500-character Unicode biography with its questionnaire.
            body_limit = {API_ROOT + "profile/photo/upload": PHOTO_REQUEST_BYTES,
                          API_ROOT + "profile/save": 8192}.get(self.path, 4096)
            payload = _request_body(self.rfile, self.headers.get_all("Content-Length", []),
                                    self.headers.get_all("Content-Type", []), maximum=body_limit)
            cookies = SimpleCookie()
            if len(self.headers.get_all("Cookie", [])) > 1:
                raise ChatError(400, "Invalid preview cookie.")
            cookies.load(self.headers.get("Cookie", ""))
            token = cookies[COOKIE_NAME].value if COOKIE_NAME in cookies else None
            expected = self.headers.get_all("X-FieldForge-Participant", [])
            if expected:
                if (len(expected) != 1 or not re.fullmatch(r"[a-f0-9]{24}", expected[0])
                        or app.store.account_resume(token)["viewer"]["id"] != expected[0]):
                    raise ChatError(401, "The account in this browser changed. Resume the current session when ready.")
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
        # Profile images are sanitized PNG data, fetched through the authenticated API.
        self.csp = self.csp.replace("img-src 'self' blob:", "img-src 'self' blob: data:")
        root = Path(__file__).parent
        for path, filename, mime in (
            ("/commons", "commons.html", "text/html; charset=utf-8"),
            ("/commons.js", "commons.js", "text/javascript; charset=utf-8"),
            ("/commons.css", "commons.css", "text/css; charset=utf-8"),
            ("/commons-private.js", "commons-private.js", "text/javascript; charset=utf-8"),
            ("/commons-search.js", "commons-search.js", "text/javascript; charset=utf-8"),
            ("/commons-accounts.js", "commons-accounts.js", "text/javascript; charset=utf-8"),
            ("/commons-profiles.js", "commons-profiles.js", "text/javascript; charset=utf-8"),
            ("/commons-owner", "commons-owner.html", "text/html; charset=utf-8"),
            ("/commons-owner.js", "commons-owner.js", "text/javascript; charset=utf-8"),
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
                 b'<p class="hint">Local accounts can keep your inbox across sessions. Public membership is not active.</p></section>')
        page = page.replace(
            b'No account, profile photo, public directory, chat or encrypted messaging is active here.',
            b'Public accounts, an internet-wide directory and encrypted messaging are not active. '
            b'Use the local chat preview button above to try shared rooms and optional profiles on this computer.')
        self.assets["/"] = (page.replace(b"<main>", b"<main>" + entry, 1), mime)

    def chat_response(self, path, payload, token):
        name = path.removeprefix(API_ROOT)
        schemas = {"join": {"name", "skill", "consent"}, "read": {"room"},
                   "send": {"room", "body", "request_id"}, "delete": {"message"},
                   "block": {"target", "blocked"}, "report": {"message", "reason"},
                   "export": set(), "leave": set(), "private/inbox": set(),
                   "private/create": {"title", "kind", "contacts", "request_id"},
                   "private/accept": {"thread"}, "private/read": {"thread"},
                   "private/search": {"query"},
                   "private/send": {"thread", "body", "lifetime", "request_id"},
                   "private/open": {"thread", "message"}, "private/delete": {"thread", "message"},
                   "private/leave": {"thread"}, "private/export": set(),
                   "private/report": {"thread", "message", "reason"},
                   "account/register": {"username", "password", "skill", "consent"},
                   "account/login": {"username", "password", "consent"},
                   "account/resume": {"consent"},
                   "account/recover": {"username", "recovery_code", "new_password", "consent"},
                   "account/password": {"password", "new_password"},
                   "account/export": {"password"},
                   "account/export/page": {"export_token", "section", "after"},
                   "account/export/finish": {"export_token"},
                   "account/close": {"password", "username", "confirm"},
                   "profile/get": set(), "profile/save": {"profile", "revision"},
                   "profile/photo/upload": {"encoded", "revision"},
                   "profile/photo/remove": {"revision"}, "profile/photo/read": {"asset_id"},
                   "profile/delete": {"revision"}, "profile/export": set(),
                   "profile/directory": {"query", "category", "offset"},
                   "profile/block": {"profile_id"},
                   "profile/invite": {"profile_id", "title", "request_id"},
                   "owner/login": {"username", "password", "code", "consent"},
                   "owner/dashboard": set(), "owner/reports": set(), "owner/lock": set(),
                   "owner/members": {"query", "offset"},
                   "owner/control": {"target", "action", "reason"},
                   "owner/resolve": {"scope", "message", "action", "reason"},
                   "owner/password": {"password", "code", "new_password"}}
        if name not in schemas:
            raise ChatError(404, "Chat endpoint not found.")
        optional = {"private/read": {"before"}, "private/search": {"thread", "before"}}.get(name, set())
        if not schemas[name] <= set(payload) or not set(payload) <= schemas[name] | optional:
            raise ChatError(400, "Unsupported chat request fields.")
        result = {"ok": True}
        cookie = None
        if name.startswith("owner/"):
            if name == "owner/login":
                fields = dict(payload)
                if fields.pop("consent") is not True:
                    raise ChatError(400, "Confirm connection to the local owner console.")
                token, result = self.store.owner_login(token=token, **fields)
                cookie = _cookie(token)
            else:
                methods = {"dashboard": self.store.owner_dashboard, "members": self.store.owner_members,
                           "reports": self.store.owner_reports, "control": self.store.owner_control,
                           "resolve": self.store.owner_resolve, "lock": self.store.owner_lock,
                           "password": self.store.owner_password}
                result = methods[name.split("/")[1]](token, **payload) or {"ok": True}
        elif name.startswith("profile/"):
            methods = {"get": self.store.profile_get, "save": self.store.profile_save,
                       "photo/upload": self.store.profile_photo_upload,
                       "photo/remove": self.store.profile_photo_remove,
                       "photo/read": self.store.profile_photo_read, "delete": self.store.profile_delete,
                       "export": self.store.profile_export, "directory": self.store.profile_directory,
                       "block": self.store.profile_block, "invite": self.store.profile_invite}
            result = methods[name.removeprefix("profile/")](token, **payload)
        elif name.startswith("account/"):
            fields = dict(payload)
            if name in {"account/register", "account/login", "account/recover", "account/resume"} and fields.pop("consent") is not True:
                raise ChatError(400, "Confirm local account and message storage before continuing.")
            lifecycle = {"account/export": self.store.account_export,
                         "account/export/page": self.store.account_export_page,
                         "account/export/finish": self.store.account_export_finish,
                         "account/close": self.store.account_close}
            if name in lifecycle:
                result = lifecycle[name](token, **fields)
            elif name == "account/resume":
                result = self.store.account_resume(token)
            elif name == "account/recover":
                result = self.store.account_recover(**fields)
            else:
                methods = {"register": self.store.account_register, "login": self.store.account_login,
                           "password": self.store.account_change_password}
                token, result = methods[name.split("/")[1]](token=token, **fields)
                cookie = _cookie(token)
        elif name.startswith("private/"):
            methods = {"inbox": self.store.private_inbox, "create": self.store.private_create,
                       "accept": self.store.private_accept, "read": self.store.private_read,
                       "search": self.store.private_search,
                       "send": self.store.private_send, "open": self.store.private_open_once,
                       "delete": self.store.private_delete, "leave": self.store.private_leave,
                       "export": self.store.private_export, "report": self.store.private_report}
            result = methods[name.split("/")[1]](token, **payload) or {"ok": True}
        elif name == "join":
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
        response = PortalResponse.json(200, result)
        # Session revocation (leave, recovery, owner password change or closure)
        # intentionally has no Set-Cookie: a delayed response cannot delete the
        # browser's newer sign-in. The old token is already invalid server-side.
        if cookie:
            response.extra_headers = (("Set-Cookie", cookie),)
        return response


class CommonsPreviewServer(PortalHTTPServer):
    _last_expiry = 0.0

    def service_actions(self):
        # Expire unclaimed bodies even when nobody is polling a room.
        if time.monotonic() - self._last_expiry >= 60:
            try:
                self.app.store.expire_private_messages()
            except (OSError, sqlite3.Error):
                return  # Requests also check expiry; retry this sweep on the next loop.
            self._last_expiry = time.monotonic()


def make_preview_server(database, port=8765):
    server = CommonsPreviewServer(("127.0.0.1", port), PreviewApplication(AccountLifecycleStore(database)))
    server.RequestHandlerClass = PreviewHandler
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="Local SQLite chat database (outside the source tree).")
    parser.add_argument("--port", default=8765, type=int)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--review-reports", action="store_true", help="Print local reports as JSON without starting a server.")
    action.add_argument("--init-owner", action="store_true", help="Set up the sole owner interactively, without starting the server.")
    action.add_argument("--recover-owner", action="store_true", help="Reset owner factors using the saved recovery code in a local terminal.")
    args = parser.parse_args(argv)
    try:
        if not 0 <= args.port <= 65535:
            raise ValueError("Port must be between 0 and 65535.")
        if args.init_owner or args.recover_owner:
            from fieldforge.online.owner_setup import setup_owner

            setup_owner(OwnerStore(args.db), recover=args.recover_owner)
            return 0
        if args.review_reports:
            if not args.db.is_file():
                raise ValueError("Choose an existing Commons preview database to review reports.")
            print(json.dumps(OwnerStore(args.db).reports(), ensure_ascii=False, indent=2))
            return 0
        server = make_preview_server(args.db, args.port)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(2, f"Cannot start Commons preview: {exc}\n")
    print(f"Local Commons preview: http://127.0.0.1:{server.server_address[1]}/commons", flush=True)
    print("Local accounts and guest sessions. Do not expose this server to the internet.", flush=True)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
