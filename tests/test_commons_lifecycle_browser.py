"""Password-confirmed account export and closure in real Chromium sessions."""

import base64
import json
import os
import uuid
from pathlib import Path

import pytest
import test_commons_chat
import test_commons_chat_browser
import test_commons_profiles
from test_commons_accounts_browser import PASSWORD, create_account, sign_in
from test_commons_private_browser import inbox
from test_commons_profiles_browser import open_profile

from fieldforge.online.chat_store import ChatError
from fieldforge.online.commons_preview import COOKIE_NAME

preview_server = test_commons_chat.preview_server
browsers = test_commons_chat_browser.browsers
pytestmark = test_commons_chat_browser.pytestmark


def token(page):
    return next(cookie["value"] for cookie in page.context.cookies() if cookie["name"] == COOKIE_NAME)


def open_lifecycle(page, mode):
    from playwright.sync_api import expect

    page.get_by_role("button", name="Account security", exact=True).click()
    page.locator("#openAccount" + mode.title()).click()
    expect(page.locator("#account" + mode.title() + "Dialog")).to_be_visible()


def fill_close(page, username, password=PASSWORD):
    page.locator("#accountClosePassword").fill(password)
    page.locator("#accountCloseUsername").fill(username)
    page.locator("#accountCloseConfirm").check()


def hide_tab(page):
    page.evaluate("""() => {
        Object.defineProperty(document, 'hidden', {configurable: true, value: true});
        document.dispatchEvent(new Event('visibilitychange'));
        delete document.hidden;
        document.dispatchEvent(new Event('visibilitychange'));
    }""")


def clock(store):
    if not hasattr(store, "test_clock"):
        store.test_clock = [store.clock()]
        store.clock = lambda: store.test_clock[0]


def send(store, sender, body, *, thread=None, lifetime="saved"):
    clock(store)
    store.test_clock[0] += 2.1
    if thread:
        return store.private_send(sender, thread, body, lifetime, uuid.uuid4().hex)["id"]
    return store.send(sender, "general", body, uuid.uuid4().hex)["id"]


def assert_cleared(page):
    from playwright.sync_api import expect

    expect(page.locator("#joinPanel")).to_be_visible()
    for selector in ("#messages", "#privateMessages", "#threadList", "#viewOnceBody",
                     "#profilePhotoPreview", "#directoryCards"):
        expect(page.locator(selector)).to_be_empty()
    for selector in ("#message", "#privateMessage", "#contactCode", "#profileBio",
                     "#profileDisplayName", "#accountPassword", "#accountNewPassword",
                     "#accountRecovery", "#recoveryValue", "#accountExportPassword",
                     "#accountClosePassword", "#accountCloseUsername"):
        expect(page.locator(selector)).to_have_value("")
    expect(page.locator("#accountCloseConfirm")).not_to_be_checked()
    expect(page.locator("#accountCloseDialog")).to_be_hidden()
    expect(page.locator("#accountExportDialog")).to_be_hidden()
    assert page.evaluate("localStorage.length + sessionStorage.length") == 0


def test_explicit_account_controls_username_confirmation_and_mobile_layout(browsers, preview_server):
    from playwright.sync_api import expect

    _, member, url = browsers
    calls = []
    member.on("request", lambda request: calls.append(request.url)
              if "/account/export" in request.url or request.url.endswith("/account/close") else None)
    test_commons_chat_browser.join(member, url, "TEST lifecycle guest")
    member.get_by_role("button", name="Save my account", exact=True).click()
    expect(member.locator("#accountDataSection")).to_be_hidden()
    member.locator("#accountCancel").click()
    create_account(member, "TEST_Lifecycle", upgrade=True)
    open_lifecycle(member, "export")
    expect(member.locator("#accountExportIdentity")).to_have_text("@test_lifecycle")
    member.locator("#accountExportPassword").fill(PASSWORD)
    member.locator("#accountExportBack").click()
    expect(member.locator("#accountExportPassword")).to_have_value("")
    member.locator("#openAccountClose").click()
    expect(member.locator("#accountCloseSubmit")).to_be_disabled()
    fill_close(member, "Someone_else")
    expect(member.locator("#accountCloseSubmit")).to_be_disabled()
    member.locator("#accountCloseUsername").fill("TEST_LIFECYCLE")
    expect(member.locator("#accountCloseSubmit")).to_be_enabled()
    member.locator("#accountCloseConfirm").uncheck()
    expect(member.locator("#accountCloseSubmit")).to_be_disabled()
    expect(member.locator("#accountCloseConsequences")).to_contain_text("cannot be restored")
    expect(member.locator("#accountCloseConsequences")).to_contain_text("existing retention")
    assert calls == []  # Opening and preparing either form is not an API action.
    assert member.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert member.locator("#accountCloseDialog").evaluate("element => element.scrollWidth <= element.clientWidth")
    screenshot = os.environ.get("FIELDFORGE_LIFECYCLE_SCREENSHOT")
    if screenshot:
        path = Path(screenshot)
        path.parent.mkdir(parents=True, exist_ok=True)
        member.locator("#accountCloseDialog").evaluate("element => element.scrollTop = 0")
        member.screenshot(path=str(path))
        member.locator("#accountCloseDialog").evaluate("element => element.scrollTop = element.scrollHeight")
        member.screenshot(path=str(path.with_name(path.stem + "-confirmation" + path.suffix)))
    member.locator("#accountCloseBack").click()
    expect(member.locator("#accountClosePassword")).to_have_value("")
    expect(member.locator("#accountCloseUsername")).to_have_value("")
    expect(member.locator("#accountCloseConfirm")).not_to_be_checked()
    assert preview_server.app.store.account_resume(token(member))["viewer"]["username"] == "test_lifecycle"


def test_paged_export_downloads_one_complete_scoped_bundle_without_credentials(browsers, preview_server, tmp_path):
    from playwright.sync_api import expect

    member, _, url = browsers
    member.goto(url + "/commons")
    recovery = create_account(member, "TEST_Export")
    store = preview_server.app.store
    mine = token(member)
    other, peer = store.account_register("TEST_ExportPeer", PASSWORD, "")
    for number in range(505):
        send(store, mine, f"TEST exported public note {number:03}")
    peer_public = send(store, other, "TEST peer public body excluded from account bundle")
    store.report(mine, peer_public, "other")
    thread = store.private_create(mine, "TEST: Created conversation retained after leaving", "direct",
                                  [peer["viewer"]["id"]], uuid.uuid4().hex)["thread"]
    store.private_accept(other, thread)
    send(store, mine, "TEST own saved private body included after leaving", thread=thread)
    send(store, mine, "TEST own open-once body excluded from account bundle", thread=thread, lifetime="view_once")
    peer_private = send(store, other, "TEST peer private body excluded from account bundle", thread=thread)
    store.private_report(mine, thread, peer_private, "spam")
    store.private_leave(mine, thread)
    test_commons_profiles.profile(store, mine, display_name="TEST <b>chosen name</b>", bio="TEST private profile bio")
    test_commons_profiles.add_photo(store, mine)
    blocked, blocked_peer = store.join("TEST Blocked Export Peer", "")
    store.block(mine, blocked_peer["id"], True)
    requests, downloads, events = [], [], []
    member.on("request", lambda request: requests.append((request.url, request.post_data_json))
              if "/account/export" in request.url else None)
    member.on("response", lambda response: events.append("finished")
              if response.url.endswith("/account/export/finish") and response.status == 200 else None)
    member.on("download", lambda download: (downloads.append(download), events.append("download")))
    open_lifecycle(member, "export")
    member.locator("#accountExportPassword").fill(PASSWORD)
    with member.expect_download() as pending:
        member.locator("#accountExportSubmit").click()
    destination = tmp_path / "account.json"
    pending.value.save_as(destination)
    data = json.loads(destination.read_text())
    assert len(downloads) == 1 and events.index("finished") < events.index("download")
    assert data["format"] == "fieldforge-commons-account" and data["version"] == 1
    assert data["consistent_snapshot"] is False
    assert data["counts"] == {"public_messages": 505, "private_messages": 1,
                              "public_reports": 1, "private_reports": 1}
    assert data["totals"] == data["counts"]
    assert [row["body"] for row in data["public_messages"]] == [f"TEST exported public note {n:03}" for n in range(505)]
    assert data["private_messages"][0]["body"] == "TEST own saved private body included after leaving"
    assert data["conversations"][0]["status"] == "left"
    assert data["profile"]["bio"] == "TEST private profile bio"
    assert data["profile"]["visibility"] == "private"
    assert "photo_asset_id" not in data["profile"]
    assert data["photo"]["mime_type"] == "image/png"
    assert base64.b64decode(data["photo"]["encoded"]).startswith(b"\x89PNG\r\n\x1a\n")
    assert b"private GPS" not in base64.b64decode(data["photo"]["encoded"])
    assert data["blocks"] == [{"target": blocked_peer["id"], "name": "TEST Blocked Export Peer"}]
    assert data["public_reports"] == [{"message": peer_public, "reason": "other", "created": data["public_reports"][0]["created"]}]
    assert data["private_reports"][0]["message"] == peer_private
    assert isinstance(data["finished_at"], (float, int))
    serialized = destination.read_text()
    for secret in (PASSWORD, recovery, mine, other, blocked, "export_token", "password_hash", "recovery_hash",
                   "TEST peer public body", "TEST peer private body", "TEST own open-once body"):
        assert secret not in serialized
    public_pages = [payload for path, payload in requests
                    if path.endswith("/account/export/page") and payload["section"] == "public_messages"]
    assert [page["after"] for page in public_pages] == [0, data["public_messages"][499]["id"]]
    expect(member.locator("#accountExportPassword")).to_have_value("")
    expect(member.locator("#accountExportStatus")).to_contain_text("download started")
    assert member.evaluate("localStorage.length + sessionStorage.length") == 0
    with store._db() as db:
        assert db.execute("SELECT COUNT(*) FROM account_exports").fetchone()[0] == 0


def test_export_password_failure_and_expired_grant_never_download_partial_data(browsers, preview_server):
    from playwright.sync_api import expect

    member, _, url = browsers
    member.goto(url + "/commons")
    create_account(member, "TEST_ExportRetry")
    send(preview_server.app.store, token(member), "TEST available only in a completed export")
    downloads = []
    member.on("download", lambda download: downloads.append(download))
    open_lifecycle(member, "export")
    member.locator("#accountExportPassword").fill("TEST incorrect current passphrase")
    member.locator("#accountExportSubmit").click()
    expect(member.locator("#accountExportStatus")).to_contain_text("No file was downloaded")
    expect(member.locator("#joinPanel")).to_be_hidden()
    expect(member.locator("#accountExportPassword")).to_have_value("")

    def expired_finish(route):
        preview_server.app.store.test_clock[0] += 301
        response = route.fetch()
        assert response.status == 410
        route.fulfill(response=response)

    member.route("**/api/commons/account/export/finish", expired_finish, times=1)
    member.locator("#accountExportPassword").fill(PASSWORD)
    member.locator("#accountExportSubmit").click()
    expect(member.locator("#accountExportStatus")).to_contain_text("expired")
    expect(member.locator("#accountExportSubmit")).to_be_enabled()
    assert downloads == []
    expect(member.locator("#joinPanel")).to_be_hidden()
    member.locator("#accountExportPassword").fill(PASSWORD)
    with member.expect_download():
        member.locator("#accountExportSubmit").click()
    assert len(downloads) == 1


@pytest.mark.parametrize("interrupt", ["hidden", "pause", "cancel"])
def test_export_cancellation_suppresses_late_page_or_finish_reply(browsers, preview_server, interrupt):
    from playwright.sync_api import expect

    member, _, url = browsers
    member.goto(url + "/commons")
    create_account(member, "TEST_ExportCancel")
    send(preview_server.app.store, token(member), "TEST interrupted export body")
    downloads = []
    member.on("download", lambda download: downloads.append(download))

    def interrupt_reply(route):
        response = route.fetch()
        if interrupt == "hidden":
            hide_tab(member)
        elif interrupt == "pause":
            member.evaluate("document.getElementById('pauseButton').click()")
        else:
            member.locator("#accountExportBack").click()
        route.fulfill(response=response)

    action = "finish" if interrupt == "hidden" else "page"
    member.route("**/api/commons/account/export/" + action, interrupt_reply, times=1)
    open_lifecycle(member, "export")
    member.locator("#accountExportPassword").fill(PASSWORD)
    member.locator("#accountExportSubmit").click()
    expect(member.locator("#accountExportDialog")).to_be_hidden()
    expect(member.locator("#accountExportPassword")).to_have_value("")
    member.wait_for_timeout(150)
    assert downloads == []
    expect(member.locator("#accountExportStatus")).to_be_empty()
    if interrupt == "pause":
        expect(member.locator("#connectionLabel")).to_have_text("Chat paused")
        member.locator("#pauseButton").click()
    elif interrupt == "cancel":
        member.locator("#accountCancel").click()
    expect(member.locator("#joinPanel")).to_be_hidden()
    open_lifecycle(member, "export")
    expect(member.locator("#accountExportStatus")).to_be_empty()
    member.locator("#accountExportPassword").fill(PASSWORD)
    with member.expect_download():
        member.locator("#accountExportSubmit").click()
    assert len(downloads) == 1


def test_export_first_then_password_checked_closure_clears_identity_and_withdraws_own_bodies(browsers, preview_server):
    from playwright.sync_api import expect

    member, peer, url = browsers
    member.goto(url + "/commons")
    create_account(member, "TEST_Close")
    peer.goto(url + "/commons")
    create_account(peer, "TEST_ClosePeer")
    mine, theirs = token(member), token(peer)
    store = preview_server.app.store
    sent = send(store, mine, "TEST authored public body withdrawn on close")
    send(store, theirs, "TEST peer public body kept")
    thread = store.private_create(mine, "TEST shared title after member closes", "direct",
                                  [store.account_resume(theirs)["viewer"]["id"]], uuid.uuid4().hex)["thread"]
    store.private_accept(theirs, thread)
    send(store, mine, "TEST authored private body withdrawn on close", thread=thread)
    send(store, theirs, "TEST peer private body kept", thread=thread)
    test_commons_profiles.profile(store, mine, display_name="TEST closing profile", bio="TEST closing saved bio")
    test_commons_profiles.add_photo(store, mine)
    open_profile(member)
    expect(member.locator("#profilePhotoPreview img")).to_have_count(1)
    member.locator("#profileBio").fill("TEST unsaved profile draft")
    member.locator("#closeProfile").click()
    inbox(member)
    member.locator("#threadList").get_by_role("button", name="TEST shared title after member closes").click()
    expect(member.locator("#privateMessages")).to_contain_text("authored private body")
    member.locator("#privateMessage").fill("TEST unsent private draft")
    member.get_by_role("button", name="Community rooms", exact=True).click()
    member.locator("#message").fill("TEST unsent public draft")
    open_lifecycle(member, "close")
    fill_close(member, "TEST_Close")
    member.locator("#accountCloseExport").click()
    expect(member.locator("#accountClosePassword")).to_have_value("")
    member.locator("#accountExportPassword").fill(PASSWORD)
    with member.expect_download():
        member.locator("#accountExportSubmit").click()
    member.locator("#accountExportBack").click()
    expect(member.locator("#accountCloseUsername")).to_have_value("")
    expect(member.locator("#accountCloseConfirm")).not_to_be_checked()
    fill_close(member, "TEST_Close", "TEST wrong but sufficiently long password")
    member.locator("#accountCloseSubmit").click()
    expect(member.locator("#accountCloseStatus")).to_contain_text("Your account was not closed")
    expect(member.locator("#joinPanel")).to_be_hidden()
    expect(member.locator("#accountClosePassword")).to_have_value("")
    member.locator("#accountClosePassword").fill(PASSWORD)
    member.locator("#accountCloseSubmit").click()
    expect(member.locator("#status")).to_contain_text("Account closed.")
    assert_cleared(member)
    expect(peer.locator(f'#messages [data-id="{sent}"]')).to_contain_text("Closed account")
    expect(peer.locator("#messages")).to_contain_text("TEST peer public body kept")
    assert "TEST authored public body" not in peer.locator("#messages").inner_text()
    inbox(peer)
    peer.locator("#threadList").get_by_role("button", name="TEST shared title after member closes").click()
    expect(peer.locator("#privateMessages")).to_contain_text("TEST peer private body kept")
    assert "TEST authored private body" not in peer.locator("#privateMessages").inner_text()
    with pytest.raises(ChatError) as ended:
        store.account_resume(mine)
    assert ended.value.status == 401
    member.get_by_role("button", name="Resume existing session", exact=True).click()
    expect(member.locator("#status")).to_contain_text("No active session remains")
    assert_cleared(member)


@pytest.mark.parametrize("committed", [False, True])
def test_lost_closure_reply_clears_local_identity_without_claiming_success_or_retrying(browsers, preview_server, committed):
    from playwright.sync_api import expect

    member, _, url = browsers
    member.goto(url + "/commons")
    create_account(member, "TEST_CloseLost")
    mine = token(member)
    member.locator("#message").fill("TEST private unsent draft before uncertain closure")
    calls = []

    def lose_reply(route):
        calls.append(route.request.post_data_json)
        if committed:
            route.fetch()
        route.abort("failed")

    member.route("**/api/commons/account/close", lose_reply, times=1)
    open_lifecycle(member, "close")
    fill_close(member, "TEST_CloseLost")
    member.locator("#accountCloseSubmit").click()
    expect(member.locator("#status")).to_contain_text("Account closure could not be confirmed")
    assert_cleared(member)
    member.wait_for_timeout(150)
    assert len(calls) == 1
    if committed:
        with pytest.raises(ChatError):
            preview_server.app.store.account_resume(mine)
    else:
        sign_in(member, "TEST_CloseLost")
        expect(member.locator("#message")).to_have_value("")
        assert len(calls) == 1


def test_hidden_closure_completion_still_clears_the_original_account(browsers):
    from playwright.sync_api import expect

    member, _, url = browsers
    member.goto(url + "/commons")
    create_account(member, "TEST_CloseHidden")

    def hidden_reply(route):
        response = route.fetch()
        hide_tab(member)
        expect(member.locator("#accountClosePassword")).to_have_value("")
        expect(member.locator("#accountCloseUsername")).to_have_value("")
        route.fulfill(response=response)

    member.route("**/api/commons/account/close", hidden_reply, times=1)
    open_lifecycle(member, "close")
    fill_close(member, "TEST_CloseHidden")
    member.locator("#accountCloseSubmit").click()
    expect(member.locator("#status")).to_contain_text("Account closed.")
    assert_cleared(member)


@pytest.mark.parametrize("operation", ["export", "close"])
def test_delayed_lifecycle_reply_cannot_download_old_data_or_clear_a_new_account_cookie(browsers, preview_server, operation):
    from playwright.sync_api import expect

    member, _, url = browsers
    member.goto(url + "/commons")
    create_account(member, "TEST_OldLifecycle")
    store = preview_server.app.store
    store.account_register("TEST_NewLifecycle", PASSWORD, "")
    send(store, token(member), "TEST old account body must not enter the new account export")
    replacement = member.context.new_page()
    errors, downloads, switched_token = [], [], []
    replacement.on("pageerror", lambda error: errors.append(str(error)))
    member.on("download", lambda download: downloads.append(download))

    def change_account_before_reply(route):
        response = route.fetch()  # Alice's close is committed, or her export page was collected.
        replacement.goto(url + "/commons")
        sign_in(replacement, "TEST_NewLifecycle")
        switched_token.append(token(replacement))
        replacement.locator("#message").fill("TEST new account draft survives the old response")
        route.fulfill(response=response)

    endpoint = "account/close" if operation == "close" else "account/export/page"
    member.route("**/api/commons/" + endpoint, change_account_before_reply, times=1)
    try:
        open_lifecycle(member, operation)
        if operation == "close":
            fill_close(member, "TEST_OldLifecycle")
            member.locator("#accountCloseSubmit").click()
        else:
            member.locator("#accountExportPassword").fill(PASSWORD)
            member.locator("#accountExportSubmit").click()
        assert_cleared(member)
        assert downloads == []
        assert token(replacement) == switched_token[0]
        assert store.account_resume(token(replacement))["viewer"]["username"] == "test_newlifecycle"
        expect(replacement.locator("#accountIdentity")).to_have_text("Local account · TEST_NewLifecycle")
        expect(replacement.locator("#message")).to_have_value("TEST new account draft survives the old response")
        replacement.get_by_role("button", name="Send message", exact=False).click()
        expect(replacement.locator("#messages .own")).to_contain_text("TEST new account draft survives the old response")
        assert errors == []
    finally:
        replacement.close()


def test_owner_has_no_member_close_action_and_closed_member_has_no_restore_controls(browsers, preview_server):
    from playwright.sync_api import expect
    from test_commons_owner_browser import login, setup

    owner, member, url = browsers
    store = setup(preview_server)
    member.goto(url + "/commons")
    create_account(member, "TEST_ClosedOwnerRow")
    identifier = store.account_resume(token(member))["viewer"]["id"]
    open_lifecycle(member, "close")
    fill_close(member, "TEST_ClosedOwnerRow")
    member.locator("#accountCloseSubmit").click()
    expect(member.locator("#status")).to_contain_text("Account closed.")
    owner.goto(url + "/commons-owner")
    login(owner, store)
    expect(owner.locator("#ownerClosedCount")).to_have_text("1")
    row = owner.locator(f'.owner-member[data-participant="{identifier}"]')
    expect(row).to_contain_text("Closed account · Access permanently removed")
    expect(row.locator("button")).to_have_count(0)
    assert owner.locator(".owner-stats > div").count() == 4
    owner.set_viewport_size({"width": 390, "height": 844})
    assert owner.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert len(owner.locator(".owner-stats").evaluate("element => getComputedStyle(element).gridTemplateColumns.split(' ')")) == 2
    owner.get_by_role("link", name="Return to Commons", exact=True).click()
    owner.get_by_role("button", name="Resume existing session", exact=True).click()
    expect(owner.locator("#sessionName")).to_have_text("King")
    owner.get_by_role("button", name="Account security", exact=True).click()
    expect(owner.locator("#openAccountClose")).to_be_hidden()
    expect(owner.locator("#accountOwnerCloseNote")).to_contain_text("sole owner account")
    owner.locator("#openAccountExport").click()
    expect(owner.locator("#accountExportIdentity")).to_have_text("@clryan86")
    expect(owner.locator("#accountExportSubmit")).to_be_enabled()
