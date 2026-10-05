"""Account closure, retained-data export, and temporary export authorization."""

import base64
import hashlib
import io
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from fieldforge.online import accounts, chat_store
from fieldforge.online.account_lifecycle import (
    EXPORT_PAGE_SIZE,
    EXPORT_SECONDS,
    AccountLifecycleStore,
)
from fieldforge.online.accounts import AUTH_WINDOW, AccountStore
from fieldforge.online.chat_store import ChatError, ChatStore
from fieldforge.online.owner import OWNER_USERNAME, OwnerStore
from fieldforge.online.private_chat import INVITATION_COOLDOWN, PrivateChatStore
from fieldforge.online.profiles import PROFILE_FIELDS, ProfileStore

PASSWORD = "TEST lifecycle: river maple trail"
OTHER_PASSWORD = "TEST lifecycle: a different passphrase"
SECTIONS = ("public_messages", "private_messages", "public_reports", "private_reports")


@pytest.fixture
def store(tmp_path):
    now = [1_800_000_000.0]
    result = AccountLifecycleStore(tmp_path / "lifecycle.sqlite3", clock=lambda: now[0])
    result.test_clock = now
    result.test_sequence = 0
    return result


def account(store, name="TEST_Alice"):
    token, result = store.account_register(name, PASSWORD, "navigation")
    return {"token": token, "id": result["viewer"]["id"], "name": name,
            "recovery": result["recovery_code"]}


def request_id(store):
    store.test_sequence += 1
    return f"{store.test_sequence:032x}"


def invite(store, sender, recipients, title="TEST retained conversation"):
    return store.private_create(sender["token"], title, "direct" if len(recipients) == 1 else "group",
                                [person["id"] for person in recipients], request_id(store))["thread"]


def public_message(store, sender, body, room="general"):
    store.test_clock[0] += 2
    return store.send(sender["token"], room, body, request_id(store))["id"]


def private_message(store, sender, thread, body, lifetime="saved"):
    store.test_clock[0] += 2
    return store.private_send(sender["token"], thread, body, lifetime, request_id(store))["id"]


def save_profile(store, person, **changes):
    result = store.profile_get(person["token"])
    value = {key: result["profile"][key] for key in PROFILE_FIELDS}
    value.update(changes)
    return store.profile_save(person["token"], value, result["revision"])


def photo(store, person):
    image = pytest.importorskip("PIL.Image")
    metadata = pytest.importorskip("PIL.PngImagePlugin").PngInfo()
    metadata.add_text("comment", "TEST photo metadata must not be exported")
    stream = io.BytesIO()
    image.new("RGB", (16, 12), (20, 70, 120)).save(stream, format="PNG", pnginfo=metadata)
    revision = store.profile_get(person["token"])["revision"]
    result = store.profile_photo_upload(person["token"], base64.b64encode(stream.getvalue()).decode(), revision)
    return result["profile"]["photo_asset_id"]


def assert_status(status, operation):
    with pytest.raises(ChatError) as error:
        operation()
    assert error.value.status == status


def close(store, person, **changes):
    values = {"token": person["token"], "password": PASSWORD, "username": person["name"], "confirm": True}
    values.update(changes)
    return store.account_close(**values)


def begin_export(store, person):
    return store.account_export(person["token"], PASSWORD)


def page(store, person, grant, section="public_messages", after=0):
    return store.account_export_page(person["token"], grant["export_token"], section, after)


def collect_export(store, person, grant):
    sections = {}
    for section in SECTIONS:
        records, after = [], 0
        while True:
            result = page(store, person, grant, section, after)
            assert result["section"] == section
            assert len(result["records"]) <= EXPORT_PAGE_SIZE
            records.extend(result["records"])
            if result["next_after"] is None:
                break
            assert result["next_after"] > after
            after = result["next_after"]
        sections[section] = records
    return sections


def delivery_state(store):
    with store._db() as db:
        return [tuple(row) for row in db.execute(
            "SELECT message,recipient,opened FROM private_deliveries ORDER BY message,recipient")]


def test_close_requires_current_password_own_username_and_boolean_confirmation(store):
    alice = account(store)
    message = public_message(store, alice, "TEST preserve this until confirmed")
    save_profile(store, alice, bio="TEST profile remains on rejected closure")
    for confirmation in (False, 1, "true", None):
        assert_status(400, lambda: close(store, alice, confirm=confirmation))
    assert_status(400, lambda: close(store, alice, username="TEST_SomeoneElse"))
    assert_status(403, lambda: close(store, alice, password=OTHER_PASSWORD))
    assert store.account_resume(alice["token"])["viewer"]["id"] == alice["id"]
    assert store.profile_get(alice["token"])["profile"]["bio"] == "TEST profile remains on rejected closure"
    with store._db() as db:
        assert db.execute("SELECT body,deleted FROM messages WHERE id=?", (message,)).fetchone()[:] == (
            "TEST preserve this until confirmed", 0)
        assert db.execute("SELECT COUNT(*) FROM closed_accounts").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1


def test_lifecycle_operations_require_an_authenticated_saved_account(store):
    token, _ = store.join("TEST guest", "")
    for operation in (lambda: store.account_close(token, PASSWORD, "TEST_Guest", True),
                      lambda: store.account_export(token, PASSWORD)):
        assert_status(403, operation)
    for operation in (lambda: store.account_close(None, PASSWORD, "TEST_Alice", True),
                      lambda: store.account_export(None, PASSWORD)):
        assert_status(401, operation)


@pytest.mark.parametrize("guard", ["username", "configuration"])
def test_sole_owner_cannot_close_even_without_an_owner_grant(store, guard):
    owner = account(store, "TEST_OwnerFixture")
    with store._db() as db:
        if guard == "username":
            db.execute("UPDATE accounts SET username=? WHERE participant=?", (OWNER_USERNAME, owner["id"]))
            owner["name"] = OWNER_USERNAME
        else:
            db.execute("INSERT INTO owner_config VALUES(1,?,?,0)", (owner["id"], "TEST-FIXTURE-ONLY"))
        attempts = db.execute("SELECT SUM(attempts) FROM auth_attempts").fetchone()[0]
    assert_status(403, lambda: close(store, owner))
    with store._db() as db:
        assert db.execute("SELECT SUM(attempts) FROM auth_attempts").fetchone()[0] == attempts
        assert db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM closed_accounts").fetchone()[0] == 0
    assert store.account_resume(owner["token"])["viewer"]["id"] == owner["id"]


def test_close_rechecks_owner_protection_after_waiting_for_password_limit(store, monkeypatch):
    owner = account(store, "TEST_OwnerFixture")
    attempt = store._attempt

    @contextmanager
    def owner_installed_while_waiting(username):
        with attempt(username):
            with store._db() as db:
                db.execute("INSERT INTO owner_config VALUES(1,?,?,0)", (owner["id"], "TEST-FIXTURE-ONLY"))
            yield

    monkeypatch.setattr(store, "_attempt", owner_installed_while_waiting)
    assert_status(403, lambda: close(store, owner))
    assert store.account_resume(owner["token"])["viewer"]["id"] == owner["id"]


def test_close_withdraws_own_data_and_preserves_other_readers_and_safety_references(store):
    alice, bob, carol, dana = [account(store, name) for name in
                              ("TEST_Alice", "TEST_Bob", "TEST_Carol", "TEST_Dana")]
    own_public = public_message(store, alice, "TEST own public body must disappear")
    other_public = public_message(store, bob, "TEST other public body remains")
    thread = invite(store, alice, [bob, carol])
    for person in (bob, carol):
        store.private_accept(person["token"], thread)
    own_saved = private_message(store, alice, thread, "TEST own saved body must disappear")
    own_once = private_message(store, alice, thread, "TEST own once body must disappear", "view_once")
    other_saved = private_message(store, bob, thread, "TEST other saved body remains")
    other_once = private_message(store, bob, thread, "TEST third participant may still open", "view_once")
    store.report(alice["token"], other_public, "other")
    store.report(bob["token"], own_public, "spam")
    store.private_report(alice["token"], thread, other_saved, "other")
    store.private_report(bob["token"], thread, own_saved, "spam")
    store.block(alice["token"], dana["id"], True)
    store.block(carol["token"], alice["id"], True)
    save_profile(store, alice, visibility="commons", bio="TEST own profile to remove")
    asset = photo(store, alice)
    save_profile(store, alice, share_photo=True)
    grant = begin_export(store, alice)
    with store._db() as db:
        db.execute("INSERT INTO participant_controls VALUES(?,0,'other',?)", (alice["id"], store.clock()))
        db.execute("INSERT INTO moderation_resolutions VALUES('public',?,'retained','other',?)",
                   (own_public, store.clock()))
        store._audit(db, "test_prior_audit", alice["id"])
        assert db.execute("SELECT opened FROM private_deliveries WHERE message=? AND recipient=?",
                          (other_once, alice["id"])).fetchone()[0] is None

    closed_at = store.clock()
    assert close(store, alice, username=alice["name"].swapcase()) == {"closed": True}
    with store._db() as db:
        member = dict(db.execute("SELECT * FROM participants WHERE id=?", (alice["id"],)).fetchone())
        assert member == {"id": alice["id"], "name": "Closed account", "name_key": "closed:" + alice["id"],
                          "skill": "", "token_hash": None, "expires": 0, "last_sent": 0}
        tombstone = dict(db.execute("SELECT * FROM closed_accounts").fetchone())
        assert tombstone == {"participant": alice["id"], "closed": closed_at,
                             "username_hash": hashlib.sha256(alice["name"].lower().encode()).hexdigest()}
        for table in ("accounts", "profiles", "account_exports"):
            assert db.execute(f"SELECT 1 FROM {table} WHERE participant=?", (alice["id"],)).fetchone() is None
        assert db.execute("SELECT body,deleted FROM messages WHERE id=?", (own_public,)).fetchone()[:] == ("", 1)
        assert db.execute("SELECT body FROM messages WHERE id=?", (other_public,)).fetchone()[0] == (
            "TEST other public body remains")
        for message in (own_saved, own_once):
            assert db.execute("SELECT body,redacted FROM private_messages WHERE id=?", (message,)).fetchone()[:] == (
                "", "deleted")
        assert db.execute("SELECT body FROM private_messages WHERE id=?", (other_saved,)).fetchone()[0] == (
            "TEST other saved body remains")
        assert db.execute("SELECT body,redacted FROM private_messages WHERE id=?", (other_once,)).fetchone()[:] == (
            "TEST third participant may still open", "")
        assert db.execute("SELECT opened FROM private_deliveries WHERE message=? AND recipient=?",
                          (other_once, alice["id"])).fetchone()[0] == closed_at
        assert db.execute("SELECT opened FROM private_deliveries WHERE message=? AND recipient=?",
                          (other_once, carol["id"])).fetchone()[0] is None
        assert db.execute("SELECT status FROM private_members WHERE thread=? AND participant=?",
                          (thread, alice["id"])).fetchone()[0] == "left"
        assert db.execute("SELECT closed FROM private_invitation_receipts WHERE thread=?", (thread,)).fetchone()[0] is None
        assert db.execute("SELECT 1 FROM blocks WHERE viewer=?", (alice["id"],)).fetchone() is None
        assert db.execute("SELECT target FROM blocks WHERE viewer=?", (carol["id"],)).fetchone()[0] == alice["id"]
        assert db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM private_reports").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM moderation_resolutions").fetchone()[0] == 1
        assert db.execute("SELECT participant FROM participant_controls").fetchone()[0] == alice["id"]
        assert db.execute("SELECT target,reason FROM owner_audit WHERE event='account_closed'").fetchone()[:] == (
            alice["id"], "")
        assert db.execute("SELECT COUNT(*) FROM owner_audit").fetchone()[0] == 2
        assert db.execute("SELECT 1 FROM auth_attempts WHERE bucket=?", ("user:" + alice["name"].lower(),)).fetchone() is None
        assert db.execute("SELECT attempts FROM auth_attempts WHERE bucket='global'").fetchone()[0] > 0
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    shown = next(row for row in store.read(bob["token"], "general")["messages"] if row["id"] == own_public)
    assert shown["name"] == "Closed account" and shown["body"] == "" and shown["deleted"]
    assert store.private_open_once(carol["token"], thread, other_once)["body"] == "TEST third participant may still open"
    assert store.profile_directory(bob["token"], "", "", 0)["profiles"] == []
    assert_status(404, lambda: store.profile_photo_read(bob["token"], asset))
    assert_status(401, lambda: page(store, alice, grant))


def test_closing_last_member_reclaims_thread_and_keeps_closed_retry_receipt(store):
    alice, bob = account(store), account(store, "TEST_Bob")
    thread = invite(store, alice, [bob])
    private_message(store, alice, thread, "TEST inaccessible after final close")
    store.private_leave(bob["token"], thread)
    assert close(store, alice) == {"closed": True}
    with store._db() as db:
        assert db.execute("SELECT COUNT(*) FROM private_threads").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM private_messages").fetchone()[0] == 0
        receipt = db.execute("SELECT thread,owner,closed FROM private_invitation_receipts").fetchone()
        assert receipt[:] == (thread, alice["id"], store.clock())
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_closing_an_invited_recipient_consumes_once_delivery_and_preserves_sender_history(store):
    alice, bob = account(store), account(store, "TEST_Bob")
    thread = invite(store, bob, [alice])
    saved = private_message(store, bob, thread, "TEST sender retains their saved letter")
    once = private_message(store, bob, thread, "TEST no recipient remains for this once body", "view_once")
    assert close(store, alice) == {"closed": True}
    with store._db() as db:
        assert db.execute("SELECT status FROM private_members WHERE thread=? AND participant=?",
                          (thread, alice["id"])).fetchone()[0] == "left"
        assert db.execute("SELECT body FROM private_messages WHERE id=?", (saved,)).fetchone()[0] == (
            "TEST sender retains their saved letter")
        assert db.execute("SELECT body,redacted FROM private_messages WHERE id=?", (once,)).fetchone()[:] == ("", "opened")
        assert db.execute("SELECT opened FROM private_deliveries WHERE message=? AND recipient=?",
                          (once, alice["id"])).fetchone()[0] == store.clock()
        assert db.execute("SELECT closed FROM private_invitation_receipts WHERE thread=?", (thread,)).fetchone()[0] is None
    assert store.private_inbox(bob["token"])["threads"][0]["id"] == thread


def test_close_is_terminal_and_closed_username_stays_reserved_across_store_layers(store):
    alice = account(store)
    close(store, alice)
    reopened = AccountLifecycleStore(store.path, clock=store.clock)
    assert_status(401, lambda: reopened.account_resume(alice["token"]))
    assert_status(401, lambda: close(reopened, alice))
    assert_status(401, lambda: reopened.account_login(alice["name"], PASSWORD))
    assert_status(401, lambda: reopened.account_recover(alice["name"], alice["recovery"], OTHER_PASSWORD))
    for constructor in (ChatStore, PrivateChatStore, AccountStore, OwnerStore, ProfileStore, AccountLifecycleStore):
        modular = constructor(store.path, clock=store.clock)
        assert_status(409, lambda: modular.join(alice["name"].swapcase(), ""))
    assert_status(409, lambda: reopened.account_register(alice["name"].upper(), PASSWORD, "", alice["token"]))
    token, different = reopened.account_register("TEST_NewIdentity", PASSWORD, "", alice["token"])
    assert different["viewer"]["id"] != alice["id"]
    assert reopened.account_resume(token)["viewer"]["username"] == "test_newidentity"


def test_closed_label_is_reserved_for_guest_names_and_saved_profiles(store):
    alice = account(store)
    for name in ("Closed account", "CLOSED ACCOUNT", " closed   account "):
        assert_status(400, lambda: store.join(name, ""))
        assert_status(400, lambda: save_profile(store, alice, display_name=name))


def test_owner_profile_keeps_king_display_name_but_cannot_claim_the_closed_label(store):
    pyotp = pytest.importorskip("pyotp", reason="Install the commons extra for owner MFA tests")
    secret = pyotp.random_base32()
    store.owner_bootstrap(PASSWORD, secret, pyotp.TOTP(secret).at(store.clock()))
    store.test_clock[0] += 30
    token, result = store.owner_login(OWNER_USERNAME, PASSWORD, pyotp.TOTP(secret).at(store.clock()))
    owner = {"token": token, "id": result["viewer"]["id"]}
    saved = save_profile(store, owner, display_name="King")
    assert saved["profile"]["display_name"] == "King"
    for name in ("Closed account", "CLOSED ACCOUNT", " closed   account "):
        assert_status(400, lambda: save_profile(store, owner, display_name=name))
    retained = store.profile_get(token)
    assert retained["profile"]["display_name"] == "King"
    assert retained["revision"] == saved["revision"]


def test_closure_does_not_recycle_participant_capacity(store, monkeypatch):
    monkeypatch.setattr(accounts, "MAX_PARTICIPANTS", 2)
    monkeypatch.setattr(chat_store, "MAX_PARTICIPANTS", 2)
    alice = account(store)
    account(store, "TEST_Bob")
    close(store, alice)
    assert_status(409, lambda: account(store, "TEST_Carol"))
    assert_status(409, lambda: store.join("TEST guest", ""))
    with store._db() as db:
        assert db.execute("SELECT COUNT(*) FROM participants").fetchone()[0] == 2


def test_concurrent_closure_commits_once_and_never_reuses_revoked_authentication(store):
    alice = account(store)

    def attempt(_):
        try:
            return close(store, alice)
        except ChatError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, range(2)))
    assert results.count({"closed": True}) == 1
    assert results.count(401) == 1
    with store._db() as db:
        assert db.execute("SELECT COUNT(*) FROM closed_accounts").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM owner_audit WHERE event='account_closed'").fetchone()[0] == 1


def test_interrupted_closure_rolls_back_account_content_profile_and_grant(store, monkeypatch):
    alice = account(store)
    message = public_message(store, alice, "TEST atomic closure body")
    save_profile(store, alice, bio="TEST atomic closure profile")
    grant = begin_export(store, alice)

    def fail_audit(*args):
        raise RuntimeError("TEST simulated transaction interruption")

    monkeypatch.setattr(store, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="simulated transaction interruption"):
        close(store, alice)
    assert store.account_resume(alice["token"])["viewer"]["id"] == alice["id"]
    assert store.profile_get(alice["token"])["profile"]["bio"] == "TEST atomic closure profile"
    assert page(store, alice, grant)["records"][0]["id"] == message
    with store._db() as db:
        assert db.execute("SELECT COUNT(*) FROM closed_accounts").fetchone()[0] == 0
        assert db.execute("SELECT body,deleted FROM messages WHERE id=?", (message,)).fetchone()[:] == (
            "TEST atomic closure body", 0)


@pytest.mark.parametrize("operation", ["close", "export"])
def test_password_reattempt_limits_survive_restart_and_expire(store, monkeypatch, operation):
    alice = account(store)
    monkeypatch.setattr(accounts, "AUTH_ACCOUNT_LIMIT", 2)

    def perform(current, password):
        if operation == "close":
            return close(current, alice, password=password)
        return current.account_export(alice["token"], password)

    assert_status(403, lambda: perform(store, OTHER_PASSWORD))
    assert_status(429, lambda: perform(store, PASSWORD))
    reopened = AccountLifecycleStore(store.path, clock=store.clock)
    assert_status(429, lambda: perform(reopened, PASSWORD))
    assert reopened.account_resume(alice["token"])["viewer"]["id"] == alice["id"]
    store.test_clock[0] += AUTH_WINDOW
    assert perform(reopened, PASSWORD)


@pytest.mark.parametrize("operation", ["close", "export"])
def test_logout_while_waiting_for_reauthentication_invalidates_the_operation(store, monkeypatch, operation):
    alice = account(store)
    attempt = store._attempt

    @contextmanager
    def session_ended_while_waiting(username):
        with attempt(username):
            store.leave(alice["token"])
            yield

    monkeypatch.setattr(store, "_attempt", session_ended_while_waiting)
    assert_status(401, lambda: close(store, alice) if operation == "close" else begin_export(store, alice))
    with store._db() as db:
        assert db.execute("SELECT participant FROM accounts").fetchone()[0] == alice["id"]
        assert db.execute("SELECT COUNT(*) FROM closed_accounts").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM account_exports").fetchone()[0] == 0


def test_export_contains_only_retained_own_content_and_never_consumes_deliveries(store):
    alice, bob, carol, dana = [account(store, name) for name in
                              ("TEST_Alice", "TEST_Bob", "TEST_Carol", "TEST_Dana")]
    own_public = public_message(store, alice, "TEST export own public")
    other_public = public_message(store, bob, "TEST other public must not be exported")
    withdrawn = public_message(store, alice, "TEST withdrawn public must not be exported")
    store.delete(alice["token"], withdrawn)
    owned = invite(store, alice, [bob], title="TEST owned conversation title")
    store.private_accept(bob["token"], owned)
    own_saved = private_message(store, alice, owned, "TEST own saved after leaving")
    other_saved = private_message(store, bob, owned, "TEST other private must not be exported")
    own_once = private_message(store, alice, owned, "TEST own once must not be exported", "view_once")
    deleted_saved = private_message(store, alice, owned, "TEST withdrawn private must not be exported")
    store.private_delete(alice["token"], owned, deleted_saved)
    store.report(alice["token"], other_public, "other")
    store.report(bob["token"], own_public, "spam")
    store.private_report(alice["token"], owned, other_saved, "other")
    store.private_report(bob["token"], owned, own_saved, "spam")
    store.private_leave(alice["token"], owned)
    received = invite(store, bob, [alice], title="TEST other creator title must not be exported")
    store.private_accept(alice["token"], received)
    private_message(store, bob, received, "TEST unread saved remains unread")
    private_message(store, bob, received, "TEST incoming once must not be exported", "view_once")
    save_profile(store, alice, bio="TEST own profile", assessment={"interests": ["navigation"],
                 "experience": {"navigation": "learning"}, "contributions": ["teach"]})
    asset = photo(store, alice)
    save_profile(store, bob, bio="TEST other bio must not be exported")
    store.block(alice["token"], dana["id"], True)
    store.block(carol["token"], alice["id"], True)
    before = delivery_state(store)

    grant = begin_export(store, alice)
    sections = collect_export(store, alice, grant)
    manifest = grant["manifest"]
    assert manifest["format"] == "fieldforge-commons-account" and manifest["version"] == 1
    assert manifest["account"]["participant"] == alice["id"]
    assert manifest["account"]["username"] == alice["name"].lower()
    assert manifest["profile"]["bio"] == "TEST own profile"
    assert manifest["profile"]["assessment"]["experience"] == {"navigation": "learning"}
    assert set(manifest["profile"]) == PROFILE_FIELDS
    stored_photo = store.profile_photo_read(alice["token"], asset)
    assert manifest["photo"] == {key: stored_photo[key] for key in ("mime_type", "encoded")}
    assert b"TEST photo metadata" not in base64.b64decode(manifest["photo"]["encoded"])
    assert [(row["id"], row["status"]) for row in manifest["conversations"]] == [(owned, "left")]
    assert manifest["blocks"] == [{"target": dana["id"], "name": dana["name"]}]
    assert manifest["totals"] == {section: 1 for section in SECTIONS}
    assert sections["public_messages"][0]["id"] == own_public
    assert sections["private_messages"][0]["id"] == own_saved
    assert sections["private_messages"][0]["body"] == "TEST own saved after leaving"
    assert sections["public_reports"][0]["message"] == other_public
    assert sections["private_reports"][0]["message"] == other_saved
    assert set(sections["public_reports"][0]) == {"message", "reason", "created"}
    assert set(sections["private_reports"][0]) == {"message", "reason", "created"}
    artifact = json.dumps({"manifest": manifest, "sections": sections})
    for forbidden in ("must not be exported", "unread saved remains unread", "password", "recovery", "token_hash",
                      "session_hash", "opened", alice["token"], alice["recovery"], grant["export_token"], carol["id"]):
        assert forbidden not in artifact
    assert own_once not in {row["id"] for row in sections["private_messages"]}
    assert delivery_state(store) == before


def test_empty_account_export_is_explicit_and_does_not_create_a_profile(store):
    alice = account(store)
    grant = begin_export(store, alice)
    manifest = grant["manifest"]
    assert manifest["profile"] is None and manifest["photo"] is None
    assert manifest["conversations"] == [] and manifest["blocks"] == []
    assert manifest["totals"] == {section: 0 for section in SECTIONS}
    assert collect_export(store, alice, grant) == {section: [] for section in SECTIONS}
    with store._db() as db:
        assert db.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 0


def test_export_grant_is_hashed_replaced_and_bound_to_the_current_account(store):
    alice, bob = account(store), account(store, "TEST_Bob")
    first = begin_export(store, alice)
    second = begin_export(store, alice)
    assert second["export_token"] != first["export_token"]
    assert_status(410, lambda: page(store, alice, first))
    assert_status(410, lambda: page(store, bob, second))
    assert page(store, alice, second)["records"] == []
    with store._db() as db:
        row = dict(db.execute("SELECT * FROM account_exports").fetchone())
        assert row["participant"] == alice["id"]
        assert row["token_hash"] == hashlib.sha256(second["export_token"].encode()).hexdigest()
        assert row["session_hash"] == hashlib.sha256(alice["token"].encode()).hexdigest()
        assert row["expires"] == store.clock() + EXPORT_SECONDS
        assert db.execute("SELECT COUNT(*) FROM account_exports").fetchone()[0] == 1


def test_export_grant_has_an_absolute_five_minute_expiry_without_signing_out(store):
    alice = account(store)
    grant = begin_export(store, alice)
    store.test_clock[0] += EXPORT_SECONDS - 1
    assert page(store, alice, grant)["records"] == []
    store.test_clock[0] += 1
    assert_status(410, lambda: page(store, alice, grant))
    assert_status(410, lambda: store.account_export_finish(alice["token"], grant["export_token"]))
    assert store.account_resume(alice["token"])["viewer"]["id"] == alice["id"]


@pytest.mark.parametrize("rotation", ["login", "password", "recovery"])
def test_export_cannot_follow_a_session_or_credential_rotation(store, rotation):
    alice = account(store)
    grant = begin_export(store, alice)
    old_token = alice["token"]
    if rotation == "login":
        alice["token"], _ = store.account_login(alice["name"], PASSWORD)
    elif rotation == "password":
        alice["token"], _ = store.account_change_password(old_token, PASSWORD, OTHER_PASSWORD)
    else:
        store.account_recover(alice["name"], alice["recovery"], OTHER_PASSWORD)
        alice["token"], _ = store.account_login(alice["name"], OTHER_PASSWORD)
    assert_status(401, lambda: store.account_export_page(old_token, grant["export_token"], "public_messages", 0))
    assert_status(410, lambda: page(store, alice, grant))
    assert store.account_resume(alice["token"])["viewer"]["id"] == alice["id"]


def test_finishing_export_revokes_only_that_grant(store):
    alice, bob = account(store), account(store, "TEST_Bob")
    first, other = begin_export(store, alice), begin_export(store, bob)
    assert store.account_export_finish(alice["token"], first["export_token"]) == {"ok": True}
    assert_status(410, lambda: page(store, alice, first))
    assert_status(410, lambda: store.account_export_finish(alice["token"], first["export_token"]))
    assert page(store, bob, other)["records"] == []
    assert store.account_resume(alice["token"])["viewer"]["id"] == alice["id"]


def test_export_rejects_invalid_references_sections_and_cursors(store):
    alice = account(store)
    grant = begin_export(store, alice)
    for reference in (None, "", "x" * 42, "x" * 44, "!" * 43, 1):
        assert_status(400, lambda: store.account_export_page(alice["token"], reference, "public_messages", 0))
    assert_status(410, lambda: store.account_export_page(alice["token"], "x" * 43, "public_messages", 0))
    for section in (None, 1, "accounts", "private_deliveries", "public_messages; DROP TABLE accounts"):
        assert_status(400, lambda: page(store, alice, grant, section))
    for after in (None, True, False, -1, "0", 0.5, 2**63):
        assert_status(400, lambda: page(store, alice, grant, after=after))
    assert page(store, alice, grant, after=2**63 - 1)["records"] == []


def test_export_ceilings_exclude_later_posts_and_explain_concurrent_withdrawal(store):
    alice, bob = account(store), account(store, "TEST_Bob")
    public_message(store, alice, "TEST first retained public")
    removed = public_message(store, alice, "TEST withdrawn during export")
    thread = invite(store, alice, [bob])
    private_message(store, alice, thread, "TEST first retained private")
    grant = begin_export(store, alice)
    public_message(store, alice, "TEST later public outside ceiling")
    private_message(store, alice, thread, "TEST later private outside ceiling")
    store.delete(alice["token"], removed)
    sections = collect_export(store, alice, grant)
    assert [row["body"] for row in sections["public_messages"]] == ["TEST first retained public"]
    assert [row["body"] for row in sections["private_messages"]] == ["TEST first retained private"]
    assert grant["manifest"]["totals"]["public_messages"] == 2
    assert grant["manifest"]["consistent_snapshot"] is False
    assert "concurrent changes" in grant["manifest"]["scope"]


def test_export_pages_all_retained_records_including_more_than_1000_and_left_threads(store):
    alice, bob = account(store), account(store, "TEST_Bob")
    expected = {section: [] for section in SECTIONS}
    # Bulk fixtures stay inside normal retention: at most 1000 public records
    # per room and 200 private records per thread. Sending histories through
    # the real API would exercise message throttling instead of export paging.
    with store._db() as db:
        for index in range(1100):
            row = db.execute("INSERT INTO messages(room,author,body,created,request_id) VALUES(?,?,?,?,?)",
                             ("general" if index < 900 else "navigation", alice["id"],
                              f"TEST own retained public {index}", store.clock(), request_id(store)))
            expected["public_messages"].append(row.lastrowid)
        for index in range(600):
            row = db.execute("INSERT INTO messages(room,author,body,created,request_id) VALUES(?,?,?,?,?)",
                             ("food", bob["id"], f"TEST other public report target {index}",
                              store.clock(), request_id(store)))
            db.execute("INSERT INTO reports VALUES(?,?,'other',?)", (alice["id"], row.lastrowid, store.clock()))
            expected["public_reports"].append(row.lastrowid)

    for index in range(13):
        if index and index % 2 == 0:
            store.test_clock[0] += INVITATION_COOLDOWN
        sender, recipient = (alice, bob) if index % 2 == 0 else (bob, alice)
        thread = invite(store, sender, [recipient], title=f"TEST retained thread {index}")
        store.private_accept(recipient["token"], thread)
        with store._db() as db:
            for message_index in range(90):
                for author, reader in ((alice, bob), (bob, alice)):
                    row = db.execute("INSERT INTO private_messages(thread,author,body,lifetime,created,request_id) "
                                     "VALUES(?,?,?,'saved',?,?)", (thread, author["id"],
                                     f"TEST {author['name']} retained private {index}:{message_index}",
                                     store.clock(), request_id(store)))
                    db.execute("INSERT INTO private_deliveries VALUES(?,?,NULL)", (row.lastrowid, reader["id"]))
                    if author is alice:
                        expected["private_messages"].append(row.lastrowid)
                    else:
                        db.execute("INSERT INTO private_reports VALUES(?,?,'other',?)",
                                   (row.lastrowid, alice["id"], store.clock()))
                        expected["private_reports"].append(row.lastrowid)
        store.private_leave(alice["token"], thread)

    before = delivery_state(store)
    grant = begin_export(store, alice)
    assert grant["manifest"]["totals"] == {"public_messages": 1100, "private_messages": 1170,
                                           "public_reports": 600, "private_reports": 1170}
    assert grant["manifest"]["page_size"] == 500
    sections = collect_export(store, alice, grant)
    for section, rows in sections.items():
        identifier = "message" if section.endswith("reports") else "id"
        assert [row[identifier] for row in rows] == expected[section]
        assert len({row[identifier] for row in rows}) == len(rows)
    assert all("TEST_Alice" in row["body"] for row in sections["private_messages"])
    assert all(row["status"] == "left" for row in grant["manifest"]["conversations"])
    assert delivery_state(store) == before
    with store._db() as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_schema_six_migration_preserves_accounts_history_profiles_and_schema_eight(store):
    alice, bob = account(store), account(store, "TEST_Bob")
    own_public = public_message(store, alice, "TEST retained from schema six")
    thread = invite(store, alice, [bob])
    own_private = private_message(store, alice, thread, "TEST private retained from schema six")
    save_profile(store, alice, bio="TEST schema six profile")
    asset = photo(store, alice)
    with sqlite3.connect(store.path) as db:
        db.execute("DROP TABLE account_exports")
        db.execute("DROP TABLE closed_accounts")
        db.execute("PRAGMA user_version=6")

    reopened = AccountLifecycleStore(store.path, clock=store.clock)
    assert reopened.account_resume(alice["token"])["viewer"]["id"] == alice["id"]
    assert reopened.profile_get(alice["token"])["profile"]["bio"] == "TEST schema six profile"
    assert reopened.profile_photo_read(alice["token"], asset)["mime_type"] == "image/png"
    grant = begin_export(reopened, alice)
    assert page(reopened, alice, grant)["records"][0]["id"] == own_public
    assert page(reopened, alice, grant, "private_messages")["records"][0]["id"] == own_private
    assert close(reopened, alice) == {"closed": True}
    for constructor in (ChatStore, PrivateChatStore, AccountStore, OwnerStore, ProfileStore, AccountLifecycleStore):
        constructor(store.path, clock=store.clock)
        with sqlite3.connect(store.path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 9
            assert db.execute("SELECT COUNT(*) FROM closed_accounts").fetchone()[0] == 1
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert reopened.account_resume(bob["token"])["viewer"]["id"] == bob["id"]
    assert reopened.private_inbox(bob["token"])["threads"][0]["id"] == thread


def test_owner_console_distinguishes_closed_accounts_and_cannot_restore_them(store):
    owner, alice = account(store, "TEST_OwnerFixture"), account(store)
    store.join("TEST active guest", "")
    with store._db() as db:
        db.execute("INSERT INTO owner_config VALUES(1,?,?,0)", (owner["id"], "TEST-FIXTURE-ONLY"))
        db.execute("INSERT INTO owner_grants VALUES(?,?)",
                   (hashlib.sha256(owner["token"].encode()).hexdigest(), store.clock() + 300))
    close(store, alice)
    dashboard = store.owner_dashboard(owner["token"])
    assert dashboard["accounts"] == 1
    assert dashboard["guests"] == 1
    assert dashboard["closed_accounts"] == 1
    members = store.owner_members(owner["token"], "", 0)["members"]
    closed_member = next(member for member in members if member["id"] == alice["id"])
    assert closed_member["closed"]
    assert closed_member["name"] == "Closed account" and closed_member["username"] is None
    assert not closed_member["active_session"]
    assert not next(member for member in members if member["id"] == owner["id"])["closed"]
    assert store.owner_members(owner["token"], "Closed account", 0)["total"] == 1
    assert store.owner_members(owner["token"], alice["name"], 0)["members"] == []
    assert dashboard["audit"][0]["target_label"] == "Closed account"
    for action in ("restore", "suspend", "revoke"):
        assert_status(409, lambda: store.owner_control(owner["token"], alice["id"], action, "other"))
    with store._db() as db:
        assert db.execute("SELECT COUNT(*) FROM owner_audit").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM participant_controls").fetchone()[0] == 0
        assert db.execute("SELECT 1 FROM accounts WHERE participant=?", (alice["id"],)).fetchone() is None
    assert_status(401, lambda: store.account_resume(alice["token"]))


def test_suspension_revokes_export_access_and_cannot_be_bypassed_by_closure(store):
    alice = account(store)
    grant = begin_export(store, alice)
    with store._db() as db:
        db.execute("INSERT INTO participant_controls VALUES(?,1,'other',?)", (alice["id"], store.clock()))
    assert_status(401, lambda: close(store, alice))
    assert_status(401, lambda: begin_export(store, alice))
    assert_status(401, lambda: page(store, alice, grant))
    with store._db() as db:
        assert db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM closed_accounts").fetchone()[0] == 0
