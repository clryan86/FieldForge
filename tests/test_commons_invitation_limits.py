"""Invitation capacity, persistent abuse limits, and closed-thread reclamation."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from fieldforge.online import private_chat
from fieldforge.online.accounts import AccountStore
from fieldforge.online.chat_store import SESSION_SECONDS, ChatError
from fieldforge.online.owner import OwnerStore

PASSWORD = "TEST only: invitation river trail"


@pytest.fixture
def store(tmp_path):
    now = [1_800_000_000.0]
    result = AccountStore(tmp_path / "invitations.sqlite3", clock=lambda: now[0])
    result.test_clock = now
    return result


def account(store, name):
    token, result = store.account_register(name, PASSWORD, "")
    return {"token": token, "id": result["viewer"]["id"], "name": name}


def guest(store, name):
    token, viewer = store.join(name, "")
    return {"token": token, "id": viewer["id"], "name": name}


def sign_in(store, person):
    person["token"], result = store.account_login(person["name"], PASSWORD)
    assert result["viewer"]["id"] == person["id"]


def invite(store, sender, recipients, key=1, title="TEST invitation"):
    return store.private_create(sender["token"], title, "direct" if len(recipients) == 1 else "group",
                                [person["id"] for person in recipients], f"{key:032x}")


def assert_status(status, operation):
    with pytest.raises(ChatError) as error:
        operation()
    assert error.value.status == status


def count_receipts(store):
    with store._db() as db:
        return db.execute("SELECT COUNT(*) FROM private_invitation_receipts").fetchone()[0]


def close_thread(store, thread, people):
    for person in people:
        store.private_leave(person["token"], thread)


def test_declined_invitation_frees_recipient_capacity_without_erasing_sender_history(store, monkeypatch):
    monkeypatch.setattr(private_chat, "MAX_MEMBER_THREADS", 1)
    alice, bob, carol = [account(store, name) for name in ("TEST_Alice", "TEST_Bob", "TEST_Carol")]
    first = invite(store, alice, [bob])["thread"]
    store.private_send(alice["token"], first, "TEST sender keeps this saved letter", "saved", "a" * 32)
    store.private_leave(bob["token"], first)
    assert store.private_inbox(bob["token"])["threads"] == []

    second = invite(store, carol, [bob])["thread"]
    assert store.private_inbox(bob["token"])["threads"][0]["id"] == second
    assert store.private_read(alice["token"], first)["messages"][0]["body"] == "TEST sender keeps this saved letter"
    assert_status(404, lambda: store.private_read(bob["token"], first))
    assert_status(409, lambda: invite(store, alice, [carol], key=2))


def test_leaving_accepted_thread_frees_membership_but_preserves_remaining_readers(store, monkeypatch):
    monkeypatch.setattr(private_chat, "MAX_MEMBER_THREADS", 1)
    alice, bob, carol = [account(store, name) for name in ("TEST_Alice", "TEST_Bob", "TEST_Carol")]
    first = invite(store, alice, [bob])["thread"]
    store.private_accept(bob["token"], first)
    store.private_send(alice["token"], first, "TEST retained for the remaining reader", "saved", "a" * 32)
    store.private_leave(alice["token"], first)

    second = invite(store, alice, [carol], key=2)["thread"]
    assert store.private_inbox(alice["token"])["threads"][0]["id"] == second
    assert store.private_read(bob["token"], first)["messages"][0]["body"] == "TEST retained for the remaining reader"
    assert_status(404, lambda: store.private_read(alice["token"], first))


def test_global_capacity_recycles_only_after_last_member_leaves_and_preserves_retry(store, monkeypatch):
    monkeypatch.setattr(private_chat, "MAX_THREADS", 1)
    alice, bob, carol, dana = [account(store, name) for name in ("TEST_Alice", "TEST_Bob", "TEST_Carol", "TEST_Dana")]
    first = invite(store, alice, [bob])["thread"]
    store.private_accept(bob["token"], first)
    message = store.private_send(alice["token"], first, "TEST closed-thread body", "saved", "a" * 32)["id"]
    store.private_report(bob["token"], first, message, "other")
    store.private_leave(alice["token"], first)
    assert_status(409, lambda: invite(store, carol, [dana]))
    assert store.private_read(bob["token"], first)["messages"][0]["body"] == "TEST closed-thread body"

    store.private_leave(bob["token"], first)
    second = invite(store, carol, [dana])["thread"]
    with store._db() as db:
        assert db.execute("SELECT id FROM private_threads").fetchone()[0] == second
        assert db.execute("SELECT 1 FROM private_members WHERE thread=?", (first,)).fetchone() is None
        assert db.execute("SELECT 1 FROM private_messages WHERE id=?", (message,)).fetchone() is None
        assert db.execute("SELECT 1 FROM private_reports WHERE message=?", (message,)).fetchone() is None
        assert db.execute("SELECT closed FROM private_invitation_receipts WHERE thread=?", (first,)).fetchone()[0] is not None
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    retry = invite(store, alice, [bob])
    assert retry == {"thread": first, "duplicate": True, "closed": True}
    assert_status(409, lambda: invite(store, alice, [bob], title="TEST changed retry"))
    assert store.private_inbox(bob["token"])["threads"] == []


def test_pending_saved_invitee_keeps_a_conversation_after_creator_leaves(store, monkeypatch):
    monkeypatch.setattr(private_chat, "MAX_THREADS", 1)
    alice, bob, carol, dana = [account(store, name) for name in ("TEST_Alice", "TEST_Bob", "TEST_Carol", "TEST_Dana")]
    thread = invite(store, alice, [bob])["thread"]
    store.private_send(alice["token"], thread, "TEST invitation still has a reader", "saved", "a" * 32)
    store.private_leave(alice["token"], thread)
    assert_status(409, lambda: invite(store, carol, [dana]))
    assert invite(store, alice, [bob]) == {"thread": thread, "duplicate": True, "closed": False}
    store.private_accept(bob["token"], thread)
    assert store.private_read(bob["token"], thread)["messages"][0]["body"] == "TEST invitation still has a reader"


@pytest.mark.parametrize("initial_group", [False, True])
def test_pair_cooldown_survives_decline_restart_and_group_changes_and_is_directed(store, initial_group):
    alice, bob, carol, dana = [account(store, name) for name in ("TEST_Alice", "TEST_Bob", "TEST_Carol", "TEST_Dana")]
    recipients = [bob, carol] if initial_group else [bob]
    first = invite(store, alice, recipients)["thread"]
    store.private_leave(bob["token"], first)
    reopened = AccountStore(store.path, clock=store.clock)
    assert_status(429, lambda: invite(reopened, alice, [bob], key=2))
    assert_status(429, lambda: invite(reopened, alice, [bob, dana], key=3))
    if initial_group:
        assert_status(429, lambda: invite(reopened, alice, [carol], key=4))
    assert reopened.private_inbox(dana["token"])["threads"] == []
    assert count_receipts(reopened) == 1
    assert invite(reopened, alice, list(reversed(recipients)))["duplicate"] is True

    reverse = invite(reopened, bob, [alice])["thread"]
    assert reverse != first
    store.test_clock[0] += private_chat.INVITATION_COOLDOWN - 1
    assert_status(429, lambda: invite(reopened, alice, [bob], key=5))
    store.test_clock[0] += 1
    assert invite(reopened, alice, [bob], key=5)["duplicate"] is False


def test_daily_budget_counts_each_recipient_and_survives_closed_threads_and_restart(store, monkeypatch):
    monkeypatch.setattr(private_chat, "MAX_DAILY_INVITATIONS", 3)
    alice, bob, carol, dana, ellis = [account(store, name) for name in
                                     ("TEST_Alice", "TEST_Bob", "TEST_Carol", "TEST_Dana", "TEST_Ellis")]
    group = invite(store, alice, [bob, carol])["thread"]
    direct = invite(store, alice, [dana], key=2)["thread"]
    assert invite(store, alice, [carol, bob])["duplicate"] is True
    assert_status(429, lambda: invite(store, alice, [ellis], key=3))
    close_thread(store, group, [bob, carol, alice])
    close_thread(store, direct, [dana, alice])
    reopened = AccountStore(store.path, clock=store.clock)
    assert_status(429, lambda: invite(reopened, alice, [ellis], key=3))

    store.test_clock[0] += private_chat.INVITATION_WINDOW - 1
    sign_in(reopened, alice)
    assert_status(429, lambda: invite(reopened, alice, [ellis], key=3))
    store.test_clock[0] += 1
    assert invite(reopened, alice, [ellis], key=3)["duplicate"] is False
    assert count_receipts(reopened) == 3


def test_rejected_group_is_atomic_and_does_not_consume_sender_budget_or_pair_cooldowns(store, monkeypatch):
    monkeypatch.setattr(private_chat, "MAX_DAILY_INVITATIONS", 2)
    alice, bob, carol, dana = [account(store, name) for name in ("TEST_Alice", "TEST_Bob", "TEST_Carol", "TEST_Dana")]
    assert_status(429, lambda: invite(store, alice, [bob, carol, dana]))
    assert count_receipts(store) == 0
    for recipient in (bob, carol, dana):
        assert store.private_inbox(recipient["token"])["threads"] == []
    assert invite(store, alice, [bob, carol], key=2)["duplicate"] is False


def test_blocked_contact_is_unavailable_before_throttles_but_original_retry_is_safe(store, monkeypatch):
    monkeypatch.setattr(private_chat, "MAX_DAILY_INVITATIONS", 1)
    alice, bob = [account(store, name) for name in ("TEST_Alice", "TEST_Bob")]
    thread = invite(store, alice, [bob])["thread"]
    close_thread(store, thread, [bob, alice])
    store.block(bob["token"], alice["id"], True)
    assert_status(404, lambda: invite(store, alice, [bob], key=2))
    assert invite(store, alice, [bob]) == {"thread": thread, "duplicate": True, "closed": True}
    assert count_receipts(store) == 1


def test_concurrent_identical_retries_create_one_receipt_and_charge_once(store, monkeypatch):
    monkeypatch.setattr(private_chat, "MAX_DAILY_INVITATIONS", 2)
    alice, bob, carol = [account(store, name) for name in ("TEST_Alice", "TEST_Bob", "TEST_Carol")]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: invite(store, alice, [bob]), range(2)))
    assert len({result["thread"] for result in results}) == 1
    assert sorted(result["duplicate"] for result in results) == [False, True]
    assert count_receipts(store) == 1
    assert invite(store, alice, [carol], key=2)["duplicate"] is False


def test_concurrent_new_ids_cannot_bypass_pair_cooldown(store):
    alice, bob = [account(store, name) for name in ("TEST_Alice", "TEST_Bob")]

    def attempt(key):
        try:
            invite(store, alice, [bob], key=key)
        except ChatError as error:
            return error.status
        return 200

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, (1, 2)))
    assert sorted(results) == [200, 429]
    assert len(store.private_inbox(bob["token"])["threads"]) == 1
    assert count_receipts(store) == 1


def test_receipt_cap_never_evicts_protected_retries_and_releases_after_expiry(store, monkeypatch):
    monkeypatch.setattr(private_chat, "MAX_INVITATION_RECEIPTS", 2)
    alice, bob, carol, dana = [account(store, name) for name in ("TEST_Alice", "TEST_Bob", "TEST_Carol", "TEST_Dana")]
    first = invite(store, alice, [bob])["thread"]
    second = invite(store, carol, [dana])["thread"]
    close_thread(store, first, [bob, alice])
    close_thread(store, second, [dana, carol])
    assert_status(429, lambda: invite(store, alice, [carol], key=2))
    assert invite(store, alice, [bob])["closed"] is True
    assert count_receipts(store) == 2

    store.test_clock[0] += private_chat.INVITATION_RETRY_SECONDS - 1
    sign_in(store, alice)
    assert_status(429, lambda: invite(store, alice, [carol], key=2))
    assert invite(store, alice, [bob])["thread"] == first
    store.test_clock[0] += 1
    assert invite(store, alice, [carol], key=2)["duplicate"] is False
    assert count_receipts(store) == 1
    with store._db() as db:
        assert db.execute("SELECT COUNT(*) FROM private_invitation_contacts").fetchone()[0] == 1
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_retry_window_starts_at_closure_and_live_history_is_never_ttl_evicted(store, monkeypatch):
    monkeypatch.setattr(private_chat, "MAX_INVITATION_RECEIPTS", 1)
    alice, bob, carol = [account(store, name) for name in ("TEST_Alice", "TEST_Bob", "TEST_Carol")]
    original = store.clock()
    thread = invite(store, alice, [bob])["thread"]
    store.private_accept(bob["token"], thread)
    store.private_send(alice["token"], thread, "TEST saved beyond receipt retention", "saved", "a" * 32)
    store.test_clock[0] = original + private_chat.INVITATION_RETRY_SECONDS + 1
    store.expire_private_messages()
    sign_in(store, alice)
    sign_in(store, bob)
    assert invite(store, alice, [bob]) == {"thread": thread, "duplicate": True, "closed": False}
    assert store.private_read(bob["token"], thread)["messages"][0]["body"] == "TEST saved beyond receipt retention"
    close_thread(store, thread, [bob, alice])
    closed = store.clock()

    store.test_clock[0] = closed + private_chat.INVITATION_RETRY_SECONDS - 1
    sign_in(store, alice)
    assert invite(store, alice, [bob])["closed"] is True
    assert_status(429, lambda: invite(store, alice, [carol], key=2))
    store.test_clock[0] += 1
    assert invite(store, alice, [carol], key=2)["duplicate"] is False


def test_backward_clock_during_closure_does_not_shorten_created_receipt_window(store, monkeypatch):
    monkeypatch.setattr(private_chat, "MAX_INVITATION_RECEIPTS", 1)
    alice, bob, carol = [account(store, name) for name in ("TEST_Alice", "TEST_Bob", "TEST_Carol")]
    created = store.clock()
    thread = invite(store, alice, [bob])["thread"]
    store.test_clock[0] -= 100
    close_thread(store, thread, [bob, alice])
    store.test_clock[0] = created - 100 + private_chat.INVITATION_RETRY_SECONDS
    sign_in(store, alice)
    assert_status(429, lambda: invite(store, alice, [carol], key=2))
    assert invite(store, alice, [bob])["closed"] is True
    store.test_clock[0] = created + private_chat.INVITATION_RETRY_SECONDS
    assert invite(store, alice, [carol], key=2)["duplicate"] is False


@pytest.mark.parametrize("ended", ["logout", "expiry"])
def test_irrecoverable_guest_threads_are_reclaimed_without_a_manual_leave(store, monkeypatch, ended):
    monkeypatch.setattr(private_chat, "MAX_THREADS", 1)
    alice, bob = [guest(store, name) for name in ("TEST guest Alice", "TEST guest Bob")]
    thread = invite(store, alice, [bob])["thread"]
    store.private_accept(bob["token"], thread)
    store.private_send(alice["token"], thread, "TEST orphaned guest text", "saved", "a" * 32)
    if ended == "logout":
        store.leave(alice["token"])
        store.leave(bob["token"])
    else:
        store.test_clock[0] += SESSION_SECONDS + 1
    reopened = AccountStore(store.path, clock=store.clock)
    with reopened._db() as db:
        assert db.execute("SELECT COUNT(*) FROM private_threads").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM private_messages").fetchone()[0] == 0
        assert db.execute("SELECT closed FROM private_invitation_receipts WHERE thread=?", (thread,)).fetchone()[0] is not None
    carol, dana = [account(reopened, name) for name in ("TEST_Carol", "TEST_Dana")]
    assert invite(reopened, carol, [dana])["duplicate"] is False


def test_guest_retirement_preserves_saved_accounts_and_consumes_only_guest_deliveries(store):
    alice, carol = [account(store, name) for name in ("TEST_Alice", "TEST_Carol")]
    bob = guest(store, "TEST guest Bob")
    thread = invite(store, alice, [bob, carol])["thread"]
    store.private_accept(bob["token"], thread)
    store.private_accept(carol["token"], thread)
    message = store.private_send(alice["token"], thread, "TEST one-time content for surviving reader", "view_once", "a" * 32)["id"]
    store.test_clock[0] += SESSION_SECONDS + 1
    store.expire_private_messages()
    with store._db() as db:
        memberships = dict(db.execute("SELECT participant,status FROM private_members WHERE thread=?", (thread,)).fetchall())
        assert memberships == {alice["id"]: "accepted", bob["id"]: "left", carol["id"]: "accepted"}
        deliveries = dict(db.execute("SELECT recipient,opened FROM private_deliveries WHERE message=?", (message,)).fetchall())
        assert deliveries[bob["id"]] is not None and deliveries[carol["id"]] is None
    sign_in(store, carol)
    assert store.private_open_once(carol["token"], thread, message)["body"] == "TEST one-time content for surviving reader"
    with store._db() as db:
        assert db.execute("SELECT body FROM private_messages WHERE id=?", (message,)).fetchone()[0] == ""


@pytest.mark.parametrize("suspended", [False, True])
def test_logged_out_or_suspended_saved_invitee_is_never_retired_as_a_guest(store, suspended):
    alice, bob = [account(store, name) for name in ("TEST_Alice", "TEST_Bob")]
    thread = invite(store, alice, [bob])["thread"]
    store.private_send(alice["token"], thread, "TEST pending saved-account letter", "saved", "a" * 32)
    store.leave(alice["token"])
    store.leave(bob["token"])
    owner_store = OwnerStore(store.path, clock=store.clock)
    if suspended:
        with owner_store._db() as db:
            db.execute("INSERT INTO participant_controls VALUES(?,?,?,?)", (bob["id"], 1, "TEST fixture", store.clock()))
    store.test_clock[0] += SESSION_SECONDS + 1
    owner_store.expire_private_messages()
    with owner_store._db() as db:
        assert dict(db.execute("SELECT participant,status FROM private_members WHERE thread=?", (thread,)).fetchall()) == {
            alice["id"]: "accepted", bob["id"]: "invited"}
        if suspended:
            db.execute("UPDATE participant_controls SET suspended=0 WHERE participant=?", (bob["id"],))
    sign_in(owner_store, bob)
    owner_store.private_accept(bob["token"], thread)
    assert owner_store.private_read(bob["token"], thread)["messages"][0]["body"] == "TEST pending saved-account letter"


def test_schema_five_backfill_preserves_live_history_closed_retries_and_abuse_limits(store, monkeypatch):
    monkeypatch.setattr(private_chat, "MAX_DAILY_INVITATIONS", 1)
    alice, bob, carol, dana, ellis = [account(store, name) for name in
                                     ("TEST_Alice", "TEST_Bob", "TEST_Carol", "TEST_Dana", "TEST_Ellis")]
    active = invite(store, alice, [bob])["thread"]
    closed = invite(store, carol, [dana])["thread"]
    store.private_send(alice["token"], active, "TEST keep legacy saved history", "saved", "a" * 32)
    store.private_send(carol["token"], closed, "TEST reclaim legacy closed history", "saved", "a" * 32)
    # Construct the prior schema's real state: invitation metadata existed only
    # in threads/members, and all-left threads still retained their old bodies.
    with store._db() as db:
        db.execute("DROP TABLE private_invitation_contacts")
        db.execute("DROP TABLE private_invitation_receipts")
        db.execute("UPDATE private_members SET status='left' WHERE thread=?", (closed,))
        db.execute("PRAGMA user_version=5")
    reopened = AccountStore(store.path, clock=store.clock)
    assert reopened.private_read(alice["token"], active)["messages"][0]["body"] == "TEST keep legacy saved history"
    assert invite(reopened, alice, [bob]) == {"thread": active, "duplicate": True, "closed": False}
    assert invite(reopened, carol, [dana]) == {"thread": closed, "duplicate": True, "closed": True}
    assert_status(429, lambda: invite(reopened, alice, [ellis], key=2))
    with reopened._db() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 7
        assert db.execute("SELECT 1 FROM private_messages WHERE thread=?", (closed,)).fetchone() is None
        assert db.execute("SELECT recipient FROM private_invitation_contacts WHERE thread=?", (closed,)).fetchone()[0] == dana["id"]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
