"""Exercise real invitations, private audiences and one-time message delivery."""

import json
import os
from pathlib import Path

import test_commons_chat
import test_commons_chat_browser

preview_server = test_commons_chat.preview_server
browsers = test_commons_chat_browser.browsers
join = test_commons_chat_browser.join
pytestmark = test_commons_chat_browser.pytestmark


def inbox(page):
    from playwright.sync_api import expect

    page.get_by_role("button", name="Private inbox").click()
    expect(page.locator("#contactCode")).not_to_have_value("")
    return page.locator("#contactCode").input_value()


def invite(page, title, contacts, *, group=False):
    from playwright.sync_api import expect

    page.get_by_role("button", name="New", exact=True).click()
    page.get_by_label("Subject or group name").fill(title)
    page.get_by_label("Conversation type").select_option("group" if group else "direct")
    page.get_by_label("Recipient contact codes").fill("\n".join(contacts))
    page.get_by_role("button", name="Send invitation", exact=True).click()
    expect(page.locator("#privateTitle")).to_have_text(title)


def accept(page, title):
    from playwright.sync_api import expect

    page.locator("#threadList").get_by_role("button", name=title).click()
    expect(page.locator("#privateInvitation")).to_be_visible()
    page.get_by_role("button", name="Accept invitation").click()
    expect(page.locator("#privateCompose")).to_be_visible()


def test_saved_inbox_invitations_replies_and_outsider_cannot_read(browsers, tmp_path):
    from playwright.sync_api import expect

    alice, bob, url = browsers
    join(alice, url, "Test Sender")
    join(bob, url, "Test Recipient")
    bob_code = inbox(bob)
    inbox(alice)
    invite(alice, "TEST: Offline trip preparation", [bob_code])
    alice.locator("#privateMessage").fill("TEST: Can you review the local map plan?")
    alice.get_by_role("button", name="Send privately").click()
    expect(alice.locator("#privateMessage")).to_have_value("")
    expect(bob.locator("#threadList")).to_contain_text("Invitation")
    assert "Can you review" not in bob.locator("body").inner_text()
    accept(bob, "TEST: Offline trip preparation")
    expect(bob.locator("#privateMessages")).to_contain_text("Can you review the local map plan?")
    bob.locator("#privateMessage").fill("TEST: Yes. I will check the saved route.")
    bob.get_by_role("button", name="Send privately").click()
    expect(alice.locator("#privateMessages .message-body")).to_have_count(2)
    for page in (alice, bob):
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    outsider_context = alice.context.browser.new_context()
    try:
        outsider = outsider_context.new_page()
        join(outsider, url, "Test Outsider")
        inbox(outsider)
        expect(outsider.locator("#threadList")).to_contain_text("No invitations")
        thread = bob.evaluate("async () => (await (await fetch('/api/commons/private/inbox', {method:'POST', headers:{'Content-Type':'application/json','X-FieldForge-Chat':'preview-v1'},body:'{}'})).json()).threads[0].id")
        result = outsider.evaluate("""async thread => {
            const response = await fetch('/api/commons/private/read', {method:'POST',
              headers:{'Content-Type':'application/json','X-FieldForge-Chat':'preview-v1'},body:JSON.stringify({thread})});
            return {status:response.status,text:await response.text()};
        }""", thread)
        assert result["status"] == 404 and "local map plan" not in result["text"]
    finally:
        outsider_context.close()

    with alice.expect_download() as download:
        alice.get_by_role("button", name="Export my saved sent messages").click()
    destination = tmp_path / "private-export.json"
    download.value.save_as(destination)
    content = json.loads(destination.read_text())
    assert len(content["messages"]) == 1
    assert "Can you review" in content["messages"][0]["body"]
    assert "saved route" not in destination.read_text()
    alice.get_by_role("button", name="Pause chat", exact=True).click()
    expect(alice.get_by_role("button", name="Send privately")).to_be_disabled()
    alice.get_by_role("button", name="Resume chat", exact=True).click()
    expect(alice.get_by_role("button", name="Send privately")).to_be_enabled()


def test_private_group_view_once_clears_body_and_cannot_reopen(browsers):
    from playwright.sync_api import expect

    alice, bob, url = browsers
    join(alice, url, "Test Group Host")
    join(bob, url, "Test Group Member")
    bob_code = inbox(bob)
    context = alice.context.browser.new_context()
    try:
        carol = context.new_page()
        join(carol, url, "Test Second Member")
        carol_code = inbox(carol)
        inbox(alice)
        title = "TEST: Supply planning group"
        invite(alice, title, [bob_code, carol_code], group=True)
        accept(bob, title)
        accept(carol, title)
        alice.locator("#privateLifetime").select_option("view_once")
        alice.locator("#privateMessage").fill("TEST: This text should be delivered once per recipient.")
        alice.get_by_role("button", name="Send privately").click()
        expect(bob.get_by_role("button", name="Open once", exact=True)).to_be_visible()
        expect(carol.get_by_role("button", name="Open once", exact=True)).to_be_visible()
        assert "delivered once per recipient" not in bob.locator("body").inner_text()
        screenshot = os.environ.get("FIELDFORGE_PRIVATE_SCREENSHOT")
        if screenshot:
            path = Path(screenshot)
            path.parent.mkdir(parents=True, exist_ok=True)
            alice.screenshot(path=str(path), full_page=True)
        bob.on("dialog", lambda dialog: dialog.accept())
        bob.bring_to_front()
        bob.clock.install()
        bob.get_by_role("button", name="Open once", exact=True).click()
        expect(bob.locator("#viewOnceBody")).to_have_text("TEST: This text should be delivered once per recipient.")
        bob.clock.fast_forward(31_000)
        expect(bob.locator("#viewOnceBody")).to_be_empty()
        expect(bob.get_by_role("button", name="Open once", exact=True)).to_have_count(0)
        expect(carol.get_by_role("button", name="Open once", exact=True)).to_have_count(1)
        carol.on("dialog", lambda dialog: dialog.accept())
        carol.bring_to_front()
        carol.get_by_role("button", name="Open once", exact=True).click()
        expect(carol.locator("#viewOnceBody")).not_to_be_empty()
        carol.get_by_role("button", name="Close and clear").click()
        expect(carol.locator("#viewOnceBody")).to_be_empty()
        expect(carol.get_by_role("button", name="Open once", exact=True)).to_have_count(0)
        expect(bob.locator(".private-disclosure")).to_contain_text("Screenshots")
    finally:
        context.close()


def test_lost_view_once_response_cannot_be_retried_or_replayed(browsers):
    from playwright.sync_api import expect

    alice, bob, url = browsers
    join(alice, url, "Test One-time Sender")
    join(bob, url, "Test One-time Reader")
    code = inbox(bob)
    inbox(alice)
    invite(alice, "TEST: Lost response", [code])
    accept(bob, "TEST: Lost response")
    alice.locator("#privateLifetime").select_option("view_once")
    alice.locator("#privateMessage").fill("TEST: Never replay after a lost open response.")
    alice.get_by_role("button", name="Send privately").click()
    expect(bob.get_by_role("button", name="Open once", exact=True)).to_be_visible()
    def lose_response(route):
        route.fetch()
        route.abort("failed")
    bob.route("**/api/commons/private/open", lose_response, times=1)
    bob.on("dialog", lambda dialog: dialog.accept())
    bob.get_by_role("button", name="Open once", exact=True).click()
    expect(bob.locator("#status")).to_contain_text("may already be consumed")
    expect(bob.locator("#viewOnceBody")).to_be_empty()
    bob.get_by_role("button", name="Resume chat", exact=True).click()
    expect(bob.get_by_role("button", name="Open once", exact=True)).to_have_count(0)
    assert "Never replay" not in bob.locator("body").inner_text()
