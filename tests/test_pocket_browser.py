"""Opt-in real browser suite; CI requires local-file tests in Chromium and WebKit.

FIELDFORGE_BROWSER_TESTS=1 makes missing browser/dependencies a FAILURE, not a skip.
Memory mode is for restricted development containers only, not file-opening proof.
"""

import os
from dataclasses import replace

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.pocket import capture_pocket, render_pocket, save_pocket


@pytest.fixture(scope="module")
def browser():
    if os.environ.get("FIELDFORGE_BROWSER_TESTS") != "1":
        pytest.skip("Opt-in browser job required; no browser download during regular tests")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as driver:
        kind = os.environ.get("FIELDFORGE_BROWSER", "chromium")
        assert kind in {"chromium", "webkit", "firefox"}
        options = {"headless": True}
        if os.environ.get("FIELDFORGE_BROWSER_EXECUTABLE"):
            options["executable_path"] = os.environ["FIELDFORGE_BROWSER_EXECUTABLE"]
        engine = getattr(driver, kind).launch(**options)
        yield engine
        engine.close()


@pytest.fixture
def snapshot(tmp_path):
    library = KnowledgeLibrary(tmp_path / "library.db")
    library.upsert(KnowledgeArticle("water", "Café water records", "Original water worksheet.\r\n\r\nEnd conditions.\n", "water"))
    library.upsert(KnowledgeArticle("tools", "Equipment ledger", "Copper tool location and measurement.\n", "tools"))
    library.upsert(KnowledgeArticle("third", "Classroom record", "Share the measurement lesson.\n", "education"))
    library.annotate("water", bookmarked=True, note="PRIVATE_NOTE_729")
    collection = capture_pocket(library.database_path, slugs=("water", "tools", "third"))
    return tmp_path, collection


@pytest.fixture
def reader(browser, snapshot):
    path, collection = snapshot
    contexts = []
    failures, network = [], []
    def open_page(*, javascript=True, width=1280, content=None, fragment=""):
        context = browser.new_context(offline=True, java_script_enabled=javascript,
                                      viewport={"width": width, "height": 900}, has_touch=width < 500)
        contexts.append(context)
        page = context.new_page()
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.on("request", lambda request: network.append(request.url)
                if request.url.startswith(("http:", "https:", "ws:", "wss:")) else None)
        mode = os.environ.get("FIELDFORGE_BROWSER_MODE", "file")
        assert mode in {"file", "memory"}
        if mode == "file":
            target = path / f"reader-{len(contexts)}.html"
            if content is None:
                save_pocket(collection, target, acknowledged=True)
            else:
                target.write_bytes(content)
            page.goto(target.as_uri() + fragment, wait_until="load")
        else:
            # This does not navigate to file:// or bypass any container policy.
            page.set_content((content or render_pocket(collection)).decode(), wait_until="load")
            if fragment:
                page.evaluate("value => { location.hash = value; }", fragment)
        if javascript and content is None:
            page.wait_for_selector("html.enhanced")
        return page
    yield open_page
    for context in contexts:
        assert all(not row["localStorage"] for row in context.storage_state()["origins"])
        context.close()
    assert not network, network
    assert not failures, failures


def test_offline_full_text_sources_and_zero_initial_automatic_print(reader, snapshot):
    _, collection = snapshot
    page = reader()
    assert page.locator(".entry:visible").count() == 1
    assert page.locator("#ref-1 .article-body").text_content() == collection.entries[0].article.body
    assert "PRIVATE_NOTE_729" not in page.content()
    assert page.locator("#ref-1").inner_text().find("Not supplied") >= 0
    assert page.locator(".provenance").first.get_attribute("open") is not None
    assert page.locator("#results").inner_text().startswith("3 of 3")


def test_search_accent_case_substrings_and_category_reset(reader):
    page = reader()
    page.locator("#query").fill("CAFE water")
    page.wait_for_function("() => document.querySelector('#results').textContent.startsWith('1 of 3')")
    assert page.locator(".choice:visible").count() == 1
    assert page.locator("#ref-1").is_visible()
    page.locator("#query").fill("measure")
    page.wait_for_function("() => document.querySelector('#results').textContent.startsWith('2 of 3')")
    page.locator("#category").select_option("tools")
    assert page.locator(".choice:visible strong").inner_text() == "Equipment ledger"
    assert page.locator("#ref-2").is_visible()
    page.locator("#reset").click()
    assert page.locator("#query").input_value() == ""
    assert page.locator(".choice:visible").count() == 3


def test_no_results_never_shows_old_article_as_answer(reader):
    page = reader()
    page.locator("#query").fill("not-a-match.*<script>")
    page.wait_for_selector("#empty:visible")
    assert page.locator(".entry:visible").count() == 0
    assert page.locator(".choice:visible").count() == 0
    assert "does not prove" in page.locator("#empty").inner_text()
    page.locator("#reset").click()
    assert page.locator(".entry:visible").count() == 1


def test_links_keyboard_focus_hash_navigation_and_back_to_contents(reader):
    page = reader()
    page.locator('a[href="#ref-2"]').focus()
    page.keyboard.press("Enter")
    assert page.locator("#ref-2").is_visible()
    page.wait_for_function("() => document.activeElement === document.querySelector('#ref-2 h2')")
    assert page.url.endswith("#ref-2")
    page.locator("#ref-2 .back").click()
    page.wait_for_function("() => document.activeElement.id === 'contents'")
    page.evaluate("location.hash = '#ref-3'")
    page.wait_for_selector("#ref-3:visible")
    assert page.locator('a[href="#ref-3"]').get_attribute("aria-current") == "true"


def test_only_known_hashes_select_articles(reader):
    page = reader(fragment="#ref-3")
    page.wait_for_selector("#ref-3:visible")
    page.evaluate("location.hash = '#%3Cscript%3E'")
    assert page.locator("#ref-3").is_visible()


@pytest.mark.parametrize("width", [320, 390, 768, 1280])
def test_responsive_layout_large_type_and_dark_view(reader, width):
    page = reader(width=width)
    page.locator("#size").select_option("largest")
    page.locator("#theme").click()
    assert page.locator("html").get_attribute("data-theme") == "dark"
    assert page.locator("#theme").get_attribute("aria-pressed") == "true"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for control in ("#query", "#category", "#size", "#theme", "#reset"):
        box = page.locator(control).bounding_box()
        assert box["height"] >= 44
        assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1


def test_print_is_explicit_and_only_open_article_prints(reader):
    page = reader()
    page.evaluate("() => { window.printCalls = 0; window.print = () => { window.printCalls++; }; }")
    page.locator('a[href="#ref-2"]').click()
    page.locator("#ref-2 details").evaluate("node => { node.open = false; }")
    assert page.evaluate("window.printCalls") == 0
    page.locator("#ref-2 .print").click()
    assert page.evaluate("window.printCalls") == 1
    page.emulate_media(media="print")
    assert not page.locator("#contents").is_visible()
    assert not page.locator("#tools").is_visible()
    assert page.locator(".entry:visible").count() == 1
    assert page.locator("#ref-2 details").get_attribute("open") is not None


def test_no_javascript_remains_a_complete_readable_document(reader):
    page = reader(javascript=False)
    assert not page.locator("#tools").is_visible()
    assert page.locator(".entry:visible").count() == 3
    assert "End conditions." in page.locator("#ref-1").inner_text()
    page.locator('a[href="#ref-3"]').click()
    assert page.url.endswith("#ref-3")


def test_blocked_script_falls_back_without_hiding_article_text(reader, snapshot):
    _, collection = snapshot
    # Changing script bytes invalidates the fixed CSP hash, so none of it runs.
    content = render_pocket(collection).replace(b'<script>', b'<script>/*changed*/')
    page = reader(content=content)
    assert page.locator("html.enhanced").count() == 0
    assert not page.locator("#tools").is_visible()
    assert page.locator(".entry:visible").count() == 3


def test_adversarial_content_metadata_and_search_never_execute(reader, snapshot):
    _, collection = snapshot
    from fieldforge.knowledge.binder import BinderEntry
    attack = '</script><script>window.PWNED=1</script><img src="https://example.invalid/leak">'
    article = replace(collection.entries[0].article, slug='id"<x>', title=attack, body=attack + "\nliteral.*word",
                      source_publisher=attack, license=attack)
    content = render_pocket(replace(collection, entries=(BinderEntry(article),)))
    page = reader(content=content)
    page.wait_for_selector("html.enhanced")
    assert page.evaluate("window.PWNED") is None
    assert page.locator("img, iframe, svg, object").count() == 0
    assert page.locator(".article-body").text_content() == article.body
    page.locator("#query").fill("literal.*word")
    page.wait_for_function("() => document.querySelector('#results').textContent.startsWith('1 of 1')")
    assert page.locator(".entry:visible").count() == 1


def test_session_preferences_and_search_are_not_persisted(reader):
    page = reader()
    page.locator("#query").fill("copper")
    page.locator("#size").select_option("largest")
    page.locator("#theme").click()
    fresh = reader()
    assert fresh.locator("#query").input_value() == ""
    assert fresh.locator("#size").input_value() == "normal"
    assert fresh.locator("html").get_attribute("data-theme") == "light"
