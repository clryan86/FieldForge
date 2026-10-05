"""Private-message audience, one-time delivery, migration, expiry and abuse boundaries."""

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from fieldforge.online.chat_store import ChatError, ChatStore
from fieldforge.online.private_chat import VIEW_ONCE_SECONDS, PrivateChatStore


@pytest.fixture
def private_store(tmp_path):
    now = [1000.0]
    store = PrivateChatStore(tmp_path / "private.sqlite3", clock=lambda: now[0])
    store.test_clock = now
    return store


def participants(store):
    return [store.join(name, "") for name in ("Alice", "Bob", "Carol", "Outside")]


def create(store, people, *, group=False):
    token, _ = people[0]
    result = store.private_create(token, "Private test subject", "group" if group else "direct",
                                  [person[1]["id"] for person in people[1:]], "a" * 32)
    return result["thread"]


def send(store, token, thread, *, body="Private text", lifetime="saved", key="b" * 32):
    return store.private_send(token, thread, body, lifetime, key)["id"]


def test_migrates_v1_without_losing_public_history_or_downgrading_v2(tmp_path):
    path = tmp_path / "old.sqlite3"
    old = ChatStore(path, clock=lambda: 1000)
    token, _ = old.join("Alice", "")
    old.send(token, "general", "Keep this public message", "a" * 32)
    private = PrivateChatStore(path, clock=lambda: 1000)
    assert private.read(token, "general")["messages"][0]["body"] == "Keep this public message"
    ChatStore(path)  # An older public-only caller must not lower the schema version.
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_invitation_acceptance_and_outsider_access_boundaries(private_store):
    store = private_store
    alice, bob, _, outsider = participants(store)
    thread = create(store, [alice, bob])
    message = send(store, alice[0], thread)
    assert store.private_inbox(outsider[0])["threads"] == []
    invite = store.private_inbox(bob[0])["threads"][0]
    assert invite["status"] == "invited" and invite["title"] == "Private test subject"
    assert "Private text" not in json.dumps(invite)
    for token in (outsider[0], bob[0]):
        with pytest.raises(ChatError) as error:
            store.private_read(token, thread)
        assert error.value.status == 404
    with pytest.raises(ChatError):
        store.private_accept(outsider[0], thread)
    store.private_accept(bob[0], thread)
    assert store.private_read(bob[0], thread)["messages"][0]["body"] == "Private text"
    assert store.private_inbox(bob[0])["threads"][0]["unread"] == 0
    for operation in (
        lambda: store.private_delete(outsider[0], thread, message),
        lambda: store.private_delete(bob[0], thread, message),
        lambda: store.private_report(outsider[0], thread, message, "spam"),
        lambda: send(store, outsider[0], thread),
    ):
        with pytest.raises(ChatError):
            operation()
    assert store.private_export(outsider[0])["messages"] == []


def test_view_once_is_absent_from_history_exports_reports_and_atomic(private_store):
    store = private_store
    alice, bob, _, outsider = participants(store)
    thread = create(store, [alice, bob])
    message = send(store, alice[0], thread, body="Ephemeral secret", lifetime="view_once")
    store.private_accept(bob[0], thread)
    for token in (alice[0], bob[0]):
        assert "Ephemeral secret" not in json.dumps(store.private_read(token, thread))
        assert "Ephemeral secret" not in json.dumps(store.private_export(token))
        assert "Ephemeral secret" not in json.dumps(store.export(token))
    store.private_report(bob[0], thread, message, "other")
    assert "Ephemeral secret" not in json.dumps(store.reports())
    for token in (alice[0], outsider[0]):
        with pytest.raises(ChatError):
            store.private_open_once(token, thread, message)

    def open_once(_):
        try:
            return store.private_open_once(bob[0], thread, message)
        except ChatError as error:
            return error.status
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(open_once, range(2)))
    assert sum(isinstance(item, dict) and item["body"] == "Ephemeral secret" for item in results) == 1
    assert 410 in results
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT body,redacted FROM private_messages WHERE id=?", (message,)).fetchone() == ("", "opened")
    with pytest.raises(ChatError):
        PrivateChatStore(store.path, clock=store.clock).private_open_once(bob[0], thread, message)


def test_group_has_one_delivery_per_recipient_then_removes_body(private_store):
    store = private_store
    alice, bob, carol, outsider = participants(store)
    thread = create(store, [alice, bob, carol], group=True)
    message = send(store, alice[0], thread, lifetime="view_once")
    for participant in (bob, carol):
        store.private_accept(participant[0], thread)
    store.private_open_once(bob[0], thread, message)
    assert store.private_read(bob[0], thread)["messages"][0]["can_open"] is False
    assert store.private_read(carol[0], thread)["messages"][0]["can_open"] is True
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT body FROM private_messages WHERE id=?", (message,)).fetchone()[0] == "Private text"
    store.private_leave(carol[0], thread)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT body FROM private_messages WHERE id=?", (message,)).fetchone()[0] == ""
    with pytest.raises(ChatError):
        store.private_accept(carol[0], thread)
    with pytest.raises(ChatError):
        store.private_read(outsider[0], thread)


def test_expiration_sweep_clears_unopened_content_after_restart(private_store):
    store = private_store
    alice, bob, *_ = participants(store)
    thread = create(store, [alice, bob])
    message = send(store, alice[0], thread, lifetime="view_once")
    store.test_clock[0] += VIEW_ONCE_SECONDS
    reopened = PrivateChatStore(store.path, clock=store.clock)
    reopened.expire_private_messages()
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT body,redacted FROM private_messages WHERE id=?", (message,)).fetchone() == ("", "expired")


def test_blocking_stops_invites_and_private_delivery_in_both_directions(private_store):
    store = private_store
    alice, bob, *_ = participants(store)
    thread = create(store, [alice, bob])
    store.private_accept(bob[0], thread)
    message = send(store, alice[0], thread, lifetime="view_once")
    store.block(bob[0], alice[1]["id"], True)
    assert store.private_read(bob[0], thread)["messages"] == []
    for actor, recipient in ((alice, bob), (bob, alice)):
        with pytest.raises(ChatError):
            store.private_create(actor[0], "Try again", "direct", [recipient[1]["id"]], "c" * 32)
        with pytest.raises(ChatError):
            send(store, actor[0], thread, key="d" * 32)
    store.block(bob[0], alice[1]["id"], False)
    with pytest.raises(ChatError):
        store.private_open_once(bob[0], thread, message)


def test_deleted_view_once_cannot_be_resurrected_by_lost_reply_retry(private_store):
    store = private_store
    alice, bob, *_ = participants(store)
    thread = create(store, [alice, bob])
    message = send(store, alice[0], thread, lifetime="view_once")
    store.private_delete(alice[0], thread, message)
    assert send(store, alice[0], thread, lifetime="view_once") == message
    store.private_accept(bob[0], thread)
    with pytest.raises(ChatError):
        store.private_open_once(bob[0], thread, message)


def test_saved_reply_and_private_export_keep_separate_audiences(private_store):
    store = private_store
    alice, bob, *_ = participants(store)
    thread = create(store, [alice, bob])
    store.private_accept(bob[0], thread)
    send(store, alice[0], thread, body="Alice's private note")
    send(store, bob[0], thread, body="Bob's reply")
    assert len(store.private_read(bob[0], thread)["messages"]) == 2
    assert [item["body"] for item in store.private_export(alice[0])["messages"]] == ["Alice's private note"]
    assert store.read(alice[0], "general")["messages"] == []
    store.private_leave(bob[0], thread)
    assert store.private_export(bob[0])["messages"] == []


@pytest.mark.parametrize("contacts,kind", [([], "direct"), (["bad"], "direct"), ([None], "direct"),
                                          (["a" * 24, "b" * 24], "direct"), (["a" * 24] * 8, "group"),
                                          (["a" * 24], []), ("a" * 24, "direct")])
def test_rejects_invalid_recipients_and_kinds(private_store, contacts, kind):
    token, _ = private_store.join("Alice", "")
    with pytest.raises(ChatError):
        private_store.private_create(token, "Subject", kind, contacts, "a" * 32)


def test_creation_retry_is_idempotent_and_request_ids_cannot_change_content(private_store):
    store = private_store
    alice, bob, *_ = participants(store)
    thread = create(store, [alice, bob])
    assert create(store, [alice, bob]) == thread
    with pytest.raises(ChatError):
        store.private_create(alice[0], "Different", "direct", [bob[1]["id"]], "a" * 32)
    send(store, alice[0], thread)
    with pytest.raises(ChatError):
        send(store, alice[0], thread, body="Changed")


def test_private_retention_and_conversation_capacity_are_bounded(private_store, monkeypatch):
    store = private_store
    monkeypatch.setattr("fieldforge.online.private_chat.MAX_THREAD_MESSAGES", 2)
    monkeypatch.setattr("fieldforge.online.private_chat.MAX_MEMBER_THREADS", 1)
    alice, bob, *_ = participants(store)
    thread = create(store, [alice, bob])
    for number in range(3):
        store.test_clock[0] += 2
        send(store, alice[0], thread, body=str(number), key=f"{number:032x}")
    assert [item["body"] for item in store.private_read(alice[0], thread)["messages"]] == ["1", "2"]
    with pytest.raises(ChatError, match="conversation limit"):
        store.private_create(alice[0], "Another subject", "direct", [bob[1]["id"]], "d" * 32)


def test_idle_server_sweep_expires_bodies_without_client_requests(tmp_path):
    from fieldforge.online.commons_preview import make_preview_server

    server = make_preview_server(tmp_path / "idle.sqlite3", 0)
    try:
        store = server.app.store
        now = [1000.0]
        store.clock = lambda: now[0]
        alice, bob, *_ = participants(store)
        thread = create(store, [alice, bob])
        message = send(store, alice[0], thread, lifetime="view_once")
        now[0] += VIEW_ONCE_SECONDS
        server._last_expiry = time.monotonic() - 61
        server.service_actions()
        with sqlite3.connect(store.path) as db:
            assert db.execute("SELECT body FROM private_messages WHERE id=?", (message,)).fetchone()[0] == ""
    finally:
        server.server_close()
