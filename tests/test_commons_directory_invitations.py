"""Directory contact consent shares the private inbox's authenticated lifecycle."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_commons_chat
import test_commons_profiles

from fieldforge.online import private_chat
from fieldforge.online.account_lifecycle import AccountLifecycleStore
from fieldforge.online.accounts import AccountStore
from fieldforge.online.chat_store import ChatError, ChatStore
from fieldforge.online.owner import OwnerStore
from fieldforge.online.private_chat import PrivateChatStore
from fieldforge.online.profiles import PROFILE_FIELDS, ProfileStore

PASSWORD = "TEST directory: a long local passphrase"
INVITE_API = "/api/commons/profile/invite"
preview_server = test_commons_chat.preview_server
api = test_commons_chat.api


@pytest.fixture
def store(tmp_path):
    now = [1_800_000_000.0]
    result = AccountLifecycleStore(tmp_path / "directory.sqlite3", clock=lambda: now[0])
    result.test_clock = now
    return result


def account(store, name):
    token, result = store.account_register(name, PASSWORD, "")
    return {"token": token, "id": result["viewer"]["id"], "name": name}


def sign_in(store, person):
    person["token"], _ = store.account_login(person["name"], PASSWORD)


def profile(store, person, **changes):
    current = store.profile_get(person["token"])
    values = {key: current["profile"][key] for key in PROFILE_FIELDS}
    return store.profile_save(person["token"], {**values, **changes}, current["revision"])


def listed(store, person, *, allow=True):
    profile(store, person, visibility="commons", allow_invitations=allow)
    with store._db() as db:
        return db.execute("SELECT profile_id FROM profiles WHERE participant=?", (person["id"],)).fetchone()[0]


def invite(store, sender, profile_id, *, key=1, title="TEST directory invitation"):
    return store.profile_invite(sender["token"], profile_id, title, f"{key:032x}")


def contact_invite(store, sender, recipients, *, key=1):
    return store.private_create(sender["token"], "TEST contact invitation",
                                "direct" if len(recipients) == 1 else "group",
                                [person["id"] for person in recipients], f"{key:032x}")


def denied(status, operation):
    with pytest.raises(ChatError) as error:
        operation()
    assert error.value.status == status


def counts(store):
    with store._db() as db:
        return tuple(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in
                     ("private_threads", "private_invitation_receipts", "private_invitation_contacts"))


def close_account(store, person):
    store.account_close(person["token"], PASSWORD, person["name"], True)


def test_version_seven_profiles_migrate_without_enabling_invitations(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    older = AccountStore(path, clock=lambda: 1_800_000_000.0)
    alice, bob = account(older, "TEST_Alice"), account(older, "TEST_Bob")
    thread = contact_invite(older, alice, [bob])["thread"]
    older.send(alice["token"], "general", "TEST retained public text", "2" * 32)
    # An actual pre-consent table, not merely an older user_version on a new table.
    with older._db() as db:
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
                   (alice["id"], "a" * 32, "TEST older shared profile", "TEST retained biography",
                    "commons", 0, 0, '{"interests":[],"experience":{},"contributions":[]}',
                    None, None, 4, 1, older.clock()))
        assert db.execute("PRAGMA user_version").fetchone()[0] == 7
    upgraded = AccountLifecycleStore(path, clock=older.clock)
    saved = upgraded.profile_get(alice["token"])
    assert saved["revision"] == 4 and saved["profile"]["bio"] == "TEST retained biography"
    assert saved["profile"]["visibility"] == "commons"
    assert saved["profile"]["allow_invitations"] is False
    entry = upgraded.profile_directory(bob["token"], "", "", 0)["profiles"][0]
    assert entry["profile_id"] == "a" * 32 and entry["accepts_invitations"] is False
    assert upgraded.private_inbox(bob["token"])["threads"][0]["id"] == thread
    assert upgraded.read(bob["token"], "general")["messages"][0]["body"] == "TEST retained public text"
    profile(upgraded, alice, allow_invitations=True)
    for constructor in (ChatStore, PrivateChatStore, AccountStore, OwnerStore, ProfileStore,
                        AccountLifecycleStore):
        constructor(path, clock=older.clock)
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 9
            assert db.execute("SELECT allow_invitations FROM profiles").fetchone()[0] == 1
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_separate_opt_in_defaults_private_legacy_save_revokes_and_exports_preserve(store):
    alice, bob = account(store, "TEST_Alice"), account(store, "TEST_Bob")
    assert store.profile_get(alice["token"])["profile"]["allow_invitations"] is False
    profile_id = listed(store, alice, allow=False)
    entry = store.profile_directory(bob["token"], "", "", 0)["profiles"][0]
    assert entry["accepts_invitations"] is False and entry["own"] is False
    denied(404, lambda: invite(store, bob, profile_id))
    profile(store, alice, allow_invitations=True)
    entry = store.profile_directory(alice["token"], "", "", 0)["profiles"][0]
    assert entry["accepts_invitations"] is True and entry["own"] is True
    assert alice["id"] not in json.dumps(entry)
    assert store.profile_export(alice["token"])["profile"]["allow_invitations"] is True
    manifest = store.account_export(alice["token"], PASSWORD)["manifest"]
    assert manifest["profile"]["allow_invitations"] is True
    current = store.profile_get(alice["token"])
    legacy = {key: current["profile"][key] for key in PROFILE_FIELDS - {"allow_invitations"}}
    updated = store.profile_save(alice["token"], legacy, current["revision"])
    assert updated["profile"]["allow_invitations"] is False
    assert "allow_invitations" not in legacy  # Request dictionaries are not mutated.
    assert counts(store) == (0, 0, 0)


@pytest.mark.parametrize("value", [None, 0, 1, "yes", [], {}])
def test_opt_in_requires_a_boolean_and_rejected_save_preserves_existing_consent(store, value):
    alice = account(store, "TEST_Alice")
    listed(store, alice)
    revision = store.profile_get(alice["token"])["revision"]
    denied(400, lambda: profile(store, alice, allow_invitations=value))
    current = store.profile_get(alice["token"])
    assert current["profile"]["allow_invitations"] is True and current["revision"] == revision


def test_directory_invitation_uses_normal_acceptance_and_offline_saved_recipient(store):
    alice, bob = account(store, "TEST_Alice"), account(store, "TEST_Bob")
    profile_id = listed(store, bob)
    store.leave(bob["token"])
    response = invite(store, alice, profile_id)
    assert set(response) == {"thread", "duplicate", "closed"}
    assert response["duplicate"] is False and response["closed"] is False
    assert bob["id"] not in json.dumps(response) and alice["id"] not in json.dumps(response)
    assert counts(store) == (1, 1, 1)
    thread = response["thread"]
    store.private_send(alice["token"], thread, "TEST saved greeting", "saved", "a" * 32)
    sign_in(store, bob)
    received = store.private_inbox(bob["token"])["threads"][0]
    assert received["id"] == thread and received["status"] == "invited" and received["kind"] == "direct"
    denied(404, lambda: store.private_read(bob["token"], thread))
    store.private_accept(bob["token"], thread)
    assert store.private_read(bob["token"], thread)["messages"][0]["body"] == "TEST saved greeting"


@pytest.mark.parametrize("change", ["private", "optout", "deleted", "recreated", "recipient_block",
                                    "sender_block", "suspended", "closed"])
def test_a_stale_directory_card_does_not_override_current_recipient_state(store, change):
    alice, bob = account(store, "TEST_Alice"), account(store, "TEST_Bob")
    profile_id = listed(store, bob)
    if change == "private":
        profile(store, bob, visibility="private")
    elif change == "optout":
        profile(store, bob, allow_invitations=False)
    elif change in {"deleted", "recreated"}:
        store.profile_delete(bob["token"], store.profile_get(bob["token"])["revision"])
        if change == "recreated":
            assert listed(store, bob) != profile_id
    elif change == "recipient_block":
        store.block(bob["token"], alice["id"], True)
    elif change == "sender_block":
        store.block(alice["token"], bob["id"], True)
    elif change == "suspended":
        with store._db() as db:
            db.execute("INSERT INTO participant_controls VALUES(?,1,'harassment',?)", (bob["id"], store.clock()))
    elif change == "closed":
        close_account(store, bob)
    denied(404, lambda: invite(store, alice, profile_id))
    assert counts(store) == (0, 0, 0)


def test_guests_self_invites_and_inactive_senders_cannot_use_the_directory(store):
    alice = account(store, "TEST_Alice")
    profile_id = listed(store, alice)
    guest, _ = store.join("TEST guest", "")
    denied(403, lambda: store.profile_invite(guest, profile_id, "TEST guest request", "a" * 32))
    denied(400, lambda: invite(store, alice, profile_id))
    denied(401, lambda: store.profile_invite(None, profile_id, "TEST no session", "b" * 32))
    store.leave(alice["token"])
    denied(401, lambda: invite(store, alice, profile_id))
    assert counts(store) == (0, 0, 0)


def test_owner_role_cannot_override_directory_consent_or_blocks(store):
    pyotp = pytest.importorskip("pyotp")
    secret = pyotp.random_base32()
    store.owner_bootstrap(PASSWORD, secret, pyotp.TOTP(secret).at(store.clock()))
    store.test_clock[0] += 30
    token, result = store.owner_login("CLRYAN86", PASSWORD, pyotp.TOTP(secret).at(store.clock()))
    owner = {"token": token, "id": result["viewer"]["id"], "name": "CLRYAN86"}
    bob = account(store, "TEST_Bob")
    profile_id = listed(store, bob, allow=False)
    denied(404, lambda: invite(store, owner, profile_id))
    profile(store, bob, allow_invitations=True, visibility="private")
    denied(404, lambda: invite(store, owner, profile_id))
    profile(store, bob, visibility="commons")
    store.block(bob["token"], owner["id"], True)
    denied(404, lambda: invite(store, owner, profile_id))
    assert counts(store) == (0, 0, 0)


@pytest.mark.parametrize("profile_id", [None, True, [], "a" * 24, "g" * 32])
def test_malformed_or_non_profile_identifiers_never_become_contact_codes(store, profile_id):
    alice = account(store, "TEST_Alice")
    denied(404, lambda: invite(store, alice, profile_id))
    assert counts(store) == (0, 0, 0)


@pytest.mark.parametrize("change", ["optout", "deleted", "recreated", "blocked", "closed"])
def test_exact_lost_reply_retries_return_only_existing_receipts_after_consent_changes(store, change):
    alice, bob = account(store, "TEST_Alice"), account(store, "TEST_Bob")
    profile_id = listed(store, bob)
    first = invite(store, alice, profile_id)
    if change == "optout":
        profile(store, bob, allow_invitations=False)
    elif change in {"deleted", "recreated"}:
        store.profile_delete(bob["token"], store.profile_get(bob["token"])["revision"])
        if change == "recreated":
            replacement_id = listed(store, bob)
            denied(409, lambda: invite(store, alice, replacement_id))
    elif change == "blocked":
        store.block(bob["token"], alice["id"], True)
    elif change == "closed":
        close_account(store, bob)
    result = invite(store, alice, profile_id)
    assert result == {**first, "duplicate": True}
    assert counts(store) == (1, 1, 1)
    denied(409, lambda: invite(store, alice, profile_id, title="TEST changed subject"))
    assert bob["id"] not in json.dumps(result)


def test_closed_receipts_survive_restart_and_cannot_recreate_a_deleted_profile(store):
    alice, bob = account(store, "TEST_Alice"), account(store, "TEST_Bob")
    profile_id = listed(store, bob)
    first = invite(store, alice, profile_id)
    store.private_leave(alice["token"], first["thread"])
    store.private_leave(bob["token"], first["thread"])
    store.profile_delete(bob["token"], store.profile_get(bob["token"])["revision"])
    reopened = AccountLifecycleStore(store.path, clock=store.clock)
    assert invite(reopened, alice, profile_id) == {**first, "duplicate": True, "closed": True}
    assert counts(reopened) == (0, 1, 1)
    denied(404, lambda: reopened.private_read(alice["token"], first["thread"]))
    store.test_clock[0] += private_chat.INVITATION_RETRY_SECONDS
    sign_in(reopened, alice)
    reopened.expire_private_messages()
    assert counts(reopened) == (0, 0, 0)
    denied(404, lambda: invite(reopened, alice, profile_id))
    assert counts(reopened) == (0, 0, 0)


def test_request_ids_bind_directory_target_title_and_contact_source(store):
    alice, bob, carol = [account(store, name) for name in ("TEST_Alice", "TEST_Bob", "TEST_Carol")]
    bob_profile, carol_profile = listed(store, bob), listed(store, carol)
    original = invite(store, alice, bob_profile)
    denied(409, lambda: invite(store, alice, carol_profile))
    denied(409, lambda: contact_invite(store, alice, [bob]))
    contact_invite(store, alice, [carol], key=2)
    denied(409, lambda: invite(store, alice, carol_profile, key=2))
    assert invite(store, alice, bob_profile) == {**original, "duplicate": True}
    assert counts(store) == (2, 2, 2)


def test_both_invitation_sources_share_contact_cooldown_and_exact_boundary(store):
    alice, bob = account(store, "TEST_Alice"), account(store, "TEST_Bob")
    profile_id = listed(store, bob)
    contact_invite(store, alice, [bob])
    denied(429, lambda: invite(store, alice, profile_id, key=2))
    store.test_clock[0] += private_chat.INVITATION_COOLDOWN
    invite(store, alice, profile_id, key=2)
    denied(429, lambda: contact_invite(store, alice, [bob], key=3))
    assert counts(store) == (2, 2, 2)


def test_directory_invites_share_group_weighted_daily_allowance(store, monkeypatch):
    monkeypatch.setattr(private_chat, "MAX_DAILY_INVITATIONS", 2)
    alice, bob, carol, dana = [account(store, name) for name in
                              ("TEST_Alice", "TEST_Bob", "TEST_Carol", "TEST_Dana")]
    profile_id = listed(store, dana)
    contact_invite(store, alice, [bob, carol])
    denied(429, lambda: invite(store, alice, profile_id, key=2))
    assert counts(store) == (1, 1, 2)
    store.test_clock[0] += private_chat.INVITATION_WINDOW
    sign_in(store, alice)
    invite(store, alice, profile_id, key=2)
    assert counts(store) == (2, 2, 3)


@pytest.mark.parametrize("limit", ["MAX_THREADS", "MAX_MEMBER_THREADS", "MAX_INVITATION_RECEIPTS"])
def test_directory_invites_share_database_capacity_and_failure_is_atomic(store, monkeypatch, limit):
    monkeypatch.setattr(private_chat, limit, 1)
    alice, bob, carol = [account(store, name) for name in ("TEST_Alice", "TEST_Bob", "TEST_Carol")]
    profile_id = listed(store, bob)
    contact_invite(store, carol, [bob])
    denied(429 if limit == "MAX_INVITATION_RECEIPTS" else 409,
           lambda: invite(store, alice, profile_id))
    assert counts(store) == (1, 1, 1)
    assert store.private_inbox(alice["token"])["threads"] == []


def test_concurrent_retries_create_one_invitation_and_one_quota_receipt(store):
    alice, bob = account(store, "TEST_Alice"), account(store, "TEST_Bob")
    profile_id = listed(store, bob)
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(lambda _: invite(store, alice, profile_id), range(2)))
    assert results[0]["thread"] == results[1]["thread"]
    assert {result["duplicate"] for result in results} == {True, False}
    assert counts(store) == (1, 1, 1)


def test_competing_contact_and_directory_requests_cannot_bypass_shared_cooldown(store):
    alice, bob = account(store, "TEST_Alice"), account(store, "TEST_Bob")
    profile_id = listed(store, bob)

    def submit(directory):
        try:
            return invite(store, alice, profile_id) if directory else contact_invite(store, alice, [bob], key=2)
        except ChatError as error:
            return error.status

    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(submit, (True, False)))
    assert sum(isinstance(value, dict) for value in results) == 1 and 429 in results
    assert counts(store) == (1, 1, 1)


def test_profile_consent_check_and_creation_hold_one_write_transaction(store, monkeypatch):
    alice, bob = account(store, "TEST_Alice"), account(store, "TEST_Bob")
    profile_id = listed(store, bob)
    original = store._visible
    observed = []

    def checked(db, member, row):
        # A concurrent opt-out cannot commit between the consent read and insert.
        with sqlite3.connect(store.path, timeout=0) as competing:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competing.execute("BEGIN IMMEDIATE")
        observed.append(db.in_transaction)
        return original(db, member, row)

    monkeypatch.setattr(store, "_visible", checked)
    invite(store, alice, profile_id)
    assert observed == [True] and counts(store) == (1, 1, 1)


def test_http_directory_invitation_is_strict_authenticated_and_does_not_disclose_contacts(preview_server):
    store = preview_server.app.store
    alice, bob = account(store, "TEST_Alice"), account(store, "TEST_Bob")
    profile_id = listed(store, bob)
    payload = {"profile_id": profile_id, "title": "TEST HTTP invitation", "request_id": "a" * 32}
    for options in ({"origin": False}, {"custom": False}, {"origin": "https://attacker.invalid"}):
        assert api(preview_server, INVITE_API, payload, token=alice["token"], **options)[0] == 403
    assert api(preview_server, INVITE_API, payload)[0] == 401
    for extra in ({"contacts": [bob["id"]]}, {"kind": "group"}, {"owner": bob["id"]}, {"role": "owner"}):
        assert api(preview_server, INVITE_API, {**payload, **extra}, token=alice["token"])[0] == 400
    for field in payload:
        missing = {key: value for key, value in payload.items() if key != field}
        assert api(preview_server, INVITE_API, missing, token=alice["token"])[0] == 400
    # A cookie changed in another tab cannot invite as the newly signed-in member.
    assert test_commons_profiles.bound_api(preview_server, "profile/invite", payload,
                                          bob["token"], alice["id"])[0] == 401
    assert counts(store) == (0, 0, 0)
    status, _, body = api(preview_server, INVITE_API, payload, token=alice["token"])
    first = json.loads(body)
    assert status == 200 and set(first) == {"thread", "duplicate", "closed"}
    assert bob["id"].encode() not in body and alice["id"].encode() not in body
    profile(store, bob, allow_invitations=False)
    retry_status, _, retry_body = api(preview_server, INVITE_API, payload, token=alice["token"])
    assert retry_status == 200 and json.loads(retry_body) == {**first, "duplicate": True}
    assert api(preview_server, INVITE_API, {**payload, "request_id": "b" * 32}, token=alice["token"])[0] == 404
    assert counts(store) == (1, 1, 1)
