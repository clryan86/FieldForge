"""Bounded private-history navigation and invitation lifecycle in real Chromium."""

import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_commons_chat
import test_commons_chat_browser
from test_commons_private_browser import inbox

from fieldforge.online.chat_store import ChatError
from fieldforge.online.commons_preview import COOKIE_NAME

preview_server = test_commons_chat.preview_server
browsers = test_commons_chat_browser.browsers
join = test_commons_chat_browser.join
pytestmark = test_commons_chat_browser.pytestmark


def token(page):
    return next(cookie["value"] for cookie in page.context.cookies() if cookie["name"] == COOKIE_NAME)


def send(seed, body, lifetime="saved"):
    seed.store.test_clock[0] += 2.1
    return seed.store.private_send(seed.sender, seed.thread, body, lifetime, uuid.uuid4().hex)["id"]


def seed_history(store, page, count=130, *, view_once_at=None, accepted=True):
    if not hasattr(store, "test_clock"):
        store.test_clock = [store.clock()]
        store.clock = lambda: store.test_clock[0]
    sender, person = store.join("TEST History Sender", "")
    reader = token(page)
    contact = store.private_inbox(reader)["contact_code"]
    title = "TEST: Saved trip history"
    thread = store.private_create(sender, title, "direct", [contact], uuid.uuid4().hex)["thread"]
    if accepted:
        store.private_accept(reader, thread)
    seed = SimpleNamespace(store=store, sender=sender, person=person, reader=reader,
                           thread=thread, title=title, contact=contact, ids=[])
    for number in range(count):
        body = "TEST private one-time history body" if number == view_once_at else f"TEST history note {number:03}"
        seed.ids.append(send(seed, body, "view_once" if number == view_once_at else "saved"))
    return seed


def choose_history(page, seed):
    from playwright.sync_api import expect

    inbox(page)
    page.locator("#threadList").get_by_role("button", name=seed.title).click()
    expect(page.locator("#privateOlder")).to_be_enabled()
    expect(page.locator("#privateMessages > article")).to_have_count(100)


def test_more_than_one_hundred_unread_pages_and_new_messages_stay_bounded_on_mobile(browsers, preview_server):
    from playwright.sync_api import expect

    _, bob, url = browsers
    join(bob, url, "TEST History Reader")
    seed = seed_history(preview_server.app.store, bob)
    inbox(bob)
    card = bob.locator("#threadList").get_by_role("button", name=seed.title)
    expect(card).to_contain_text("130 unread")
    card.click()
    expect(bob.locator("#privateMessages > article")).to_have_count(100)
    expect(card).to_contain_text("30 unread")
    expect(bob.locator("#privateLatest")).to_be_hidden()
    assert "TEST history note 000" not in bob.locator("#privateMessages").inner_text()
    bob.get_by_role("button", name="Older messages", exact=True).click()
    expect(bob.locator("#privateMessages > article")).to_have_count(30)
    expect(bob.locator("#privateMessages")).to_contain_text("TEST history note 000")
    expect(card).to_contain_text("0 unread")
    expect(bob.locator("#privateOlder")).to_be_disabled()
    expect(bob.locator("#privateLatest")).to_be_visible()
    assert bob.locator("#privateScroll").evaluate("element => element.scrollTop") == 0
    assert "TEST history note 129" not in bob.locator("#privateMessages").inner_text()
    reads = []
    bob.on("request", lambda request: reads.append(request.post_data_json)
           if request.url.endswith("/api/commons/private/read") else None)
    send(seed, "TEST: New arrival while reading older history")
    expect(card).to_contain_text("1 unread")
    expect(bob.locator("#privateHistoryStatus")).to_contain_text("Older messages")
    expect(bob.locator("#privateMessages > article")).to_have_count(30)
    assert "New arrival" not in bob.locator("#privateMessages").inner_text()
    assert reads and all(read.get("before") == seed.ids[30] for read in reads)
    bob.locator("#privateMessage").fill("TEST: Reply sent while browsing older messages")
    bob.get_by_role("button", name="Send privately", exact=True).click()
    expect(bob.locator("#status")).to_contain_text("choose Back to latest")
    expect(bob.locator("#privateMessages > article")).to_have_count(30)
    assert "Reply sent while browsing" not in bob.locator("#privateMessages").inner_text()
    assert bob.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert bob.locator("#privateHistory").evaluate("element => element.scrollWidth <= element.clientWidth")
    screenshot = os.environ.get("FIELDFORGE_HISTORY_SCREENSHOT")
    if screenshot:
        path = Path(screenshot)
        path.parent.mkdir(parents=True, exist_ok=True)
        bob.screenshot(path=str(path), full_page=True)
    bob.get_by_role("button", name="Back to latest", exact=True).click()
    expect(bob.locator("#privateMessages > article")).to_have_count(100)
    expect(bob.locator("#privateMessages")).to_contain_text("New arrival while reading older history")
    expect(bob.locator("#privateMessages")).to_contain_text("Reply sent while browsing older messages")
    expect(card).to_contain_text("0 unread")
    assert "TEST history note 000" not in bob.locator("#privateMessages").inner_text()
    assert bob.locator("#privateScroll").evaluate("element => element.scrollHeight - element.scrollTop - element.clientHeight < 2")


def test_current_older_page_rechecks_withdrawals_expiry_and_blocks_without_view_once_bodies(browsers, preview_server):
    from playwright.sync_api import expect

    alice, _, url = browsers
    join(alice, url, "TEST History Privacy")
    seed = seed_history(preview_server.app.store, alice, view_once_at=5)
    choose_history(alice, seed)
    alice.get_by_role("button", name="Older messages", exact=True).click()
    expect(alice.locator("#privateMessages > article")).to_have_count(30)
    expect(alice.locator("#privateHistoryStatus")).to_contain_text("1 unread")
    expect(alice.get_by_role("button", name="Open once", exact=True)).to_be_visible()
    assert "TEST private one-time history body" not in alice.locator("body").inner_html()
    seed.store.private_delete(seed.sender, seed.thread, seed.ids[0])
    expect(alice.locator(f'#privateMessages [data-id="{seed.ids[0]}"]')).to_contain_text("withdrawn")
    assert "TEST history note 000" not in alice.locator("#privateMessages").inner_html()
    with seed.store._db() as db:
        db.execute("UPDATE private_messages SET expires=? WHERE id=?", (seed.store.clock() - 1, seed.ids[5]))
    expect(alice.locator(f'#privateMessages [data-id="{seed.ids[5]}"]')).to_contain_text("Message expired")
    expect(alice.get_by_role("button", name="Open once", exact=True)).to_have_count(0)
    expect(alice.locator("#privateHistoryStatus")).to_contain_text("Older messages")
    assert "TEST private one-time history body" not in alice.locator("body").inner_html()
    seed.store.block(seed.reader, seed.person["id"], True)
    expect(alice.locator("#privateMessages")).to_be_empty()
    expect(alice.locator("#privateHistoryStatus")).to_contain_text("No messages remain on this older page")
    expect(alice.locator("#privateLatest")).to_be_enabled()
    alice.get_by_role("button", name="Back to latest", exact=True).click()
    expect(alice.locator("#privateHistoryStatus")).to_contain_text("0 latest visible messages")
    expect(alice.locator("#privateMessages")).to_be_empty()


def test_retention_can_empty_a_cursor_without_restoring_cached_history(browsers, preview_server):
    from playwright.sync_api import expect

    alice, _, url = browsers
    join(alice, url, "TEST History Retention")
    seed = seed_history(preview_server.app.store, alice, count=120)
    choose_history(alice, seed)
    alice.get_by_role("button", name="Older messages", exact=True).click()
    expect(alice.locator("#privateMessages > article")).to_have_count(20)
    for number in range(201):
        send(seed, f"TEST retained new note {number:03}")
    expect(alice.locator("#privateMessages")).to_be_empty()
    expect(alice.locator("#privateHistoryStatus")).to_contain_text("No messages remain on this older page")
    expect(alice.locator("#privateLatest")).to_be_enabled()
    assert "TEST history note" not in alice.locator("#privateMessages").inner_html()
    alice.get_by_role("button", name="Back to latest", exact=True).click()
    expect(alice.locator("#privateMessages > article")).to_have_count(100)
    expect(alice.locator("#privateMessages")).to_contain_text("TEST retained new note 200")
    expect(alice.locator("#privateOlder")).to_be_enabled()


def test_late_page_replies_hidden_pause_navigation_and_logout_clear_received_history(browsers, preview_server):
    from playwright.sync_api import expect

    alice, _, url = browsers
    join(alice, url, "TEST History Lifecycle")
    seed = seed_history(preview_server.app.store, alice)
    inbox(alice)

    def hide_during_latest_reply(route):
        response = route.fetch()
        alice.evaluate("""() => {
            Object.defineProperty(document, 'hidden', {configurable: true, value: true});
            document.dispatchEvent(new Event('visibilitychange'));
            delete document.hidden;
        }""")
        route.fulfill(response=response)

    alice.route("**/api/commons/private/read", hide_during_latest_reply, times=1)
    alice.locator("#threadList").get_by_role("button", name=seed.title).click()
    alice.wait_for_timeout(150)
    expect(alice.locator("#privateMessages")).to_be_empty()
    expect(alice.locator("#privateOlder")).to_be_disabled()
    expect(alice.locator("#privateLatest")).to_be_hidden()
    alice.get_by_role("button", name="Private inbox", exact=False).click()
    expect(alice.locator("#privateOlder")).to_be_enabled()

    def return_to_latest_during_old_reply(route):
        response = route.fetch()
        alice.evaluate("document.getElementById('privateLatest').click()")
        expect(alice.locator("#privateMessages > article")).to_have_count(100)
        route.fulfill(response=response)

    alice.route("**/api/commons/private/read", return_to_latest_during_old_reply, times=1)
    alice.get_by_role("button", name="Older messages", exact=True).click()
    expect(alice.locator("#privateLatest")).to_be_hidden()
    expect(alice.locator("#privateMessages > article")).to_have_count(100)
    assert "TEST history note 000" not in alice.locator("#privateMessages").inner_text()
    alice.get_by_role("button", name="Older messages", exact=True).click()
    expect(alice.locator("#privateMessages > article")).to_have_count(30)
    alice.get_by_role("button", name="Community rooms", exact=True).click()
    expect(alice.locator("#privateMessages")).to_be_empty()
    expect(alice.locator("#privateLatest")).to_be_hidden()
    alice.get_by_role("button", name="Private inbox", exact=False).click()
    expect(alice.locator("#privateMessages > article")).to_have_count(100)
    alice.get_by_role("button", name="Older messages", exact=True).click()
    expect(alice.locator("#privateMessages > article")).to_have_count(30)
    alice.locator("#privatePause").click()
    expect(alice.locator("#privateMessages")).to_be_empty()
    expect(alice.locator("#privateHistory")).to_be_hidden()
    expect(alice.locator("#privateEmpty")).to_contain_text("Chat is paused")
    alice.locator("#privatePause").click()
    expect(alice.locator("#privateMessages > article")).to_have_count(100)

    def logout_during_history_reply(route):
        response = route.fetch()
        alice.evaluate("document.getElementById('privateLeaveSession').click()")
        route.fulfill(response=response)

    alice.route("**/api/commons/private/read", logout_during_history_reply, times=1)
    alice.get_by_role("button", name="Older messages", exact=True).click()
    expect(alice.locator("#joinPanel")).to_be_visible()
    expect(alice.locator("#privateMessages")).to_be_empty()
    expect(alice.locator("#privateHistory")).to_be_hidden()
    expect(alice.locator("#viewOnceBody")).to_be_empty()
    expect(alice.locator("#contactCode")).to_have_value("")
    alice.get_by_label("Preview name", exact=True).fill("TEST Fresh History Session")
    alice.locator("#consent").check()
    alice.get_by_role("button", name="Join local chat").click()
    expect(alice.locator("#connectionLabel")).to_have_text("Local chat connected")
    inbox(alice)
    expect(alice.locator("#threadList")).to_contain_text("No invitations or conversations yet")
    expect(alice.locator("#privateMessages")).to_be_empty()
    expect(alice.locator("#privateLatest")).to_be_hidden()


def test_decline_and_block_frees_recipient_capacity_without_exposing_messages(browsers, preview_server, monkeypatch):
    from playwright.sync_api import expect

    monkeypatch.setattr("fieldforge.online.private_chat.MAX_MEMBER_THREADS", 1)
    _, bob, url = browsers
    join(bob, url, "TEST Invitation Recipient")
    seed = seed_history(preview_server.app.store, bob, count=1, accepted=False)
    other, _ = seed.store.join("TEST Different Inviter", "")
    with pytest.raises(ChatError) as full:
        seed.store.private_create(other, "TEST blocked by full inbox", "direct", [seed.contact], uuid.uuid4().hex)
    assert full.value.status == 409
    inbox(bob)
    bob.locator("#threadList").get_by_role("button", name=seed.title).click()
    expect(bob.locator("#privateInvitation")).to_be_visible()
    expect(bob.locator("#privateMessages")).to_be_empty()
    assert "TEST history note 000" not in bob.locator("body").inner_text()
    assert bob.evaluate("document.documentElement.scrollWidth <= innerWidth")
    bob.on("dialog", lambda dialog: dialog.accept())
    bob.get_by_role("button", name="Decline and block sender", exact=True).click()
    expect(bob.locator("#status")).to_contain_text("Invitation declined and sender blocked")
    expect(bob.locator("#privateInvitation")).to_be_hidden()
    assert seed.title not in bob.locator("#threadList").inner_text()
    assert "TEST history note 000" not in bob.locator("body").inner_html()
    with pytest.raises(ChatError) as blocked:
        seed.store.private_create(seed.sender, "TEST unwanted retry", "direct", [seed.contact], uuid.uuid4().hex)
    assert blocked.value.status == 404
    seed.store.private_create(other, "TEST welcome invitation", "direct", [seed.contact], uuid.uuid4().hex)
    expect(bob.locator("#threadList")).to_contain_text("TEST welcome invitation")


def test_lost_invitation_retry_reports_a_closed_conversation_without_reopening(browsers, preview_server):
    from playwright.sync_api import expect

    alice, _, url = browsers
    join(alice, url, "TEST Closed Invite Sender")
    store = preview_server.app.store
    recipient, person = store.join("TEST Closed Invite Recipient", "")
    sender = token(alice)
    inbox(alice)
    alice.get_by_role("button", name="New", exact=True).click()
    alice.get_by_label("Subject or group name", exact=True).fill("TEST closed invitation retry")
    alice.get_by_label("Recipient contact codes", exact=True).fill(person["id"])

    def close_then_lose_reply(route):
        response = route.fetch()
        thread = response.json()["thread"]
        store.private_leave(recipient, thread)
        store.private_leave(sender, thread)
        route.abort("failed")

    alice.route("**/api/commons/private/create", close_then_lose_reply, times=1)
    alice.get_by_role("button", name="Send invitation", exact=True).click()
    expect(alice.locator("#connectionLabel")).to_have_text("Chat paused")
    alice.get_by_role("button", name="Cancel", exact=True).click()
    alice.locator("#privatePause").click()
    expect(alice.locator("#connectionLabel")).to_have_text("Local chat connected")
    alice.get_by_role("button", name="New", exact=True).click()
    expect(alice.locator("#conversationTitle")).to_have_value("TEST closed invitation retry")
    alice.get_by_role("button", name="Send invitation", exact=True).click()
    expect(alice.locator("#status")).to_contain_text("conversation has since closed")
    expect(alice.locator("#newConversationDialog")).to_be_hidden()
    expect(alice.locator("#threadList")).to_contain_text("No invitations or conversations yet")
    expect(alice.locator("#privateMessages")).to_be_empty()
    expect(alice.locator("#conversationTitle")).to_have_value("")
    expect(alice.locator("#conversationContacts")).to_have_value("")
    _, fresh = store.join("TEST Next Invite Recipient", "")
    alice.get_by_role("button", name="New", exact=True).click()
    alice.get_by_label("Subject or group name", exact=True).fill("TEST new invitation after closed retry")
    alice.get_by_label("Recipient contact codes", exact=True).fill(fresh["id"])
    alice.get_by_role("button", name="Send invitation", exact=True).click()
    expect(alice.locator("#status")).to_contain_text("Invitation sent")
    expect(alice.locator("#privateTitle")).to_have_text("TEST new invitation after closed retry")
