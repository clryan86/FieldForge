"""Owner notices through the real console and explicitly connected member UI."""

import os
import uuid
from pathlib import Path

import pytest
import test_commons_chat
import test_commons_chat_browser
from test_commons_accounts_browser import create_account
from test_commons_history_browser import token
from test_commons_owner import PASSWORD, code
from test_commons_owner_browser import login, setup
from test_commons_private_browser import inbox
from test_commons_session_browser import freeze_polling, install_clock, switch_shared_cookie

preview_server = test_commons_chat.preview_server
browsers = test_commons_chat_browser.browsers
join = test_commons_chat_browser.join
pytestmark = test_commons_chat_browser.pytestmark


def seed_notice(store, title="TEST: A notice for the whole camp", body="TEST: Bring your offline maps to the practice session."):
    store.test_clock[0] += 30
    owner, _ = store.owner_login("CLRYAN86", PASSWORD, code(store))
    result = store.owner_announcements_publish(owner, title, body, str(uuid.uuid4()))
    return owner, result["announcement"]


def publish(page, title, body):
    from playwright.sync_api import expect

    page.locator("#ownerAnnouncementTitle").fill(title)
    page.locator("#ownerAnnouncementBody").fill(body)
    with page.expect_response("**/api/commons/owner/announcements/publish") as response:
        page.get_by_role("button", name="Publish announcement", exact=True).click()
    assert response.value.status == 200
    announcement = response.value.json()["announcement"]
    expect(page.locator(f'#ownerAnnouncementList > article[data-id="{announcement["id"]}"]')).to_contain_text(title)
    expect(page.locator("#ownerAnnouncementTitle")).to_have_value("")
    expect(page.locator("#ownerAnnouncementBody")).to_have_value("")
    return announcement


def hidden(page, *, restore=True):
    page.evaluate("""() => {
        Object.defineProperty(document, 'hidden', {configurable: true, value: true});
        document.dispatchEvent(new Event('visibilitychange'));
    }""")
    if restore:
        page.evaluate("""() => {
            delete document.hidden;
            document.dispatchEvent(new Event('visibilitychange'));
        }""")


def screenshot(page, variable):
    if destination := os.environ.get(variable):
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=True)


def test_owner_publishes_plain_text_notice_to_mobile_rooms_and_inbox_then_withdraws(browsers, preview_server):
    from playwright.sync_api import expect

    owner, member, url = browsers
    store = setup(preview_server)
    calls = []
    for page in (owner, member):
        page.on("request", lambda request: calls.append(request.url) if "/api/" in request.url else None)
    owner.goto(url + "/commons-owner")
    member.goto(url + "/commons")
    assert calls == []
    expect(member.locator("#commonsAnnouncements")).to_be_hidden()
    login(owner, store)
    join(member, url, "TEST Announcement Reader")
    title = "TEST: Map practice at Base camp"
    body = "TEST: Bring your downloaded maps and a notebook.\n<b>These are literal tags.</b>"
    item = publish(owner, title, body)
    notice = member.locator(f'#commonsAnnouncementList > article[data-id="{item["id"]}"]')
    expect(notice).to_contain_text(title)
    expect(notice).to_contain_text(body)
    expect(notice).to_contain_text("Owner announcement")
    assert notice.locator("b, script, img, a").count() == 0
    assert owner.locator("#ownerAnnouncementList b, #ownerAnnouncementList script").count() == 0
    for page in (owner, member):
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(owner, "FIELDFORGE_OWNER_ANNOUNCEMENT_SCREENSHOT")
    screenshot(member, "FIELDFORGE_MEMBER_ANNOUNCEMENT_SCREENSHOT")

    member.locator("#message").fill("TEST: My unrelated room draft")
    member.locator("#message").focus()
    notice.evaluate("element => element.setAttribute('data-test-preserved', 'true')")
    with member.expect_response("**/api/commons/announcements"):
        pass
    expect(notice).to_have_attribute("data-test-preserved", "true")
    expect(member.locator("#message")).to_be_focused()
    expect(member.locator("#message")).to_have_value("TEST: My unrelated room draft")
    inbox(member)
    expect(member.locator("#commonsAnnouncements")).to_be_visible()
    expect(notice).to_be_visible()

    owner.on("dialog", lambda dialog: dialog.accept())
    owner.locator(f'#ownerAnnouncementList > article[data-id="{item["id"]}"]').get_by_role(
        "button", name="Withdraw announcement"
    ).click()
    expect(member.locator("#commonsAnnouncementList > article")).to_have_count(0)
    expect(owner.locator("#ownerAnnouncementList > article")).to_have_count(0)
    expect(owner.locator("#ownerAudit")).to_contain_text("publish announcement")
    expect(owner.locator("#ownerAudit")).to_contain_text("withdraw announcement")
    assert title not in owner.locator("#ownerAudit").inner_text()
    assert body not in owner.locator("#ownerAudit").inner_text()


def test_console_draft_survives_refresh_and_validates_unicode_before_publishing(browsers, preview_server):
    from playwright.sync_api import expect

    _, owner, url = browsers  # Exercise the owner composer at 390 pixels too.
    store = setup(preview_server)
    owner.goto(url + "/commons-owner")
    login(owner, store)
    title = "TEST: " + "🌲" * 74  # 80 Unicode characters, more than 80 UTF-16 code units.
    owner.locator("#ownerAnnouncementTitle").fill(title)
    owner.locator("#ownerAnnouncementBody").fill("TEST: Keep this draft through a console refresh.")
    owner.get_by_role("button", name="Refresh console", exact=True).click()
    expect(owner.locator("#ownerStatus")).to_contain_text("Console refreshed")
    expect(owner.locator("#ownerAnnouncementTitle")).to_have_value(title)
    expect(owner.locator("#ownerAnnouncementBody")).to_have_value("TEST: Keep this draft through a console refresh.")
    calls = []
    owner.on("request", lambda request: calls.append(request.post_data_json)
             if request.url.endswith("/owner/announcements/publish") else None)
    owner.locator("#ownerAnnouncementBody").fill("🌲" * 501)
    owner.locator("#ownerAnnouncementForm").evaluate(
        "form => form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))"
    )
    expect(owner.locator("#ownerAnnouncementBody")).to_have_value("🌲" * 501)
    assert calls == []
    # Exactly 2,000 UTF-8 bytes is allowed, and no markup interpretation occurs.
    publish(owner, title, "é" * 1000)
    assert len(calls) == 1
    assert calls[0]["title"] == title
    assert owner.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_submitted_composer_disables_edits_and_duplicate_submits(browsers, preview_server):
    from playwright.sync_api import expect

    owner, _, url = browsers
    store = setup(preview_server)
    owner.goto(url + "/commons-owner")
    login(owner, store)
    held, calls = [], []

    def hold(route):
        calls.append(route.request.post_data_json)
        held.append((route, route.fetch()))
        owner.evaluate("document.documentElement.setAttribute('data-test-announcement-held', 'true')")

    owner.route("**/api/commons/owner/announcements/publish", hold)
    owner.locator("#ownerAnnouncementTitle").fill("TEST: One submitted notice")
    owner.locator("#ownerAnnouncementBody").fill("TEST: One request, even if submit is repeated.")
    owner.get_by_role("button", name="Publish announcement", exact=True).click()
    expect(owner.locator("html")).to_have_attribute("data-test-announcement-held", "true")
    expect(owner.locator("#ownerAnnouncementTitle")).to_be_disabled()
    expect(owner.locator("#ownerAnnouncementBody")).to_be_disabled()
    owner.locator("#ownerAnnouncementForm").evaluate(
        "form => form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))"
    )
    assert len(calls) == 1
    held[0][0].fulfill(response=held[0][1])
    expect(owner.locator("#ownerAnnouncementList > article")).to_have_count(1)
    expect(owner.locator("#ownerAnnouncementTitle")).to_be_enabled()
    expect(owner.locator("#ownerAnnouncementTitle")).to_have_value("")
    assert len(calls) == 1


def test_confirmed_publication_is_reported_accurately_when_followup_refresh_fails(browsers, preview_server):
    from playwright.sync_api import expect

    owner, _, url = browsers
    store = setup(preview_server)
    owner.goto(url + "/commons-owner")
    login(owner, store)
    owner.route("**/api/commons/owner/announcements", lambda route: route.fulfill(
        status=503, content_type="application/json",
        body='{"error":{"message":"TEST: Announcement refresh is temporarily unavailable."}}'
    ), times=1)
    owner.locator("#ownerAnnouncementTitle").fill("TEST: Saved before refresh failed")
    owner.locator("#ownerAnnouncementBody").fill("TEST: This notice was confirmed saved.")
    with owner.expect_response("**/api/commons/owner/announcements/publish") as response:
        owner.get_by_role("button", name="Publish announcement", exact=True).click()
    assert response.value.status == 200
    expect(owner.locator("#ownerAnnouncementStatus")).to_contain_text("published")
    expect(owner.locator("#ownerAnnouncementStatus")).to_contain_text("refresh")
    assert "draft is retained" not in owner.locator("#ownerAnnouncementStatus").inner_text()
    expect(owner.locator("#ownerAnnouncementTitle")).to_have_value("")
    expect(owner.locator("#ownerAnnouncementBody")).to_have_value("")
    owner.get_by_role("button", name="Refresh console", exact=True).click()
    expect(owner.locator("#ownerAnnouncementList > article")).to_have_count(1)
    expect(owner.locator("#ownerAnnouncementList")).to_contain_text("TEST: Saved before refresh failed")


@pytest.mark.parametrize("interruption", ["hidden", "lost_reply"])
def test_publish_reply_cannot_repopulate_cleared_console_or_trigger_automatic_retry(browsers, preview_server, interruption):
    from playwright.sync_api import expect

    owner, _, url = browsers
    store = setup(preview_server)
    owner.goto(url + "/commons-owner")
    login(owner, store)
    calls = []

    def interrupted(route):
        calls.append(route.request.post_data_json)
        response = route.fetch()  # Commit first, then lose access to the old view/reply.
        if interruption == "hidden":
            hidden(owner)
            route.fulfill(response=response)
        else:
            route.abort("failed")

    owner.route("**/api/commons/owner/announcements/publish", interrupted, times=1)
    owner.locator("#ownerAnnouncementTitle").fill("TEST: Committed before interruption")
    owner.locator("#ownerAnnouncementBody").fill("TEST: Refresh to discover the saved result.")
    owner.get_by_role("button", name="Publish announcement", exact=True).click()
    expect(owner.locator("#ownerDashboard")).to_be_hidden()
    expect(owner.locator("#ownerAnnouncementTitle")).to_have_value("")
    expect(owner.locator("#ownerAnnouncementBody")).to_have_value("")
    expect(owner.locator("#ownerAnnouncementList")).to_be_empty()
    owner.get_by_role("button", name="Resume verified console", exact=True).click()
    expect(owner.locator("#ownerAnnouncementList > article")).to_have_count(1)
    expect(owner.locator("#ownerAnnouncementList")).to_contain_text("TEST: Committed before interruption")
    assert len(calls) == 1


@pytest.mark.parametrize("transition", ["pause", "hidden"])
def test_late_member_notice_reply_is_discarded_after_view_clears(browsers, preview_server, transition):
    from playwright.sync_api import expect

    member, _, url = browsers
    store = setup(preview_server)
    seed_notice(store)
    install_clock(member)
    join(member, url, "TEST Late Notice Reader")
    expect(member.locator("#commonsAnnouncementList > article")).to_have_count(1)
    freeze_polling(member)

    def stale_reply(route):
        response = route.fetch()
        if transition == "pause":
            member.locator("#pauseButton").evaluate("button => button.click()")
        else:
            hidden(member)  # A hide→show cycle before the response must invalidate it too.
        route.fulfill(response=response)
        member.evaluate("document.documentElement.setAttribute('data-test-notice-released', 'true')")

    member.route("**/api/commons/announcements", stale_reply, times=1)
    member.get_by_role("button", name="Maps & navigation", exact=True).click()
    expect(member.locator("html")).to_have_attribute("data-test-notice-released", "true")
    expect(member.locator("#commonsAnnouncementList")).to_be_empty()
    expect(member.locator("#commonsAnnouncements")).to_be_hidden()
    if transition == "pause":
        member.get_by_role("button", name="Resume chat", exact=True).click()
    else:
        member.get_by_role("button", name="Base camp", exact=True).click()
    expect(member.locator("#commonsAnnouncementList > article")).to_have_count(1)


def test_hidden_member_stops_notice_reads_and_explicit_pause_and_logout_clear_notice_text(browsers, preview_server):
    from playwright.sync_api import expect

    member, _, url = browsers
    store = setup(preview_server)
    seed_notice(store)
    join(member, url, "TEST Paused Notice Reader")
    expect(member.locator("#commonsAnnouncementList > article")).to_have_count(1)
    calls = []
    member.on("request", lambda request: calls.append(request.url)
              if request.url.endswith("/api/commons/announcements") else None)
    hidden(member, restore=False)
    expect(member.locator("#commonsAnnouncementList")).to_be_empty()
    before = len(calls)
    member.wait_for_timeout(2250)
    assert len(calls) == before
    member.evaluate("""() => {
        delete document.hidden;
        document.dispatchEvent(new Event('visibilitychange'));
    }""")
    expect(member.locator("#commonsAnnouncementList > article")).to_have_count(1)
    member.get_by_role("button", name="Pause chat", exact=True).click()
    expect(member.locator("#commonsAnnouncementList")).to_be_empty()
    before = len(calls)
    member.wait_for_timeout(2250)
    assert len(calls) == before
    member.get_by_role("button", name="Resume chat", exact=True).click()
    expect(member.locator("#commonsAnnouncementList > article")).to_have_count(1)
    member.get_by_role("button", name="Leave chat", exact=True).click()
    expect(member.locator("#joinPanel")).to_be_visible()
    expect(member.locator("#commonsAnnouncementList")).to_be_empty()
    expect(member.locator("#commonsAnnouncements")).to_be_hidden()


def test_member_cookie_switch_cannot_read_notices_as_another_account_before_resume(browsers, preview_server):
    from playwright.sync_api import expect

    member, other, url = browsers
    store = setup(preview_server)
    seed_notice(store)
    install_clock(member)
    member.goto(url + "/commons")
    create_account(member, "TEST_NoticeAlice")
    other.goto(url + "/commons")
    create_account(other, "TEST_NoticeBob")
    expect(member.locator("#commonsAnnouncementList > article")).to_have_count(1)
    freeze_polling(member)
    original_token = token(member)
    expected_id = store.account_resume(original_token)["viewer"]["id"]
    switched = switch_shared_cookie(member, url, "TEST_NoticeBob")
    try:
        with member.expect_request("**/api/commons/announcements") as request:
            member.get_by_role("button", name="Maps & navigation", exact=True).click()
        # Both room and notice requests carry the old identity. Whichever 401
        # arrives first clears the session and may abort its parallel sibling.
        assert request.value.headers["x-fieldforge-participant"] == expected_id
        expect(member.locator("#joinPanel")).to_be_visible()
        expect(member.locator("#commonsAnnouncementList")).to_be_empty()
        member.get_by_role("button", name="Resume existing session", exact=True).click()
        expect(member.locator("#sessionName")).to_have_text("TEST_NoticeBob")
        expect(member.locator("#commonsAnnouncementList > article")).to_have_count(1)
    finally:
        switched.close()


def test_expired_owner_grant_clears_announcement_draft_and_never_publishes(browsers, preview_server):
    from playwright.sync_api import expect

    owner, _, url = browsers
    store = setup(preview_server)
    owner.goto(url + "/commons-owner")
    login(owner, store)
    owner.locator("#ownerAnnouncementTitle").fill("TEST: Expired owner draft")
    owner.locator("#ownerAnnouncementBody").fill("TEST: This must not become an announcement.")
    store.test_clock[0] += 15 * 60
    with owner.expect_response("**/api/commons/owner/announcements/publish") as response:
        owner.get_by_role("button", name="Publish announcement", exact=True).click()
    assert response.value.status == 403
    expect(owner.locator("#ownerDashboard")).to_be_hidden()
    expect(owner.locator("#ownerAnnouncementTitle")).to_have_value("")
    expect(owner.locator("#ownerAnnouncementBody")).to_have_value("")
    expect(owner.locator("#ownerAnnouncementList")).to_be_empty()
    login(owner, store)
    expect(owner.locator("#ownerAnnouncementList > article")).to_have_count(0)
