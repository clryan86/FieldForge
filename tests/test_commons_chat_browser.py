"""Real two-browser chat tests; opt in like the existing portal browser suite."""

import json
import os
from pathlib import Path

import pytest
import test_commons_chat

preview_server = test_commons_chat.preview_server
pytestmark = pytest.mark.skipif(
    os.environ.get("FIELDFORGE_PORTAL_BROWSER_TESTS") != "1",
    reason="Opt-in Playwright checks require an installed browser",
)


@pytest.fixture
def browsers(preview_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        options = {}
        if os.environ.get("FIELDFORGE_BROWSER_EXECUTABLE"):
            options["executable_path"] = os.environ["FIELDFORGE_BROWSER_EXECUTABLE"]
        browser = playwright.chromium.launch(**options)
        first = browser.new_context(viewport={"width": 1440, "height": 1000})
        second = browser.new_context(viewport={"width": 390, "height": 844})
        alice, bob = first.new_page(), second.new_page()
        errors = []
        alice.on("pageerror", lambda error: errors.append(str(error)))
        bob.on("pageerror", lambda error: errors.append(str(error)))
        url = f"http://127.0.0.1:{preview_server.server_address[1]}"
        try:
            yield alice, bob, url
            assert errors == []
        finally:
            browser.close()


def join(page, url, name, skill=""):
    from playwright.sync_api import expect

    page.goto(url + "/commons")
    page.get_by_label("Preview name", exact=True).fill(name)
    page.get_by_label("Optional skill label").select_option(skill)
    page.locator("#consent").check()
    page.get_by_role("button", name="Join local chat").click()
    expect(page.locator("#connectionLabel")).to_have_text("Local chat connected")
    expect(page.locator("#sessionName")).to_have_text(name)


def test_two_browser_conversation_controls_and_layout(browsers, preview_server, tmp_path):
    from playwright.sync_api import expect

    alice, bob, url = browsers
    api_calls = []
    alice.on("request", lambda request: api_calls.append(request.url) if "/api/" in request.url else None)
    alice.goto(url)
    alice.get_by_role("link", name="Open local chat preview").click()
    expect(alice.get_by_role("heading", name="Enter local Commons")).to_be_visible()
    assert api_calls == []
    join(alice, url, "Test River", "navigation")
    join(bob, url, "Test Morgan", "food")
    alice.get_by_label("Your message", exact=True).fill("TEST: Planning our offline maps. <b>Plain text only.</b>")
    alice.get_by_role("button", name="Send message").click()
    expect(bob.locator(".message-body")).to_contain_text("<b>Plain text only.</b>")
    assert bob.locator(".message-body b").count() == 0
    expect(bob.locator(".skill-tag")).to_have_text("MAP · self-reported")
    bob.get_by_label("Your message", exact=True).fill("TEST: I can help with the food and water checklist.")
    bob.get_by_role("button", name="Send message").click()
    expect(alice.locator(".message-body")).to_have_count(2)
    screenshot = os.environ.get("FIELDFORGE_CHAT_SCREENSHOT")
    if screenshot:
        destination = Path(screenshot)
        destination.parent.mkdir(parents=True, exist_ok=True)
        alice.screenshot(path=str(destination), full_page=True)
    for page in (alice, bob):
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    bob.get_by_role("button", name="Report", exact=True).click()
    bob.get_by_label("Reason", exact=True).select_option("other")
    bob.get_by_role("button", name="Save report").click()
    expect(bob.locator("#status")).to_contain_text("Report saved")
    assert preview_server.app.store.reports()[0]["reason"] == "other"
    bob.get_by_role("button", name="Block", exact=True).click()
    expect(bob.locator(".message-body")).to_have_count(1)
    bob.get_by_text("Blocked participants", exact=False).click()
    bob.get_by_role("button", name="Unblock", exact=True).click()
    expect(bob.locator(".message-body")).to_have_count(2)
    assert "Planning our offline maps" in bob.locator(".message-body").first.inner_text()

    alice.on("dialog", lambda dialog: dialog.accept())
    alice.get_by_role("button", name="Delete", exact=True).click()
    expect(bob.locator(".message.deleted")).to_contain_text("Message removed.")
    with bob.expect_download() as download:
        bob.get_by_role("button", name="Export my messages").click()
    exported = tmp_path / "mine.json"
    download.value.save_as(exported)
    data = json.loads(exported.read_text())
    assert len(data["messages"]) == 1 and data["participant"]["name"] == "Test Morgan"

    alice.get_by_label("Your message", exact=True).fill("Unsent base camp draft")
    alice.get_by_role("button", name="Maps & navigation", exact=True).click()
    expect(alice.get_by_label("Your message", exact=True)).to_have_value("")
    alice.get_by_label("Your message", exact=True).fill("Unsent map draft")
    alice.get_by_role("button", name="Base camp", exact=True).click()
    expect(alice.get_by_label("Your message", exact=True)).to_have_value("Unsent base camp draft")
    alice.get_by_role("button", name="Pause chat").click()
    calls_before = len(api_calls)
    alice.wait_for_timeout(2300)
    assert len(api_calls) == calls_before
    expect(alice.get_by_role("button", name="Send message")).to_be_disabled()
    alice.get_by_role("button", name="Resume chat").click()
    expect(alice.locator("#connectionLabel")).to_have_text("Local chat connected")
    bob.get_by_role("button", name="Leave chat").click()
    expect(bob.locator("#joinPanel")).to_be_visible()
    expect(bob.locator("#status")).to_contain_text("You left chat")


def test_lost_send_response_retains_draft_and_retry_does_not_duplicate(browsers):
    from playwright.sync_api import expect

    alice, bob, url = browsers
    join(alice, url, "Test Retry")
    join(bob, url, "Test Observer")
    def lose_response(route):
        route.fetch()  # The server committed the message; the browser loses its reply.
        route.abort("failed")
    alice.route("**/api/commons/send", lose_response, times=1)
    alice.locator("#message").fill("TEST: Deliver exactly once after retry.")
    alice.get_by_role("button", name="Send message").click()
    expect(alice.locator("#connectionLabel")).to_have_text("Chat paused")
    expect(alice.locator("#message")).to_have_value("TEST: Deliver exactly once after retry.")
    expect(bob.locator(".message-body")).to_have_count(1)
    alice.get_by_role("button", name="Resume chat").click()
    alice.get_by_role("button", name="Send message").click()
    expect(alice.locator("#message")).to_have_value("")
    expect(alice.locator(".message-body")).to_have_count(1)

    requests = []
    alice.on("request", lambda request: requests.append(request.url) if "/api/" in request.url else None)
    alice.reload()
    expect(alice.locator("#joinPanel")).to_be_visible()
    assert requests == []  # A saved session cookie is not consent to reconnect.
    alice.locator("#displayName").fill("Different requested name")
    alice.locator("#consent").check()
    alice.get_by_role("button", name="Join local chat").click()
    expect(alice.locator("#sessionName")).to_have_text("Test Retry")
    expect(alice.locator("#status")).to_contain_text("Joined as Test Retry")
    alice.context.set_offline(True)
    expect(alice.locator("#connectionLabel")).to_have_text("Chat paused")
    alice.context.set_offline(False)
    expect(alice.locator("#connectionLabel")).to_have_text("Chat paused")
