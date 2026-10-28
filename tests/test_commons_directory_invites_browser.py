"""Verify directory consent, invitation retries and session-bound browser actions."""

import os
from pathlib import Path

import pytest
import test_commons_chat
import test_commons_chat_browser
import test_commons_profiles
from test_commons_accounts_browser import PASSWORD, create_account, save_recovery
from test_commons_private_browser import accept, inbox
from test_commons_profiles_browser import (
    hide_tab,
    open_profile,
    refresh_directory,
    save_profile,
    session_token,
)
from test_commons_session_browser import freeze_polling, install_clock, switch_shared_cookie

preview_server = test_commons_chat.preview_server
browsers = test_commons_chat_browser.browsers
join = test_commons_chat_browser.join
pytestmark = test_commons_chat_browser.pytestmark

SENDER = "TEST_DirectorySender"
RECIPIENT = "TEST_DirectoryRecipient"


def open_directory(page):
    from playwright.sync_api import expect

    page.get_by_role("button", name="Member directory", exact=True).click()
    expect(page.locator("#directoryRefresh")).to_be_enabled()


def directory_card(page, username):
    return page.locator(".directory-card").filter(
        has=page.get_by_text("@" + username.lower(), exact=True)
    )


def open_invitation(page, username=RECIPIENT):
    from playwright.sync_api import expect

    directory_card(page, username).get_by_role(
        "button", name="Invite to chat", exact=True
    ).click()
    expect(page.locator("#directoryInviteDialog")).to_be_visible()
    expect(page.locator("#directoryInviteUsername")).to_have_text("@" + username.lower())


def prepare_invitation(browsers, preview_server):
    """Save two real accounts and a consenting recipient, then open the sender's form."""
    alice, bob, url = browsers
    alice.goto(url + "/commons")
    create_account(alice, SENDER)
    bob.goto(url + "/commons")
    create_account(bob, RECIPIENT)
    test_commons_profiles.profile(
        preview_server.app.store, session_token(bob), visibility="commons",
        allow_invitations=True,
    )
    open_directory(alice)
    open_invitation(alice)
    return alice, bob, url


def lose_invitation_reply(page):
    """Commit the request, retain its public payload, and lose only the response."""
    captured = []

    def lose_response(route):
        response = route.fetch()
        captured.append((route.request.post_data_json, response.status, response.json()))
        route.abort("failed")

    page.route("**/api/commons/profile/invite", lose_response, times=1)
    return captured


def test_profile_opt_in_opens_real_inbox_and_recipient_can_accept_and_reply(browsers):
    from playwright.sync_api import expect

    alice, bob, url = browsers
    alice.goto(url + "/commons")
    create_account(alice, RECIPIENT)
    open_profile(alice)
    expect(alice.locator("#profileAllowInvitations")).not_to_be_checked()
    name = "TEST Guide <img src=x onerror=alert(1)>"
    alice.locator("#profileDisplayName").fill(name)
    alice.locator("#profileVisibility").check()
    save_profile(alice)

    bob.goto(url + "/commons")
    create_account(bob, SENDER)
    open_directory(bob)
    card = directory_card(bob, RECIPIENT)
    expect(card).to_be_visible()
    expect(card.get_by_role("button", name="Invite to chat", exact=True)).to_have_count(0)
    alice.locator("#profileAllowInvitations").check()
    save_profile(alice)
    alice.get_by_role("button", name="Close profile", exact=True).click()
    open_profile(alice)
    expect(alice.locator("#profileAllowInvitations")).to_be_checked()
    alice.get_by_role("button", name="Close profile", exact=True).click()
    open_directory(alice)
    expect(directory_card(alice, RECIPIENT).get_by_role(
        "button", name="Invite to chat", exact=True
    )).to_have_count(0)
    alice.get_by_role("button", name="Close directory", exact=True).click()
    recipient_contact = inbox(alice)

    refresh_directory(bob)
    expect(card).to_contain_text(name)
    expect(card.locator("img, script")).to_have_count(0)
    assert recipient_contact not in card.inner_html()
    open_invitation(bob)
    dialog = bob.locator("#directoryInviteDialog")
    expect(bob.get_by_role("heading", name="Invite to a private conversation")).to_be_visible()
    expect(bob.locator("#directoryInviteName")).to_have_text(name)
    expect(dialog.locator("img, script")).to_have_count(0)
    expect(bob.get_by_label("Conversation subject", exact=True)).to_have_attribute("maxlength", "100")
    expect(bob.locator("#directoryInviteSend")).to_be_disabled()
    assert recipient_contact not in dialog.inner_html()
    assert bob.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert dialog.evaluate("element => element.scrollWidth <= element.clientWidth")

    title = "TEST: Local map planning <b>plain text</b>"
    bob.locator("#directoryInviteSubject").fill(title)
    screenshot = os.environ.get("FIELDFORGE_DIRECTORY_INVITE_SCREENSHOT")
    if screenshot:
        destination = Path(screenshot)
        destination.parent.mkdir(parents=True, exist_ok=True)
        bob.screenshot(path=str(destination), full_page=True)
    with bob.expect_response("**/api/commons/profile/invite") as response:
        bob.locator("#directoryInviteSend").click()
    assert response.value.status == 200
    payload = response.value.request.post_data_json
    assert set(payload) == {"profile_id", "title", "request_id"}
    assert payload["profile_id"] != recipient_contact
    assert payload["title"] == title
    expect(dialog).to_be_hidden()
    expect(bob.locator("#directoryInviteSubject")).to_have_value("")
    expect(bob.locator("#privateWorkspace")).to_be_visible()
    expect(bob.locator("#privateTitle")).to_have_text(title)
    expect(bob.locator("#privateTitle b")).to_have_count(0)
    expect(bob.locator("#privateParticipants")).to_contain_text(RECIPIENT)
    expect(bob.locator("#privateCompose")).to_be_visible()
    bob.locator("#privateMessage").fill("TEST: Please review the saved route.")
    bob.get_by_role("button", name="Send privately", exact=True).click()
    expect(bob.locator("#privateMessage")).to_have_value("")
    expect(alice.locator("#threadList")).to_contain_text(title)
    assert "Please review the saved route" not in alice.locator("body").inner_text()
    accept(alice, title)
    expect(alice.locator("#privateMessages")).to_contain_text("Please review the saved route")
    alice.locator("#privateMessage").fill("TEST: Accepted. I can help with the route.")
    alice.get_by_role("button", name="Send privately", exact=True).click()
    expect(bob.locator("#privateMessages .message-body")).to_have_count(2)
    expect(bob.locator("#privateMessages")).to_contain_text("I can help with the route")
    for page in (alice, bob):
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_guest_can_browse_but_must_save_account_before_inviting(browsers, preview_server):
    from playwright.sync_api import expect

    _, bob, url = browsers
    store = preview_server.app.store
    token, _ = test_commons_profiles.account(store, RECIPIENT)
    test_commons_profiles.profile(store, token, visibility="commons", allow_invitations=True)
    calls = []
    bob.on("request", lambda request: calls.append(request.url)
           if request.url.endswith("/api/commons/profile/invite") else None)
    join(bob, url, "TEST Directory Guest")
    open_directory(bob)
    open_invitation(bob)
    expect(bob.locator("#directoryInviteGuest")).to_be_visible()
    send = bob.locator("#directoryInviteSend")
    assert not send.is_visible() or send.is_disabled()
    expect(bob.get_by_role("button", name="Save my account to invite", exact=True)).to_be_enabled()
    assert calls == []
    assert bob.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert bob.locator("#directoryInviteDialog").evaluate(
        "element => element.scrollWidth <= element.clientWidth"
    )
    bob.locator("#directoryInviteSaveAccount").click()
    expect(bob.locator("#directoryInviteDialog")).to_be_hidden()
    bob.get_by_label("Account username", exact=True).fill("TEST_DirectoryGuestSaved")
    bob.get_by_label("Password", exact=True).fill(PASSWORD)
    bob.get_by_label("Confirm password", exact=True).fill(PASSWORD)
    bob.locator("#accountConsent").check()
    bob.get_by_role("button", name="Create local account", exact=True).click()
    save_recovery(bob)
    expect(bob.locator("#accountIdentity")).to_have_text("Local account · TEST_DirectoryGuestSaved")
    assert calls == []
    open_directory(bob)
    open_invitation(bob)
    expect(bob.locator("#directoryInviteGuest")).to_be_hidden()
    expect(bob.locator("#directoryInviteSubject")).to_be_enabled()
    expect(bob.locator("#directoryInviteSubject")).to_have_value("")
    assert calls == []
    bob.locator("#directoryInviteSubject").fill("TEST: Unsent guest upgrade draft")
    bob.locator("#directoryInviteCancel").click()
    expect(bob.locator("#directoryInviteSubject")).to_have_value("")
    open_invitation(bob)
    expect(bob.locator("#directoryInviteSubject")).to_have_value("")
    assert calls == []


@pytest.mark.parametrize("withdrawal", ["invitations", "listing", "block"])
def test_stale_directory_card_cannot_bypass_current_recipient_consent(
    browsers, preview_server, withdrawal
):
    from playwright.sync_api import expect

    alice, bob, _ = prepare_invitation(browsers, preview_server)
    store = preview_server.app.store
    if withdrawal == "block":
        sender = store.account_resume(session_token(alice))["viewer"]["id"]
        store.block(session_token(bob), sender, True)
    else:
        changes = {"allow_invitations": False} if withdrawal == "invitations" else {"visibility": "private"}
        test_commons_profiles.profile(store, session_token(bob), **changes)
    alice.locator("#directoryInviteSubject").fill("TEST: Stale card must not authorize contact")
    with alice.expect_response("**/api/commons/profile/invite") as response:
        alice.locator("#directoryInviteSend").click()
    assert response.value.status == 404
    expect(alice.locator("#directoryInviteStatus")).to_contain_text("unavailable")
    expect(alice.locator("#directoryInviteDialog")).to_be_visible()
    expect(alice.locator("#directoryInviteSubject")).to_have_value("TEST: Stale card must not authorize contact")
    expect(alice.locator("#directoryInviteSend")).to_be_enabled()
    expect(alice.locator("#connectionLabel")).to_have_text("Local chat connected")
    expect(alice.locator("#privateWorkspace")).to_be_hidden()
    assert store.private_inbox(session_token(alice))["threads"] == []
    assert store.private_inbox(session_token(bob))["threads"] == []
    alice.locator("#directoryInviteCancel").click()
    expect(alice.locator("#directoryInviteSubject")).to_have_value("")


@pytest.mark.parametrize("withdraw_after_loss", [False, True])
def test_lost_reply_requires_explicit_same_request_retry_without_duplicate(
    browsers, preview_server, withdraw_after_loss
):
    from playwright.sync_api import expect

    alice, bob, _ = prepare_invitation(browsers, preview_server)
    title = "TEST: One invitation despite a lost response"
    alice.locator("#directoryInviteSubject").fill(title)
    captured = lose_invitation_reply(alice)
    alice.locator("#directoryInviteSend").click()
    expect(alice.locator("#connectionLabel")).to_have_text("Chat paused")
    assert len(captured) == 1 and captured[0][1] == 200
    first_payload, _, original = captured[0]
    expect(alice.locator("#directoryInviteDialog")).to_be_hidden()
    expect(alice.locator("#directoryInviteName")).to_be_empty()
    expect(alice.locator("#directoryInviteUsername")).to_be_empty()
    expect(alice.locator("#directoryInviteSubject")).to_have_value("")
    expect(alice.locator("#directoryCards")).to_be_empty()
    assert alice.evaluate("localStorage.length + sessionStorage.length") == 0
    store = preview_server.app.store
    if withdraw_after_loss:
        test_commons_profiles.profile(store, session_token(bob), visibility="private", allow_invitations=False)
    attempts = []
    alice.on("request", lambda request: attempts.append(request.post_data_json)
             if request.url.endswith("/api/commons/profile/invite") else None)
    alice.get_by_role("button", name="Resume chat", exact=True).click()
    expect(alice.locator("#connectionLabel")).to_have_text("Local chat connected")
    open_directory(alice)
    expect(alice.locator("#directoryInviteRetry")).to_be_visible()
    if withdraw_after_loss:
        expect(directory_card(alice, RECIPIENT)).to_have_count(0)
        alice.get_by_role("button", name="Review pending invitation", exact=True).click()
    else:
        open_invitation(alice)
    expect(alice.locator("#directoryInviteSubject")).to_have_value(title)
    expect(alice.locator("#directoryInviteUsername")).to_have_text("@" + RECIPIENT.lower())
    assert attempts == []  # Reopening the saved draft never resends it automatically.
    with alice.expect_response("**/api/commons/profile/invite") as response:
        alice.locator("#directoryInviteSend").click()
    assert response.value.status == 200
    assert response.value.json() == {"thread": original["thread"], "duplicate": True, "closed": False}
    assert attempts == [first_payload]
    expect(alice.locator("#privateTitle")).to_have_text(title)
    expect(alice.locator("#privateWorkspace")).to_be_visible()
    for page in (alice, bob):
        threads = store.private_inbox(session_token(page))["threads"]
        assert len(threads) == 1 and threads[0]["id"] == original["thread"]


@pytest.mark.parametrize("dismiss", ["cancel", "hidden", "different_target"])
def test_late_invitation_reply_cannot_reopen_cleared_view_or_replace_new_target(
    browsers, preview_server, dismiss
):
    from playwright.sync_api import expect

    alice, bob, _ = prepare_invitation(browsers, preview_server)
    title = "TEST: Delayed invitation result"
    other_name = "TEST_DirectoryThird"
    if dismiss == "different_target":
        token, _ = test_commons_profiles.account(preview_server.app.store, other_name)
        test_commons_profiles.profile(
            preview_server.app.store, token, visibility="commons", allow_invitations=True
        )
    held = []

    def hold_reply(route):
        held.append((route, route.fetch()))
        alice.evaluate("document.documentElement.dataset.testInviteHeld = 'true'")

    alice.route("**/api/commons/profile/invite", hold_reply, times=1)
    alice.locator("#directoryInviteSubject").fill(title)
    alice.locator("#directoryInviteSend").click()
    expect(alice.locator("html")).to_have_attribute("data-test-invite-held", "true")
    expect(alice.locator("#directoryInviteSend")).to_be_disabled()
    expect(alice.locator("#directoryInviteSubject")).to_be_disabled()
    expect(alice.locator("#directoryInviteCancel")).to_be_enabled()
    if dismiss == "hidden":
        hide_tab(alice)
    else:
        alice.locator("#directoryInviteCancel").click()
    expect(alice.locator("#directoryInviteDialog")).to_be_hidden()
    expect(alice.locator("#directoryInviteSubject")).to_have_value("")
    if dismiss == "different_target":
        refresh_directory(alice)
        open_invitation(alice, other_name)
        alice.locator("#directoryInviteSubject").fill("TEST: New recipient draft")
    route, response = held.pop()
    assert response.status == 200
    route.fulfill(response=response)
    alice.wait_for_timeout(100)  # Deliver the deliberately delayed response callbacks.
    expect(alice.locator("#privateWorkspace")).to_be_hidden()
    expect(alice.locator("#connectionLabel")).to_have_text("Local chat connected")
    if dismiss == "different_target":
        expect(alice.locator("#directoryInviteDialog")).to_be_visible()
        expect(alice.locator("#directoryInviteUsername")).to_have_text("@" + other_name.lower())
        expect(alice.locator("#directoryInviteSubject")).to_have_value("TEST: New recipient draft")
        expect(alice.locator("#directoryInviteSend")).to_be_enabled()
    else:
        expect(alice.locator("#directoryInviteDialog")).to_be_hidden()
        expect(alice.locator("#directoryInviteName")).to_be_empty()
        expect(alice.locator("#directoryInviteSubject")).to_have_value("")
        if dismiss == "hidden":
            expect(alice.locator("#directoryCards")).to_be_empty()
        else:
            expect(directory_card(alice, RECIPIENT)).to_be_visible()
    assert len(preview_server.app.store.private_inbox(session_token(bob))["threads"]) == 1
    assert alice.evaluate("localStorage.length + sessionStorage.length") == 0


def test_cookie_switch_before_poll_cannot_send_invitation_as_the_new_account(browsers, preview_server):
    from playwright.sync_api import expect

    alice, _, url = browsers
    install_clock(alice)
    alice, bob, _ = prepare_invitation(browsers, preview_server)
    freeze_polling(alice)
    original_contact = alice.locator("#contactCode").input_value()
    alice.locator("#directoryInviteSubject").fill("TEST: Never send as the new account")
    preview_server.app.store.account_register("TEST_DirectorySwitched", PASSWORD, "")
    switched = switch_shared_cookie(alice, url, "TEST_DirectorySwitched")
    try:
        expect(alice.locator("#sessionName")).to_have_text(SENDER)
        with alice.expect_response("**/api/commons/profile/invite") as response:
            alice.locator("#directoryInviteSend").click()
        assert response.value.status == 401
        assert response.value.request.headers["x-fieldforge-participant"] == original_contact
        expect(alice.locator("#joinPanel")).to_be_visible()
        expect(alice.locator("#directoryInviteDialog")).to_be_hidden()
        expect(alice.locator("#directoryInviteName")).to_be_empty()
        expect(alice.locator("#directoryInviteSubject")).to_have_value("")
        expect(alice.locator("#directoryCards")).to_be_empty()
        assert preview_server.app.store.private_inbox(session_token(bob))["threads"] == []
        with preview_server.app.store._db() as db:
            assert db.execute("SELECT COUNT(*) FROM private_threads").fetchone()[0] == 0
        alice.get_by_role("button", name="Resume existing session", exact=True).click()
        expect(alice.locator("#accountIdentity")).to_have_text("Local account · TEST_DirectorySwitched")
        open_directory(alice)
        expect(alice.locator("#directoryInviteRetry")).to_be_hidden()
        open_invitation(alice)
        expect(alice.locator("#directoryInviteSubject")).to_have_value("")
    finally:
        switched.close()


def test_closed_invitation_replay_reports_closed_without_recreating_conversation(browsers, preview_server):
    from playwright.sync_api import expect

    alice, bob, _ = prepare_invitation(browsers, preview_server)
    title = "TEST: Closed invitation stays closed"
    alice.locator("#directoryInviteSubject").fill(title)
    captured = lose_invitation_reply(alice)
    alice.locator("#directoryInviteSend").click()
    expect(alice.locator("#connectionLabel")).to_have_text("Chat paused")
    original_payload, status, original = captured[0]
    assert status == 200
    inbox(bob)
    bob.locator("#threadList").get_by_role("button", name=title).click()
    expect(bob.locator("#privateInvitation")).to_be_visible()
    bob.on("dialog", lambda dialog: dialog.accept())
    bob.locator("#declineConversation").click()
    expect(bob.locator("#status")).to_contain_text("Invitation declined")
    store = preview_server.app.store
    store.private_leave(session_token(alice), original["thread"])
    alice.get_by_role("button", name="Resume chat", exact=True).click()
    open_directory(alice)
    open_invitation(alice)
    expect(alice.locator("#directoryInviteSubject")).to_have_value(title)
    with alice.expect_response("**/api/commons/profile/invite") as response:
        alice.locator("#directoryInviteSend").click()
    assert response.value.status == 200
    assert response.value.request.post_data_json == original_payload
    assert response.value.json() == {"thread": original["thread"], "duplicate": True, "closed": True}
    expect(alice.locator("#directoryInviteStatus")).to_have_text(
        "That invitation was already sent and the conversation has since closed. No new invitation was created."
    )
    expect(alice.locator("#directoryInviteDialog")).to_be_visible()
    expect(alice.locator("#directoryInviteSend")).to_be_disabled()
    expect(alice.locator("#directoryInviteCancel")).to_be_enabled()
    expect(alice.locator("#privateWorkspace")).to_be_hidden()
    assert store.private_inbox(session_token(alice))["threads"] == []
    assert store.private_inbox(session_token(bob))["threads"] == []
    with store._db() as db:
        assert db.execute("SELECT COUNT(*) FROM private_threads").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM private_invitation_receipts").fetchone()[0] == 1
