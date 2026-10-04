"""Browser portal -> downloaded route -> offline desktop storage compatibility.

The existing Chromium/WebKit CI job opts in. No live third-party service or real
personal address is involved: both portal and providers are local test servers.
"""

import json
import os
from xml.etree import ElementTree as ET

import pytest
import test_online_integration

from fieldforge.online.storage import PortalLibrary
from fieldforge_gps.gpx_review import parse_gpx
from fieldforge_gps.places import read_catalog

operated_portal = test_online_integration.operated_portal

pytestmark = pytest.mark.skipif(
    os.environ.get("FIELDFORGE_PORTAL_BROWSER_TESTS") != "1",
    reason="The dedicated Chromium/WebKit CI job requires the portal browser workflow",
)


def _accept_connection(dialog):
    assert dialog.type == "confirm" and "Connect to the internet?" in dialog.message
    dialog.accept()


def _connect(page):
    from playwright.sync_api import expect

    page.locator("#consent").check()
    page.locator("#connect").click()
    expect(page.locator("#connectionBadge")).to_have_text("Portal connected")


def _assert_no_horizontal_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), page.evaluate("""() => {
        const viewport = window.innerWidth;
        const overflowing = Array.from(document.querySelectorAll("body *")).map(node => {
            const rect = node.getBoundingClientRect(), style = getComputedStyle(node);
            return {
                tag: node.tagName, id: node.id, className: node.getAttribute("class"),
                left: rect.left, right: rect.right, width: rect.width,
                scrollWidth: node.scrollWidth, clientWidth: node.clientWidth,
                minWidth: style.minWidth, display: style.display,
                gridColumns: style.gridTemplateColumns, overflowWrap: style.overflowWrap,
                whiteSpace: style.whiteSpace,
            };
        }).filter(node => node.width > 0 && (node.right > viewport
            || node.scrollWidth > node.clientWidth))
            .sort((a, b) => b.right - a.right).slice(0, 20);
        return {viewport, scrollWidth: document.documentElement.scrollWidth, overflowing};
    }""")


def test_homepage_connection_warning_can_cancel_without_any_api_request(portal_page, operated_portal):
    from playwright.sync_api import expect

    page, _context, calls = portal_page
    page.goto(operated_portal[0], wait_until="networkidle")
    expect(page.locator("#libraryTitle")).to_have_text("Knowledge & program packs")
    expect(page.locator("#tiersTitle")).to_have_text("Packages for the amount you need")
    expect(page.locator(".pack")).to_have_count(15)
    assert not any("/api/" in url for url in calls)
    page.remove_listener("dialog", _accept_connection)
    warnings = []
    def reject(dialog):
        warnings.append(dialog.message)
        dialog.dismiss()
    page.on("dialog", reject)
    page.locator("#consent").check()
    page.locator("#connect").click()
    expect(page.locator("#connectionStatus")).to_contain_text("Stayed offline")
    expect(page.locator("#addressQuery")).to_be_disabled()
    assert len(warnings) == 1 and "Connect to the internet?" in warnings[0]
    assert not any("/api/" in url for url in calls)
    page.remove_listener("dialog", reject)
    page.on("dialog", _accept_connection)
    _connect(page)
    for width in (390, 1280):
        page.set_viewport_size({"width": width, "height": 844})
        _assert_no_horizontal_overflow(page)


def test_map_filters_paging_and_correct_download_survive_disconnect(portal_page, operated_portal, tmp_path):
    from PIL import Image
    from playwright.sync_api import expect

    from fieldforge.online.catalog import publish_map

    url, _provider, source, _asset = operated_portal
    image = tmp_path / "island.png"
    Image.new("RGB", (8, 8), "green").save(image)
    for number in range(25):
        publish_map(source.parent / "published-maps", image, map_id=f"island-{number:03}",
                    title=f"Island {number:03}", source_name="Éclair Survey",
                    attribution="Original test fixture", license="Test fixture only",
                    coverage="South islands", version="1")
    page, context, calls = portal_page
    page.goto(url, wait_until="networkidle")
    _connect(page)
    before = len(calls)
    page.locator("#mapFilter").fill("south eclair")
    page.locator("#mapKind").select_option("image")
    page.locator("#mapOrder").select_option("smallest")
    expect(page.locator("#mapsStatus")).to_contain_text("25 of 26")
    expect(page.locator("#mapCatalog .map-card")).to_have_count(24)
    page.get_by_role("checkbox", name="Add Island 000 to download list", exact=True).check()
    page.locator("#mapNext").click()
    expect(page.locator("#mapCatalog .map-card h3")).to_have_text("Island 024")
    page.get_by_role("checkbox", name="Add Island 024 to download list", exact=True).check()
    expect(page.locator("#downloadListTotal")).to_contain_text("2 maps")
    assert len(calls) == before  # All discovery is local to the loaded catalog.
    with page.expect_download() as captured:
        page.get_by_role("link", name="Download Island 024", exact=True).click()
    target = tmp_path / "downloaded-map.png"
    captured.value.save_as(target)
    assert captured.value.suggested_filename == "island-024.png"
    assert target.read_bytes() == image.read_bytes()
    context.set_offline(True)
    expect(page.locator("#connectionBadge")).to_have_text("Offline")
    before = len(calls)
    page.locator("#mapFilter").fill("no such region")
    expect(page.locator("#mapsStatus")).to_contain_text("No matches")
    expect(page.locator("#mapCatalog .map-card")).to_have_count(0)
    page.locator("#resetMapFilters").click()
    page.locator("#mapOrder").select_option("largest")
    expect(page.locator("#mapCatalog .map-card h3").first).to_have_text("Synthetic test overview")
    expect(page.locator("#mapCatalog .download-link").first).to_have_attribute("aria-disabled", "true")
    assert len(calls) == before
    expect(page.locator("#downloadListTotal")).to_contain_text("2 maps")
    with page.expect_download() as exported:
        page.locator("#saveDownloadList").click()
    selection = tmp_path / "browser-list.json"
    exported.value.save_as(selection)
    from fieldforge.online.client import PortalClient
    from fieldforge.online.download_list import download_maps, load_download_list

    document = load_download_list(selection)
    assert document["portal"] == url
    assert document["total_bytes"] == 2 * image.stat().st_size
    assert [item["id"] for item in document["maps"]] == ["island-000", "island-024"]
    assert all(item["source"] == "Éclair Survey" for item in document["maps"])
    # A separate desktop connection is explicit; importing the list did not connect.
    client = PortalClient(document["portal"])
    assert not client.connected
    client.connect()
    try:
        downloaded = download_maps(client, document, tmp_path / "from-browser-list")
        assert len(downloaded) == 2 and all(path.read_bytes() == image.read_bytes() for path in downloaded)
    finally:
        client.disconnect()
    page.locator("#clearDownloadList").click()
    expect(page.locator("#downloadListTotal")).to_contain_text("0 maps")
    expect(page.locator("#saveDownloadList")).to_be_disabled()


def test_changed_catalog_keeps_selected_snapshot_and_disables_its_download(portal_page, operated_portal):
    from playwright.sync_api import expect

    page, _context, _calls = portal_page
    url, _provider, _source, asset = operated_portal
    page.goto(url, wait_until="networkidle")
    _connect(page)
    page.get_by_role("checkbox", name="Add Synthetic test overview to download list", exact=True).check()
    page.locator("#downloadListDetails").evaluate("node => node.open = true")
    changed = dict(asset, title="Changed catalog title")
    page.route("**/api/v1/maps", lambda route: route.fulfill(json={"maps": [changed]}))
    page.locator("#disconnect").click()
    _connect(page)
    expect(page.locator("#downloadListItems")).to_contain_text("Synthetic test overview")
    expect(page.locator("#downloadListItems")).to_contain_text("Unavailable or changed")
    expect(page.locator("#downloadListItems .download-link")).to_have_attribute("aria-disabled", "true")
    assert page.locator("#downloadListItems .download-link").get_attribute("href") is None
    page.set_viewport_size({"width": 390, "height": 844})
    _assert_no_horizontal_overflow(page)


def test_browser_downloads_import_offline_and_mobile_layout(operated_portal, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    url, provider, source, asset = operated_portal
    # Provider data must remain literal text in the page and in downloaded XML.
    label = 'Fixture Depot <img src=x onerror="window.bad=true">'
    provider.geocoding[0]["display_name"] = label
    failures, calls = [], []
    with sync_playwright() as playwright:
        browser_type = getattr(playwright, os.environ.get("FIELDFORGE_BROWSER", "chromium"))
        browser = browser_type.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
        page = context.new_page()
        page.on("dialog", _accept_connection)
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.on("request", lambda request: calls.append(request.url))
        try:
            page.goto(url, wait_until="networkidle")
            assert not any("/api/" in call for call in calls)
            expect(page.locator("#addressQuery")).to_be_disabled()
            expect(page.locator("#routeButton")).to_be_disabled()
            expect(page.locator("#connectionBadge")).to_have_text("Offline")
            page.locator("#connect").click()
            expect(page.locator("#connectionStatus")).to_contain_text("Choose to send")
            assert not any("/api/" in call for call in calls)
            page.locator("#consent").check()
            assert not any("/api/" in call for call in calls)
            page.locator("#connect").click()
            expect(page.locator("#addressQuery")).to_be_enabled()
            expect(page.locator("#mapCatalog .map-card")).to_have_count(1)
            expect(page.locator("#providers")).to_contain_text("Fixture geocoder")
            assert provider.requests == []
            page.locator("#addressQuery").fill("Fixture Depot")
            assert provider.requests == []  # No autocomplete/request on keystrokes.
            page.locator("#searchButton").click()
            expect(page.locator("#searchResults .result")).to_have_count(2)
            expect(page.locator("#searchResults .result h3").first).to_have_text(label)
            assert page.locator("#searchResults img").count() == 0
            expect(page.locator("#selectedAddress")).to_be_hidden()
            results = page.locator("#searchResults .result")
            results.nth(0).get_by_role("button", name="Select place", exact=True).click()
            expect(page.locator("#selectedAddressTitle")).to_have_text(label)
            assert page.locator("#selectedAddress img").count() == 0
            results.nth(0).get_by_role("button", name="Use as start", exact=True).click()
            results.nth(1).get_by_role("button", name="Use as destination", exact=True).click()
            expect(page.locator("#startLatitude")).to_have_value("40")
            expect(page.locator("#startLongitude")).to_have_value("-75")
            expect(page.locator("#endLatitude")).to_have_value("40.02")
            expect(page.locator("#endLongitude")).to_have_value("-75.01")

            with page.expect_download() as transfer:
                page.get_by_role("link", name="Download " + asset["title"], exact=True).click()
            downloaded_map = tmp_path / transfer.value.suggested_filename
            transfer.value.save_as(downloaded_map)
            assert downloaded_map.read_bytes() == source.read_bytes()

            page.locator("#routeButton").click()
            expect(page.locator("#routeOptions .route-card")).to_have_count(2)
            page.locator("#routeOptions .route-card").nth(1).get_by_role("button", name="Review").click()
            expect(page.locator("#routePreview")).to_be_visible()
            expect(page.locator("#routeDetails")).to_contain_text("Turn right onto Test Lane.")
            encoded_positions = provider.requests[-1]["path"].split("/route/v1/driving/", 1)[1].split("?", 1)[0]
            assert [tuple(map(float, point.split(","))) for point in encoded_positions.split(";")] == [
                (-75.0, 40.0), (-75.01, 40.02),
            ]
            provider_requests = len(provider.requests)
            context.set_offline(True)
            expect(page.locator("#addressQuery")).to_be_disabled()
            expect(page.locator("#routeButton")).to_be_disabled()
            expect(page.locator("#startLongitude")).to_have_value("-75")
            assert page.locator(".download-link").get_attribute("href") is None
            assert page.locator("#downloadPlace").is_enabled()
            with page.expect_download() as transfer:
                page.locator("#downloadPlace").click()
            downloaded_place = tmp_path / transfer.value.suggested_filename
            transfer.value.save_as(downloaded_place)
            selected = read_catalog(downloaded_place, consent=True, wgs84_confirmed=True).places[0]
            assert selected.name == provider.geocoding[1]["display_name"]
            assert (selected.latitude, selected.longitude) == (40.02, -75.01)
            assert "Fixture geocoder" in selected.source
            page.locator("#mapCatalog summary").click()
            with page.expect_download() as transfer:
                page.get_by_role("button", name="Save map details", exact=True).click()
            source_note = tmp_path / transfer.value.suggested_filename
            transfer.value.save_as(source_note)
            assert json.loads(source_note.read_bytes())["sha256"] == asset["sha256"]
            with page.expect_download() as transfer:
                page.locator("#downloadRoute").click()
            downloaded_route = tmp_path / transfer.value.suggested_filename
            transfer.value.save_as(downloaded_route)
            assert downloaded_route.name.endswith(".route.json")
            envelope = json.loads(downloaded_route.read_text())
            library = PortalLibrary(tmp_path / "offline-library")
            installed_route = library.import_route(downloaded_route)
            route = library.load_route(installed_route)
            assert route == envelope["route"]
            assert route["geometry"][1] == [-75.008, 40.012]
            assert route["steps"][1]["instruction"] == "Turn right onto Test Lane."

            with page.expect_download() as transfer:
                page.locator("#downloadGpx").click()
            downloaded_gpx = tmp_path / transfer.value.suggested_filename
            transfer.value.save_as(downloaded_gpx)
            document = ET.fromstring(downloaded_gpx.read_bytes())
            ns = {"g": "http://www.topografix.com/GPX/1/1"}
            assert document.find("g:trk/g:type", ns).text == "planned-route"
            assert document.findall(".//g:trkpt/g:time", ns) == []
            assert len(document.findall(".//g:trkpt", ns)) == len(route["geometry"])
            assert parse_gpx(downloaded_gpx.read_bytes()).point_count == len(route["geometry"])
            assert len(provider.requests) == provider_requests

            # A network-online event enables Connect but never starts API work.
            old_calls = len(calls)
            context.set_offline(False)
            expect(page.locator("#connect")).to_be_enabled()
            expect(page.locator("#addressQuery")).to_be_disabled()
            assert len(calls) == old_calls
            _connect(page)
            expect(page.locator("#addressQuery")).to_be_enabled()
            page.locator("#disconnect").click()
            expect(page.locator("#connectionBadge")).to_have_text("Offline")
            expect(page.locator("#addressQuery")).to_be_disabled()
            assert page.locator(".download-link").get_attribute("href") is None
            assert len(provider.requests) == provider_requests

            page.set_viewport_size({"width": 390, "height": 844})
            _assert_no_horizontal_overflow(page)
            expect(page.locator("#downloadRoute")).to_be_enabled()
            page.screenshot(path=str(tmp_path / "portal-mobile-offline.png"), full_page=True)
            assert all(not origin["localStorage"] for origin in context.storage_state()["origins"])
            assert all(call.startswith(url + "/") or call.startswith("blob:") for call in calls)
            assert failures == []
        finally:
            context.close()
            browser.close()


@pytest.fixture
def offline_route_download_page(operated_portal):
    from playwright.sync_api import expect, sync_playwright

    url, provider, _source, _asset = operated_portal
    failures = []
    with sync_playwright() as playwright:
        browser_type = getattr(playwright, os.environ.get("FIELDFORGE_BROWSER", "chromium"))
        browser = browser_type.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
        page = context.new_page()
        page.on("dialog", _accept_connection)
        page.on("pageerror", lambda error: failures.append(str(error)))
        try:
            page.goto(url, wait_until="networkidle")
            _connect(page)
            expect(page.locator("#connectionBadge")).to_have_text("Portal connected")
            context.set_offline(True)
            expect(page.locator("#connectionBadge")).to_have_text("Offline")
            yield page, provider
        finally:
            context.close()
            browser.close()
    assert failures == []


def _large_browser_export_route():
    from fieldforge.online.models import validate_route

    geometry = [
        [-75.123456789 + index * 1e-8, 40.123456789 + index * 1e-8]
        for index in range(50_000)
    ]
    return validate_route({
        "id": "large-fictional-browser-route",
        "title": "Large fictional browser export",
        "mode": "driving",
        "distance_m": 10_000,
        "duration_s": 10_000,
        "geometry": geometry,
        "steps": [{
            "instruction": "Turn right onto " + "X" * 400 + ".",
            "distance_m": 1,
            "duration_s": 1,
            "latitude": 40,
            "longitude": -75,
        } for _ in range(10_000)],
        "start": {"latitude": geometry[0][1], "longitude": geometry[0][0]},
        "end": {"latitude": geometry[-1][1], "longitude": geometry[-1][0]},
        "source": "Original FieldForge browser regression fixture",
        "attribution": "Synthetic route data for software verification; no real roads.",
        "license": "CC0-1.0",
        "created_at": "2026-10-04T00:00:00Z",
    })


def test_large_browser_route_download_stays_importable(offline_route_download_page, tmp_path):
    from fieldforge.online.models import MAX_JSON_BYTES

    page, provider = offline_route_download_page
    route = _large_browser_export_route()
    envelope = {
        "schema_version": 1, "kind": "planned-route",
        "saved_at": "2026-10-04T00:00:00.000Z", "route": route,
    }
    # This valid route reproduces the regression: indentation alone used to make
    # its browser download larger than the desktop's complete-document limit.
    compact = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    pretty = json.dumps(envelope, ensure_ascii=False, indent=2).encode("utf-8")
    assert len(compact) <= MAX_JSON_BYTES < len(pretty)
    page.evaluate("""route => {
        state.routes = [route];
        state.selected = route;
        document.getElementById("routePreview").hidden = false;
    }""", route)
    with page.expect_download() as transfer:
        page.locator("#downloadRoute").click()
    downloaded = tmp_path / transfer.value.suggested_filename
    transfer.value.save_as(downloaded)
    document_bytes = downloaded.read_bytes()
    assert downloaded.name.endswith(".route.json")
    assert len(document_bytes) <= MAX_JSON_BYTES
    assert json.loads(document_bytes)["route"] == route
    library = PortalLibrary(tmp_path / "large-route-offline-library")
    imported = library.import_route(downloaded)
    assert library.load_route(imported) == route
    assert PortalLibrary(library.root).load_route(imported) == route
    assert downloaded.read_bytes() == document_bytes
    assert provider.requests == []


def test_oversized_utf8_route_envelope_shows_error_without_download(offline_route_download_page):
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import expect

    from fieldforge.online.models import MAX_JSON_BYTES

    page, provider = offline_route_download_page
    sizes = page.evaluate("""({route, limit}) => {
        const envelope = {
            schema_version: 1, kind: "planned-route",
            saved_at: new Date().toISOString(), route,
        };
        const byteSize = value => new Blob([JSON.stringify(value)]).size;
        let remaining = limit + 1 - byteSize(envelope);
        if (remaining <= 0) throw new Error("The base fixture must fit the document limit.");
        for (const step of route.steps) {
            const room = 1000 - step.instruction.length;
            const unicode = Math.min(room, Math.floor(remaining / 2));
            step.instruction += "é".repeat(unicode);
            remaining -= unicode * 2;
            if (remaining === 1 && unicode < room) {
                step.instruction += "X";
                remaining--;
            }
            if (remaining === 0) break;
        }
        if (remaining !== 0) throw new Error("Insufficient valid instruction space for the fixture.");
        state.routes = [route];
        state.selected = route;
        window.__routeBeforeFailedExport = JSON.stringify(route);
        document.getElementById("routePreview").hidden = false;
        return {
            routeBytes: byteSize(route),
            envelopeBytes: byteSize(envelope),
            envelopeCharacters: JSON.stringify(envelope).length,
            longestInstruction: Math.max(...route.steps.map(step => step.instruction.length)),
        };
    }""", {"route": _large_browser_export_route(), "limit": MAX_JSON_BYTES})
    # Neither measuring just the route nor counting JavaScript characters catches
    # this exact full-envelope overflow; the multibyte text must be counted.
    assert sizes["routeBytes"] <= MAX_JSON_BYTES
    assert sizes["envelopeCharacters"] < MAX_JSON_BYTES
    assert sizes["envelopeBytes"] == MAX_JSON_BYTES + 1
    assert sizes["longestInstruction"] <= 1000
    downloads = []
    page.on("download", lambda download: downloads.append(download))
    with pytest.raises(PlaywrightTimeoutError):
        with page.expect_download(timeout=1000):
            page.locator("#downloadRoute").click()
    expect(page.locator("#routeStatus.error")).to_be_visible()
    expect(page.locator("#routeStatus")).to_contain_text("8 MiB")
    expect(page.locator("#downloadRoute")).to_be_enabled()
    assert downloads == []
    assert page.evaluate("""() => state.selected === state.routes[0]
        && JSON.stringify(state.selected) === window.__routeBeforeFailedExport""")
    assert provider.requests == []


@pytest.fixture
def portal_page(operated_portal):
    from playwright.sync_api import sync_playwright

    url = operated_portal[0]
    errors, calls = [], []
    with sync_playwright() as playwright:
        browser_type = getattr(playwright, os.environ.get("FIELDFORGE_BROWSER", "chromium"))
        browser = browser_type.launch()
        context = browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.on("dialog", _accept_connection)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: calls.append(request.url))
        try:
            yield page, context, calls
            assert all(not origin["localStorage"] for origin in context.storage_state()["origins"])
        finally:
            context.close()
            browser.close()
    assert errors == []
    assert all(call.startswith(url + "/") or call.startswith("blob:") for call in calls)


def test_disconnect_rejects_late_search_and_network_failure_requires_connect(portal_page, operated_portal):
    from playwright.sync_api import expect

    page, _context, calls = portal_page
    # The first search deliberately ignores AbortSignal. Its late completion
    # must not replace results from a new explicit connection or change controls.
    page.add_init_script("""(() => {
        const original = window.fetch.bind(window);
        let holdFirstSearch = true;
        window.fetch = (path, options) => {
            if (path === "/api/v1/search" && holdFirstSearch) {
                holdFirstSearch = false;
                window.__heldSearchSignal = options.signal;
                return new Promise(resolve => {
                    window.__finishOldSearch = () => resolve(new Response(JSON.stringify({results: [{
                        label: "Obsolete search must not replace new results", latitude: 1, longitude: 2,
                        source: "Fixture", attribution: "Fixture", license: "CC0-1.0",
                        retrieved_at: "2026-10-04T00:00:00Z",
                    }]}), {status: 200, headers: {"Content-Type": "application/json"}}));
                });
            }
            return original(path, options);
        };
    })();""")
    page.goto(operated_portal[0], wait_until="networkidle")
    assert not any("/api/" in call for call in calls)
    _connect(page)
    page.locator("#addressQuery").fill("First fictional search")
    page.locator("#searchButton").click()
    page.wait_for_function("() => typeof window.__finishOldSearch === 'function'")
    page.locator("#disconnect").click()
    expect(page.locator("#connectionBadge")).to_have_text("Offline")
    assert page.evaluate("window.__heldSearchSignal.aborted")
    _connect(page)
    page.locator("#addressQuery").fill("New fictional search")
    page.locator("#searchButton").click()
    expect(page.locator("#searchResults .result")).to_have_count(2)
    expected = page.locator("#searchResults").text_content()
    page.evaluate("async () => { window.__finishOldSearch(); await new Promise(resolve => setTimeout(resolve, 0)); }")
    expect(page.locator("#searchResults")).to_have_text(expected)
    expect(page.locator("#connectionBadge")).to_have_text("Portal connected")
    expect(page.locator("#addressQuery")).to_be_enabled()

    page.route("**/api/v1/search", lambda request: request.abort("failed"))
    page.locator("#addressQuery").fill("Network failure fixture")
    page.locator("#searchButton").click()
    expect(page.locator("#connectionBadge")).to_have_text("Offline")
    expect(page.locator("#connectionStatus")).to_contain_text("Press Connect")
    before_online_event = len(calls)
    page.evaluate("window.dispatchEvent(new Event('online'))")
    expect(page.locator("#connect")).to_be_enabled()
    expect(page.locator("#addressQuery")).to_be_disabled()
    assert len(calls) == before_online_event
    expect(page.locator("#searchResults")).to_have_text(expected)


def test_selected_csv_tiny_coordinates_and_full_source_survive_offline(portal_page, operated_portal, tmp_path):
    from playwright.sync_api import expect

    from fieldforge.online.models import validate_search_result

    page, context, calls = portal_page
    url, provider, _source, _asset = operated_portal
    chosen = validate_search_result({
        "label": 'Fictional "tiny", مكان <test> ' + "界" * 170,
        "latitude": 1e-7, "longitude": -2e-7,
        "source": "Original fixture " + "S" * 450,
        "attribution": "Original fixture attribution " + "A" * 3000,
        "license": "CC0-1.0", "retrieved_at": "2026-10-04T00:00:00Z",
    })
    page.route("**/api/v1/search", lambda request: request.fulfill(json={"results": [chosen]}))
    candidate = provider.routing["routes"][0]
    candidate["geometry"]["coordinates"] = [[-2e-7, 1e-7], [0.0, 0.0]]
    candidate["legs"][0]["steps"] = [candidate["legs"][0]["steps"][0], candidate["legs"][0]["steps"][-1]]
    candidate["legs"][0]["steps"][0]["maneuver"]["location"] = [-2e-7, 1e-7]
    candidate["legs"][0]["steps"][1]["maneuver"]["location"] = [0.0, 0.0]
    provider.routing["routes"] = [candidate]
    page.goto(url, wait_until="networkidle")
    assert not any("/api/" in call for call in calls)
    _connect(page)
    page.locator("#addressQuery").fill("Fictional tiny place")
    page.locator("#searchButton").click()
    expect(page.locator("#searchResults .result")).to_have_count(1)
    expect(page.locator("#selectedAddress")).to_be_hidden()
    page.get_by_role("button", name="Select place", exact=True).click()
    expect(page.locator("#selectedAddressTitle")).to_have_text(chosen["label"])
    assert page.locator("#selectedAddressTitle test").count() == 0
    page.get_by_role("button", name="Use as start", exact=True).click()
    expect(page.locator("#startLatitude")).to_have_value("0.0000001")
    expect(page.locator("#startLongitude")).to_have_value("-0.0000002")
    page.locator("#endLatitude").fill("0")
    page.locator("#endLongitude").fill("0")
    page.locator("#routeButton").click()
    expect(page.locator("#routePreview")).to_be_visible()
    page.locator("#endLatitude").fill("1")
    expect(page.locator("#routeSelectionStatus")).to_be_visible()
    expect(page.locator("#routeProvenance")).to_contain_text("to 0, 0")
    context.set_offline(True)
    expect(page.locator("#connectionBadge")).to_have_text("Offline")
    with page.expect_download() as pending:
        page.locator("#downloadPlace").click()
    csv_path = tmp_path / pending.value.suggested_filename
    pending.value.save_as(csv_path)
    catalog = read_catalog(csv_path, consent=True, wgs84_confirmed=True)
    place = catalog.places[0]
    assert (place.latitude, place.longitude) == (1e-7, -2e-7)
    assert len(place.name) <= 160 and place.name.startswith('Fictional "tiny", مكان <test>')
    assert len(place.source) <= 512 and "fieldforge-place.source.json" in place.source
    expect(page.locator("#searchStatus")).to_contain_text("shortened")
    with page.expect_download() as pending:
        page.locator("#downloadPlaceDetails").click()
    source_path = tmp_path / pending.value.suggested_filename
    pending.value.save_as(source_path)
    assert json.loads(source_path.read_bytes()) == chosen
    with page.expect_download() as pending:
        page.locator("#downloadGpx").click()
    gpx_path = tmp_path / pending.value.suggested_filename
    pending.value.save_as(gpx_path)
    assert parse_gpx(gpx_path.read_bytes()).point_count == 2
    assert b'lat="0.0000001"' in gpx_path.read_bytes()
    assert b'lon="-0.0000002"' in gpx_path.read_bytes()
    page.set_viewport_size({"width": 390, "height": 844})
    _assert_no_horizontal_overflow(page)


def test_unconfigured_provider_status_keeps_online_actions_unavailable(portal_page, operated_portal):
    from playwright.sync_api import expect

    page, _context, calls = portal_page
    page.route("**/api/v1/status", lambda request: request.fulfill(json={
        "api_version": 1, "name": "Unconfigured fixture portal", "geocoding": False,
        "routing": False, "catalog": True, "route_modes": [], "providers": {},
    }))
    page.goto(operated_portal[0], wait_until="networkidle")
    assert not any("/api/" in call for call in calls)
    _connect(page)
    expect(page.locator("#mapCatalog .map-card")).to_have_count(1)
    expect(page.locator("#addressQuery")).to_be_disabled()
    expect(page.locator("#routeButton")).to_be_disabled()
    expect(page.locator("#connectionStatus")).to_contain_text("Address provider not configured")
    expect(page.locator("#connectionStatus")).to_contain_text("Route provider not configured")
    expect(page.locator("#providers")).to_be_hidden()
    page.locator("#consent").uncheck()
    expect(page.locator("#connectionBadge")).to_have_text("Offline")
    assert page.locator(".download-link").get_attribute("href") is None
