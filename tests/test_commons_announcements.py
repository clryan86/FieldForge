"""Owner announcements preserve MFA, retry receipts, retention and HTTP boundaries."""

import hashlib
import http.client
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_commons_chat

from fieldforge.online.account_lifecycle import AccountLifecycleStore
from fieldforge.online.accounts import AccountStore
from fieldforge.online.chat_store import ChatError, ChatStore
from fieldforge.online.commons_preview import COOKIE_NAME
from fieldforge.online.owner import (
    ANNOUNCEMENT_RETENTION_SECONDS,
    MAX_ACTIVE_ANNOUNCEMENTS,
    MAX_ANNOUNCEMENT_RECORDS,
    OWNER_SECONDS,
    OwnerStore,
)
from fieldforge.online.private_chat import PrivateChatStore
from fieldforge.online.profiles import PROFILE_FIELDS, ProfileStore

preview_server = test_commons_chat.preview_server
api = test_commons_chat.api
PASSWORD = "TEST announcements: river maple trail"
MEMBER_API = "/api/commons/announcements"
OWNER_API = "/api/commons/owner/announcements"
PUBLISH_API = OWNER_API + "/publish"
WITHDRAW_API = OWNER_API + "/withdraw"
CONSTRUCTORS = (ChatStore, PrivateChatStore, AccountStore, OwnerStore,
                ProfileStore, AccountLifecycleStore)


@pytest.fixture
def store(tmp_path):
    now = [1_800_000_000.0]
    result = OwnerStore(tmp_path / "announcements.sqlite3", clock=lambda: now[0])
    result.test_clock = now
    return result


def owner_login(store, *, advance=True):
    pyotp = pytest.importorskip("pyotp", reason="Owner MFA requires the commons extra")
    if advance:
        store.test_clock[0] += 30
    return store.owner_login(
        "CLRYAN86", PASSWORD, pyotp.TOTP(store.test_secret).at(store.clock()))[0]


def bootstrap_owner(store):
    pyotp = pytest.importorskip("pyotp", reason="Owner MFA requires the commons extra")
    store.test_secret = pyotp.random_base32()
    store.owner_bootstrap(
        PASSWORD, store.test_secret, pyotp.TOTP(store.test_secret).at(store.clock()))
    return owner_login(store)


@pytest.fixture
def owner(store):
    return bootstrap_owner(store)


@pytest.fixture
def http_owner(preview_server):
    store = preview_server.app.store
    store.test_clock = [1_800_000_000.0]
    store.clock = lambda: store.test_clock[0]
    return bootstrap_owner(store)


def request_id(store):
    store.test_sequence = getattr(store, "test_sequence", 0) + 1
    return f"{store.test_sequence:032x}"


def publish(store, token, *, title="TEST owner notice", body="TEST notice body", key=None):
    return store.owner_announcements_publish(
        token, title, body, request_id(store) if key is None else key)


def records(store, table="owner_announcements"):
    with sqlite3.connect(store.path) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id")]


def snapshot(store):
    with sqlite3.connect(store.path) as db:
        return {
            "announcements": db.execute("SELECT * FROM owner_announcements ORDER BY id").fetchall(),
            "audit": db.execute("SELECT * FROM owner_audit ORDER BY id").fetchall(),
            "sequence": db.execute("SELECT * FROM sqlite_sequence ORDER BY name").fetchall(),
        }


def announcement_audit(store):
    return [row for row in records(store, "owner_audit")
            if row["event"] in {"publish_announcement", "withdraw_announcement"}]


def denied(status, operation):
    with pytest.raises(ChatError) as error:
        operation()
    assert error.value.status == status


def expired_receipt(store, owner):
    response = publish(store, owner, title="TEST expired receipt")
    identifier = response["announcement"]["id"]
    store.owner_announcements_withdraw(owner, identifier)
    with store._db() as db:
        db.execute("UPDATE owner_announcements SET withdrawn=? WHERE id=?",
                   (store.clock() - ANNOUNCEMENT_RETENTION_SECONDS, identifier))
    return identifier


def concurrent(operations):
    barrier = threading.Barrier(len(operations))

    def attempt(operation):
        barrier.wait(timeout=5)
        try:
            return operation()
        except ChatError as error:
            return error

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        return list(pool.map(attempt, operations))


def raw_http(server, path, *, token, data=None, headers=None, declared_length=None):
    host = f"127.0.0.1:{server.server_address[1]}"
    connection = http.client.HTTPConnection(host, timeout=5)
    try:
        request_headers = {
            "Content-Type": "application/json", "Origin": "http://" + host,
            "X-FieldForge-Chat": "preview-v1", "Cookie": f"{COOKIE_NAME}={token}",
            **(headers or {}),
        }
        if declared_length is not None:
            # Oversize requests are rejected from headers without reading a body.
            connection.putrequest("POST", path)
            for name, value in request_headers.items():
                connection.putheader(name, value)
            connection.putheader("Content-Length", str(declared_length))
            connection.endheaders()
        else:
            connection.request("POST", path, data, request_headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_joined_guests_accounts_and_owner_receive_only_active_public_fields(store, owner):
    account, _ = store.account_register("TEST_Reader", PASSWORD, "")
    guest, _ = store.join("TEST joined guest", "")
    assert store.announcements(guest) == {"announcements": [], "limit": 5}
    notices = [publish(store, owner, title=f"TEST notice {index}")["announcement"]
               for index in range(3)]
    store.owner_announcements_withdraw(owner, notices[1]["id"])
    # Created times are metadata; IDs, not wall-clock changes, determine order.
    with store._db() as db:
        db.execute("UPDATE owner_announcements SET created=? WHERE id=?",
                   (store.clock() + 1000, notices[0]["id"]))
    notices[0]["created"] = store.clock() + 1000
    expected = {"announcements": [notices[2], notices[0]], "limit": 5}
    for token in (account, guest, owner):
        assert store.announcements(token) == expected
    assert store.owner_announcements(owner) == expected
    serialized = json.dumps(expected)
    for private_value in (owner, store.test_secret, "request_id", "fingerprint", "withdrawn"):
        assert private_value not in serialized
    assert all(set(row) == {"id", "title", "body", "created"}
               for row in expected["announcements"])


def test_old_active_notice_remains_visible_behind_newer_withdrawn_receipts(store, owner):
    oldest = publish(store, owner)["announcement"]
    for index in range(12):
        newer = publish(store, owner, title=f"TEST retired notice {index}")["announcement"]
        store.owner_announcements_withdraw(owner, newer["id"])
    expected = {"announcements": [oldest], "limit": 5}
    assert store.announcements(owner) == expected
    assert store.owner_announcements(owner) == expected
    assert len(records(store)) == 13


def test_chat_blocks_do_not_hide_service_notices_or_change_private_deliveries(store, owner):
    reader, data = store.account_register("TEST_Reader", PASSWORD, "")
    reader_id = data["viewer"]["id"]
    owner_id = store.account_resume(owner)["viewer"]["id"]
    thread = store.private_create(owner, "TEST private delivery state", "direct",
                                  [reader_id], request_id(store))["thread"]
    store.private_accept(reader, thread)
    for lifetime in ("saved", "view_once"):
        store.test_clock[0] += 2
        store.private_send(owner, thread, f"TEST private {lifetime} body", lifetime, request_id(store))
    notice = publish(store, owner)["announcement"]
    expected = {"announcements": [notice], "limit": 5}

    def delivery_state():
        with sqlite3.connect(store.path) as db:
            return (
                db.execute("SELECT * FROM private_messages ORDER BY id").fetchall(),
                db.execute("SELECT * FROM private_deliveries ORDER BY message,recipient").fetchall(),
            )

    before = delivery_state()
    assert len(before[1]) == 2 and all(row[2] is None for row in before[1])
    assert store.announcements(reader) == expected
    assert store.owner_announcements(owner) == expected
    assert delivery_state() == before
    for blocker, target in ((reader, owner_id), (owner, reader_id)):
        store.block(blocker, target, True)
        # Blocking intentionally consumes matching open-once deliveries.
        # Announcement reads must preserve the state after that separate action.
        after_block = delivery_state()
        assert store.announcements(reader) == expected
        assert store.owner_announcements(owner) == expected
        assert delivery_state() == after_block
        store.block(blocker, target, False)


def test_canonical_publication_retry_keeps_original_identity_time_and_single_audit(store, owner):
    key = "00000000-0000-0000-0000-000000000001"
    original = publish(store, owner, title="\t TEST \r\nOwner   bulletin ",
                       body="\r\nLine one\r\n  preserve   this \tspacing\r\n", key=key)
    notice = original["announcement"]
    assert original == {
        "announcement": {"id": notice["id"], "title": "TEST Owner bulletin",
                         "body": "Line one\n  preserve   this \tspacing", "created": store.clock()},
        "withdrawn": False,
    }
    before = snapshot(store)
    store.test_clock[0] += 1
    assert publish(store, owner, title=notice["title"], body=notice["body"], key=key) == original
    assert snapshot(store) == before
    for title, body in (("Changed title", notice["body"]),
                        (notice["title"], "Line one\n preserve this spacing")):
        denied(409, lambda: publish(store, owner, title=title, body=body, key=key))
        assert snapshot(store) == before
    row = records(store)[0]
    assert row["request_id"] == key
    assert len(row["fingerprint"]) == 64 and int(row["fingerprint"], 16) >= 0
    audit = announcement_audit(store)
    assert [(event["event"], event["target"], event["reason"]) for event in audit] == [
        ("publish_announcement", f"announcement:{notice['id']}", "")]
    dashboard = store.owner_dashboard(owner)
    assert next(event for event in dashboard["audit"]
                if event["event"] == "publish_announcement")["target_label"] == f"Announcement #{notice['id']}"


def test_retry_fingerprint_distinguishes_title_body_boundaries(store, owner):
    key = request_id(store)
    publish(store, owner, title="a", body="bc", key=key)
    before = snapshot(store)
    denied(409, lambda: publish(store, owner, title="ab", body="c", key=key))
    assert snapshot(store) == before


def test_withdrawal_scrubs_content_and_retries_never_republish_or_extend_retention(store, owner):
    title = "TEST distinctive withdrawn title 9a347f"
    body = "TEST distinctive withdrawn body 7dc923"
    key = request_id(store)
    first = publish(store, owner, title=title, body=body, key=key)
    identifier, created = first["announcement"]["id"], first["announcement"]["created"]
    fingerprint = records(store)[0]["fingerprint"]
    store.test_clock[0] += 1
    assert store.owner_announcements_withdraw(owner, identifier) == {"ok": True}
    withdrawn_at = store.clock()
    row = records(store)[0]
    assert row == {"id": identifier, "title": "", "body": "", "created": created,
                   "withdrawn": withdrawn_at, "request_id": key, "fingerprint": fingerprint}
    assert store.announcements(owner) == {"announcements": [], "limit": 5}
    before = snapshot(store)
    store.test_clock[0] += 1
    assert store.owner_announcements_withdraw(owner, identifier) == {"ok": True}
    assert publish(store, owner, title=title, body=body, key=key) == {
        "announcement": {"id": identifier, "title": "", "body": "", "created": created},
        "withdrawn": True,
    }
    assert snapshot(store) == before
    denied(409, lambda: publish(store, owner, title=title, body="Changed text", key=key))
    assert snapshot(store) == before
    reopened = OwnerStore(store.path, clock=store.clock)
    assert reopened.owner_announcements(owner) == {"announcements": [], "limit": 5}
    assert [(event["event"], event["target"]) for event in announcement_audit(store)] == [
        ("publish_announcement", f"announcement:{identifier}"),
        ("withdraw_announcement", f"announcement:{identifier}"),
    ]
    assert title not in json.dumps(records(store, "owner_audit"))
    assert body not in json.dumps(records(store, "owner_audit"))
    assert title.encode() not in store.path.read_bytes()
    assert body.encode() not in store.path.read_bytes()


def test_exact_seven_day_retention_keeps_active_notices_and_then_forgets_withdrawn_retry(store, owner):
    active = publish(store, owner, title="TEST lasting notice")["announcement"]
    key = request_id(store)
    original = publish(store, owner, title="TEST temporary notice", key=key)["announcement"]
    store.owner_announcements_withdraw(owner, original["id"])
    withdrawn_at = store.clock()
    store.test_clock[0] = withdrawn_at + ANNOUNCEMENT_RETENTION_SECONDS - 1
    owner = owner_login(store, advance=False)
    assert publish(store, owner, title="TEST temporary notice", key=key) == {
        "announcement": {**original, "title": "", "body": ""}, "withdrawn": True}
    assert store.owner_announcements_withdraw(owner, original["id"]) == {"ok": True}
    assert records(store)[1]["withdrawn"] == withdrawn_at
    assert store.owner_announcements(owner)["announcements"] == [active]
    assert len(records(store)) == 2
    store.test_clock[0] += 1
    assert store.announcements(owner)["announcements"] == [active]
    assert [row["id"] for row in records(store)] == [active["id"]]
    replacement = publish(store, owner, title="TEST changed after receipt expiry", key=key)
    assert replacement["withdrawn"] is False
    assert replacement["announcement"]["id"] > original["id"]
    assert replacement["announcement"]["created"] == store.clock()
    denied(404, lambda: store.owner_announcements_withdraw(owner, original["id"]))


@pytest.mark.parametrize("operation", ["member_feed", "owner_feed", "publish", "withdraw"])
def test_successful_authenticated_operations_prune_expired_receipts(store, owner, operation):
    stale = expired_receipt(store, owner)
    active = publish(store, owner)["announcement"]["id"]
    calls = {
        "member_feed": lambda: store.announcements(owner),
        "owner_feed": lambda: store.owner_announcements(owner),
        "publish": lambda: publish(store, owner),
        "withdraw": lambda: store.owner_announcements_withdraw(owner, active),
    }
    # Publishing the active fixture also prunes, so restore a stale receipt explicitly.
    with store._db() as db:
        db.execute("INSERT INTO owner_announcements(id,title,body,created,withdrawn,request_id,fingerprint) "
                   "VALUES(?,'','',?,?,?,?)",
                   (stale, store.clock() - ANNOUNCEMENT_RETENTION_SECONDS,
                    store.clock() - ANNOUNCEMENT_RETENTION_SECONDS, "f" * 32, "f" * 64))
    calls[operation]()
    assert stale not in [row["id"] for row in records(store)]


def test_withdrawn_zero_timestamp_is_a_receipt_and_not_an_active_notice(store, owner):
    key = request_id(store)
    original = publish(store, owner, key=key)["announcement"]
    with store._db() as db:
        db.execute("UPDATE owner_announcements SET title='',body='',created=0,withdrawn=0")
    # This fixture covers the valid epoch-zero timestamp without using truthiness.
    store.test_clock[0] = ANNOUNCEMENT_RETENTION_SECONDS - 1
    assert store.announcements(owner) == {"announcements": [], "limit": 5}
    assert publish(store, owner, key=key) == {
        "announcement": {**original, "title": "", "body": "", "created": 0}, "withdrawn": True}
    before = snapshot(store)
    assert store.owner_announcements_withdraw(owner, original["id"]) == {"ok": True}
    assert snapshot(store) == before


def test_title_body_and_retry_validation_preserves_records_and_audit(store, owner):
    expired_receipt(store, owner)
    before = snapshot(store)
    invalid_text = [None, True, 1, [], {}, "", " \r\n\t ", "\x00", "a\x7fb",
                    "a\u0085b", "a\u202eb", "a\u2066b", "a\ud800b", "a\uffffb"]
    for value in [*invalid_text, "t" * 81, "😀" * 81]:
        denied(400, lambda: publish(store, owner, title=value))
        assert snapshot(store) == before
    for value in [*invalid_text, "x" * 1001, "😀" * 501, "😀" * 499 + "abcde"]:
        denied(400, lambda: publish(store, owner, body=value))
        assert snapshot(store) == before
    for value in (None, True, 1, [], {}, "a" * 31, "a" * 37, "z" * 32, "A" * 32, "a" * 31 + "\n"):
        denied(400, lambda: store.owner_announcements_publish(owner, "TEST title", "TEST body", value))
        assert snapshot(store) == before


def test_maximum_unicode_text_limits_accept_canonical_content(store, owner):
    result = publish(store, owner, title="  " + "😀" * 80 + "  ", body="é" * 1000)
    assert result["announcement"]["title"] == "😀" * 80
    assert result["announcement"]["body"] == "é" * 1000
    assert publish(store, owner, body="😀" * 500)["announcement"]["body"] == "😀" * 500
    literal = "<img src=x onerror=alert(1)> ' OR 1=1 -- %_"
    assert publish(store, owner, title=literal, body=literal)["announcement"]["body"] == literal


def test_withdrawal_ids_are_strict_positive_javascript_safe_integers(store, owner):
    identifier = publish(store, owner)["announcement"]["id"]
    expired_receipt(store, owner)
    before = snapshot(store)
    for value in (None, True, False, 0, -1, 1.0, "1", [], {}, 2**53, 2**63, 2**80):
        denied(400, lambda: store.owner_announcements_withdraw(owner, value))
        assert snapshot(store) == before
    for value in (identifier + 100, 2**53 - 1):
        denied(404, lambda: store.owner_announcements_withdraw(owner, value))
        assert snapshot(store) == before


def test_active_capacity_allows_existing_retries_and_withdrawal_frees_one_slot(store, owner):
    first_key = request_id(store)
    first = publish(store, owner, key=first_key)
    for index in range(MAX_ACTIVE_ANNOUNCEMENTS - 1):
        publish(store, owner, title=f"TEST active {index}")
    before = snapshot(store)
    assert len(store.announcements(owner)["announcements"]) == 5
    assert publish(store, owner, key=first_key) == first
    denied(409, lambda: publish(store, owner))
    assert snapshot(store) == before
    store.owner_announcements_withdraw(owner, first["announcement"]["id"])
    replacement = publish(store, owner)
    assert replacement["announcement"]["id"] > first["announcement"]["id"]
    assert len(records(store)) == 6
    assert len(store.owner_announcements(owner)["announcements"]) == 5


def test_actual_thousand_record_limit_preserves_receipts_and_reclaims_only_expired_rows(store, owner):
    first_key = request_id(store)
    first = publish(store, owner, key=first_key)
    with store._db() as db:
        db.executemany(
            "INSERT INTO owner_announcements(title,body,created,withdrawn,request_id,fingerprint) "
            "VALUES('','',?,?,?,?)",
            [(store.clock(), store.clock(), f"{10_000 + index:032x}", "f" * 64)
             for index in range(MAX_ANNOUNCEMENT_RECORDS - 1)])
    assert len(records(store)) == 1000
    before = snapshot(store)
    assert publish(store, owner, key=first_key) == first
    denied(409, lambda: publish(store, owner))
    assert snapshot(store) == before
    store.owner_announcements_withdraw(owner, first["announcement"]["id"])
    assert publish(store, owner, key=first_key)["withdrawn"] is True
    before = snapshot(store)
    denied(409, lambda: publish(store, owner))
    assert snapshot(store) == before
    assert len(records(store)) == 1000
    with store._db() as db:
        db.execute("UPDATE owner_announcements SET withdrawn=? WHERE id=?",
                   (store.clock() - ANNOUNCEMENT_RETENTION_SECONDS, first["announcement"]["id"] + 1))
    new = publish(store, owner)
    assert len(records(store)) == 1000
    assert store.announcements(owner)["announcements"] == [new["announcement"]]


def test_concurrent_identical_publications_and_withdrawals_each_write_one_audit(store, owner):
    key = request_id(store)
    results = concurrent([lambda: publish(store, owner, key=key) for _ in range(4)])
    assert all(result == results[0] for result in results)
    assert isinstance(results[0], dict)
    assert len(records(store)) == 1
    assert len(announcement_audit(store)) == 1
    identifier = results[0]["announcement"]["id"]
    results = concurrent([lambda: store.owner_announcements_withdraw(owner, identifier)
                          for _ in range(4)])
    assert results == [{"ok": True}] * 4
    assert [event["event"] for event in announcement_audit(store)] == [
        "publish_announcement", "withdraw_announcement"]
    assert records(store)[0]["title"] == records(store)[0]["body"] == ""


def test_concurrent_distinct_publications_cannot_overfill_the_last_active_slot(store, owner):
    for index in range(4):
        publish(store, owner, title=f"TEST previous {index}")
    keys = [request_id(store), request_id(store)]
    before = len(announcement_audit(store))
    results = concurrent([lambda key=key: publish(store, owner, key=key) for key in keys])
    assert sum(isinstance(result, dict) for result in results) == 1
    assert [result.status for result in results if isinstance(result, ChatError)] == [409]
    assert len(store.announcements(owner)["announcements"]) == 5
    assert len(records(store)) == 5
    assert len(announcement_audit(store)) == before + 1


def test_concurrent_changed_payload_reusing_one_retry_id_only_publishes_one_notice(store, owner):
    key = request_id(store)
    results = concurrent([lambda body=body: publish(store, owner, body=body, key=key)
                          for body in ("TEST first competing body", "TEST second competing body")])
    assert sum(isinstance(result, dict) for result in results) == 1
    assert [result.status for result in results if isinstance(result, ChatError)] == [409]
    assert len(records(store)) == len(announcement_audit(store)) == 1


def test_nonowners_and_missing_sessions_cannot_list_publish_retry_or_withdraw(store, owner):
    key = request_id(store)
    active = publish(store, owner, key=key)["announcement"]["id"]
    account, _ = store.account_register("TEST_Reader", PASSWORD, "")
    guest, _ = store.join("TEST guest reader", "")
    expired_receipt(store, owner)
    before = snapshot(store)
    for token, status in ((account, 403), (guest, 403), (None, 401), ("x" * 43, 401)):
        for operation in (lambda: store.owner_announcements(token),
                          lambda: publish(store, token),
                          lambda: publish(store, token, key=key),
                          lambda: store.owner_announcements_withdraw(token, active)):
            denied(status, operation)
            assert snapshot(store) == before
    for token in (None, "x" * 43, "invalid"):
        denied(401, lambda: store.announcements(token))
        assert snapshot(store) == before


@pytest.mark.parametrize("condition,status", [
    ("locked", 403), ("expired_grant", 403), ("revoked", 401),
    ("expired_session", 401), ("suspended", 401),
])
def test_owner_authorization_is_rechecked_before_cleanup_and_every_retry(store, owner, condition, status):
    key = request_id(store)
    active = publish(store, owner, key=key)["announcement"]["id"]
    expired_receipt(store, owner)
    participant = store.account_resume(owner)["viewer"]["id"]
    if condition == "locked":
        store.owner_lock(owner)
    elif condition == "expired_grant":
        store.test_clock[0] += OWNER_SECONDS
    elif condition == "revoked":
        store.leave(owner)
    else:
        with store._db() as db:
            if condition == "expired_session":
                db.execute("UPDATE participants SET expires=? WHERE id=?", (store.clock(), participant))
            else:
                # Preserve the cookie to prove the current suspension hook is checked.
                db.execute("INSERT INTO participant_controls VALUES(?,1,'other',?)",
                           (participant, store.clock()))
    before = snapshot(store)
    for operation in (lambda: store.owner_announcements(owner),
                      lambda: publish(store, owner),
                      lambda: publish(store, owner, key=key),
                      lambda: store.owner_announcements_withdraw(owner, active)):
        denied(status, operation)
        assert snapshot(store) == before
    if status == 403:
        assert store.announcements(owner)["announcements"][0]["id"] == active
    else:
        denied(401, lambda: store.announcements(owner))
        assert snapshot(store) == before


@pytest.mark.parametrize("condition", ["suspended", "revoked", "expired"])
def test_member_feed_rechecks_current_account_session_and_suspension(store, owner, condition):
    token, result = store.account_register("TEST_Reader", PASSWORD, "")
    participant = result["viewer"]["id"]
    expired_receipt(store, owner)
    if condition == "expired":
        with store._db() as db:
            db.execute("UPDATE participants SET expires=? WHERE id=?", (store.clock(), participant))
    elif condition == "revoked":
        store.owner_control(owner, participant, "revoke", "other")
    else:
        with store._db() as db:
            db.execute("INSERT INTO participant_controls VALUES(?,1,'other',?)",
                       (participant, store.clock()))
    before = snapshot(store)
    denied(401, lambda: store.announcements(token))
    assert snapshot(store) == before


def test_rejected_conflict_capacity_and_unknown_withdrawal_roll_back_expiry_cleanup(store, owner):
    key = request_id(store)
    publish(store, owner, key=key)
    for index in range(3):
        publish(store, owner, title=f"TEST active {index}")
    stale = expired_receipt(store, owner)
    # Fill the fifth active slot without invoking a cleanup before the rejected calls.
    with store._db() as db:
        db.execute("INSERT INTO owner_announcements(title,body,created,request_id,fingerprint) "
                   "VALUES('TEST fifth active','TEST body',?,?,?)",
                   (store.clock(), "e" * 32, "e" * 64))
    before = snapshot(store)
    for status, operation in (
            (409, lambda: publish(store, owner, body="Changed retry body", key=key)),
            (409, lambda: publish(store, owner)),
            (404, lambda: store.owner_announcements_withdraw(owner, 2**53 - 1)),
            (404, lambda: store.owner_announcements_withdraw(owner, stale))):
        denied(status, operation)
        assert snapshot(store) == before


def test_audit_failure_rolls_back_publication_withdrawal_and_receipt_cleanup(store, owner, monkeypatch):
    active = publish(store, owner)["announcement"]["id"]
    expired_receipt(store, owner)
    original_audit = store._audit

    def fail_after_audit(db, event, target, reason=""):
        original_audit(db, event, target, reason)
        raise RuntimeError("TEST simulated audit failure")

    monkeypatch.setattr(store, "_audit", fail_after_audit)
    before = snapshot(store)
    for operation in (lambda: publish(store, owner),
                      lambda: store.owner_announcements_withdraw(owner, active)):
        with pytest.raises(RuntimeError, match="simulated audit failure"):
            operation()
        assert snapshot(store) == before


def test_actual_schema_eight_migration_preserves_content_and_all_narrower_opens(tmp_path):
    now = [1_800_000_000.0]

    def clock():
        return now[0]

    path = tmp_path / "version-eight.sqlite3"
    previous = AccountLifecycleStore(path, clock=clock)
    alice, alice_data = previous.account_register("TEST_Alice", PASSWORD, "")
    bob, bob_data = previous.account_register("TEST_Bob", PASSWORD, "")
    previous.send(alice, "general", "TEST public before announcements", "a" * 32)
    thread = previous.private_create(alice, "TEST retained private thread", "direct",
                                     [bob_data["viewer"]["id"]], "b" * 32)["thread"]
    previous.private_accept(bob, thread)
    now[0] += 2
    previous.private_send(alice, thread, "TEST private before announcements", "saved", "c" * 32)
    profile = previous.profile_get(alice)
    profile_fields = {field: profile["profile"][field] for field in PROFILE_FIELDS}
    previous.profile_save(alice, {**profile_fields, "bio": "TEST retained profile",
                                 "visibility": "commons", "allow_invitations": True}, profile["revision"])
    with sqlite3.connect(path) as db:
        # Schema 8 really lacks the new table; this is not just a version relabel.
        db.execute("DROP TABLE owner_announcements")
        db.execute("PRAGMA user_version=8")
        assert db.execute("SELECT name FROM sqlite_master WHERE name='owner_announcements'").fetchone() is None
    upgraded = AccountLifecycleStore(path, clock=clock)
    assert upgraded.account_resume(alice)["viewer"]["id"] == alice_data["viewer"]["id"]
    assert upgraded.read(bob, "general")["messages"][0]["body"] == "TEST public before announcements"
    assert upgraded.private_read(bob, thread)["messages"][0]["body"] == "TEST private before announcements"
    assert upgraded.profile_get(alice)["profile"]["bio"] == "TEST retained profile"
    assert upgraded.profile_get(alice)["profile"]["allow_invitations"] is True
    assert upgraded.announcements(bob) == {"announcements": [], "limit": 5}
    with upgraded._db() as db:
        db.execute("INSERT INTO owner_announcements(title,body,created,request_id,fingerprint) "
                   "VALUES('TEST persistent notice','TEST persistent body',?,?,?)",
                   (clock(), "d" * 32, hashlib.sha256(b"TEST migration fixture").hexdigest()))
    expected = records(upgraded)
    for constructor in CONSTRUCTORS:
        constructor(path, clock=clock)
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 9
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert records(upgraded) == expected
    assert ProfileStore(path, clock=clock).profile_get(alice)["profile"]["allow_invitations"] is True


def test_owner_version_nine_does_not_skip_real_legacy_profile_consent_migration(tmp_path):
    def clock():
        return 1_800_000_000.0

    path = tmp_path / "pre-consent.sqlite3"
    previous = AccountStore(path, clock=clock)
    alice, data = previous.account_register("TEST_Legacy", PASSWORD, "")
    with previous._db() as db:
        db.execute("""CREATE TABLE profiles (
            participant TEXT PRIMARY KEY REFERENCES accounts(participant) ON DELETE CASCADE,
            profile_id TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL, bio TEXT NOT NULL,
            visibility TEXT NOT NULL CHECK(visibility IN ('private','commons')),
            share_skills INTEGER NOT NULL CHECK(share_skills IN (0,1)),
            share_photo INTEGER NOT NULL CHECK(share_photo IN (0,1)), assessment TEXT NOT NULL,
            photo_asset_id TEXT UNIQUE, photo_png BLOB, revision INTEGER NOT NULL,
            saved INTEGER NOT NULL CHECK(saved IN (0,1)), updated REAL NOT NULL,
            CHECK((photo_asset_id IS NULL) = (photo_png IS NULL)))""")
        db.execute("INSERT INTO profiles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (data["viewer"]["id"], "a" * 32, "TEST legacy profile", "TEST legacy biography",
                    "commons", 0, 0, '{"interests":[],"experience":{},"contributions":[]}',
                    None, None, 4, 1, clock()))
        assert db.execute("PRAGMA user_version").fetchone()[0] == 7
    OwnerStore(path, clock=clock)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 9
        assert "allow_invitations" not in {row[1] for row in db.execute("PRAGMA table_info(profiles)")}
    upgraded = AccountLifecycleStore(path, clock=clock)
    profile = upgraded.profile_get(alice)
    assert profile["revision"] == 4
    assert profile["profile"]["bio"] == "TEST legacy biography"
    assert profile["profile"]["allow_invitations"] is False
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 9
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("constructor", CONSTRUCTORS)
def test_future_schema_versions_remain_rejected_without_mutation(tmp_path, constructor):
    path = tmp_path / "future.sqlite3"
    OwnerStore(path)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=10")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Unsupported Commons"):
        constructor(path)
    assert path.read_bytes() == before


def test_http_nested_routes_publish_retry_read_and_withdraw_with_safe_responses(preview_server, http_owner):
    store = preview_server.app.store
    guest, _ = store.join("TEST HTTP guest", "")
    payload = {"title": "TEST HTTP notice", "body": "TEST HTTP body", "request_id": "a" * 32}
    status, headers, body = api(preview_server, PUBLISH_API, payload, token=http_owner)
    assert status == 200 and "no-store" in headers["Cache-Control"]
    assert "Set-Cookie" not in headers
    first = json.loads(body)
    assert set(first) == {"announcement", "withdrawn"}
    assert set(first["announcement"]) == {"id", "title", "body", "created"}
    assert first["withdrawn"] is False
    assert json.loads(api(preview_server, PUBLISH_API, payload, token=http_owner)[2]) == first
    for path, token in ((MEMBER_API, guest), (OWNER_API, http_owner)):
        status, headers, body = api(preview_server, path, {}, token=token)
        assert status == 200 and "no-store" in headers["Cache-Control"]
        assert headers["Content-Type"].startswith("application/json")
        assert json.loads(body) == {"announcements": [first["announcement"]], "limit": 5}
        assert "Set-Cookie" not in headers
    withdrawal = {"announcement": first["announcement"]["id"]}
    for _ in range(2):
        status, _, body = api(preview_server, WITHDRAW_API, withdrawal, token=http_owner)
        assert status == 200 and json.loads(body) == {"ok": True}
    retry = json.loads(api(preview_server, PUBLISH_API, payload, token=http_owner)[2])
    assert retry == {"announcement": {**first["announcement"], "title": "", "body": ""}, "withdrawn": True}
    assert json.loads(api(preview_server, MEMBER_API, {}, token=guest)[2]) == {"announcements": [], "limit": 5}
    assert len(announcement_audit(store)) == 2


def test_http_provenance_methods_strict_schemas_and_nonowner_permissions(preview_server, http_owner):
    store = preview_server.app.store
    active = publish(store, http_owner)["announcement"]["id"]
    guest, _ = store.join("TEST HTTP guest", "")
    routes = [
        (MEMBER_API, {}), (OWNER_API, {}),
        (PUBLISH_API, {"title": "TEST", "body": "TEST", "request_id": "b" * 32}),
        (WITHDRAW_API, {"announcement": active}),
    ]
    before = snapshot(store)
    for path, payload in routes:
        for options in ({"origin": False}, {"origin": "https://attacker.invalid"},
                        {"custom": False}, {"method": "GET"}):
            assert api(preview_server, path, payload, token=http_owner, **options)[0] == 403
            assert snapshot(store) == before
        assert api(preview_server, path, {**payload, "owner": True}, token=http_owner)[0] == 400
        for missing in payload:
            assert api(preview_server, path, {key: value for key, value in payload.items() if key != missing},
                       token=http_owner)[0] == 400
        assert api(preview_server, path, [payload], token=http_owner)[0] == 400
        assert api(preview_server, path, payload)[0] == 401
        if path != MEMBER_API:
            assert api(preview_server, path, payload, token=guest)[0] == 403
        assert snapshot(store) == before
    assert api(preview_server, OWNER_API + "/replace", {}, token=http_owner)[0] == 404
    assert api(preview_server, WITHDRAW_API, {"announcement": 2**53}, token=http_owner)[0] == 400
    assert snapshot(store) == before


def test_http_escaped_unicode_uses_publish_limit_and_exact_8192_boundary(preview_server, http_owner):
    payload = {"title": "😀" * 80, "body": "é" * 1000, "request_id": "a" * 32}
    encoded = json.dumps(payload).encode()
    assert 4096 < len(encoded) < 8192
    status, _, body = api(preview_server, PUBLISH_API, payload, token=http_owner)
    assert status == 200
    first = json.loads(body)
    assert first["announcement"]["title"] == payload["title"]
    assert first["announcement"]["body"] == payload["body"]
    encoded_utf8 = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert len(encoded_utf8) < 4096
    status, _, body = raw_http(
        preview_server, PUBLISH_API, token=http_owner, data=encoded_utf8)
    assert status == 200 and json.loads(body) == first
    status, _, body = raw_http(
        preview_server, PUBLISH_API, token=http_owner, data=encoded.ljust(8192, b" "))
    assert status == 200 and json.loads(body) == first
    before = snapshot(preview_server.app.store)
    assert raw_http(preview_server, PUBLISH_API, token=http_owner, declared_length=8193)[0] == 413
    assert raw_http(preview_server, MEMBER_API, token=http_owner, declared_length=4097)[0] == 413
    assert snapshot(preview_server.app.store) == before


def test_http_participant_binding_rejects_stale_browser_identity_before_publication(preview_server, http_owner):
    store = preview_server.app.store
    _, outsider = store.join("TEST different browser identity", "")
    owner_id = store.account_resume(http_owner)["viewer"]["id"]
    payload = json.dumps({"title": "TEST bound notice", "body": "TEST bound body", "request_id": "a" * 32}).encode()
    before = snapshot(store)
    status, _, _ = raw_http(
        preview_server, PUBLISH_API, token=http_owner, data=payload,
        headers={"X-FieldForge-Participant": outsider["id"]})
    assert status == 401 and snapshot(store) == before
    status, _, body = raw_http(
        preview_server, PUBLISH_API, token=http_owner, data=payload,
        headers={"X-FieldForge-Participant": owner_id})
    assert status == 200 and json.loads(body)["announcement"]["title"] == "TEST bound notice"
