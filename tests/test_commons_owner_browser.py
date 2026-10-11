"""Real-browser owner access, moderation, expiry and credential workflows."""

import os
import time
from pathlib import Path

import pytest
import test_commons_accounts_browser
import test_commons_chat
import test_commons_chat_browser
from test_commons_owner import NEW_PASSWORD, PASSWORD, make_reports

pyotp = pytest.importorskip("pyotp")
preview_server = test_commons_chat.preview_server
browsers = test_commons_chat_browser.browsers
pytestmark = test_commons_chat_browser.pytestmark


def setup(preview_server):
    store = preview_server.app.store
    now = [time.time()]
    store.clock = lambda: now[0]
    store.test_clock = now
    store.test_secret = pyotp.random_base32()
    store.owner_bootstrap(PASSWORD, store.test_secret, pyotp.TOTP(store.test_secret).at(now[0]))
    return store


def login(page, store, password=PASSWORD):
    from playwright.sync_api import expect

    store.test_clock[0] += 30
    page.get_by_label("Owner password", exact=True).fill(password)
    page.get_by_label("Authenticator code", exact=True).fill(pyotp.TOTP(store.test_secret).at(store.clock()))
    page.locator("#ownerConsent").check()
    page.get_by_role("button", name="Verify owner access", exact=True).click()
    expect(page.locator("#ownerConnection")).to_have_text("Owner verified")
    expect(page.locator("#ownerPassword")).to_have_value("")
    expect(page.locator("#ownerCode")).to_have_value("")


def test_owner_moderation_and_suspension_reach_regular_chat(browsers, preview_server):
    from playwright.sync_api import expect

    owner, bob, url = browsers
    store = setup(preview_server)
    bob.goto(url + "/commons")
    test_commons_accounts_browser.create_account(bob, "TEST_Bob")
    bob.get_by_label("Your message", exact=True).fill("TEST reported room message <b>literal text</b>")
    bob.get_by_role("button", name="Send message").click()
    expect(bob.locator("#messages")).to_contain_text("reported room message")
    reporter_context = owner.context.browser.new_context()
    try:
        reporter = reporter_context.new_page()
        test_commons_chat_browser.join(reporter, url, "TEST Reporter")
        reporter.get_by_role("button", name="Report", exact=True).click()
        reporter.get_by_label("Reason", exact=True).select_option("spam")
        reporter.get_by_role("button", name="Save report", exact=True).click()
        expect(reporter.locator("#status")).to_contain_text("Report saved")
    finally:
        reporter_context.close()

    requests = []
    owner.on("request", lambda request: requests.append(request.url) if "/api/" in request.url else None)
    owner.goto(url + "/commons-owner")
    assert not requests
    login(owner, store)
    expect(owner.locator("#ownerReports")).to_contain_text("<b>literal text</b>")
    assert owner.locator("#ownerReports b").count() == 0
    owner.on("dialog", lambda dialog: dialog.accept())
    owner.get_by_role("button", name="Remove message", exact=True).click()
    expect(bob.locator(".message.deleted")).to_contain_text("Message removed.")
    owner.get_by_label("Find a participant", exact=True).fill("TEST_Bob")
    owner.get_by_role("button", name="Search", exact=True).click()
    expect(owner.locator(".owner-member")).to_have_count(1)
    owner.get_by_role("button", name="Suspend", exact=True).click()
    expect(bob.locator("#joinPanel")).to_be_visible()
    expect(owner.locator(".owner-member")).to_contain_text("Suspended")
    owner.get_by_role("button", name="Restore access", exact=True).click()
    expect(owner.locator(".owner-member")).to_contain_text("Signed out")
    test_commons_accounts_browser.sign_in(bob, "TEST_Bob")
    owner.get_by_role("button", name="Refresh console", exact=True).click()
    expect(owner.locator(".owner-member")).to_contain_text("Session active")
    owner.get_by_role("button", name="Revoke session", exact=True).click()
    expect(bob.locator("#joinPanel")).to_be_visible()
    expect(owner.locator("#ownerAudit")).to_contain_text("revoke")
    owner.get_by_role("button", name="Lock console", exact=True).click()
    expect(owner.locator("#ownerDashboard")).to_be_hidden()
    expect(owner.locator("#ownerReports")).to_be_empty()
    owner.get_by_role("button", name="Resume verified console", exact=True).click()
    expect(owner.locator("#ownerStatus")).to_contain_text("verification is required")


def test_owner_private_report_boundaries_resume_expiry_and_password_change(browsers, preview_server):
    from playwright.sync_api import expect

    owner, other, url = browsers
    store = setup(preview_server)
    make_reports(store)
    owner.goto(url + "/commons-owner")
    login(owner, store)
    expect(owner.locator("#ownerReports")).to_contain_text("reported saved private body")
    expect(owner.locator("#ownerReports")).to_contain_text("Open-once body is unavailable")
    assert "never reveal" not in owner.locator("body").inner_text()
    assert "unreported private body" not in owner.locator("body").inner_text()
    assert owner.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot = os.environ.get("FIELDFORGE_OWNER_SCREENSHOT")
    if screenshot:
        path = Path(screenshot)
        path.parent.mkdir(parents=True, exist_ok=True)
        owner.screenshot(path=str(path), full_page=True)
    other.goto(url + "/commons-owner")
    other.get_by_role("button", name="Resume verified console", exact=True).click()
    expect(other.locator("#ownerDashboard")).to_be_hidden()
    expect(other.locator("#ownerReports")).to_be_empty()
    assert other.evaluate("document.documentElement.scrollWidth <= innerWidth")
    requests = []
    owner.on("request", lambda request: requests.append(request.url) if "/api/" in request.url else None)
    owner.reload()
    assert not requests
    owner.get_by_role("button", name="Resume verified console", exact=True).click()
    expect(owner.locator("#ownerReports")).to_contain_text("reported saved private body")
    # A reply already in flight must not repopulate the console after tab hiding.
    def hidden_during_reply(route):
        response = route.fetch()
        owner.evaluate("""() => {
            Object.defineProperty(document, 'hidden', {configurable: true, value: true});
            document.dispatchEvent(new Event('visibilitychange'));
            delete document.hidden;
        }""")
        route.fulfill(response=response)
    owner.route("**/api/commons/owner/reports", hidden_during_reply, times=1)
    owner.get_by_role("button", name="Refresh console", exact=True).click()
    expect(owner.locator("#ownerStatus")).to_contain_text("submitted action may have completed")
    expect(owner.locator("#ownerDashboard")).to_be_hidden()
    expect(owner.locator("#ownerReports")).to_be_empty()
    owner.get_by_role("button", name="Resume verified console", exact=True).click()
    expect(owner.locator("#ownerReports")).to_contain_text("reported saved private body")
    store.test_clock[0] += 15 * 60
    owner.get_by_role("button", name="Refresh console", exact=True).click()
    expect(owner.locator("#ownerDashboard")).to_be_hidden()
    login(owner, store)
    owner.get_by_role("button", name="Owner security", exact=True).click()
    owner.get_by_label("Current owner password", exact=True).fill(PASSWORD)
    owner.get_by_label("New owner password", exact=True).fill(NEW_PASSWORD)
    owner.get_by_label("Confirm new owner password", exact=True).fill(NEW_PASSWORD)
    store.test_clock[0] += 30
    owner.get_by_label("Fresh authenticator code", exact=True).fill(pyotp.TOTP(store.test_secret).at(store.clock()))
    owner.get_by_role("button", name="Update owner credentials", exact=True).click()
    expect(owner.locator("#ownerRecoveryDialog")).to_be_visible()
    assert len(owner.locator("#ownerRecoveryValue").input_value()) == 43
    owner.locator("#ownerRecoverySaved").check()
    owner.get_by_role("button", name="Continue to owner sign-in", exact=True).click()
    expect(owner.locator("#ownerRecoveryValue")).to_have_value("")
    expect(owner.locator("#ownerCurrentPassword")).to_have_value("")
    login(owner, store, NEW_PASSWORD)
    # The owner can explicitly return to chat using the ordinary session cookie.
    owner.get_by_role("link", name="Return to Commons", exact=True).click()
    owner.get_by_role("button", name="Resume existing session", exact=True).click()
    expect(owner.locator("#sessionName")).to_have_text("King")
