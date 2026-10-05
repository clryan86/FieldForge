"""Profile privacy, ownership, photo boundaries, migrations and HTTP regressions."""

import base64
import copy
import http.client
import io
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_commons_chat

from fieldforge.online.chat_store import ChatError
from fieldforge.online.commons_preview import COOKIE_NAME, PHOTO_REQUEST_BYTES
from fieldforge.online.owner import OwnerStore
from fieldforge.online.profiles import ProfileStore
from fieldforge.online.server import PortalApplication, PortalConfig, PortalError

PASSWORD = "TEST profiles: a local passphrase"
preview_server = test_commons_chat.preview_server
api = test_commons_chat.api


@pytest.fixture
def store(tmp_path):
    now = [100_000.0]
    result = ProfileStore(tmp_path / "profiles.sqlite3", clock=lambda: now[0])
    result.test_clock = now
    return result


def account(store, name="TEST_Alice"):
    token, response = store.account_register(name, PASSWORD, "")
    return token, response["viewer"]


def profile(store, token, **changes):
    result = store.profile_get(token)
    value = result["profile"]
    value.pop("photo_asset_id")
    value.update(changes)
    return store.profile_save(token, value, result["revision"])


def png_source():
    image = pytest.importorskip("PIL.Image")
    metadata = pytest.importorskip("PIL.PngImagePlugin").PngInfo()
    metadata.add_text("location", "TEST private GPS metadata must not survive")
    stream = io.BytesIO()
    image.new("RGB", (320, 240), (25, 90, 60)).save(stream, format="PNG", pnginfo=metadata)
    return base64.b64encode(stream.getvalue()).decode("ascii")


def add_photo(store, token):
    result = store.profile_get(token)
    return store.profile_photo_upload(token, png_source(), result["revision"])


def directory(store, token, **filters):
    return store.profile_directory(token, **{"query": "", "category": "", "offset": 0, **filters})


def test_default_private_profile_and_separate_skill_consent(store):
    alice, identity = account(store)
    bob, _ = account(store, "TEST_Bob")
    original = store.profile_get(alice)
    assert original["profile"]["visibility"] == "private"
    assert not original["saved"] and original["revision"] == 0
    assert not original["profile"]["share_photo"] and not original["profile"]["share_skills"]
    assessment = {"interests": ["medical", "navigation"],
                  "experience": {"medical": "professionally_qualified", "navigation": "learning"},
                  "contributions": ["teach", "remote"]}
    saved = profile(store, alice, display_name="TEST River <b>literal</b>",
                    bio="TEST: I like maps.", assessment=assessment)
    assert saved["profile"]["assessment"] == assessment
    assert directory(store, bob)["profiles"] == []
    profile(store, alice, visibility="commons")
    entry = directory(store, bob)["profiles"][0]
    assert entry["display_name"] == "TEST River <b>literal</b>"
    assert entry["username"] == "test_alice"
    assert entry["categories"] == [] and entry["contributions"] == []
    assert not entry["credential_verified"]
    assert identity["id"] not in json.dumps(entry)
    assert "professionally_qualified" not in json.dumps(entry)
    assert entry["profile_id"] != identity["id"]
    assert directory(store, bob, category="medical")["profiles"] == []
    profile(store, alice, share_skills=True)
    entry = directory(store, bob, category="medical")["profiles"][0]
    assert entry["categories"][0]["badge"] == "MED"
    assert entry["categories"][0]["status"] == "self-reported"
    assert entry["contributions"] == ["teach", "remote"]
    assert "experience" not in entry and "assessment" not in entry
    assert store.account_resume(alice)["viewer"]["name"] == "TEST_Alice"
    profile(store, alice, visibility="private")
    assert directory(store, bob)["profiles"] == []
    assert store.profile_get(alice)["profile"]["assessment"] == assessment


def test_guests_can_browse_but_cannot_create_profiles_or_read_another_private_profile(store):
    alice, _ = account(store)
    guest, _ = store.join("TEST guest", "")
    private = profile(store, alice, bio="TEST hidden personal bio")
    assert directory(store, guest)["profiles"] == []
    for operation in (lambda: store.profile_get(guest), lambda: store.profile_delete(guest, 0),
                      lambda: store.profile_export(guest), lambda: store.profile_photo_upload(guest, "invalid", 0)):
        with pytest.raises(ChatError) as error:
            operation()
        assert error.value.status == 403
    with pytest.raises(ChatError) as error:
        store.profile_save(guest, {key: value for key, value in private["profile"].items() if key != "photo_asset_id"}, 0)
    assert error.value.status == 403
    with pytest.raises(ChatError) as error:
        directory(store, None)
    assert error.value.status == 401


def test_public_skill_order_never_reveals_private_experience_ranking(store):
    alice, _ = account(store)
    bob, _ = account(store, "TEST_Bob")
    answers = {"interests": ["navigation", "medical"],
               "experience": {"navigation": "exploring", "medical": "professionally_qualified"},
               "contributions": []}
    profile(store, alice, visibility="commons", share_skills=True, assessment=answers)
    before = directory(store, bob)["profiles"][0]
    assert [entry["category"] for entry in before["categories"]] == ["navigation", "medical"]
    answers["experience"] = {"navigation": "professionally_qualified", "medical": "exploring"}
    profile(store, alice, assessment=answers)
    assert directory(store, bob)["profiles"][0] == before


def test_photo_is_private_until_explicitly_shared_and_previous_ids_are_revoked(store):
    alice, _ = account(store)
    bob, _ = account(store, "TEST_Bob")
    first = add_photo(store, alice)
    asset = first["profile"]["photo_asset_id"]
    assert not first["profile"]["share_photo"]
    photo = store.profile_photo_read(alice, asset)
    decoded = base64.b64decode(photo["encoded"])
    assert photo["mime_type"] == "image/png" and b"private GPS" not in decoded
    with pytest.raises(ChatError) as error:
        store.profile_photo_read(bob, asset)
    assert error.value.status == 404
    profile(store, alice, visibility="commons")
    assert directory(store, bob)["profiles"][0]["photo_asset_id"] is None
    profile(store, alice, share_photo=True)
    assert store.profile_photo_read(bob, asset) == photo
    replacement = add_photo(store, alice)
    second = replacement["profile"]["photo_asset_id"]
    assert second != asset and not replacement["profile"]["share_photo"]
    for reader, photo_id in ((alice, asset), (bob, asset), (bob, second)):
        with pytest.raises(ChatError) as error:
            store.profile_photo_read(reader, photo_id)
        assert error.value.status == 404
    profile(store, alice, share_photo=True)
    assert store.profile_photo_read(bob, second)
    profile(store, alice, visibility="private")
    with pytest.raises(ChatError):
        store.profile_photo_read(bob, second)
    removed = store.profile_photo_remove(alice, store.profile_get(alice)["revision"])
    assert removed["profile"]["photo_asset_id"] is None and not removed["profile"]["share_photo"]
    with pytest.raises(ChatError):
        store.profile_photo_read(alice, second)


def test_directory_blocks_use_existing_private_message_blocking_rules(store):
    alice, a = account(store)
    bob, b = account(store, "TEST_Bob")
    profile(store, alice, visibility="commons")
    photo = add_photo(store, alice)["profile"]["photo_asset_id"]
    profile(store, alice, share_photo=True)
    thread = store.private_create(alice, "TEST invitation", "direct", [b["id"]], "1" * 32)["thread"]
    store.private_accept(bob, thread)
    message = store.private_send(alice, thread, "TEST clear on block", "view_once", "2" * 32)["id"]
    entry = directory(store, bob)["profiles"][0]
    store.profile_block(bob, entry["profile_id"])
    assert directory(store, bob)["profiles"] == []
    with pytest.raises(ChatError):
        store.profile_photo_read(bob, photo)
    with pytest.raises(ChatError):
        store.private_open_once(bob, thread, message)
    store.block(bob, a["id"], False)
    assert directory(store, bob)["profiles"]
    with pytest.raises(ChatError):
        store.private_open_once(bob, thread, message)  # Unblocking never restores a consumed delivery.
    store.block(alice, b["id"], True)
    assert directory(store, bob)["profiles"] == []
    with pytest.raises(ChatError):
        store.profile_photo_read(bob, photo)


def test_suspension_hides_directory_and_photos_without_owner_privilege_bypass(store):
    pyotp = pytest.importorskip("pyotp")
    secret = pyotp.random_base32()
    store.owner_bootstrap(PASSWORD, secret, pyotp.TOTP(secret).at(store.clock()))
    store.test_clock[0] += 30
    owner, _ = store.owner_login("CLRYAN86", PASSWORD, pyotp.TOTP(secret).at(store.clock()))
    alice, identity = account(store)
    photo = add_photo(store, alice)["profile"]["photo_asset_id"]
    with pytest.raises(ChatError) as error:
        store.profile_photo_read(owner, photo)
    assert error.value.status == 404  # Owner role cannot read a private profile photo.
    profile(store, alice, visibility="commons", share_photo=True)
    assert directory(store, owner)["profiles"] and store.profile_photo_read(owner, photo)
    store.owner_control(owner, identity["id"], "suspend", "harassment")
    assert directory(store, owner)["profiles"] == []
    with pytest.raises(ChatError):
        store.profile_photo_read(owner, photo)
    with pytest.raises(ChatError):
        store.profile_get(alice)
    store.owner_control(owner, identity["id"], "restore", "other")
    assert directory(store, owner)["profiles"]
    assert profile(store, owner, display_name="King")["profile"]["display_name"] == "King"


@pytest.mark.parametrize("changes", [
    {"display_name": "King"}, {"display_name": "a\u202eb"}, {"bio": "x" * 501},
    {"visibility": "public"}, {"share_skills": 1}, {"share_photo": "false"},
    {"share_photo": True}, {"role": "owner"}, {"photo_asset_id": "a" * 32},
    {"assessment": {"interests": ["medical"], "experience": {"medical": "verified"}, "contributions": []}},
    {"assessment": {"interests": ["medical"] * 6, "experience": {}, "contributions": []}},
])
def test_invalid_profiles_cannot_publish_extra_fields_or_claim_reserved_role(store, changes):
    alice, _ = account(store)
    with pytest.raises(ChatError) as error:
        profile(store, alice, **changes)
    assert error.value.status == 400
    assert not store.profile_get(alice)["saved"]


def test_conflicting_tabs_never_overwrite_edits_or_resurrect_deleted_profile(store):
    alice, _ = account(store)
    original = store.profile_get(alice)
    draft = {key: value for key, value in original["profile"].items() if key != "photo_asset_id"}
    def save(name):
        try:
            return store.profile_save(alice, {**draft, "display_name": name}, original["revision"])
        except ChatError as error:
            return error.status
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(save, ("TEST tab one", "TEST tab two")))
    assert sum(isinstance(value, dict) for value in results) == 1 and 409 in results
    current = store.profile_get(alice)
    deleted = store.profile_delete(alice, current["revision"])
    assert deleted["revision"] > current["revision"] and not deleted["saved"]
    for stale in (original["revision"], current["revision"]):
        with pytest.raises(ChatError) as error:
            store.profile_save(alice, draft, stale)
        assert error.value.status == 409


def test_delete_erases_profile_photo_and_answers_but_preserves_account_inbox_and_messages(store):
    alice, a = account(store)
    bob, b = account(store, "TEST_Bob")
    photo = add_photo(store, alice)["profile"]["photo_asset_id"]
    saved = profile(store, alice, visibility="commons", share_photo=True, bio="TEST remove this bio")
    public_id = directory(store, bob)["profiles"][0]["profile_id"]
    store.send(alice, "general", "TEST keep this message", "1" * 32)
    store.private_create(alice, "TEST keep this inbox", "direct", [b["id"]], "2" * 32)
    store.profile_delete(alice, saved["revision"])
    assert directory(store, bob)["profiles"] == []
    with pytest.raises(ChatError):
        store.profile_photo_read(alice, photo)
    with sqlite3.connect(store.path) as db:
        row = db.execute("SELECT display_name,bio,assessment,photo_png FROM profiles").fetchone()
    assert row[0] == row[1] == "" and row[3] is None and "interests\":[]" in row[2]
    assert store.read(bob, "general")["messages"][0]["body"] == "TEST keep this message"
    assert store.private_inbox(alice)["threads"]
    store.leave(alice)
    alice, response = store.account_login("TEST_Alice", PASSWORD)
    assert response["viewer"]["id"] == a["id"]
    assert not store.profile_get(alice)["saved"]
    profile(store, alice, visibility="commons")
    assert directory(store, bob)["profiles"][0]["profile_id"] != public_id


def test_export_contains_only_own_profile_and_sanitized_photo(store):
    alice, _ = account(store)
    bob, _ = account(store, "TEST_Bob")
    profile(store, bob, bio="TEST other person's private bio")
    add_photo(store, alice)
    saved = profile(store, alice, bio="TEST export my own biography")
    exported = store.profile_export(alice)
    assert exported["format"] == "fieldforge-commons-profile"
    assert exported["profile"] == saved["profile"]
    assert exported["photo"]["mime_type"] == "image/png"
    text = json.dumps(exported)
    for forbidden in ("other person's", "password", "recovery", "token", "totp", "private GPS"):
        assert forbidden not in text


def test_search_pages_show_only_opted_in_skill_tags_and_have_stable_order(store):
    viewer, _ = account(store, "TEST_Viewer")
    for index in range(14):
        token, _ = account(store, f"TEST_Member_{index:02d}")
        profile(store, token, display_name=f"TEST Person {index:02d}", visibility="commons")
    first = directory(store, viewer)
    second = directory(store, viewer, offset=12)
    assert first["total"] == second["total"] == 14
    assert len(first["profiles"]) == 12 and len(second["profiles"]) == 2
    assert first["profiles"][-1]["display_name"] == "TEST Person 11"
    assert directory(store, viewer, query="MEMBER_13")["profiles"][0]["display_name"] == "TEST Person 13"
    for filters in ({"offset": True}, {"offset": 1}, {"offset": 1001}, {"query": "x" * 61}, {"category": ["medical"]}):
        with pytest.raises(ChatError):
            directory(store, viewer, **filters)


def test_migration_keeps_existing_accounts_messages_and_owner_utilities_do_not_downgrade(tmp_path):
    path = tmp_path / "migration.sqlite3"
    previous = OwnerStore(path)
    alice, response = previous.account_register("TEST_Existing", PASSWORD, "")
    previous.send(alice, "general", "TEST pre-profile retained message", "a" * 32)
    store = ProfileStore(path)
    assert store.profile_get(alice)["viewer"]["id"] == response["viewer"]["id"]
    assert store.read(alice, "general")["messages"][0]["body"] == "TEST pre-profile retained message"
    profile(store, alice, bio="TEST survives owner utilities")
    OwnerStore(path).reports()
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
    assert ProfileStore(path).profile_get(alice)["profile"]["bio"] == "TEST survives owner utilities"


def test_upload_rechecks_session_and_revision_after_decoder_returns(store, monkeypatch):
    import fieldforge.online.profile_photos as photos

    alice, _ = account(store)
    def edit_during_decode(encoded):
        profile(store, alice, bio="TEST keep concurrent edit")
        return b"TEST normalized data fixture"
    monkeypatch.setattr(photos, "normalize_profile_photo", edit_during_decode)
    with pytest.raises(ChatError) as error:
        store.profile_photo_upload(alice, "TEST source", 0)
    assert error.value.status == 409
    assert store.profile_get(alice)["profile"]["photo_asset_id"] is None
    revision = store.profile_get(alice)["revision"]
    monkeypatch.setattr(photos, "normalize_profile_photo", lambda encoded: (store.leave(alice), b"TEST")[1])
    with pytest.raises(ChatError) as error:
        store.profile_photo_upload(alice, "TEST", revision)
    assert error.value.status == 401


def test_photo_decoder_unavailable_does_not_disable_profiles_or_change_saved_data(store, monkeypatch):
    import fieldforge.online.profile_photos as photos

    alice, _ = account(store)
    saved = profile(store, alice, bio="TEST text still works")
    def unavailable(encoded):
        raise photos.PhotoSupportUnavailable("Test missing decoder")
    monkeypatch.setattr(photos, "normalize_profile_photo", unavailable)
    with pytest.raises(ChatError) as error:
        store.profile_photo_upload(alice, "TEST", saved["revision"])
    assert error.value.status == 503
    assert store.profile_get(alice)["revision"] == saved["revision"]


def bound_api(server, path, data, token, participant):
    host = f"127.0.0.1:{server.server_address[1]}"
    connection = http.client.HTTPConnection(host, timeout=5)
    connection.request("POST", "/api/commons/" + path, json.dumps(data), {
        "Content-Type": "application/json", "Origin": "http://" + host,
        "X-FieldForge-Chat": "preview-v1", "X-FieldForge-Participant": participant,
        "Cookie": f"{COOKIE_NAME}={token}",
    })
    response = connection.getresponse()
    status, body = response.status, response.read()
    connection.close()
    return status, json.loads(body)


def test_http_binds_established_browser_actions_to_the_displayed_participant(preview_server):
    store = preview_server.app.store
    alice, a = account(store)
    bob, b = account(store, "TEST_Bob")
    draft = {"room": "general", "body": "TEST never post as Bob", "request_id": "a" * 32}
    status, _ = bound_api(preview_server, "send", draft, bob, a["id"])
    assert status == 401 and store.read(bob, "general")["messages"] == []
    assert bound_api(preview_server, "profile/get", {}, bob, a["id"])[0] == 401
    assert bound_api(preview_server, "private/inbox", {}, bob, a["id"])[0] == 401
    assert bound_api(preview_server, "profile/get", {}, bob, b["id"])[0] == 200
    assert bound_api(preview_server, "send", draft, alice, a["id"])[0] == 200
    assert bound_api(preview_server, "profile/get", {}, alice, "malformed")[0] == 401


def test_http_profile_shapes_no_store_and_endpoint_specific_upload_limit(preview_server):
    store = preview_server.app.store
    alice, _ = account(store)
    status, headers, body = api(preview_server, "/api/commons/profile/get", {}, token=alice)
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert json.loads(body)["profile"]["visibility"] == "private"
    assert api(preview_server, "/api/commons/profile/get", {})[0] == 401
    assert api(preview_server, "/api/commons/profile/get", {"participant": "someone"}, token=alice)[0] == 400
    assert api(preview_server, "/api/commons/profile/export", {}, token=alice, origin=False)[0] == 403
    valid = {"encoded": png_source(), "revision": 0}
    assert api(preview_server, "/api/commons/profile/photo/upload", valid, token=alice)[0] == 200
    # The server rejects an oversized Content-Length before reading its body.
    # Sending megabytes after that rejection can race the connection close and
    # raise BrokenPipeError in the test client instead of observing the 413.
    host = f"127.0.0.1:{preview_server.server_address[1]}"
    for path, size in (("profile/photo/upload", PHOTO_REQUEST_BYTES + 1), ("send", 4097)):
        connection = http.client.HTTPConnection(host, timeout=5)
        try:
            connection.request("POST", "/api/commons/" + path, headers={
                "Content-Type": "application/json", "Content-Length": str(size),
                "Origin": "http://" + host, "X-FieldForge-Chat": "preview-v1",
                "Cookie": f"{COOKIE_NAME}={alice}",
            })
            response = connection.getresponse()
            assert response.status == 413
            response.read()
        finally:
            connection.close()
    assert api(preview_server, "/api/commons/profile/photo/read", {"asset_id": "x"}, token=alice)[0] == 404
    assert api(preview_server, "/api/commons/profile/get", method="GET", token=alice)[0] == 403
    ordinary = PortalApplication(PortalConfig())
    with pytest.raises(PortalError) as error:
        ordinary.dispatch("POST", "/api/commons/profile/get", {})
    assert error.value.status == 404
    assert "img-src 'self' blob: data:" in headers["Content-Security-Policy"]
    assert "data:" not in ordinary.csp


def test_http_preserves_draft_when_another_session_saved_newer_revision(preview_server):
    alice, _ = account(preview_server.app.store)
    saved = profile(preview_server.app.store, alice, bio="TEST newest saved text")
    stale = copy.deepcopy(saved["profile"])
    stale.pop("photo_asset_id")
    stale["bio"] = "TEST outdated edit"
    response = api(preview_server, "/api/commons/profile/save", {"profile": stale, "revision": 0}, token=alice)
    assert response[0] == 409
    assert preview_server.app.store.profile_get(alice)["profile"]["bio"] == "TEST newest saved text"


def test_http_accepts_bounded_unicode_profile_even_when_json_escapes_code_points(preview_server):
    alice, _ = account(preview_server.app.store)
    value = preview_server.app.store.profile_get(alice)["profile"]
    value.pop("photo_asset_id")
    value.update(display_name="😀" * 60, bio="😀" * 500)
    status, _, body = api(preview_server, "/api/commons/profile/save", {"profile": value, "revision": 0}, token=alice)
    assert status == 200
    assert json.loads(body)["profile"]["bio"] == "😀" * 500
