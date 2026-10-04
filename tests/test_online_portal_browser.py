"""Browser portal served over real localhost HTTP; no public data requests."""

import hashlib
import json

import pytest
from test_online_portal import map_entry as map_entry
from test_online_portal import portal as portal
from test_pocket_browser import browser as browser

from fieldforge_gps.gpx_review import parse_gpx
from fieldforge_gps.places import read_catalog


@pytest.fixture
def page(browser, portal):
    context = browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 1000})
    tab = context.new_page()
    errors, calls = [], []
    tab.on("pageerror", lambda error: errors.append(str(error)))
    tab.on("request", lambda request: calls.append(request.url))
    tab.goto(portal[0], wait_until="networkidle")
    assert not any("/api/" in url for url in calls)
    yield tab, context, calls
    assert all(not origin["localStorage"] for origin in context.storage_state()["origins"])
    context.close()
    assert not errors
    assert all(url.startswith(portal[0] + "/") or url.startswith("blob:") for url in calls)


def connect(page):
    tab = page[0]
    tab.locator("#consent").check()
    tab.locator("#connect").click()
    tab.wait_for_function("() => !document.querySelector('#query').disabled")


def select_address(page):
    tab = page[0]
    tab.locator("#query").fill("Fictional Beacon")
    tab.locator("#search").click()
    tab.locator(".result").first.wait_for()
    assert tab.locator("#selected").is_hidden()
    tab.locator(".result").first.click()
    assert tab.locator("#coordinates").input_value() == "10.125, 20.25"
    assert "<test>" in tab.locator("#address-label").inner_text()
    assert tab.locator("#address-label test").count() == 0


def save_download(tab, selector, target):
    with tab.expect_download() as pending:
        tab.locator(selector).click()
    pending.value.save_as(target)


def test_offline_search_gate_selected_coordinates_save_and_no_autoreconnect(page, portal, tmp_path):
    tab, context, calls = page
    assert tab.locator("#query").is_disabled()
    tab.locator("#connect").click()
    assert not any("/api/" in url for url in calls)
    connect(page)
    tab.locator("#query").fill("Fictional")
    assert not portal[2]  # Typing is not autocomplete or an automatic search.
    select_address(page)
    context.set_offline(True)
    tab.wait_for_function("() => document.querySelector('#query').disabled")
    assert tab.locator("a.download").get_attribute("href") is None
    target = tmp_path / "place.csv"
    save_download(tab, "#save-address", target)
    assert read_catalog(target, consent=True, wgs84_confirmed=True).places[0].longitude == 20.25
    old_calls = len(calls)
    context.set_offline(False)
    tab.wait_for_function("() => !document.querySelector('#connect').disabled")
    assert tab.locator("#query").is_disabled() and len(calls) == old_calls


def test_route_map_and_source_downloads_survive_offline(page, portal, tmp_path, map_entry):
    tab = page[0]
    connect(page)
    select_address(page)
    tab.locator("#use-start").click()
    tab.locator("#end-lat").fill("10.4")
    tab.locator("#end-lon").fill("20.5")
    tab.locator("#plan").click()
    tab.locator("#route-result").wait_for(state="visible")
    assert "20.25,10.125;20.5,10.4" in portal[2][-1][0]
    target = tmp_path / "map.mbtiles"
    save_download(tab, "a.download", target)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == map_entry["sha256"]
    tab.locator("#disconnect").click()
    note = tmp_path / "source.json"
    save_download(tab, ".map-card button", note)
    assert json.loads(note.read_text())["sha256"] == map_entry["sha256"]
    route = tmp_path / "route.gpx"
    save_download(tab, "#save-route", route)
    assert parse_gpx(route.read_bytes()).point_count == 3
    assert b"PLANNED" in route.read_bytes() and b"<time>" not in route.read_bytes()


def test_tiny_coordinates_export_as_decimal_and_mobile_does_not_overflow(page, tmp_path):
    tab = page[0]
    connect(page)
    # Server-valid small coordinates must remain readable by the offline readers.
    tab.route("**/api/v1/search", lambda route: route.fulfill(json={"results": [{
        "label": "Fictional tiny coordinate", "latitude": 1e-7, "longitude": -2e-7,
        "source": "Fixture", "attribution": "Original fixture"}]}))
    tab.route("**/api/v1/route", lambda route: route.fulfill(json={"profile": "driving",
        "coordinates": [[-2e-7, 1e-7], [0, 0]], "distance_m": 1, "duration_s": 1,
        "source": "Fixture", "attribution": "Original fixture", "created_at": "2026-10-04"}))
    tab.set_viewport_size({"width": 390, "height": 844})
    tab.locator("#query").fill("Fictional")
    tab.locator("#search").click()
    tab.locator(".result").click()
    tab.locator("#use-start").click()
    tab.locator("#use-end").click()
    assert tab.locator("#start-lat").input_value() == "0.0000001"
    tab.locator("#plan").click()
    tab.locator("#route-result").wait_for(state="visible")
    assert tab.evaluate("document.documentElement.scrollWidth <= innerWidth")
    target = tmp_path / "tiny.gpx"
    save_download(tab, "#save-route", target)
    assert parse_gpx(target.read_bytes()).point_count == 2
    assert b'lat="0.0000001"' in target.read_bytes()


def test_unconfigured_providers_keep_search_and_route_unavailable(page, portal):
    portal[1].geocoder = portal[1].router = None
    tab = page[0]
    tab.locator("#consent").check()
    tab.locator("#connect").click()
    tab.wait_for_function("() => !document.querySelector('#refresh').disabled")
    assert tab.locator("#query").is_disabled() and tab.locator("#plan").is_disabled()
    assert "not configured" in tab.locator("#status").inner_text()
