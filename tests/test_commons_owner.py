"""Owner factor, privilege, moderation and credential-boundary regressions."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_commons_chat

from fieldforge.online.accounts import AUTH_WINDOW, AccountStore
from fieldforge.online.chat_store import ChatError
from fieldforge.online.owner import OWNER_SECONDS, OwnerStore
from fieldforge.online.owner_setup import setup_owner

pyotp = pytest.importorskip("pyotp", reason="Install the commons extra for owner MFA tests")
preview_server = test_commons_chat.preview_server
api = test_commons_chat.api
PASSWORD = "TEST owner only: a long passphrase"
NEW_PASSWORD = "TEST owner only: replacement phrase"


@pytest.fixture
def store(tmp_path):
    now = [100_000.0]
    result = OwnerStore(tmp_path / "owner.sqlite3", clock=lambda: now[0])
    result.test_clock = now
    result.test_secret = pyotp.random_base32()
    result.test_recovery = result.owner_bootstrap(PASSWORD, result.test_secret, pyotp.TOTP(result.test_secret).at(now[0]))["recovery_code"]
    return result


def code(store):
    return pyotp.TOTP(store.test_secret).at(store.clock())


def login(store):
    store.test_clock[0] += 30
    return store.owner_login("CLRYAN86", PASSWORD, code(store))[0]


def member(store, name="TEST_Alice"):
    return store.account_register(name, PASSWORD, "")


def test_only_one_owner_and_no_registration_or_password_only_bypass(store):
    with pytest.raises(ChatError) as error:
        store.owner_bootstrap(PASSWORD, pyotp.random_base32(), "123456")
    assert error.value.status in (401, 409)
    fresh = pyotp.random_base32()
    with pytest.raises(ChatError) as error:
        store.owner_bootstrap(PASSWORD, fresh, pyotp.TOTP(fresh).at(store.clock()))
    assert error.value.status == 409
    for username in ("CLRYAN86", "King", "admin"):
        with pytest.raises(ChatError):
            store.account_register(username, PASSWORD, "")
    with pytest.raises(ChatError) as error:
        store.account_login("CLRYAN86", PASSWORD)
    assert error.value.status == 403
    with pytest.raises(ChatError):
        store.account_recover("CLRYAN86", store.test_recovery, NEW_PASSWORD)
    owner = login(store)
    assert store.owner_dashboard(owner)["owner"]["name"] == "King"
    with pytest.raises(ChatError):
        store.account_change_password(owner, PASSWORD, NEW_PASSWORD)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM owner_config").fetchone()[0] == 1


def test_wrong_password_totp_replay_and_expired_steps_cannot_open_console(store):
    store.test_clock[0] += 30
    otp = code(store)
    with pytest.raises(ChatError):
        store.owner_login("CLRYAN86", NEW_PASSWORD, otp)
    token, _ = store.owner_login("CLRYAN86", PASSWORD, otp)
    with pytest.raises(ChatError):
        store.owner_login("CLRYAN86", PASSWORD, otp)
    assert store.owner_dashboard(token)
    store.test_clock[0] += 120
    with pytest.raises(ChatError):
        store.owner_login("CLRYAN86", PASSWORD, otp)
    reopened = OwnerStore(store.path, clock=store.clock)
    with pytest.raises(ChatError):
        reopened.owner_login("CLRYAN86", PASSWORD, otp)


def test_simultaneous_authenticator_replay_only_issues_one_session(store):
    store.test_clock[0] += 30
    otp = code(store)
    def attempt(_):
        try:
            return store.owner_login("CLRYAN86", PASSWORD, otp)
        except ChatError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(isinstance(value, tuple) for value in results) == 1
    assert 401 in results


def test_owner_grant_expiry_lock_and_normal_logout_revoke_access(store):
    token = login(store)
    store.test_clock[0] += OWNER_SECONDS
    with pytest.raises(ChatError) as error:
        store.owner_dashboard(token)
    assert error.value.status == 403
    assert store.read(token, "general")["viewer"]["name"] == "King"
    token = login(store)
    store.owner_lock(token)
    with pytest.raises(ChatError):
        store.owner_reports(token)
    assert store.account_resume(token)["viewer"]["name"] == "King"
    token = login(store)
    store.leave(token)
    with pytest.raises(ChatError) as error:
        store.owner_dashboard(token)
    assert error.value.status == 401


def test_every_owner_operation_rejects_regular_accounts_and_guests(store):
    regular, data = member(store)
    guest, _ = store.join("TEST guest", "")
    for token in (regular, guest, None):
        calls = [lambda: store.owner_dashboard(token), lambda: store.owner_members(token, "", 0),
                 lambda: store.owner_reports(token), lambda: store.owner_lock(token),
                 lambda: store.owner_control(token, data["viewer"]["id"], "suspend", "spam"),
                 lambda: store.owner_resolve(token, "public", 1, "remove", "spam"),
                 lambda: store.owner_password(token, PASSWORD, code(store), NEW_PASSWORD)]
        for call in calls:
            with pytest.raises(ChatError) as error:
                call()
            assert error.value.status in (401, 403)
    assert store.read(regular, "general")


def test_suspension_revokes_existing_session_blocks_login_contact_and_survives_restart(store):
    owner = login(store)
    alice, data = member(store)
    bob, _ = member(store, "TEST_Bob")
    target = data["viewer"]["id"]
    store.owner_control(owner, target, "suspend", "harassment")
    reopened = OwnerStore(store.path, clock=store.clock)
    for call in (lambda: reopened.private_inbox(alice), lambda: reopened.account_login("TEST_Alice", PASSWORD),
                 lambda: reopened.private_create(bob, "TEST invite", "direct", [target], "a" * 32)):
        with pytest.raises(ChatError):
            call()
    assert reopened.owner_members(owner, "TEST_Alice", 0)["members"][0]["suspended"]
    reopened.owner_control(owner, target, "restore", "other")
    with pytest.raises(ChatError):
        reopened.private_inbox(alice)  # Restoring never reactivates a revoked cookie.
    alice, returning = reopened.account_login("TEST_Alice", PASSWORD)
    assert returning["viewer"]["id"] == target
    reopened.owner_control(owner, target, "revoke", "other")
    with pytest.raises(ChatError):
        reopened.read(alice, "general")
    assert reopened.account_login("TEST_Alice", PASSWORD)
    events = [r["event"] for r in reopened.owner_dashboard(owner)["audit"]]
    assert events[:3] == ["revoke", "restore", "suspend"]


def test_owner_cannot_be_suspended_and_guest_revocation_does_not_restore_identity(store):
    owner = login(store)
    owner_id = store.owner_dashboard(owner)["owner"]["id"]
    for action in ("suspend", "restore", "revoke"):
        with pytest.raises(ChatError):
            store.owner_control(owner, owner_id, action, "other")
    guest, data = store.join("TEST Guest", "")
    store.owner_control(owner, data["id"], "suspend", "spam")
    store.owner_control(owner, data["id"], "restore", "other")
    with pytest.raises(ChatError):
        store.read(guest, "general")


def make_reports(store):
    alice, a = member(store)
    bob, b = member(store, "TEST_Bob")
    public = store.send(alice, "general", "TEST reported room text <b>literal</b>", "a" * 32)["id"]
    store.report(bob, public, "spam")
    thread = store.private_create(alice, "TEST private", "direct", [b["viewer"]["id"]], "b" * 32)["thread"]
    store.private_accept(bob, thread)
    store.test_clock[0] += 2
    private = store.private_send(alice, thread, "TEST reported saved private body", "saved", "c" * 32)["id"]
    store.private_report(bob, thread, private, "harassment")
    store.test_clock[0] += 2
    unreported = store.private_send(alice, thread, "TEST unreported private body", "saved", "d" * 32)["id"]
    store.test_clock[0] += 2
    once = store.private_send(alice, thread, "TEST never reveal this to moderation", "view_once", "e" * 32)["id"]
    store.private_report(bob, thread, once, "other")
    return alice, bob, thread, public, private, unreported, once


def test_only_reported_bodies_can_be_reviewed_open_once_body_never_leaks(store):
    owner = login(store)
    alice, bob, thread, public, private, unreported, once = make_reports(store)
    reports = store.owner_reports(owner)["reports"]
    rendered = json.dumps(reports)
    assert "reported saved private body" in rendered and "reported room text" in rendered
    assert "unreported private body" not in rendered and "never reveal" not in rendered
    assert next(r for r in reports if r["scope"] == "private" and r["message"] == once)["body"] == ""
    with pytest.raises(ChatError):
        store.owner_resolve(owner, "private", unreported, "remove", "spam")
    with pytest.raises(ChatError):
        store.private_read(owner, thread)  # Owner status is not membership in every private thread.
    store.owner_resolve(owner, "public", public, "dismiss", "other")
    assert store.read(bob, "general")["messages"][0]["body"]
    store.owner_resolve(owner, "public", public, "remove", "spam")
    assert store.read(bob, "general")["messages"][0]["body"] == ""
    store.owner_resolve(owner, "private", private, "remove", "harassment")
    store.owner_resolve(owner, "private", once, "remove", "unsafe")
    messages = store.private_read(bob, thread)["messages"]
    assert next(m for m in messages if m["id"] == private)["state"] == "moderated"
    with pytest.raises(ChatError):
        store.private_open_once(bob, thread, once)
    store.owner_resolve(owner, "private", private, "dismiss", "other")
    assert "reported saved private body" not in json.dumps(store.private_export(alice))
    assert "reported saved private body" not in json.dumps(store.owner_reports(owner))
    audit = json.dumps(store.owner_dashboard(owner)["audit"])
    assert "private:" in audit and "body" not in audit and "reported room text" not in audit


def test_owner_password_rotation_requires_fresh_code_and_revokes_all_old_access(store):
    owner = login(store)
    with pytest.raises(ChatError):
        store.owner_password(owner, PASSWORD, code(store), NEW_PASSWORD)
    store.test_clock[0] += 30
    new = store.owner_password(owner, PASSWORD, code(store), NEW_PASSWORD)
    assert new["recovery_code"] != store.test_recovery
    with pytest.raises(ChatError):
        store.owner_dashboard(owner)
    store.test_clock[0] += 30
    token, _ = store.owner_login("CLRYAN86", NEW_PASSWORD, code(store))
    assert store.owner_dashboard(token)
    secret = pyotp.random_base32()
    with pytest.raises(ChatError):
        store.owner_recover(store.test_recovery, PASSWORD, secret, pyotp.TOTP(secret).at(store.clock()))


def test_local_recovery_changes_both_factors_revokes_tokens_and_consumes_code(store):
    owner = login(store)
    secret = pyotp.random_base32()
    result = store.owner_recover(store.test_recovery, NEW_PASSWORD, secret, pyotp.TOTP(secret).at(store.clock()))
    with pytest.raises(ChatError):
        store.owner_dashboard(owner)
    with pytest.raises(ChatError):
        store.owner_recover(store.test_recovery, PASSWORD, secret, pyotp.TOTP(secret).at(store.clock()))
    store.test_clock[0] += 30
    with pytest.raises(ChatError):
        store.owner_login("CLRYAN86", NEW_PASSWORD, code(store))
    token, _ = store.owner_login("CLRYAN86", NEW_PASSWORD, pyotp.TOTP(secret).at(store.clock()))
    assert store.owner_dashboard(token)
    assert result["recovery_code"] != store.test_recovery
    for payload in [store.owner_dashboard(token), store.owner_members(token, "", 0), store.owner_reports(token), store.export(token)]:
        rendered = json.dumps(payload)
        for sensitive in (secret, result["recovery_code"], NEW_PASSWORD):
            assert sensitive not in rendered


def test_audit_is_bounded_and_member_pagination_search_is_safe(store, monkeypatch):
    monkeypatch.setattr("fieldforge.online.owner.MAX_AUDIT", 3)
    owner = login(store)
    for index in range(52):
        _, person = store.join(f"TEST Guest {index:02}", "")
        if index < 4:
            store.owner_control(owner, person["id"], "revoke", "other")
    assert len(store.owner_dashboard(owner)["audit"]) == 3
    assert len(store.owner_members(owner, "TEST Guest", 0)["members"]) == 50
    assert len(store.owner_members(owner, "TEST Guest", 50)["members"]) == 2
    assert store.owner_members(owner, "' OR 1=1 --", 0)["total"] == 0
    assert store.owner_members(owner, "CLRYAN86", 0)["members"][0]["owner"]


def test_rate_limits_owner_guesses_persist_and_migration_preserves_accounts(tmp_path):
    path = tmp_path / "migration.sqlite3"
    accounts = AccountStore(path)
    token, data = accounts.account_register("TEST_Migration", PASSWORD, "")
    store = OwnerStore(path)
    assert store.private_inbox(token)["contact_code"] == data["viewer"]["id"]
    for _ in range(8):
        with pytest.raises(ChatError) as error:
            store.owner_login("CLRYAN86", PASSWORD, "000000")
        assert error.value.status == 401
    reopened = OwnerStore(path)
    with pytest.raises(ChatError) as error:
        reopened.owner_login("CLRYAN86", PASSWORD, "000000")
    assert error.value.status == 429
    AccountStore(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4


def test_http_owner_requires_factors_consent_origin_and_never_exposes_setup(preview_server):
    store = preview_server.app.store
    now = [100_000.0]
    store.clock = lambda: now[0]
    secret = pyotp.random_base32()
    store.owner_bootstrap(PASSWORD, secret, pyotp.TOTP(secret).at(now[0]))
    now[0] += 30
    payload = {"username": "CLRYAN86", "password": PASSWORD, "code": pyotp.TOTP(secret).at(now[0]), "consent": True}
    for options in ({"origin": False}, {"origin": "https://attacker.invalid"}, {"custom": False}):
        assert api(preview_server, "/api/commons/owner/login", payload, **options)[0] == 403
    assert api(preview_server, "/api/commons/owner/login", {**payload, "consent": False})[0] == 400
    for name in ("setup", "bootstrap", "recover", "promote"):
        assert api(preview_server, "/api/commons/owner/" + name, {})[0] == 404
    assert api(preview_server, "/api/commons/owner/dashboard", {})[0] == 401
    status, headers, body = api(preview_server, "/api/commons/owner/login", payload)
    assert status == 200 and "no-store" in headers["Cache-Control"]
    assert secret.encode() not in body and PASSWORD.encode() not in body
    token = headers["Set-Cookie"].split(";", 1)[0].split("=", 1)[1]
    assert api(preview_server, "/api/commons/owner/dashboard", {}, token=token)[0] == 200
    assert api(preview_server, "/api/commons/owner/control", {"target": "a" * 24, "action": "suspend", "reason": "spam", "role": "owner"}, token=token)[0] == 400
    assert api(preview_server, "/api/commons/owner/lock", {}, token=token)[0] == 200
    assert api(preview_server, "/api/commons/owner/dashboard", {}, token=token)[0] == 403
    assert api(preview_server, "/commons-owner", method="GET")[0] == 200


def test_setup_requires_local_terminal_and_never_replaces_existing_owner(store, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(ChatError) as error:
        setup_owner(store)
    assert error.value.status == 400
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    with pytest.raises(ChatError) as error:
        setup_owner(store)
    assert error.value.status == 409


def test_wrong_recovery_cannot_change_factors(store):
    owner = login(store)
    secret = pyotp.random_base32()
    with pytest.raises(ChatError):
        store.owner_recover("wrong", NEW_PASSWORD, secret, pyotp.TOTP(secret).at(store.clock()))
    assert store.owner_dashboard(owner)
    store.test_clock[0] += AUTH_WINDOW
    assert login(store)


def test_interactive_setup_confirms_authenticator_before_creating_owner(tmp_path, monkeypatch, capsys):
    store = OwnerStore(tmp_path / "setup.sqlite3", clock=lambda: 100_000.0)
    secret = pyotp.random_base32()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr(pyotp, "random_base32", lambda: secret)
    prompts = iter([PASSWORD, PASSWORD, "wrong"])
    monkeypatch.setattr("fieldforge.online.owner_setup.getpass.getpass", lambda prompt: next(prompts))
    with pytest.raises(ChatError):
        setup_owner(store)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM owner_config").fetchone()[0] == 0
    prompts = iter([PASSWORD, PASSWORD, pyotp.TOTP(secret).at(store.clock())])
    setup_owner(store)
    output = capsys.readouterr().out
    assert PASSWORD not in output
    assert "Owner configured: CLRYAN86" in output and "has not started" in output
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM owner_config").fetchone()[0] == 1
