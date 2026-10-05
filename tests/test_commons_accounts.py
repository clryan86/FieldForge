"""Account persistence, credential rotation and authorization regression tests."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_commons_chat

from fieldforge.online.accounts import AUTH_ACCOUNT_LIMIT, AUTH_WINDOW, AccountStore
from fieldforge.online.chat_store import SESSION_SECONDS, ChatError, ChatStore
from fieldforge.online.private_chat import PrivateChatStore

preview_server = test_commons_chat.preview_server
api = test_commons_chat.api
PASSWORD = "TEST only: river maple trail"
NEW_PASSWORD = "TEST only: another long passphrase"


@pytest.fixture
def store(tmp_path):
    now = [100_000.0]
    result = AccountStore(tmp_path / "accounts.sqlite3", clock=lambda: now[0])
    result.test_clock = now
    return result


def register(store, name="TestAlice", token=None):
    return store.account_register(name, PASSWORD, "navigation", token)


def assert_unauthorized(store, token):
    with pytest.raises(ChatError) as error:
        store.private_inbox(token)
    assert error.value.status == 401


def test_account_preserves_id_inbox_blocks_and_offline_invitations(store):
    alice, a = register(store)
    bob, b = register(store, "TestBob")
    store.leave(bob)
    thread = store.private_create(alice, "TEST supplies", "direct", [b["viewer"]["id"]], "a" * 32)["thread"]
    saved = store.private_send(alice, thread, "TEST saved letter", "saved", "b" * 32)["id"]
    reopened = AccountStore(store.path, clock=store.clock)
    bob, returning = reopened.account_login("testBOB", PASSWORD)
    assert returning["viewer"]["id"] == b["viewer"]["id"]
    assert returning["viewer"]["account"] is True
    assert reopened.private_inbox(bob)["threads"][0]["status"] == "invited"
    reopened.private_accept(bob, thread)
    assert reopened.private_read(bob, thread)["messages"][0]["body"] == "TEST saved letter"
    with pytest.raises(ChatError):
        reopened.private_delete(bob, thread, saved)
    reopened.block(bob, a["viewer"]["id"], True)
    reopened.leave(bob)
    bob, _ = reopened.account_login("TestBob", PASSWORD)
    assert reopened.read(bob, "general")["blocked"][0]["id"] == a["viewer"]["id"]
    assert reopened.private_read(bob, thread)["messages"] == []


def test_guest_upgrade_keeps_messages_and_rotates_session(store):
    guest, person = store.join("Guest", "food")
    store.send(guest, "general", "TEST guest note", "a" * 32)
    bob, member = store.join("Bob", "")
    thread = store.private_create(guest, "TEST guest thread", "direct", [member["id"]], "b" * 32)["thread"]
    token, data = register(store, token=guest)
    assert data["viewer"]["id"] == person["id"]
    assert data["viewer"]["name"] == "TestAlice"
    assert store.private_inbox(token)["threads"][0]["id"] == thread
    assert store.export(token)["messages"][0]["body"] == "TEST guest note"
    assert_unauthorized(store, guest)
    store.private_accept(bob, thread)
    assert store.private_read(bob, thread)["thread"]["participants"][1]["name"] == "TestAlice"
    with pytest.raises(ChatError):
        register(store, "AnotherAccount", token=token)


def test_expired_and_logged_out_account_name_cannot_be_reclaimed(store):
    old, data = register(store)
    store.test_clock[0] += SESSION_SECONDS
    assert_unauthorized(store, old)
    for _ in range(2):
        with pytest.raises(ChatError):
            store.join("testalice", "")
        with pytest.raises(ChatError):
            register(store, "testalice")
        new, result = store.account_login("TestAlice", PASSWORD)
        assert result["viewer"]["id"] == data["viewer"]["id"]
        store.leave(new)
    # An expired guest cannot claim its former participant id through registration.
    guest, member = store.join("Transient", "")
    store.leave(guest)
    _, registered = register(store, "Transient", guest)
    assert registered["viewer"]["id"] != member["id"]


def test_login_rotates_tokens_and_ends_previous_browser_session(store):
    first, data = register(store)
    second, again = store.account_login("TestAlice", PASSWORD)
    assert first != second and again["viewer"] == data["viewer"]
    assert_unauthorized(store, first)
    assert store.account_resume(second)["viewer"] == again["viewer"]
    other, _ = register(store, "TestBob")
    third, _ = store.account_login("TestAlice", PASSWORD, other)
    assert_unauthorized(store, second)
    assert_unauthorized(store, other)
    assert store.account_resume(third)["viewer"]["name"] == "TestAlice"


def test_recovery_replaces_code_password_and_revokes_session_without_signin(store):
    token, data = register(store)
    store.send(token, "general", "TEST survives recovery", "a" * 32)
    reset = store.account_recover("TestAlice", data["recovery_code"], NEW_PASSWORD)
    assert set(reset) == {"recovery_code"}
    assert reset["recovery_code"] != data["recovery_code"]
    assert_unauthorized(store, token)
    with pytest.raises(ChatError):
        store.account_login("TestAlice", PASSWORD)
    with pytest.raises(ChatError):
        store.account_recover("TestAlice", data["recovery_code"], PASSWORD)
    new, returning = store.account_login("TestAlice", NEW_PASSWORD)
    assert returning["viewer"]["id"] == data["viewer"]["id"]
    assert store.export(new)["messages"][0]["body"] == "TEST survives recovery"
    store.account_recover("TestAlice", reset["recovery_code"], PASSWORD)
    assert_unauthorized(store, new)


def test_password_update_requires_current_password_and_rotates_all_secrets(store):
    token, data = register(store)
    with pytest.raises(ChatError):
        store.account_change_password(token, NEW_PASSWORD, PASSWORD)
    assert store.account_resume(token)["viewer"]["account"]
    rotated, result = store.account_change_password(token, PASSWORD, NEW_PASSWORD)
    assert result["recovery_code"] != data["recovery_code"]
    assert_unauthorized(store, token)
    with pytest.raises(ChatError):
        store.account_recover("TestAlice", data["recovery_code"], PASSWORD)
    assert store.account_resume(rotated)["viewer"]["id"] == data["viewer"]["id"]
    guest, _ = store.join("Guest", "")
    with pytest.raises(ChatError) as error:
        store.account_change_password(guest, PASSWORD, NEW_PASSWORD)
    assert error.value.status == 403


def test_single_use_recovery_is_atomic_across_requests(store):
    _, data = register(store)
    def recover(_):
        try:
            return store.account_recover("TestAlice", data["recovery_code"], NEW_PASSWORD)
        except ChatError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(recover, range(2)))
    assert sum(isinstance(value, dict) for value in results) == 1
    assert 401 in results


def test_failed_credentials_are_generic_and_throttled_across_restart(store):
    register(store)
    messages = []
    for name in ("TestAlice", "UnknownAccount"):
        with pytest.raises(ChatError) as error:
            store.account_login(name, NEW_PASSWORD)
        messages.append(str(error.value))
    assert messages[0] == messages[1]
    # Registration and successful sign-ins also count; failures must not roll counters back.
    for _ in range(AUTH_ACCOUNT_LIMIT - 2):
        with pytest.raises(ChatError) as error:
            store.account_login("TestAlice", NEW_PASSWORD)
        assert error.value.status == 401
    reopened = AccountStore(store.path, clock=store.clock)
    with pytest.raises(ChatError) as error:
        reopened.account_login("TestAlice", PASSWORD)
    assert error.value.status == 429
    with pytest.raises(ChatError) as error:
        reopened.account_recover("TestAlice", "x" * 43, NEW_PASSWORD)
    assert error.value.status == 429
    store.test_clock[0] += AUTH_WINDOW
    assert reopened.account_login("TestAlice", PASSWORD)[1]["viewer"]["account"]


def test_global_limit_bounds_unknown_user_buckets_and_survives_restart(store, monkeypatch):
    monkeypatch.setattr("fieldforge.online.accounts.AUTH_GLOBAL_LIMIT", 3)
    for index in range(3):
        with pytest.raises(ChatError) as error:
            store.account_login(f"Unknown{index}", PASSWORD)
        assert error.value.status == 401
    reopened = AccountStore(store.path, clock=store.clock)
    with pytest.raises(ChatError) as error:
        reopened.account_login("AnotherUnknown", PASSWORD)
    assert error.value.status == 429
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM auth_attempts").fetchone()[0] == 4
    store.test_clock[0] += AUTH_WINDOW
    assert register(reopened)[1]["viewer"]["account"]


def test_simultaneous_registration_cannot_claim_same_username(store):
    def create(_):
        try:
            return register(store)
        except ChatError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert sum(isinstance(value, tuple) for value in results) == 1
    assert 409 in results
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1


def test_passwords_and_recovery_codes_are_not_stored_or_exported(store):
    token, data = register(store)
    _, second = register(store, "TestBob")
    with sqlite3.connect(store.path) as db:
        rows = db.execute("SELECT password_hash,recovery_hash FROM accounts").fetchall()
    assert rows[0][0].startswith("scrypt$32768$8$3$")
    assert rows[0][0] != rows[1][0]  # A fresh salt even for the same password.
    assert data["recovery_code"] != second["recovery_code"]
    raw_database = store.path.read_bytes()
    assert PASSWORD.encode() not in raw_database and data["recovery_code"].encode() not in raw_database
    for raw in [json.dumps(store.export(token)).encode(),
                json.dumps(store.private_export(token)).encode(), json.dumps(store.reports()).encode()]:
        assert PASSWORD.encode() not in raw
        assert data["recovery_code"].encode() not in raw
        assert rows[0][0].encode() not in raw


@pytest.mark.parametrize("username", ["ab", "a" * 33, "a b", "_user", "1user", "Кing", "King", "CLRYAN86", "admin", None])
def test_invalid_and_owner_names_cannot_register(store, username):
    with pytest.raises(ChatError) as error:
        register(store, username)
    assert error.value.status == 400


@pytest.mark.parametrize("password", ["x" * 14, "x" * 129, "\ud800" * 15, None, {}])
def test_invalid_passwords_rejected(store, password):
    with pytest.raises(ChatError) as error:
        store.account_register("TestAlice", password, "")
    assert error.value.status == 400


def test_password_whitespace_is_preserved(store):
    password = "  TEST spaces stay  "
    store.account_register("TestAlice", password, "")
    with pytest.raises(ChatError):
        store.account_login("TestAlice", password.strip())
    assert store.account_login("TestAlice", password)[1]["viewer"]["account"]


def test_upgrades_existing_database_without_losing_guest_or_private_history(tmp_path):
    path = tmp_path / "old.sqlite3"
    store = PrivateChatStore(path)
    alice, member = store.join("GuestAlice", "")
    bob, target = store.join("GuestBob", "")
    thread = store.private_create(alice, "TEST migration", "direct", [target["id"]], "a" * 32)["thread"]
    store.private_accept(bob, thread)
    store.private_send(alice, thread, "TEST old private message", "saved", "b" * 32)
    accounts = AccountStore(path)
    assert accounts.private_read(bob, thread)["messages"][0]["body"] == "TEST old private message"
    token, data = register(accounts, token=alice)
    assert data["viewer"]["id"] == member["id"]
    assert accounts.private_read(token, thread)["messages"][0]["own"] is True
    ChatStore(path)
    PrivateChatStore(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6


def test_account_http_protections_cookie_and_recovery(preview_server):
    payload = {"username": "TestAlice", "password": PASSWORD, "skill": "", "consent": True}
    path = "/api/commons/account/register"
    for options in ({"origin": False}, {"origin": "https://attacker.invalid"}, {"custom": False}):
        assert api(preview_server, path, payload, **options)[0] == 403
    assert api(preview_server, path, {**payload, "consent": False})[0] == 400
    assert api(preview_server, path, {**payload, "role": "admin"})[0] == 400
    status, headers, body = api(preview_server, path, payload)
    assert status == 200
    assert "no-store" in headers["Cache-Control"]
    assert "HttpOnly" in headers["Set-Cookie"] and "SameSite=Strict" in headers["Set-Cookie"]
    token = headers["Set-Cookie"].split(";", 1)[0].split("=", 1)[1]
    result = json.loads(body)
    assert api(preview_server, "/api/commons/account/resume", {"consent": True}, token=token)[0] == 200
    assert api(preview_server, "/api/commons/account/password", {"password": PASSWORD, "new_password": NEW_PASSWORD})[0] == 401
    status, headers, body = api(preview_server, "/api/commons/account/recover", {
        "username": "TestAlice", "recovery_code": result["recovery_code"], "new_password": NEW_PASSWORD, "consent": True})
    assert status == 200 and "Max-Age=0" in headers["Set-Cookie"]
    assert api(preview_server, "/api/commons/private/inbox", {}, token=token)[0] == 401
    assert api(preview_server, "/api/commons/account/login", {
        "username": "TestAlice", "password": NEW_PASSWORD, "consent": True})[0] == 200
