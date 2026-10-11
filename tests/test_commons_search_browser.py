"""Saved-message discovery, privacy and history jumps through the real browser UI."""

import os
import re
import uuid
from pathlib import Path

import pytest
import test_commons_chat
import test_commons_chat_browser
from test_commons_accounts_browser import create_account
from test_commons_history_browser import seed_history, send, token
from test_commons_private_browser import inbox
from test_commons_session_browser import freeze_polling, install_clock, switch_shared_cookie

preview_server = test_commons_chat.preview_server
browsers = test_commons_chat_browser.browsers
join = test_commons_chat_browser.join
pytestmark = test_commons_chat_browser.pytestmark


def open_search(page):
    from playwright.sync_api import expect

    page.get_by_role("button", name="Search saved messages", exact=True).click()
    expect(page.locator("#privateSearchDialog")).to_be_visible()
    expect(page.locator("#privateSearchQuery")).to_be_focused()


def search(page, query):
    from playwright.sync_api import expect

    page.locator("#privateSearchQuery").fill(query)
    with page.expect_response("**/api/commons/private/search") as response:
        page.locator("#privateSearchSubmit").click()
    assert response.value.status == 200
    result = response.value.json()
    expect(page.locator("#privateSearchResults > article")).to_have_count(len(result["results"]))
    return result


def results(page):
    return page.locator("#privateSearchResults > article")


def test_mobile_explicit_search_pages_and_opens_a_message_beyond_latest_history(browsers, preview_server):
    from playwright.sync_api import expect

    _, bob, url = browsers
    calls = []
    bob.on("request", lambda request: calls.append(request.post_data_json)
           if request.url.endswith("/api/commons/private/search") else None)
    join(bob, url, "TEST Search Reader")
    seed = seed_history(preview_server.app.store, bob, view_once_at=5)
    inbox(bob)
    card = bob.locator("#threadList").get_by_role("button", name=seed.title)
    expect(card).to_contain_text("130 unread")
    open_search(bob)
    bob.locator("#privateSearchQuery").fill("history note")
    assert calls == []
    first = search(bob, "history note")
    assert len(first["results"]) == 20
    assert first["results"][0]["id"] == seed.ids[-1]
    assert first["older_before"] == seed.ids[110]
    expect(card).to_contain_text("130 unread")
    assert "TEST private one-time history body" not in bob.content()
    with bob.expect_response("**/api/commons/private/search") as response:
        bob.get_by_role("button", name="Older results", exact=True).click()
    assert response.value.request.post_data_json["before"] == first["older_before"]
    expect(results(bob)).to_have_count(20)
    expect(results(bob).first).to_contain_text("history note 109")
    expect(results(bob).last).to_contain_text("history note 090")
    bob.get_by_role("button", name="Back to newest", exact=True).click()
    expect(results(bob).first).to_contain_text("history note 129")
    hit = search(bob, "history note 000")["results"][0]
    assert hit["id"] == seed.ids[0]
    expect(bob.locator("#privateSearchOlder")).to_be_disabled()
    assert bob.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert bob.locator("#privateSearchDialog").evaluate(
        "element => element.scrollWidth <= element.clientWidth"
    )
    screenshot = os.environ.get("FIELDFORGE_SEARCH_SCREENSHOT")
    if screenshot:
        path = Path(screenshot)
        path.parent.mkdir(parents=True, exist_ok=True)
        bob.screenshot(path=str(path), full_page=False)
    results(bob).get_by_role("button", name="Open conversation:").click()
    expect(bob.locator("#privateSearchDialog")).to_be_hidden()
    expect(bob.locator("#privateSearchResults")).to_be_empty()
    target = bob.locator(f'#privateMessages [data-id="{seed.ids[0]}"]')
    expect(target).to_contain_text("history note 000")
    expect(target).to_be_focused()
    expect(target).to_have_class("private-message search-match")
    # The first read marks the delivery opened. Its next response changes the
    # rendered state; replacing that article must preserve intentional focus.
    expect(target).to_have_attribute("data-value", re.compile(r'"state":"opened"'))
    expect(target).to_be_focused()
    bob.locator("#privateMessage").focus()
    with bob.expect_response("**/api/commons/private/read"):
        pass
    expect(bob.locator("#privateMessage")).to_be_focused()
    expect(bob.locator("#privateLatest")).to_be_visible()
    expect(card).to_contain_text("129 unread")
    bob.get_by_role("button", name="Back to latest", exact=True).click()
    expect(bob.locator("#privateMessages > article")).to_have_count(100)
    assert "history note 000" not in bob.locator("#privateMessages").inner_text()


def test_search_scope_plain_text_and_no_background_history_read_receipts(browsers, preview_server):
    from playwright.sync_api import expect

    alice, _, url = browsers
    join(alice, url, "TEST Search Scope")
    seed = seed_history(preview_server.app.store, alice, count=2)
    inbox(alice)
    alice.locator("#threadList").get_by_role("button", name=seed.title).click()
    expect(alice.locator("#privateMessages > article")).to_have_count(2)
    open_search(alice)
    marker = 'TEST literal 100%_ Straße <img src=x onerror="alert(1)">'
    primary_id = send(seed, marker)
    other_sender, _ = seed.store.join("TEST Search Other Sender", "")
    other = seed.store.private_create(other_sender, "TEST: Another accepted conversation", "direct",
                                      [seed.contact], uuid.uuid4().hex)["thread"]
    seed.store.private_accept(seed.reader, other)
    other_id = seed.store.private_send(other_sender, other, marker, "saved", uuid.uuid4().hex)["id"]
    seed.store.test_clock[0] += 2.1
    once_id = seed.store.private_send(other_sender, other, "TEST literal sealed body", "view_once",
                                     uuid.uuid4().hex)["id"]
    alice.locator("#privateSearchThread").select_option(seed.thread)
    found = search(alice, "100%_ STRASSE")
    assert [row["id"] for row in found["results"]] == [primary_id]
    expect(results(alice)).to_contain_text(marker)
    assert results(alice).locator("img, script").count() == 0
    alice.locator("#privateSearchThread").select_option("")
    found = search(alice, "100%_ STRASSE")
    assert {row["id"] for row in found["results"]} == {primary_id, other_id}
    expect(alice.locator("#threadList").get_by_role("button", name=seed.title)).to_contain_text("1 unread")
    with seed.store._db() as db:
        assert db.execute("SELECT COUNT(*) FROM private_deliveries WHERE message IN (?,?,?) "
                          "AND opened IS NOT NULL", (primary_id, other_id, once_id)).fetchone()[0] == 0
    assert "TEST literal sealed body" not in alice.content()
    assert not alice.evaluate("Object.keys(localStorage).some(key => /search/i.test(key))")
    assert not alice.evaluate("Object.keys(sessionStorage).some(key => /search/i.test(key))")
    assert "STRASSE" not in alice.url


@pytest.mark.parametrize("transition", ["close", "edit", "hide", "pause", "leave"])
def test_late_search_reply_cannot_restore_closed_or_outdated_results(browsers, preview_server, transition):
    from playwright.sync_api import expect

    alice, _, url = browsers
    join(alice, url, "TEST Search Lifecycle")
    seed_history(preview_server.app.store, alice, count=3)
    inbox(alice)
    open_search(alice)
    completed = []

    def change_view_during_reply(route):
        response = route.fetch()
        assert response.status == 200
        assert response.json()["results"]
        if transition == "close":
            alice.evaluate("document.getElementById('closePrivateSearch').click()")
        elif transition == "edit":
            alice.locator("#privateSearchQuery").fill("a different unsent query")
        elif transition == "hide":
            alice.evaluate("""() => {
                Object.defineProperty(document, 'hidden', {configurable:true, value:true});
                document.dispatchEvent(new Event('visibilitychange'));
                delete document.hidden;
            }""")
        elif transition == "pause":
            alice.evaluate("document.getElementById('privatePause').click()")
        else:
            alice.evaluate("document.getElementById('privateLeaveSession').click()")
        route.fulfill(response=response)
        completed.append(True)
        alice.evaluate("document.documentElement.dataset.testSearchReply = 'returned'")

    alice.route("**/api/commons/private/search", change_view_during_reply, times=1)
    alice.locator("#privateSearchQuery").fill("history note")
    alice.locator("#privateSearchSubmit").click()
    expect(alice.locator("#privateSearchResults")).to_be_empty()
    # Process network completion before asserting that the stale reply stayed out.
    expect(alice.locator("html")).to_have_attribute("data-test-search-reply", "returned")
    assert completed
    assert "TEST history note" not in alice.locator("#privateSearchResults").inner_text()
    if transition == "edit":
        expect(alice.locator("#privateSearchDialog")).to_be_visible()
        expect(alice.locator("#privateSearchQuery")).to_have_value("a different unsent query")
        assert search(alice, "history note 001")["results"]
    else:
        expect(alice.locator("#privateSearchDialog")).to_be_hidden()
        expect(alice.locator("#privateSearchQuery")).to_have_value("")
    if transition == "leave":
        expect(alice.locator("#joinPanel")).to_be_visible()
    elif transition == "pause":
        expect(alice.locator("#connectionLabel")).to_have_text("Chat paused")


def test_opening_withdrawn_search_hit_rechecks_message_and_never_restores_its_copy(browsers, preview_server):
    from playwright.sync_api import expect

    alice, _, url = browsers
    join(alice, url, "TEST Search Withdrawal")
    seed = seed_history(preview_server.app.store, alice, count=3)
    inbox(alice)
    open_search(alice)
    search(alice, "history note 001")
    seed.store.private_delete(seed.sender, seed.thread, seed.ids[1])
    results(alice).get_by_role("button", name="Open conversation:").click()
    expect(alice.locator("#privateSearchDialog")).to_be_hidden()
    expect(alice.locator("#privateSearchJumpStatus")).to_contain_text("no longer available")
    expect(alice.locator("#privateSearchResults")).to_be_empty()
    expect(alice.locator("#privateMessages .search-match")).to_have_count(0)
    assert "TEST history note 001" not in alice.content()


@pytest.mark.parametrize("destination", ["rooms", "latest"])
def test_delayed_history_jump_cannot_override_later_navigation(browsers, preview_server, destination):
    from playwright.sync_api import expect

    alice, _, url = browsers
    join(alice, url, "TEST Search Navigation")
    seed = seed_history(preview_server.app.store, alice)
    inbox(alice)
    open_search(alice)
    search(alice, "history note 000")

    def navigate_before_read_arrives(route):
        response = route.fetch()
        assert response.status == 200
        assert route.request.post_data_json["before"] == seed.ids[0] + 1
        control = "publicRoomsButton" if destination == "rooms" else "privateLatest"
        alice.evaluate("id => document.getElementById(id).click()", control)
        route.fulfill(response=response)
        alice.evaluate("document.documentElement.dataset.testHistoryReply = 'returned'")

    alice.route("**/api/commons/private/read", navigate_before_read_arrives, times=1)
    results(alice).get_by_role("button", name="Open conversation:").click()
    expect(alice.locator("html")).to_have_attribute("data-test-history-reply", "returned")
    expect(alice.locator("#privateSearchResults")).to_be_empty()
    expect(alice.locator("#privateMessages .search-match")).to_have_count(0)
    expect(alice.locator("#privateSearchJumpStatus")).to_be_empty()
    if destination == "rooms":
        expect(alice.locator("#privateWorkspace")).to_be_hidden()
        expect(alice.locator("#privateMessages")).to_be_empty()
        expect(alice.locator("#publicRoomsButton")).to_have_attribute("aria-pressed", "true")
    else:
        expect(alice.locator("#privateMessages > article")).to_have_count(100)
        expect(alice.locator("#privateMessages")).to_contain_text("history note 129")
        expect(alice.locator("#privateLatest")).to_be_hidden()
    assert "TEST history note 000" not in alice.content()


def test_membership_lost_between_inbox_and_history_returns_clear_unavailable_state(browsers, preview_server):
    from playwright.sync_api import expect

    alice, _, url = browsers
    join(alice, url, "TEST Search Access Change")
    seed = seed_history(preview_server.app.store, alice, count=3)
    inbox(alice)
    open_search(alice)
    search(alice, "history note 001")

    def leave_before_history_request(route):
        seed.store.private_leave(seed.reader, seed.thread)
        response = route.fetch()
        assert response.status == 404
        route.fulfill(response=response)

    alice.route("**/api/commons/private/read", leave_before_history_request, times=1)
    results(alice).get_by_role("button", name="Open conversation:").click()
    expect(alice.locator("#privateSearchJumpStatus")).to_contain_text("no longer available")
    expect(alice.locator("#privateMessages")).to_be_empty()
    expect(alice.locator("#privateSearchResults")).to_be_empty()
    expect(alice.locator("#connectionLabel")).to_have_text("Local chat connected")
    with alice.expect_response("**/api/commons/private/inbox"):
        pass
    expect(alice.locator("#threadList")).to_contain_text("No invitations or conversations yet")
    expect(alice.locator("#privateSearchJumpStatus")).to_contain_text("no longer available")
    assert "TEST history note 001" not in alice.content()


def test_delayed_history_hit_does_not_take_focus_from_a_composer_being_used(browsers, preview_server):
    from playwright.sync_api import expect

    alice, _, url = browsers
    join(alice, url, "TEST Search Composer Focus")
    seed = seed_history(preview_server.app.store, alice, count=3)
    inbox(alice)
    open_search(alice)
    search(alice, "history note 001")

    def type_before_history_arrives(route):
        response = route.fetch()
        assert response.status == 200
        alice.locator("#privateMessage").fill("TEST: Keep typing this unsent draft")
        route.fulfill(response=response)
        alice.evaluate("document.documentElement.dataset.testComposerReply = 'returned'")

    alice.route("**/api/commons/private/read", type_before_history_arrives, times=1)
    results(alice).get_by_role("button", name="Open conversation:").click()
    expect(alice.locator("html")).to_have_attribute("data-test-composer-reply", "returned")
    target = alice.locator(f'#privateMessages [data-id="{seed.ids[1]}"]')
    expect(target).to_have_class("private-message search-match")
    expect(alice.locator("#privateMessage")).to_be_focused()
    expect(alice.locator("#privateMessage")).to_have_value("TEST: Keep typing this unsent draft")
    with alice.expect_response("**/api/commons/private/read"):
        pass
    expect(alice.locator("#privateMessage")).to_be_focused()


def test_cookie_switch_before_search_cannot_read_as_the_new_account(browsers, preview_server):
    from playwright.sync_api import expect

    alice, bob, url = browsers
    install_clock(alice)
    alice.goto(url + "/commons")
    create_account(alice, "TEST_SearchAlice")
    seed = seed_history(preview_server.app.store, alice, count=3)
    bob.goto(url + "/commons")
    create_account(bob, "TEST_SearchBob")
    inbox(alice)
    open_search(alice)
    freeze_polling(alice)
    alice.locator("#privateSearchQuery").fill("history note")
    switched = switch_shared_cookie(alice, url, "TEST_SearchBob")
    try:
        expect(alice.locator("#sessionName")).to_have_text("TEST_SearchAlice")
        with alice.expect_response("**/api/commons/private/search") as response:
            alice.locator("#privateSearchSubmit").click()
        assert response.value.status == 401
        assert response.value.request.headers["x-fieldforge-participant"] == seed.contact
        expect(alice.locator("#joinPanel")).to_be_visible()
        expect(alice.locator("#privateSearchDialog")).to_be_hidden()
        expect(alice.locator("#privateSearchQuery")).to_have_value("")
        expect(alice.locator("#privateSearchResults")).to_be_empty()
        alice.get_by_role("button", name="Resume existing session", exact=True).click()
        expect(alice.locator("#accountIdentity")).to_have_text("Local account · TEST_SearchBob")
        inbox(alice)
        open_search(alice)
        assert search(alice, "history note")["results"] == []
        assert "TEST history note" not in alice.content()
        assert token(alice) != seed.reader
    finally:
        switched.close()
