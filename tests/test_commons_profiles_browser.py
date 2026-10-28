"""Exercise opt-in profiles, local photos, directory privacy and stale UI replies."""

import base64
import io
import json
import os
from pathlib import Path

import pytest
import test_commons_chat
import test_commons_chat_browser
import test_commons_profiles
from test_commons_accounts_browser import PASSWORD, create_account, save_recovery, sign_in

from fieldforge.online.commons_preview import COOKIE_NAME

preview_server = test_commons_chat.preview_server
browsers = test_commons_chat_browser.browsers
join = test_commons_chat_browser.join
pytestmark = test_commons_chat_browser.pytestmark


def open_profile(page):
    from playwright.sync_api import expect

    page.get_by_role("button", name="My profile", exact=True).click()
    expect(page.locator("#profileDisplayName")).to_be_enabled()
    return page.locator("#profileForm")


def save_profile(page):
    from playwright.sync_api import expect

    page.get_by_role("button", name="Save profile", exact=True).click()
    expect(page.locator("#profileStatus")).to_contain_text("Profile saved")
    expect(page.locator("#profileSave")).to_be_enabled()


def refresh_directory(page):
    from playwright.sync_api import expect

    page.get_by_role("button", name="Refresh directory", exact=True).click()
    expect(page.locator("#directoryRefresh")).to_be_enabled()


def session_token(page):
    return next(cookie["value"] for cookie in page.context.cookies() if cookie["name"] == COOKIE_NAME)


def hide_tab(page):
    page.evaluate("""() => {
        Object.defineProperty(document, 'hidden', {configurable: true, value: true});
        document.dispatchEvent(new Event('visibilitychange'));
        delete document.hidden;
        document.dispatchEvent(new Event('visibilitychange'));
    }""")


def test_guest_guidance_explicit_profile_entry_and_optional_photo_support(browsers, monkeypatch):
    from playwright.sync_api import expect

    _, alice, url = browsers  # Exercise the editor and guest upgrade at 390px.
    calls = []
    alice.on("request", lambda request: calls.append(request.url) if "/api/" in request.url else None)
    alice.goto(url + "/commons")
    expect(alice.locator("#openProfile")).to_be_disabled()
    expect(alice.locator("#openDirectory")).to_be_disabled()
    assert calls == []
    join(alice, url, "TEST Profile Guest")
    assert not any("/profile/" in call for call in calls)
    alice.get_by_role("button", name="My profile", exact=True).click()
    expect(alice.locator("#profileGuest")).to_contain_text("Profiles start private")
    expect(alice.locator("#profileForm")).to_be_hidden()
    assert not any("/profile/" in call for call in calls)
    alice.get_by_role("button", name="Save my account to add a profile", exact=True).click()
    expect(alice.locator("#profileDialog")).to_be_hidden()
    alice.get_by_label("Account username", exact=True).fill("TEST_ProfileGuest")
    alice.get_by_label("Password", exact=True).fill(PASSWORD)
    alice.get_by_label("Confirm password", exact=True).fill(PASSWORD)
    alice.locator("#accountConsent").check()
    alice.get_by_role("button", name="Create local account", exact=True).click()
    save_recovery(alice)
    assert not any("/profile/" in call for call in calls)
    monkeypatch.setattr("fieldforge.online.profiles._photo_support", lambda: False)
    open_profile(alice)
    expect(alice.locator("#profileVisibility")).not_to_be_checked()
    expect(alice.locator("#profileShareSkills")).not_to_be_checked()
    expect(alice.locator("#profileSharePhoto")).not_to_be_checked()
    expect(alice.locator("#profilePhotoUploadFields")).to_be_hidden()
    expect(alice.locator("#profilePhotoUnavailable")).to_contain_text("unavailable")
    assert sum("/profile/get" in call for call in calls) == 1
    profile_calls = [call for call in calls if "/profile/" in call]
    alice.wait_for_timeout(2200)
    assert [call for call in calls if "/profile/" in call] == profile_calls
    for category in ["medical", "food", "construction", "water", "power"]:
        alice.locator(f'#profileInterests input[value="{category}"]').check()
    expect(alice.locator('#profileInterests input[value="navigation"]')).to_be_disabled()
    alice.locator('#profileInterests input[value="food"]').uncheck()
    expect(alice.locator('#profileInterests input[value="navigation"]')).to_be_enabled()
    assert alice.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert alice.locator("#profileDialog").evaluate("element => element.scrollWidth <= element.clientWidth")
    alice.locator("#profileBio").fill("TEST: unsaved profile text")
    alice.get_by_role("button", name="Close profile", exact=True).click()
    expect(alice.locator("#profileBio")).to_have_value("")
    assert alice.evaluate("localStorage.length + sessionStorage.length") == 0


def test_directory_opt_in_separate_skill_consent_plain_text_and_withdrawal(browsers):
    from playwright.sync_api import expect

    alice, bob, url = browsers
    alice.goto(url + "/commons")
    create_account(alice, "TEST_ProfileRiver")
    open_profile(alice)
    alice.locator("#profileDisplayName").fill("TEST River <b>plain text</b>")
    alice.locator("#profileBio").fill("TEST: Maps and teaching. <img src=x onerror=alert(1)>")
    alice.locator('#profileInterests input[value="navigation"]').check()
    alice.locator('#profileInterests input[value="medical"]').check()
    alice.get_by_label("Medical & first aid experience", exact=True).select_option("professionally_qualified")
    alice.locator('#profileContributions input[value="teach"]').check()
    save_profile(alice)
    expect(alice.locator("#sessionName")).to_have_text("TEST_ProfileRiver")
    join(bob, url, "TEST Directory Visitor")
    bob.get_by_role("button", name="Member directory", exact=True).click()
    expect(bob.locator("#directoryPage")).to_have_text("0 shared profiles")
    alice.locator("#profileVisibility").check()
    save_profile(alice)
    refresh_directory(bob)
    card = bob.locator(".directory-card")
    expect(card).to_have_count(1)
    expect(card).to_contain_text("TEST River <b>plain text</b>")
    expect(card).to_contain_text("@test_profileriver")
    expect(card.locator("b, img, script")).to_have_count(0)
    expect(card.locator(".directory-skills")).to_have_count(0)
    alice.locator("#profileShareSkills").check()
    save_profile(alice)
    refresh_directory(bob)
    expect(card.locator(".directory-skills")).to_contain_text("Maps & navigation")
    expect(card.locator(".directory-skills")).to_contain_text("Medical & first aid")
    expect(card).to_contain_text("Self-reported interests")
    expect(card).to_contain_text("Ways to help: Teaching")
    card_text = card.inner_text()
    assert "professionally_qualified" not in card_text
    assert "Professional experience" not in card_text
    assert alice.locator("#contactCode").input_value() not in card_text
    for page in (alice, bob):
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.evaluate("Array.from(document.querySelectorAll('dialog[open]')).every(d => d.scrollWidth <= d.clientWidth)")
    screenshot = os.environ.get("FIELDFORGE_PROFILE_SCREENSHOT")
    if screenshot:
        path = Path(screenshot)
        path.parent.mkdir(parents=True, exist_ok=True)
        alice.locator("#profileDialog").evaluate("element => element.scrollTo(0, 0)")
        alice.screenshot(path=str(path), full_page=True)
        bob.screenshot(path=str(path.with_name(path.stem + "-mobile" + path.suffix)), full_page=True)
    alice.locator("#profileVisibility").uncheck()
    save_profile(alice)
    refresh_directory(bob)
    expect(bob.locator(".directory-card")).to_have_count(0)
    expect(bob.locator("#directoryPage")).to_have_text("0 shared profiles")
    bob.get_by_role("button", name="Close directory", exact=True).click()
    expect(bob.locator("#directoryCards")).to_be_empty()


def test_photo_upload_is_explicit_normalized_private_and_independently_shared(browsers, tmp_path):
    from playwright.sync_api import expect

    image = pytest.importorskip("PIL.Image")
    alice, bob, url = browsers
    alice.goto(url + "/commons")
    create_account(alice, "TEST_PhotoRiver")
    contact = alice.locator("#contactCode").input_value()
    open_profile(alice)
    alice.locator("#profileDisplayName").fill("TEST River photo draft")
    alice.locator("#profileBio").fill("TEST: This draft survives uploading a photo.")
    requests = []
    alice.on("request", lambda request: requests.append(request.url) if "/profile/" in request.url else None)
    source = base64.b64decode(test_commons_profiles.png_source())
    file = {"name": "TEST-private-metadata.png", "mimeType": "image/png", "buffer": source}
    alice.locator("#profilePhotoFile").set_input_files(file)
    assert not any("photo/upload" in request for request in requests)
    expect(alice.locator("#profilePhotoPreview img")).to_have_count(0)
    alice.get_by_role("button", name="Upload photo privately", exact=True).click()
    expect(alice.locator("#profileStatus")).to_contain_text("Photo uploaded privately")
    expect(alice.locator("#profilePhotoPreview img")).to_be_visible()
    expect(alice.locator("#profileDisplayName")).to_have_value("TEST River photo draft")
    expect(alice.locator("#profileBio")).to_have_value("TEST: This draft survives uploading a photo.")
    expect(alice.locator("#profileSharePhoto")).not_to_be_checked()
    assert alice.locator("#profilePhotoFile").input_value() == ""
    preview = alice.locator("#profilePhotoPreview img").get_attribute("src")
    assert preview.startswith("data:image/png;base64,")
    normalized = base64.b64decode(preview.split(",", 1)[1])
    assert b"TEST private GPS" not in normalized
    with image.open(io.BytesIO(normalized)) as photo:
        assert max(photo.size) <= 256
        assert not photo.info
    alice.locator("#profileVisibility").check()
    save_profile(alice)
    join(bob, url, "TEST Photo Observer")
    bob.get_by_role("button", name="Member directory", exact=True).click()
    expect(bob.locator(".directory-card")).to_have_count(1)
    expect(bob.locator(".directory-card img")).to_have_count(0)
    alice.locator("#profileSharePhoto").check()
    save_profile(alice)
    refresh_directory(bob)
    expect(bob.locator(".directory-card img")).to_be_visible()
    assert bob.locator(".directory-card img").get_attribute("src") == preview
    with alice.expect_download() as download:
        alice.get_by_role("button", name="Export my profile", exact=True).click()
    destination = tmp_path / "profile.json"
    download.value.save_as(destination)
    exported = json.loads(destination.read_text())
    assert exported["format"] == "fieldforge-commons-profile"
    assert exported["photo"]["mime_type"] == "image/png"
    assert base64.b64decode(exported["photo"]["encoded"]) == normalized
    alice.locator("#profilePhotoFile").set_input_files(file)
    alice.get_by_role("button", name="Upload photo privately", exact=True).click()
    expect(alice.locator("#profileStatus")).to_contain_text("Photo uploaded privately")
    expect(alice.locator("#profileSharePhoto")).not_to_be_checked()
    refresh_directory(bob)
    expect(bob.locator(".directory-card img")).to_have_count(0)
    alice.on("dialog", lambda dialog: dialog.accept())
    alice.get_by_role("button", name="Remove photo", exact=True).click()
    expect(alice.locator("#profileStatus")).to_contain_text("Photo removed")
    expect(alice.locator("#profilePhotoPreview img")).to_have_count(0)
    expect(alice.locator("#profileSharePhoto")).to_be_disabled()
    alice.get_by_role("button", name="Delete my profile", exact=True).click()
    expect(alice.locator("#profileStatus")).to_contain_text("Profile and photo deleted")
    expect(alice.locator("#profileVisibility")).not_to_be_checked()
    alice.get_by_role("button", name="Close profile", exact=True).click()
    expect(alice.locator("#sessionName")).to_have_text("TEST_PhotoRiver")
    expect(alice.locator("#contactCode")).to_have_value(contact)
    refresh_directory(bob)
    expect(bob.locator(".directory-card")).to_have_count(0)


def test_conflicting_edits_preserve_draft_and_busy_fields_until_explicit_reload(browsers, preview_server):
    from playwright.sync_api import expect

    alice, _, url = browsers
    alice.goto(url + "/commons")
    create_account(alice, "TEST_ProfileConflict")
    open_profile(alice)
    alice.locator("#profileBio").fill("TEST: Browser draft to retain")
    token = session_token(alice)
    test_commons_profiles.profile(preview_server.app.store, token, bio="TEST: Concurrent saved change")
    disabled_during_save = []

    def capture_busy(route):
        disabled_during_save.append(alice.locator("#profileBio").is_disabled())
        route.fulfill(response=route.fetch())

    alice.route("**/api/commons/profile/save", capture_busy, times=1)
    alice.get_by_role("button", name="Save profile", exact=True).click()
    expect(alice.locator("#profileConflict")).to_be_visible()
    expect(alice.locator("#profileBio")).to_have_value("TEST: Browser draft to retain")
    expect(alice.locator("#profileSave")).to_be_disabled()
    assert disabled_during_save == [True]
    alice.on("dialog", lambda dialog: dialog.accept())
    alice.get_by_role("button", name="Reload saved profile", exact=True).click()
    expect(alice.locator("#profileBio")).to_have_value("TEST: Concurrent saved change")
    expect(alice.locator("#profileConflict")).to_be_hidden()
    expect(alice.locator("#profileSave")).to_be_enabled()


def test_late_profile_photo_and_directory_replies_cannot_repopulate_closed_views(browsers, preview_server):
    from playwright.sync_api import expect

    alice, _, url = browsers
    alice.goto(url + "/commons")
    create_account(alice, "TEST_ProfileLifecycle")
    token = session_token(alice)
    store = preview_server.app.store
    test_commons_profiles.profile(store, token, bio="TEST: Saved private bio")
    test_commons_profiles.add_photo(store, token)

    def hidden_during_get(route):
        response = route.fetch()
        hide_tab(alice)
        route.fulfill(response=response)

    alice.route("**/api/commons/profile/get", hidden_during_get, times=1)
    alice.get_by_role("button", name="My profile", exact=True).click()
    expect(alice.locator("#profileDialog")).to_be_hidden()
    expect(alice.locator("#profileBio")).to_have_value("")
    expect(alice.locator("#profilePhotoPreview img")).to_have_count(0)

    def close_during_photo(route):
        response = route.fetch()
        alice.evaluate("document.getElementById('closeProfile').click()")
        route.fulfill(response=response)

    alice.route("**/api/commons/profile/photo/read", close_during_photo, times=1)
    alice.get_by_role("button", name="My profile", exact=True).click()
    expect(alice.locator("#profileDialog")).to_be_hidden()
    expect(alice.locator("#profileBio")).to_have_value("")
    expect(alice.locator("#profilePhotoPreview img")).to_have_count(0)
    open_profile(alice)
    expect(alice.locator("#profilePhotoPreview img")).to_be_visible()
    alice.locator("#profileBio").fill("TEST: Unsaved private draft")
    alice.evaluate("document.getElementById('pauseButton').click()")
    expect(alice.locator("#connectionLabel")).to_have_text("Chat paused")
    expect(alice.locator("#profileDialog")).to_be_hidden()
    expect(alice.locator("#profileBio")).to_have_value("")
    expect(alice.locator("#profilePhotoPreview img")).to_have_count(0)
    alice.get_by_role("button", name="Resume chat", exact=True).click()
    expect(alice.locator("#connectionLabel")).to_have_text("Local chat connected")
    alice.route("**/api/commons/profile/directory", hidden_during_get, times=1)
    alice.get_by_role("button", name="Member directory", exact=True).click()
    expect(alice.locator("#directoryDialog")).to_be_hidden()
    expect(alice.locator("#directoryCards")).to_be_empty()
    open_profile(alice)
    alice.evaluate("window.dispatchEvent(new Event('offline'))")
    expect(alice.locator("#connectionLabel")).to_have_text("Chat paused")
    expect(alice.locator("#profileDialog")).to_be_hidden()
    expect(alice.locator("#profileBio")).to_have_value("")
    assert alice.evaluate("localStorage.length + sessionStorage.length") == 0


def test_same_cookie_account_change_clears_private_profile_and_directory(browsers, preview_server):
    from playwright.sync_api import expect

    alice, _, url = browsers
    alice.goto(url + "/commons")
    create_account(alice, "TEST_ProfileFirst")
    open_profile(alice)
    alice.locator("#profileBio").fill("TEST: First account private profile")
    save_profile(alice)
    alice.locator("#profileBio").fill("TEST: First account unsaved private draft")
    preview_server.app.store.account_register("TEST_ProfileSecond", PASSWORD, "")
    other_tab = alice.context.new_page()
    try:
        other_tab.goto(url + "/commons")
        sign_in(other_tab, "TEST_ProfileSecond")
        expect(alice.locator("#joinPanel")).to_be_visible()
        expect(alice.locator("#profileDialog")).to_be_hidden()
        expect(alice.locator("#profileBio")).to_have_value("")
        expect(alice.locator("#directoryCards")).to_be_empty()
        alice.get_by_role("button", name="Resume existing session", exact=True).click()
        expect(alice.locator("#accountIdentity")).to_have_text("Local account · TEST_ProfileSecond")
        open_profile(alice)
        expect(alice.locator("#profileDisplayName")).to_have_value("TEST_ProfileSecond")
        expect(alice.locator("#profileBio")).to_have_value("")
        assert "First account" not in alice.locator("#profileDialog").inner_text()
    finally:
        other_tab.close()


def test_directory_search_category_pagination_and_block_on_mobile(browsers, preview_server):
    from playwright.sync_api import expect

    _, bob, url = browsers
    store = preview_server.app.store
    for number in range(13):
        token, _ = test_commons_profiles.account(store, f"TEST_Directory_{number:02}")
        category = "navigation" if number % 2 == 0 else "food"
        test_commons_profiles.profile(store, token, display_name=f"TEST Member {number:02}",
                                      bio="TEST: Helps with local planning.", visibility="commons",
                                      share_skills=True, assessment={"interests": [category],
                                      "experience": {category: "practiced"}, "contributions": ["remote"]})
    join(bob, url, "TEST Directory Searcher")
    bob.get_by_role("button", name="Member directory", exact=True).click()
    expect(bob.locator(".directory-card")).to_have_count(12)
    expect(bob.locator("#directoryPage")).to_have_text("1–12 of 13 profiles")
    bob.get_by_role("button", name="Next", exact=True).click()
    expect(bob.locator("#directoryPage")).to_have_text("13–13 of 13 profiles")
    expect(bob.locator(".directory-card")).to_have_count(1)
    bob.get_by_role("button", name="Previous", exact=True).click()
    expect(bob.locator(".directory-card")).to_have_count(12)
    bob.get_by_label("Search member profiles", exact=True).fill("TEST Member 12")
    bob.get_by_role("button", name="Search", exact=True).click()
    expect(bob.locator(".directory-card")).to_have_count(1)
    expect(bob.locator(".directory-card")).to_contain_text("@test_directory_12")
    bob.get_by_label("Search member profiles", exact=True).fill("")
    bob.get_by_label("Interest area", exact=True).select_option("navigation")
    bob.get_by_role("button", name="Search", exact=True).click()
    expect(bob.locator(".directory-card")).to_have_count(7)
    bob.on("dialog", lambda dialog: dialog.accept())
    bob.get_by_role("button", name="Block @test_directory_00", exact=True).click()
    expect(bob.locator("#directoryStatus")).to_contain_text("Participant blocked")
    expect(bob.locator(".directory-card")).to_have_count(6)
    assert "@test_directory_00" not in bob.locator("#directoryCards").inner_text()
    assert bob.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert bob.locator("#directoryDialog").evaluate("element => element.scrollWidth <= element.clientWidth")
    bob.get_by_role("button", name="Close directory", exact=True).click()
    expect(bob.locator("#directoryCards")).to_be_empty()
    expect(bob.locator("#directoryQuery")).to_have_value("")
