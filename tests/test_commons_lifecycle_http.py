"""Account export and closure across the real Commons HTTP trust boundary."""

import base64
import http.client
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_commons_chat

from fieldforge.online.chat_store import ROOMS, SESSION_SECONDS
from fieldforge.online.commons_preview import COOKIE_NAME

preview_server = test_commons_chat.preview_server
PASSWORD = "TEST lifecycle only: silver river trail"
OTHER_PASSWORD = "TEST lifecycle only: another long phrase"
SECTIONS = ("public_messages", "private_messages", "public_reports", "private_reports")
PROFILE_FIELDS = {"display_name", "bio", "visibility", "share_skills", "share_photo", "assessment"}
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGgAAACEAIHJde6SAAAAAElFTkSuQmCC"
)


def account(server, name="TEST_Alice", password=PASSWORD):
    store = server.app.store
    if not hasattr(store, "test_clock"):
        store.test_clock = [1_900_000_000.0]
        store.clock = lambda: store.test_clock[0]
    token, result = store.account_register(name, password, "navigation")
    return {**result["viewer"], "token": token, "password": password, "recovery_code": result["recovery_code"]}


def request(server, endpoint, payload, person=None, *, participant=None, origin=True, custom=True, method="POST"):
    host = f"127.0.0.1:{server.server_address[1]}"
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = "http://" + host if origin is True else origin
    if custom:
        headers["X-FieldForge-Chat"] = "preview-v1"
    if person:
        headers["Cookie"] = f"{COOKIE_NAME}={person['token']}"
    if participant is not None:
        headers["X-FieldForge-Participant"] = participant
    connection = http.client.HTTPConnection(host, timeout=10)
    try:
        connection.request(method, "/api/commons/" + endpoint, json.dumps(payload), headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), json.loads(response.read())
    finally:
        connection.close()


def start_export(server, person):
    status, headers, result = request(server, "account/export", {"password": person["password"]}, person,
                                      participant=person["id"])
    assert status == 200, result
    assert headers["Cache-Control"] == "no-store"
    return result


def export_records(server, person, grant, section):
    after = 0
    records = []
    while True:
        status, headers, result = request(server, "account/export/page", {
            "export_token": grant, "section": section, "after": after,
        }, person, participant=person["id"])
        assert status == 200, result
        assert headers["Cache-Control"] == "no-store"
        assert int(headers["Content-Length"]) < 8 * 1024**2
        assert result["section"] == section
        assert len(result["records"]) <= 500
        records.extend(result["records"])
        if result["next_after"] is None:
            return records
        assert result["next_after"] > after
        after = result["next_after"]


def close_payload(person):
    return {"password": person["password"], "username": person["username"], "confirm": True}


def lifecycle_requests(person, grant):
    return (
        ("account/export", {"password": person["password"]}),
        ("account/export/page", {"export_token": grant, "section": "public_messages", "after": 0}),
        ("account/export/finish", {"export_token": grant}),
        ("account/close", close_payload(person)),
    )


def test_http_lifecycle_requires_origin_custom_header_post_and_exact_fields(preview_server):
    alice = account(preview_server)
    grant = start_export(preview_server, alice)["export_token"]
    for endpoint, payload in lifecycle_requests(alice, grant):
        for options in ({"origin": False}, {"origin": "https://attacker.invalid"},
                        {"custom": False}, {"method": "GET"}):
            assert request(preview_server, endpoint, payload, alice, **options)[0] == 403
        assert request(preview_server, endpoint, {**payload, "participant": alice["id"]}, alice)[0] == 400
        if payload:
            assert request(preview_server, endpoint, {}, alice)[0] == 400
    assert preview_server.app.store.account_resume(alice["token"])["viewer"]["id"] == alice["id"]


@pytest.mark.parametrize("state", ["missing", "guest", "expired", "revoked", "suspended"])
def test_http_lifecycle_requires_a_current_saved_account(preview_server, state):
    alice = account(preview_server)
    store = preview_server.app.store
    grant = start_export(preview_server, alice)["export_token"]
    caller = alice
    expected = 401
    if state == "missing":
        caller = None
    elif state == "guest":
        token, viewer = store.join("TEST lifecycle guest", "")
        caller = {**viewer, "token": token}
        expected = 403
    elif state == "expired":
        store.test_clock[0] += SESSION_SECONDS
    elif state == "revoked":
        store.leave(alice["token"])
    else:
        with store._db() as db:
            db.execute("INSERT INTO participant_controls VALUES(?,?,?,?)",
                       (alice["id"], 1, "TEST suspension", store.clock()))
    for endpoint, payload in lifecycle_requests(alice, grant):
        assert request(preview_server, endpoint, payload, caller)[0] == expected
    with store._db() as db:
        assert db.execute("SELECT 1 FROM accounts WHERE participant=?", (alice["id"],)).fetchone()


def test_http_account_switch_cannot_export_or_close_the_new_cookie_owner(preview_server):
    alice = account(preview_server)
    bob = account(preview_server, "TEST_Bob", OTHER_PASSWORD)
    grant = start_export(preview_server, alice)["export_token"]
    for endpoint, payload in lifecycle_requests(alice, grant):
        status, _, body = request(preview_server, endpoint, payload, bob, participant=alice["id"])
        assert status == 401
        assert "manifest" not in body and "records" not in body
    for person in (alice, bob):
        assert preview_server.app.store.account_resume(person["token"])["viewer"]["id"] == person["id"]
    # Even without the browser binding, Alice's grant cannot authorize Bob's session.
    payload = {"export_token": grant, "section": "public_messages", "after": 0}
    assert request(preview_server, "account/export/page", payload, bob)[0] == 410
    assert request(preview_server, "account/export/finish", {"export_token": grant}, bob)[0] == 410
    assert request(preview_server, "account/export/page", payload, alice, participant=alice["id"])[0] == 200


@pytest.mark.parametrize("endpoint", ["account/export", "account/close"])
def test_http_current_password_failure_is_forbidden_without_revoking_the_session(preview_server, endpoint):
    alice = account(preview_server)
    payload = {"password": OTHER_PASSWORD} if endpoint.endswith("export") else {
        **close_payload(alice), "password": OTHER_PASSWORD,
    }
    status, headers, result = request(preview_server, endpoint, payload, alice, participant=alice["id"])
    assert status == 403 and "Set-Cookie" not in headers
    assert "manifest" not in result and "closed" not in result
    assert preview_server.app.store.account_resume(alice["token"])["viewer"]["id"] == alice["id"]


@pytest.mark.parametrize("changes", [
    {"username": "TEST_someone_else"}, {"username": None}, {"username": []},
    {"confirm": False}, {"confirm": 1}, {"confirm": "true"},
])
def test_http_close_requires_own_typed_username_and_exact_confirmation(preview_server, changes):
    alice = account(preview_server)
    assert request(preview_server, "account/close", {**close_payload(alice), **changes}, alice)[0] == 400
    assert preview_server.app.store.account_resume(alice["token"])["viewer"]["id"] == alice["id"]


@pytest.mark.parametrize("after", [True, -1, 2**63, 1.0, "0", None, [], {}])
def test_http_export_cursor_rejects_noninteger_and_out_of_range_values(preview_server, after):
    alice = account(preview_server)
    grant = start_export(preview_server, alice)["export_token"]
    payload = {"export_token": grant, "section": "public_messages", "after": after}
    assert request(preview_server, "account/export/page", payload, alice)[0] == 400


def test_http_export_references_sections_and_action_paths_are_strict(preview_server):
    alice = account(preview_server)
    grant = start_export(preview_server, alice)["export_token"]
    for invalid in (None, 1, {}, "a" * 42, "%" * 43):
        assert request(preview_server, "account/export/page", {
            "export_token": invalid, "section": "public_messages", "after": 0,
        }, alice)[0] == 400
        assert request(preview_server, "account/export/finish", {"export_token": invalid}, alice)[0] == 400
    for invalid in (None, [], "accounts", "private_messages WHERE 1=1"):
        assert request(preview_server, "account/export/page", {
            "export_token": grant, "section": invalid, "after": 0,
        }, alice)[0] == 400
    for endpoint in ("account/export/", "account/export/page/extra", "account/close/extra"):
        assert request(preview_server, endpoint, {}, alice)[0] == 404
    for endpoint, payload in lifecycle_requests(alice, grant):
        assert request(preview_server, endpoint, payload, alice, participant="malformed")[0] == 401
    assert request(preview_server, "account/export/page", {
        "export_token": grant, "section": "public_messages", "after": 0,
    }, alice)[0] == 200


def saved_profile(store, person, bio, photo, asset):
    current = store.profile_get(person["token"])
    profile = {key: value for key, value in current["profile"].items() if key in PROFILE_FIELDS}
    profile.update(bio=bio, visibility="commons", share_skills=True,
                   assessment={"interests": ["navigation"], "experience": {"navigation": "practiced"},
                               "contributions": ["remote"]})
    store.profile_save(person["token"], profile, current["revision"])
    with store._db() as db:
        db.execute("UPDATE profiles SET photo_png=?,photo_asset_id=?,share_photo=1 WHERE participant=?",
                   (photo, asset, person["id"]))


def test_http_export_contains_only_own_records_and_preserves_unopened_deliveries(preview_server, monkeypatch):
    # Isolate the endpoint's side effects from the independently scheduled
    # expiry worker, which is allowed to clear expired bodies at any time.
    monkeypatch.setattr(preview_server, "service_actions", lambda: None)
    alice = account(preview_server)
    bob = account(preview_server, "TEST_Bob")
    store = preview_server.app.store
    saved_profile(store, alice, "TEST my private questionnaire export", PNG, "a" * 32)
    saved_profile(store, bob, "TEST OTHER PROFILE SECRET", b"TEST OTHER PHOTO SECRET", "b" * 32)
    own_public = store.send(alice["token"], "general", "TEST own public letter", "1" * 32)["id"]
    other_public = store.send(bob["token"], "general", "TEST OTHER PUBLIC BODY", "1" * 32)["id"]
    store.report(alice["token"], other_public, "other")
    thread = store.private_create(alice["token"], "TEST shared conversation", "direct", [bob["id"]], "2" * 32)["thread"]
    store.private_accept(bob["token"], thread)
    store.test_clock[0] += 2
    own_private = store.private_send(alice["token"], thread, "TEST own saved private letter", "saved", "3" * 32)["id"]
    other_private = store.private_send(bob["token"], thread, "TEST OTHER PRIVATE BODY", "saved", "3" * 32)["id"]
    store.private_report(alice["token"], thread, other_private, "unsafe")
    store.test_clock[0] += 2
    store.private_send(alice["token"], thread, "TEST OWN OPEN ONCE BODY", "view_once", "4" * 32)
    store.private_send(bob["token"], thread, "TEST OTHER OPEN ONCE BODY", "view_once", "4" * 32)
    store.test_clock[0] += 2
    withdrawn = store.send(alice["token"], "general", "TEST WITHDRAWN OWN BODY", "5" * 32)["id"]
    store.delete(alice["token"], withdrawn)
    store.private_create(bob["token"], "TEST OTHER CREATED TITLE", "direct", [alice["id"]], "6" * 32)
    with store._db() as db:
        # A deadline can pass before the periodic expiry sweep. Export itself
        # must neither run that sweep nor consume any pending delivery.
        db.execute("UPDATE private_messages SET expires=? WHERE author=? AND lifetime='view_once'",
                   (store.clock() - 1, alice["id"]))
        deliveries = [tuple(row) for row in db.execute("SELECT * FROM private_deliveries ORDER BY message,recipient")]
        messages = [tuple(row) for row in db.execute("SELECT id,body,redacted FROM private_messages ORDER BY id")]
        secrets = [tuple(row) for row in db.execute("SELECT password_hash,recovery_hash FROM accounts")]

    start = start_export(preview_server, alice)
    manifest = start["manifest"]
    assert manifest["format"] == "fieldforge-commons-account" and manifest["version"] == 1
    assert manifest["account"]["participant"] == alice["id"]
    assert manifest["account"]["username"] == alice["username"]
    assert set(manifest["profile"]) == PROFILE_FIELDS
    assert manifest["profile"]["assessment"]["experience"] == {"navigation": "practiced"}
    assert manifest["photo"] == {"mime_type": "image/png", "encoded": base64.b64encode(PNG).decode()}
    assert manifest["page_size"] == 500 and manifest["consistent_snapshot"] is False
    assert [conversation["id"] for conversation in manifest["conversations"]] == [thread]
    records = {section: export_records(preview_server, alice, start["export_token"], section) for section in SECTIONS}
    assert [row["id"] for row in records["public_messages"]] == [own_public]
    assert [row["id"] for row in records["private_messages"]] == [own_private]
    assert records["private_messages"][0]["lifetime"] == "saved"
    assert records["public_reports"][0]["message"] == other_public
    assert records["private_reports"][0]["message"] == other_private
    assert set(records["public_reports"][0]) == {"message", "reason", "created"}
    assert set(records["private_reports"][0]) == {"message", "reason", "created"}
    assert manifest["totals"] == dict.fromkeys(SECTIONS, 1)
    exported = json.dumps({"manifest": manifest, "records": records})
    forbidden = [alice["token"], bob["token"], alice["recovery_code"], bob["recovery_code"], PASSWORD,
                 "TEST OTHER PROFILE SECRET", "TEST OTHER PUBLIC BODY", "TEST OTHER PRIVATE BODY",
                 "TEST OTHER CREATED TITLE",
                 "TEST OWN OPEN ONCE BODY", "TEST OTHER OPEN ONCE BODY", "TEST WITHDRAWN OWN BODY",
                 base64.b64encode(b"TEST OTHER PHOTO SECRET").decode(), "a" * 32, "b" * 32,
                 "token_hash", "password_hash", "recovery_hash", "photo_asset_id", "request_id"]
    forbidden.extend(secret for row in secrets for secret in row)
    assert all(value not in exported for value in forbidden)
    with store._db() as db:
        assert [tuple(row) for row in db.execute("SELECT * FROM private_deliveries ORDER BY message,recipient")] == deliveries
        assert [tuple(row) for row in db.execute("SELECT id,body,redacted FROM private_messages ORDER BY id")] == messages
    assert request(preview_server, "account/export/finish", {"export_token": start["export_token"]}, alice)[0] == 200
    assert request(preview_server, "account/export/finish", {"export_token": start["export_token"]}, alice)[0] == 410


def test_http_paged_export_completes_valid_retained_history_larger_than_eight_mib(preview_server):
    alice = account(preview_server)
    store = preview_server.app.store
    # Five real rooms, each below its 1000-row limit; each body obeys both the
    # 1000-character and 2000-byte message limits. A single JSON reply would fail.
    rows = []
    for index in range(4500):
        rows.append((ROOMS[index // 900]["id"], alice["id"], f"T{index:04d}:" + "é" * 994,
                     store.clock() - 4500 + index, f"{index + 100:032x}"))
    with store._db() as db:
        db.executemany("INSERT INTO messages(room,author,body,created,request_id) VALUES(?,?,?,?,?)", rows)
    start = start_export(preview_server, alice)
    assert start["manifest"]["totals"]["public_messages"] == 4500
    exported = export_records(preview_server, alice, start["export_token"], "public_messages")
    assert len(exported) == 4500
    assert [row["body"] for row in exported] == [row[2] for row in rows]
    assert len(json.dumps(exported, ensure_ascii=False).encode()) > 8 * 1024**2


def test_http_close_revokes_session_without_cookie_mutation_and_preserves_other_messages(preview_server):
    alice = account(preview_server)
    bob = account(preview_server, "TEST_Bob")
    store = preview_server.app.store
    saved_profile(store, alice, "TEST remove this profile", PNG, "a" * 32)
    saved_profile(store, bob, "TEST keep this profile", PNG, "b" * 32)
    store.send(alice["token"], "general", "TEST withdraw my public body", "1" * 32)
    store.send(bob["token"], "general", "TEST keep Bob public body", "1" * 32)
    thread = store.private_create(alice["token"], "TEST preserved conversation", "direct", [bob["id"]], "2" * 32)["thread"]
    store.private_accept(bob["token"], thread)
    store.test_clock[0] += 2
    store.private_send(alice["token"], thread, "TEST withdraw my private body", "saved", "3" * 32)
    store.private_send(bob["token"], thread, "TEST keep Bob private body", "saved", "3" * 32)
    grant = start_export(preview_server, alice)["export_token"]
    status, headers, result = request(preview_server, "account/close", close_payload(alice), alice,
                                      participant=alice["id"])
    assert status == 200 and result == {"closed": True}
    # A delayed reply must not erase a newer account's shared browser cookie.
    # The old token is invalidated in storage, independently of browser cookies.
    assert "Set-Cookie" not in headers
    assert headers["Cache-Control"] == "no-store"
    for endpoint, payload in lifecycle_requests(alice, grant):
        assert request(preview_server, endpoint, payload, alice)[0] == 401
    assert request(preview_server, "profile/get", {}, alice)[0] == 401
    assert request(preview_server, "account/resume", {"consent": True}, alice)[0] == 401
    assert request(preview_server, "profile/photo/read", {"asset_id": "a" * 32}, bob)[0] == 404
    assert request(preview_server, "profile/photo/read", {"asset_id": "b" * 32}, bob)[0] == 200
    public = store.read(bob["token"], "general")["messages"]
    private = store.private_read(bob["token"], thread)["messages"]
    assert [row["body"] for row in public] == ["", "TEST keep Bob public body"]
    assert [row["body"] for row in private] == ["", "TEST keep Bob private body"]
    assert public[0]["name"] == private[0]["name"] == "Closed account"
    assert store.profile_get(bob["token"])["profile"]["bio"] == "TEST keep this profile"


def test_http_owner_account_cannot_be_closed(preview_server):
    pyotp = pytest.importorskip("pyotp", reason="Install the commons extra for owner MFA tests")
    store = preview_server.app.store
    store.test_clock = [1_900_000_000.0]
    store.clock = lambda: store.test_clock[0]
    secret = pyotp.random_base32()
    store.owner_bootstrap(PASSWORD, secret, pyotp.TOTP(secret).at(store.clock()))
    store.test_clock[0] += 30
    token, result = store.owner_login("CLRYAN86", PASSWORD, pyotp.TOTP(secret).at(store.clock()))
    owner = {**result["viewer"], "token": token, "password": PASSWORD}
    assert request(preview_server, "account/close", close_payload(owner), owner, participant=owner["id"])[0] == 403
    assert store.owner_dashboard(token)["owner"]["id"] == owner["id"]


@pytest.mark.parametrize("endpoint", ["leave", "account/recover"])
def test_http_revocation_replies_preserve_a_newer_accounts_cookie_and_session(preview_server, endpoint):
    alice = account(preview_server)
    bob = account(preview_server, "TEST_Bob")
    payload = {} if endpoint == "leave" else {
        "username": alice["username"], "recovery_code": alice["recovery_code"],
        "new_password": OTHER_PASSWORD, "consent": True,
    }
    # Recovery authorizes Alice by recovery code even if this browser now carries
    # Bob's newer cookie. Ordinary sign-out authorizes Alice by her own old token.
    caller = alice if endpoint == "leave" else bob
    status, headers, result = request(preview_server, endpoint, payload, caller)
    assert status == 200 and "Set-Cookie" not in headers
    assert request(preview_server, "account/resume", {"consent": True}, alice)[0] == 401
    status, _, current = request(preview_server, "account/resume", {"consent": True}, bob)
    assert status == 200 and current["viewer"]["id"] == bob["id"]

    login = {"username": alice["username"], "password": PASSWORD, "consent": True}
    if endpoint == "account/recover":
        assert set(result) == {"recovery_code"} and result["recovery_code"] != alice["recovery_code"]
        assert request(preview_server, "account/login", login)[0] == 401
        assert request(preview_server, "account/recover", payload)[0] == 401
        login["password"] = OTHER_PASSWORD
    status, _, signed_in = request(preview_server, "account/login", login)
    assert status == 200 and signed_in["viewer"]["id"] == alice["id"]
    assert request(preview_server, "account/resume", {"consent": True}, bob)[0] == 200


def test_http_owner_password_revokes_old_access_without_mutating_a_newer_accounts_cookie(preview_server):
    pyotp = pytest.importorskip("pyotp", reason="Install the commons extra for owner MFA tests")
    store = preview_server.app.store
    store.test_clock = [1_900_000_000.0]
    store.clock = lambda: store.test_clock[0]
    secret = pyotp.random_base32()
    original = store.owner_bootstrap(PASSWORD, secret, pyotp.TOTP(secret).at(store.clock()))
    store.test_clock[0] += 30
    token, result = store.owner_login("CLRYAN86", PASSWORD, pyotp.TOTP(secret).at(store.clock()))
    owner = {**result["viewer"], "token": token}
    bob = account(preview_server, "TEST_Bob")
    store.test_clock[0] += 30
    status, headers, changed = request(preview_server, "owner/password", {
        "password": PASSWORD, "new_password": OTHER_PASSWORD, "code": pyotp.TOTP(secret).at(store.clock()),
    }, owner, participant=owner["id"])
    assert status == 200 and "Set-Cookie" not in headers
    assert set(changed) == {"recovery_code"} and changed["recovery_code"] != original["recovery_code"]
    assert request(preview_server, "account/resume", {"consent": True}, owner)[0] == 401
    assert request(preview_server, "owner/dashboard", {}, owner)[0] == 401
    status, _, current = request(preview_server, "account/resume", {"consent": True}, bob)
    assert status == 200 and current["viewer"]["id"] == bob["id"]

    store.test_clock[0] += 30
    login = {"username": "CLRYAN86", "password": PASSWORD, "code": pyotp.TOTP(secret).at(store.clock()),
             "consent": True}
    assert request(preview_server, "owner/login", login)[0] == 401
    status, _, signed_in = request(preview_server, "owner/login", {**login, "password": OTHER_PASSWORD})
    assert status == 200 and signed_in["viewer"]["id"] == owner["id"]
    assert request(preview_server, "account/resume", {"consent": True}, bob)[0] == 200


def test_http_photo_decode_started_before_close_cannot_restore_the_profile(preview_server, monkeypatch):
    import fieldforge.online.profile_photos as photos

    alice = account(preview_server)
    store = preview_server.app.store
    entered = threading.Event()
    release = threading.Event()

    def decode(_encoded):
        entered.set()
        assert release.wait(10), "TEST decoder was not released"
        return PNG

    monkeypatch.setattr(photos, "normalize_profile_photo", decode)
    with ThreadPoolExecutor(max_workers=1) as pool:
        upload = pool.submit(request, preview_server, "profile/photo/upload", {"encoded": "TEST photo", "revision": 0},
                             alice, participant=alice["id"])
        try:
            assert entered.wait(5), "TEST upload did not reach decoding"
            assert request(preview_server, "account/close", close_payload(alice), alice, participant=alice["id"])[0] == 200
        finally:
            release.set()
        assert upload.result(timeout=5)[0] == 401
    with store._db() as db:
        assert db.execute("SELECT 1 FROM profiles WHERE participant=?", (alice["id"],)).fetchone() is None
        assert db.execute("SELECT 1 FROM accounts WHERE participant=?", (alice["id"],)).fetchone() is None
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
