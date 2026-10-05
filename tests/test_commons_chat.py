"""Exercise real chat persistence, ownership, session boundaries and HTTP controls."""

import http.client
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from fieldforge.online.chat_store import SESSION_SECONDS, ChatError, ChatStore
from fieldforge.online.commons_preview import COOKIE_NAME, make_preview_server
from fieldforge.online.server import PortalApplication, PortalConfig, PortalError


@pytest.fixture
def store(tmp_path):
    now = [1000.0]
    result = ChatStore(tmp_path / "chat.sqlite3", clock=lambda: now[0])
    result.test_clock = now
    return result


def send(store, token, body="Hello", *, room="general", key="a" * 32):
    return store.send(token, room, body, key)


def test_two_participants_persist_messages_and_never_return_session_secrets(store):
    alice, member = store.join("Alice", "medical")
    bob, _ = store.join("Bob", "")
    send(store, alice)
    data = ChatStore(store.path, clock=store.clock).read(bob, "general")
    assert data["messages"][0]["body"] == "Hello"
    assert data["messages"][0]["author"] == member["id"]
    assert data["messages"][0]["skill"] == "MED"
    assert not data["messages"][0]["own"]
    assert alice not in json.dumps(data)
    assert alice.encode() not in store.path.read_bytes()
    assert "token_hash" not in json.dumps(data)


def test_refuses_unrelated_database_without_changing_its_contents(tmp_path):
    path = tmp_path / "other.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE household (name TEXT)")
        db.execute("INSERT INTO household VALUES('Keep me')")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="separate Commons"):
        ChatStore(path)
    assert path.read_bytes() == before


def test_skills_names_and_rooms_cannot_create_admin_privileges(store):
    for name in ("CLRYAN86", "King", "ADMIN"):
        with pytest.raises(ChatError):
            store.join(name, "")
    for skill in ("owner", ["medical"], True):
        with pytest.raises(ChatError):
            store.join("Alice", skill)
    token, member = store.join("Alice", "medical")
    assert member["identity"] == "unverified preview name"
    assert "role" not in member
    for room in ("unknown", ["general"], None):
        with pytest.raises(ChatError):
            store.read(token, room)


def test_duplicate_names_and_session_reuse_are_explicit(store):
    token, member = store.join("Alice", "")
    with pytest.raises(ChatError, match="in use"):
        store.join("alice", "medical")
    assert store.join("Another name", "food", token) == (token, member)


def test_send_is_idempotent_and_rate_limited_even_after_delete(store):
    token, _ = store.join("Alice", "")
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(lambda _: send(store, token), range(2)))
    assert results[0]["id"] == results[1]["id"]
    assert {result["duplicate"] for result in results} == {True, False}
    with pytest.raises(ChatError, match="different message"):
        send(store, token, "Changed content")
    store.delete(token, results[0]["id"])
    with pytest.raises(ChatError) as error:
        send(store, token, key="b" * 32)
    assert error.value.status == 429
    store.test_clock[0] += 2
    send(store, token, "New message", key="b" * 32)
    assert len(store.read(token, "general")["messages"]) == 2


def test_owner_delete_block_unblock_and_report_are_persistent(store):
    alice, member = store.join("Alice", "")
    bob, _ = store.join("Bob", "")
    message = send(store, alice)["id"]
    with pytest.raises(ChatError) as error:
        store.delete(bob, message)
    assert error.value.status == 403
    store.report(bob, message, "spam")
    store.report(bob, message, "unsafe")
    assert len(store.reports()) == 1
    assert store.reports()[0]["reason"] == "unsafe"
    store.block(bob, member["id"], True)
    reopened = ChatStore(store.path, clock=store.clock)
    assert reopened.read(bob, "general")["messages"] == []
    assert reopened.read(bob, "general")["blocked"][0]["name"] == "Alice"
    reopened.block(bob, member["id"], False)
    assert len(reopened.read(bob, "general")["messages"]) == 1
    reopened.delete(alice, message)
    data = reopened.read(bob, "general")["messages"][0]
    assert data["body"] == "" and data["deleted"] is True
    assert reopened.export(alice)["messages"] == []
    assert reopened.reports()[0]["body"] == ""


def test_export_includes_only_own_retained_messages(store):
    alice, _ = store.join("Alice", "")
    bob, _ = store.join("Bob", "")
    send(store, alice, "Alice's note", room="navigation")
    send(store, bob, "Bob's note")
    result = store.export(alice)
    assert [message["body"] for message in result["messages"]] == ["Alice's note"]
    assert "Bob" not in json.dumps(result)
    assert "token" not in json.dumps(result)


def test_logout_expiry_and_old_session_cannot_be_reactivated(store):
    token, member = store.join("Alice", "")
    store.leave(token)
    with pytest.raises(ChatError) as error:
        store.read(token, "general")
    assert error.value.status == 401
    replacement, new_member = store.join("Alice", "", token)
    assert replacement != token and new_member["id"] != member["id"]
    store.test_clock[0] += SESSION_SECONDS
    with pytest.raises(ChatError):
        send(store, replacement)


@pytest.mark.parametrize("body", ["", " \n ", "x" * 1001, "😀" * 501, "a\x00b", "a\u202eb", None, {}])
def test_rejects_empty_oversize_controls_and_nontext_messages(store, body):
    token, _ = store.join("Alice", "")
    with pytest.raises(ChatError):
        send(store, token, body)


def test_room_retention_and_latest_window_are_bounded(store, monkeypatch):
    monkeypatch.setattr("fieldforge.online.chat_store.MAX_ROOM_MESSAGES", 105)
    token, _ = store.join("Alice", "")
    for index in range(110):
        store.test_clock[0] += 2
        send(store, token, str(index), key=f"{index:032x}")
    assert len(store.export(token)["messages"]) == 105
    messages = store.read(token, "general")["messages"]
    assert len(messages) == 100
    assert [messages[0]["body"], messages[-1]["body"]] == ["10", "109"]


@pytest.fixture
def preview_server(tmp_path):
    server = make_preview_server(tmp_path / "preview.sqlite3", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def api(server, path, data=None, *, token=None, origin=True, custom=True, method="POST"):
    host = f"127.0.0.1:{server.server_address[1]}"
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = "http://" + host if origin is True else origin
    if custom:
        headers["X-FieldForge-Chat"] = "preview-v1"
    if token:
        headers["Cookie"] = f"{COOKIE_NAME}={token}"
    connection = http.client.HTTPConnection(host, timeout=5)
    connection.request(method, path, json.dumps(data) if data is not None else None, headers)
    response = connection.getresponse()
    body = response.read()
    result = response.status, dict(response.getheaders()), body
    connection.close()
    return result


def test_http_requires_consent_origin_custom_header_and_session(preview_server):
    data = {"name": "Alice", "skill": "", "consent": True}
    for options in ({"origin": False}, {"origin": "https://attacker.invalid"}, {"custom": False}):
        assert api(preview_server, "/api/commons/join", data, **options)[0] == 403
    assert api(preview_server, "/api/commons/join", {**data, "consent": False})[0] == 400
    assert api(preview_server, "/api/commons/join", {**data, "role": "admin"})[0] == 400
    assert api(preview_server, "/api/commons/read", {"room": "general"})[0] == 401
    status, headers, _ = api(preview_server, "/api/commons/join", data)
    assert status == 200
    cookie = headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    token = cookie.split(";", 1)[0].split("=", 1)[1]
    assert api(preview_server, "/api/commons/read", {"room": "general"}, token=token)[0] == 200
    assert api(preview_server, "/api/commons/leave", {}, token=token)[0] == 200
    assert api(preview_server, "/api/commons/read", {"room": "general"}, token=token)[0] == 401
    assert api(preview_server, "/api/commons/reports", {}, token=token)[0] == 404


def test_preview_links_assets_and_production_portal_separation(preview_server):
    assert preview_server.server_address[0] == "127.0.0.1"
    status, headers, body = api(preview_server, "/", method="GET")
    assert status == 200 and b'Open local chat preview' in body
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    for path, mime in (("/commons", "text/html"), ("/commons.js", "text/javascript"), ("/commons.css", "text/css")):
        status, headers, body = api(preview_server, path, method="GET")
        assert status == 200 and headers["Content-Type"].startswith(mime) and body
    status, _, body = api(preview_server, "/api/v1/status", method="GET")
    assert status == 200 and not json.loads(body)["geocoding"]
    with pytest.raises(PortalError) as error:
        PortalApplication(PortalConfig()).dispatch("GET", "/commons")
    assert error.value.status == 404
