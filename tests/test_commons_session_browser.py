"""Keep shared-browser account switches from mixing drafts or late replies."""

from datetime import datetime, timezone

import pytest
import test_commons_chat
import test_commons_chat_browser
from test_commons_accounts_browser import NEW_PASSWORD, PASSWORD, create_account, sign_in
from test_commons_private_browser import accept, inbox, invite

preview_server = test_commons_chat.preview_server
browsers = test_commons_chat_browser.browsers
pytestmark = test_commons_chat_browser.pytestmark


def freeze_polling(page):
    """Stop browser timers after pending work, without pausing the chat itself."""
    page.clock.pause_at(datetime(2030, 1, 1, 1, tzinfo=timezone.utc))


def install_clock(page):
    page.clock.install(time=datetime(2030, 1, 1, tzinfo=timezone.utc))


def switch_shared_cookie(page, url, username):
    other_tab = page.context.new_page()
    other_tab.goto(url + "/commons")
    sign_in(other_tab, username)
    return other_tab


def test_shared_cookie_switch_clears_private_and_public_drafts_and_needs_resume(browsers):
    from playwright.sync_api import expect

    alice, bob, url = browsers
    alice.goto(url + "/commons")
    create_account(alice, "TEST_TabAlice")
    bob.goto(url + "/commons")
    create_account(bob, "TEST_TabBob")
    bob_code = inbox(bob)
    inbox(alice)
    title = "TEST: Shared browser private thread"
    invite(alice, title, [bob_code])
    accept(bob, title)
    alice.locator("#privateMessage").fill("TEST: Alice private unsent draft")
    alice.get_by_role("button", name="New", exact=True).click()
    alice.get_by_label("Subject or group name").fill("TEST: Alice unfinished invitation")
    alice.get_by_label("Recipient contact codes").fill(bob_code)
    alice.locator("#cancelConversation").click()
    alice.locator("#publicRoomsButton").click()
    alice.locator("#message").fill("TEST: Alice public unsent draft")

    switched = switch_shared_cookie(alice, url, "TEST_TabBob")
    try:
        expect(alice.locator("#joinPanel")).to_be_visible()
        expect(alice.locator("#status")).to_contain_text("Resume existing session")
        expect(alice.locator("#message")).to_have_value("")
        expect(alice.locator("#privateMessage")).to_have_value("")
        expect(alice.locator("#contactCode")).to_have_value("")
        expect(alice.locator("#privateParticipants")).to_be_empty()
        expect(alice.locator("#threadList")).to_be_empty()
        expect(alice.locator("#sendButton")).to_be_disabled()
        assert "Alice unfinished invitation" not in alice.content()

        alice.get_by_role("button", name="Resume existing session", exact=True).click()
        expect(alice.locator("#accountIdentity")).to_have_text("Local account · TEST_TabBob")
        inbox(alice)
        alice.locator("#threadList").get_by_role("button", name=title).click()
        expect(alice.locator("#privateCompose")).to_be_visible()
        expect(alice.locator("#privateMessage")).to_have_value("")
        alice.get_by_role("button", name="New", exact=True).click()
        expect(alice.locator("#conversationTitle")).to_have_value("")
        expect(alice.locator("#conversationContacts")).to_have_value("")
    finally:
        switched.close()


def test_switch_before_next_poll_cannot_send_a_draft_as_the_new_account(browsers, preview_server):
    from playwright.sync_api import expect

    alice, bob, url = browsers
    install_clock(alice)
    alice.goto(url + "/commons")
    create_account(alice, "TEST_BoundAlice")
    bob.goto(url + "/commons")
    create_account(bob, "TEST_BoundBob")
    freeze_polling(alice)
    draft = "TEST: Must never be sent as the second account"
    alice.locator("#message").fill(draft)
    expected_id = alice.locator("#contactCode").input_value()
    switched = switch_shared_cookie(alice, url, "TEST_BoundBob")
    try:
        # No poll has noticed the cookie change yet. The server must enforce
        # the original tab's participant header on this very send request.
        expect(alice.locator("#sessionName")).to_have_text("TEST_BoundAlice")
        with alice.expect_response("**/api/commons/send") as response:
            alice.locator("#sendButton").click()
        assert response.value.status == 401
        assert response.value.request.headers["x-fieldforge-participant"] == expected_id
        expect(alice.locator("#joinPanel")).to_be_visible()
        expect(alice.locator("#message")).to_have_value("")
        expect(alice.locator("#sendButton")).to_be_disabled()
        with preview_server.app.store._db() as db:
            assert db.execute("SELECT COUNT(*) FROM messages WHERE body=?", (draft,)).fetchone()[0] == 0
    finally:
        switched.close()


@pytest.mark.parametrize("reply", ["success", "network_failure"])
def test_delayed_export_from_a_previous_session_is_discarded_after_reconnect(browsers, reply):
    from playwright.sync_api import expect

    alice, bob, url = browsers
    install_clock(alice)
    alice.goto(url + "/commons")
    create_account(alice, "TEST_ExportAlice")
    bob.goto(url + "/commons")
    create_account(bob, "TEST_ExportBob")
    freeze_polling(alice)
    retained = []
    downloads = []

    def hold_reply(route):
        retained.append((route, route.fetch()))
        alice.evaluate("document.documentElement.setAttribute('data-test-export-reply-captured', 'true')")

    alice.on("download", lambda download: downloads.append(download.suggested_filename))
    alice.route("**/api/commons/export", hold_reply, times=1)
    alice.locator("#exportButton").click()
    # The connection label is already connected before interception finishes.
    # Wait for the held server response itself before changing the session.
    expect(alice.locator("html")).to_have_attribute("data-test-export-reply-captured", "true")
    expect(alice.locator("#connectionLabel")).to_have_text("Local chat connected")
    assert len(retained) == 1
    switched = switch_shared_cookie(alice, url, "TEST_ExportBob")
    try:
        # A bound action notices the switch, clears identity, and requires a
        # separate reconnect. The older export reply arrives after that point.
        alice.locator("#message").fill("TEST: rejected old identity action")
        alice.locator("#sendButton").click()
        expect(alice.locator("#joinPanel")).to_be_visible()
        alice.get_by_role("button", name="Resume existing session", exact=True).click()
        expect(alice.locator("#accountIdentity")).to_have_text("Local account · TEST_ExportBob")
        route, response = retained.pop()
        if reply == "success":
            with alice.expect_response("**/api/commons/export"):
                route.fulfill(response=response)
        else:
            with alice.expect_event("requestfailed", predicate=lambda request: request.url.endswith("/api/commons/export")):
                route.abort("failed")
        alice.wait_for_timeout(100)
        assert downloads == []
        expect(alice.locator("#accountIdentity")).to_have_text("Local account · TEST_ExportBob")
        expect(alice.locator("#connectionLabel")).to_have_text("Local chat connected")
        expect(alice.locator("#status")).not_to_contain_text("Exported")
    finally:
        for route, _ in retained:
            route.abort()
        switched.close()


def test_account_security_from_an_old_tab_cannot_update_the_new_account(browsers, preview_server):
    from playwright.sync_api import expect

    alice, bob, url = browsers
    install_clock(alice)
    alice.goto(url + "/commons")
    create_account(alice, "TEST_SecurityAlice")
    bob.goto(url + "/commons")
    create_account(bob, "TEST_SecurityBob")
    freeze_polling(alice)
    switched = switch_shared_cookie(alice, url, "TEST_SecurityBob")
    try:
        alice.bring_to_front()
        alice.get_by_role("button", name="Account security", exact=True).click()
        # Fixtures deliberately share a password. Even valid credentials must
        # not apply an old tab's account-security action to the new identity.
        alice.get_by_label("Current password", exact=True).fill(PASSWORD)
        alice.get_by_label("New password", exact=True).fill(NEW_PASSWORD)
        alice.get_by_label("Confirm password", exact=True).fill(NEW_PASSWORD)
        with alice.expect_response("**/api/commons/account/password") as response:
            alice.get_by_role("button", name="Update account security", exact=True).click()
        assert response.value.status == 401
        expect(alice.locator("#joinPanel")).to_be_visible()
        expect(alice.locator("#accountDialog")).not_to_be_visible()
        expect(alice.locator("#recoveryValue")).to_have_value("")
        # The second account can still authenticate with its original password.
        _, result = preview_server.app.store.account_login("TEST_SecurityBob", PASSWORD)
        assert result["viewer"]["name"] == "TEST_SecurityBob"
    finally:
        switched.close()
