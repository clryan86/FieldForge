"""Private history pagination preserves audiences, read receipts, and withdrawals."""

import json
import sqlite3

import pytest
import test_commons_chat
import test_commons_private

from fieldforge.online.chat_store import ChatError
from fieldforge.online.private_chat import MAX_THREAD_MESSAGES, PRIVATE_HISTORY_PAGE_SIZE

private_store = test_commons_private.private_store
preview_server = test_commons_chat.preview_server
api = test_commons_chat.api
HISTORY_API = "/api/commons/private/read"
INVALID_CURSORS = (True, False, 0, -1, 1.0, "1", [], {}, [1], {"id": 1}, 2**63, 2**80)


def people(store):
    if not hasattr(store, "test_clock"):
        store.test_clock = [1000.0]
        store.clock = lambda: store.test_clock[0]
    return [store.join(name, "") for name in
            ("TEST Alice", "TEST Bob", "TEST Carol", "TEST Outside")]


def request_key(store):
    store.test_history_sequence = getattr(store, "test_history_sequence", 0) + 1
    return f"{store.test_history_sequence:032x}"


def conversation(store, owner, recipients, *, accept=True):
    thread = store.private_create(
        owner[0], "TEST history subject", "group" if len(recipients) > 1 else "direct",
        [recipient[1]["id"] for recipient in recipients], request_key(store),
    )["thread"]
    if accept:
        for recipient in recipients:
            store.private_accept(recipient[0], thread)
    return thread


def message(store, author, thread, *, body=None, lifetime="saved"):
    store.test_clock[0] += 2
    key = request_key(store)
    return store.private_send(author[0], thread, body or f"TEST history {key}", lifetime, key)["id"]


def ids(page):
    return [item["id"] for item in page["messages"]]


def receipts(store, participant):
    with sqlite3.connect(store.path) as db:
        return dict(db.execute("SELECT message,opened FROM private_deliveries WHERE recipient=?",
                               (participant[1]["id"],)))


def assert_denied(operation, status):
    with pytest.raises(ChatError) as error:
        operation()
    assert error.value.status == status


def test_history_pages_use_visible_ids_across_sparse_global_message_ids(private_store):
    store = private_store
    alice, bob, carol, outsider = people(store)
    thread = conversation(store, alice, [bob])
    foreign = conversation(store, carol, [outsider])
    own_ids, foreign_ids = [], []
    for number in range(185):
        own_ids.append(message(store, alice, thread, body=f"TEST target {number}"))
        foreign_ids.append(message(store, carol, foreign, body=f"TEST unrelated secret {number}"))

    latest = store.private_read(bob[0], thread)
    assert PRIVATE_HISTORY_PAGE_SIZE == 100
    assert latest["before"] is None
    assert ids(latest) == own_ids[-100:]
    cursor = latest["older_before"]
    assert cursor == own_ids[-100]
    older = store.private_read(bob[0], thread, before=cursor)
    assert older["before"] == cursor
    assert ids(older) == own_ids[:-100]
    assert older["older_before"] is None
    assert set(ids(latest)).isdisjoint(ids(older))
    assert "TEST unrelated secret" not in json.dumps([latest, older])
    assert all(value is None for value in receipts(store, outsider).values())

    # A cursor is an exclusive numeric boundary, even when its ID belongs to
    # another thread. It must never grant access to that thread's messages.
    foreign_cursor = foreign_ids[103]
    bounded = store.private_read(bob[0], thread, before=foreign_cursor)
    eligible = [value for value in own_ids if value < foreign_cursor]
    assert ids(bounded) == eligible[-100:]
    assert bounded["before"] == foreign_cursor
    assert bounded["older_before"] == eligible[-100]
    assert "TEST unrelated secret" not in json.dumps(bounded)

    # A new arrival does not shift the fixed older-page boundary.
    newest_id = message(store, alice, thread, body="TEST arrived after opening history")
    assert ids(store.private_read(bob[0], thread, before=cursor)) == own_ids[:-100]
    assert newest_id not in ids(older)


@pytest.mark.parametrize("count", [0, 100, 101, 200])
def test_empty_and_exact_page_boundaries_do_not_advertise_phantom_older_pages(private_store, count):
    store = private_store
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    sent = [message(store, alice, thread) for _ in range(count)]
    latest = store.private_read(bob[0], thread, before=None)
    assert latest["before"] is None
    assert ids(latest) == sent[-100:]
    assert latest["older_before"] == (sent[-100] if count > 100 else None)
    if count > 100:
        older = store.private_read(bob[0], thread, before=latest["older_before"])
        assert ids(older) == sent[:-100]
        assert older["older_before"] is None
    before_first = store.private_read(bob[0], thread, before=1)
    assert before_first["messages"] == []
    assert before_first["before"] == 1
    assert before_first["older_before"] is None


def test_only_returned_saved_rows_receive_read_receipts_and_view_once_stays_sealed(private_store):
    store = private_store
    alice, bob, carol, _ = people(store)
    thread = conversation(store, alice, [bob])
    foreign = conversation(store, carol, [bob])
    foreign_id = message(store, carol, foreign, body="TEST different inbox subject")
    sent, ephemeral = [], set()
    for number in range(118):
        once = number in (0, 15, 117)
        identifier = message(store, alice, thread,
                             body=f"TEST sealed payload {number}" if once else f"TEST saved {number}",
                             lifetime="view_once" if once else "saved")
        sent.append(identifier)
        if once:
            ephemeral.add(identifier)

    # Viewing one's own sent history cannot mark the recipient's deliveries.
    store.private_read(alice[0], thread)
    assert all(value is None for value in receipts(store, bob).values())

    latest = store.private_read(bob[0], thread)
    returned = set(ids(latest))
    first_read = receipts(store, bob)
    for identifier in sent:
        if identifier in returned and identifier not in ephemeral:
            assert first_read[identifier] == store.clock()
        else:
            assert first_read[identifier] is None
    assert first_read[sent[17]] is None  # The lookahead row is not a returned row.
    assert first_read[foreign_id] is None
    assert "TEST sealed payload" not in json.dumps(latest)
    assert latest["thread"]["unread"] == 19

    store.test_clock[0] += 10
    store.private_read(bob[0], thread)
    assert receipts(store, bob) == first_read  # Polling never rewrites the first receipt.

    older = store.private_read(bob[0], thread, before=latest["older_before"])
    assert ids(older) == sent[:18]
    assert "TEST sealed payload" not in json.dumps(older)
    final_read = receipts(store, bob)
    for identifier in sent:
        assert (final_read[identifier] is None) == (identifier in ephemeral)
    assert final_read[foreign_id] is None
    assert older["thread"]["unread"] == 3
    assert all(item["body"] == "" and item["can_open"] for item in older["messages"]
               if item["id"] in ephemeral)


@pytest.mark.parametrize("reverse_block", [False, True])
def test_blocked_authors_and_messages_without_a_delivery_are_filtered_before_paging(
        private_store, reverse_block):
    store = private_store
    alice, bob, carol, _ = people(store)
    thread = conversation(store, alice, [bob, carol])
    own = message(store, bob, thread, body="TEST viewer's own old message")
    records, carol_ids = [(own, bob[1]["id"])], []
    for number in range(199):
        author = alice if number % 4 == 0 else carol
        identifier = message(store, author, thread)
        records.append((identifier, author[1]["id"]))
        if author is carol:
            carol_ids.append(identifier)
    inaccessible = set(carol_ids[:10])
    # Represent old group messages for which this participant never received a
    # delivery. Current group membership alone must not reveal these bodies.
    with sqlite3.connect(store.path) as db:
        db.executemany("DELETE FROM private_deliveries WHERE message=? AND recipient=?",
                       [(identifier, bob[1]["id"]) for identifier in inaccessible])
    blocker, target = (alice, bob) if reverse_block else (bob, alice)
    store.block(blocker[0], target[1]["id"], True)
    visible = [identifier for identifier, author in records
               if author != alice[1]["id"] and identifier not in inaccessible]

    latest = store.private_read(bob[0], thread)
    assert ids(latest) == visible[-100:]
    assert latest["older_before"] == visible[-100]
    older = store.private_read(bob[0], thread, before=latest["older_before"])
    assert ids(older) == visible[:-100]
    assert older["older_before"] is None
    assert own in ids(older)
    assert all(item["author"] != alice[1]["id"] for page in (latest, older)
               for item in page["messages"])
    assert inaccessible.isdisjoint(ids(latest) + ids(older))
    observed = receipts(store, bob)
    assert all(observed[identifier] is None for identifier, author in records
               if author == alice[1]["id"])


def test_refreshing_an_older_page_rechecks_deletion_expiry_and_current_blocks(private_store, monkeypatch):
    store = private_store
    # Keep the expiry demonstration inside the valid guest-session lifetime.
    monkeypatch.setattr("fieldforge.online.private_chat.VIEW_ONCE_SECONDS", 600)
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    withdrawn = message(store, alice, thread, body="TEST later withdrawn saved body")
    ephemeral = message(store, alice, thread, body="TEST never in history", lifetime="view_once")
    for _ in range(128):
        message(store, alice, thread)
    latest = store.private_read(bob[0], thread)
    cursor = latest["older_before"]
    older = store.private_read(bob[0], thread, before=cursor)
    assert withdrawn in ids(older) and ephemeral in ids(older)
    assert "TEST later withdrawn saved body" in json.dumps(older)
    assert "TEST never in history" not in json.dumps(older)

    store.private_delete(alice[0], thread, withdrawn)
    store.test_clock[0] += 601
    refreshed = store.private_read(bob[0], thread, before=cursor)
    rows = {item["id"]: item for item in refreshed["messages"]}
    assert refreshed["before"] == cursor
    assert rows[withdrawn]["body"] == "" and rows[withdrawn]["state"] == "deleted"
    assert rows[ephemeral]["body"] == "" and rows[ephemeral]["state"] == "expired"
    assert not rows[ephemeral]["can_open"]
    assert "TEST later withdrawn saved body" not in json.dumps(refreshed)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT body FROM private_messages WHERE id=?", (ephemeral,)).fetchone() == ("",)

    store.block(bob[0], alice[1]["id"], True)
    blocked = store.private_read(bob[0], thread, before=cursor)
    assert blocked["messages"] == []
    assert blocked["before"] == cursor and blocked["older_before"] is None


def test_cursor_remains_valid_after_retention_removes_its_original_message(private_store):
    store = private_store
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    original = [message(store, alice, thread, body=f"TEST retention old {number}")
                for number in range(101)]
    cursor = store.private_read(bob[0], thread)["older_before"]
    assert cursor == original[1]
    for _ in range(MAX_THREAD_MESSAGES):
        message(store, alice, thread, body="TEST newly retained")
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM private_messages WHERE thread=?",
                          (thread,)).fetchone()[0] == MAX_THREAD_MESSAGES
        assert db.execute("SELECT 1 FROM private_messages WHERE id=?", (cursor,)).fetchone() is None
    historical = store.private_read(bob[0], thread, before=cursor)
    assert historical["before"] == cursor
    assert historical["messages"] == [] and historical["older_before"] is None
    assert "TEST retention old" not in json.dumps(store.private_read(bob[0], thread))


@pytest.mark.parametrize("before", INVALID_CURSORS)
def test_native_history_rejects_invalid_cursor_types_without_marking_deliveries(private_store, before):
    store = private_store
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    identifier = message(store, alice, thread)
    assert_denied(lambda: store.private_read(bob[0], thread, before=before), 400)
    assert receipts(store, bob)[identifier] is None


def test_history_accepts_largest_signed_sqlite_id_boundary_and_explicit_null(private_store):
    store = private_store
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    sent = [message(store, alice, thread) for _ in range(3)]
    for before in (None, 2**63 - 1):
        page = store.private_read(bob[0], thread, before=before)
        assert ids(page) == sent
        assert page["before"] == before and page["older_before"] is None


def test_http_history_preserves_legacy_payload_and_returns_exclusive_pages(preview_server):
    store = preview_server.app.store
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    sent = [message(store, alice, thread) for _ in range(103)]
    status, headers, body = api(preview_server, HISTORY_API, {"thread": thread}, token=bob[0])
    assert status == 200 and headers["Cache-Control"] == "no-store"
    latest = json.loads(body)
    assert ids(latest) == sent[-100:]
    assert latest["before"] is None and latest["older_before"] == sent[3]
    payload = {"thread": thread, "before": latest["older_before"]}
    status, _, body = api(preview_server, HISTORY_API, payload, token=bob[0])
    assert status == 200
    older = json.loads(body)
    assert ids(older) == sent[:3]
    assert older["before"] == sent[3] and older["older_before"] is None
    status, _, body = api(preview_server, HISTORY_API, {"thread": thread, "before": None}, token=bob[0])
    assert status == 200 and ids(json.loads(body)) == sent[-100:]


def test_http_cursor_schema_and_existing_origin_guards_fail_without_reading_history(preview_server):
    store = preview_server.app.store
    alice, bob, *_ = people(store)
    thread = conversation(store, alice, [bob])
    identifier = message(store, alice, thread, body="TEST unread until a valid request")
    for before in INVALID_CURSORS:
        assert api(preview_server, HISTORY_API, {"thread": thread, "before": before}, token=bob[0])[0] == 400
    for payload in ({"before": identifier}, {"thread": thread, "before": identifier, "limit": 1000},
                    {"thread": thread, "older_before": identifier}, {"thread": thread, "offset": 0}):
        assert api(preview_server, HISTORY_API, payload, token=bob[0])[0] == 400
    for options in ({"origin": False}, {"origin": "https://unrelated.invalid"}, {"custom": False}):
        status, _, body = api(preview_server, HISTORY_API, {"thread": thread, "before": identifier + 1},
                              token=bob[0], **options)
        assert status == 403 and b"TEST unread until a valid request" not in body
    for path, payload in (("/api/commons/private/inbox", {"before": None}),
                          ("/api/commons/private/export", {"before": None}),
                          ("/api/commons/read", {"room": "general", "before": None})):
        assert api(preview_server, path, payload, token=bob[0])[0] == 400
    assert receipts(store, bob)[identifier] is None


def test_native_and_http_history_require_current_accepted_unsuspended_membership(preview_server):
    store = preview_server.app.store
    alice, bob, invited, outsider = people(store)
    thread = conversation(store, alice, [bob, invited], accept=False)
    store.private_accept(bob[0], thread)
    secret = "TEST historical audience secret"
    identifier = message(store, alice, thread, body=secret)
    cursor = identifier + 1

    def denied(token, status):
        assert_denied(lambda: store.private_read(token, thread, before=cursor), status)
        response_status, _, body = api(preview_server, HISTORY_API,
                                       {"thread": thread, "before": cursor}, token=token)
        assert response_status == status
        assert secret.encode() not in body

    denied(outsider[0], 404)
    denied(invited[0], 404)
    denied(None, 401)
    assert receipts(store, bob)[identifier] is None
    assert receipts(store, invited)[identifier] is None
    # Seed a real operator suspension row without depending on MFA setup; the
    # history endpoint must honor it for an otherwise valid accepted session.
    with sqlite3.connect(store.path) as db:
        db.execute("INSERT INTO participant_controls VALUES(?,1,'unsafe',?)",
                   (bob[1]["id"], store.clock()))
    denied(bob[0], 401)
    assert receipts(store, bob)[identifier] is None
    with sqlite3.connect(store.path) as db:
        db.execute("DELETE FROM participant_controls WHERE participant=?", (bob[1]["id"],))
    store.private_leave(bob[0], thread)
    denied(bob[0], 404)
    store.leave(alice[0])
    denied(alice[0], 401)
