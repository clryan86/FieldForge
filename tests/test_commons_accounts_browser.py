"""Exercise account creation, preserved inboxes and recovery in real browsers."""

import os
from pathlib import Path

import test_commons_accounts
import test_commons_chat
import test_commons_chat_browser
from test_commons_private_browser import accept, inbox, invite

preview_server = test_commons_chat.preview_server
browsers = test_commons_chat_browser.browsers
join = test_commons_chat_browser.join
pytestmark = test_commons_chat_browser.pytestmark
PASSWORD = test_commons_accounts.PASSWORD
NEW_PASSWORD = test_commons_accounts.NEW_PASSWORD


def save_recovery(page):
    from playwright.sync_api import expect

    expect(page.locator("#recoveryDialog")).to_be_visible()
    code = page.locator("#recoveryValue").input_value()
    assert len(code) == 43
    page.locator("#recoverySaved").check()
    page.get_by_role("button", name="Continue", exact=True).click()
    expect(page.locator("#recoveryValue")).to_have_value("")
    expect(page.locator("#accountPassword")).to_have_value("")
    return code


def create_account(page, name, *, upgrade=False):
    from playwright.sync_api import expect

    page.get_by_role("button", name="Save my account" if upgrade else "Create account", exact=True).click()
    page.get_by_label("Account username", exact=True).fill(name)
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_label("Confirm password", exact=True).fill(PASSWORD)
    page.locator("#accountConsent").check()
    page.get_by_role("button", name="Create local account", exact=True).click()
    code = save_recovery(page)
    expect(page.locator("#accountIdentity")).to_have_text("Local account · " + name)
    return code


def sign_in(page, name, password=PASSWORD):
    from playwright.sync_api import expect

    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_label("Account username", exact=True).fill(name)
    page.get_by_label("Password", exact=True).fill(password)
    page.locator("#accountConsent").check()
    page.get_by_role("button", name="Sign in to Commons", exact=True).click()
    expect(page.locator("#connectionLabel")).to_have_text("Local chat connected")
    expect(page.locator("#accountIdentity")).to_have_text("Local account · " + name)


def test_upgrade_logout_signin_and_offline_invitation_preserve_inbox(browsers):
    from playwright.sync_api import expect

    alice, bob, url = browsers
    join(alice, url, "Guest River")
    alice_code = inbox(alice)
    create_account(alice, "TEST_River", upgrade=True)
    assert alice.locator("#contactCode").input_value() == alice_code
    join(bob, url, "Guest Morgan")
    bob_code = inbox(bob)
    invite(alice, "TEST: Saved trip notes", [bob_code])
    alice.locator("#privateMessage").fill("TEST: Our inbox survives signing out.")
    alice.get_by_role("button", name="Send privately").click()
    expect(alice.locator("#privateMessage")).to_have_value("")
    accept(bob, "TEST: Saved trip notes")
    alice.get_by_role("button", name="Leave chat", exact=True).click()
    expect(alice.locator("#joinPanel")).to_be_visible()
    assert "Our inbox survives" not in alice.locator("body").inner_text()
    invite(bob, "TEST: Invitation while away", [alice_code])
    sign_in(alice, "TEST_River")
    assert inbox(alice) == alice_code
    expect(alice.locator("#threadList")).to_contain_text("Invitation while away")
    alice.locator("#threadList").get_by_role("button", name="TEST: Saved trip notes").click()
    expect(alice.locator("#privateMessages")).to_contain_text("Our inbox survives signing out.")
    for page in (alice, bob):
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot = os.environ.get("FIELDFORGE_ACCOUNT_SCREENSHOT")
    if screenshot:
        path = Path(screenshot)
        path.parent.mkdir(parents=True, exist_ok=True)
        alice.screenshot(path=str(path), full_page=True)


def test_recovery_password_change_and_session_revocation(browsers):
    from playwright.sync_api import expect

    alice, bob, url = browsers
    alice.goto(url + "/commons")
    code = create_account(alice, "TEST_Recovery")
    contact = inbox(alice)
    bob.goto(url + "/commons")
    bob.get_by_role("button", name="Recover account", exact=True).click()
    bob.get_by_label("Account username", exact=True).fill("TEST_Recovery")
    bob.get_by_label("Recovery code", exact=True).fill(code)
    bob.get_by_label("New password", exact=True).fill(NEW_PASSWORD)
    bob.get_by_label("Confirm password", exact=True).fill(NEW_PASSWORD)
    bob.locator("#accountConsent").check()
    bob.get_by_role("button", name="Reset password", exact=True).click()
    replacement = save_recovery(bob)
    assert replacement != code
    expect(alice.locator("#joinPanel")).to_be_visible()
    expect(alice.locator("#contactCode")).to_have_value("")
    sign_in(bob, "TEST_Recovery", NEW_PASSWORD)
    assert inbox(bob) == contact
    bob.get_by_role("button", name="Account security", exact=True).click()
    bob.get_by_label("Current password", exact=True).fill(NEW_PASSWORD)
    bob.get_by_label("New password", exact=True).fill(PASSWORD)
    bob.get_by_label("Confirm password", exact=True).fill(PASSWORD)
    bob.get_by_role("button", name="Update account security", exact=True).click()
    assert save_recovery(bob) != replacement
    bob.get_by_role("button", name="Leave chat", exact=True).click()
    sign_in(bob, "TEST_Recovery")
    sign_in(alice, "TEST_Recovery")
    expect(bob.locator("#joinPanel")).to_be_visible()
    expect(bob.locator("#messages")).to_be_empty()


def test_no_automatic_reconnect_and_no_secrets_left_after_lost_reply(browsers):
    from playwright.sync_api import expect

    alice, _, url = browsers
    alice.goto(url + "/commons")
    create_account(alice, "TEST_Reconnect")
    calls = []
    alice.on("request", lambda request: calls.append(request.url) if "/api/" in request.url else None)
    alice.reload()
    expect(alice.locator("#joinPanel")).to_be_visible()
    assert not calls
    alice.get_by_role("button", name="Resume existing session", exact=True).click()
    expect(alice.locator("#accountIdentity")).to_have_text("Local account · TEST_Reconnect")
    alice.get_by_role("button", name="Leave chat", exact=True).click()
    def lose_response(route):
        route.fetch()
        route.abort("failed")
    alice.route("**/api/commons/account/login", lose_response, times=1)
    alice.get_by_role("button", name="Sign in", exact=True).click()
    alice.get_by_label("Account username", exact=True).fill("TEST_Reconnect")
    alice.get_by_label("Password", exact=True).fill(PASSWORD)
    alice.locator("#accountConsent").check()
    alice.get_by_role("button", name="Sign in to Commons", exact=True).click()
    expect(alice.locator("#accountError")).to_contain_text("reply was lost")
    expect(alice.locator("#accountPassword")).to_have_value("")
    assert alice.evaluate("localStorage.length + sessionStorage.length") == 0
    alice.get_by_label("Password", exact=True).fill(PASSWORD)
    alice.get_by_role("button", name="Sign in to Commons", exact=True).click()
    expect(alice.locator("#accountIdentity")).to_have_text("Local account · TEST_Reconnect")
