"""Prepared regional maps retain their identity from browser list to offline use."""

import hashlib
import json
import os
import socket
from pathlib import Path

import test_online_portal_browser as portal_browser
from test_regional_index import build

from fieldforge.navigation import regional_index as regional
from fieldforge.online.catalog import publish_map
from fieldforge.online.client import PortalClient
from fieldforge.online.download_list import download_maps, load_download_list

operated_portal = portal_browser.operated_portal
portal_page = portal_browser.portal_page
pytestmark = portal_browser.pytestmark


def test_regional_filter_mixed_list_download_and_offline_search(
    portal_page, operated_portal, tmp_path, monkeypatch,
):
    from PIL import Image
    from playwright.sync_api import expect

    url, _provider, source, overview = operated_portal
    source_folder = tmp_path / "regional-source"
    source_folder.mkdir()
    prepared = build(source_folder)
    original_bytes = prepared.path.read_bytes()
    asset = publish_map(
        source.parent / "published-maps", prepared.path,
        map_id="test-regional-streets", title="TEST FIXTURE regional streets",
        coverage=[-70.1, 39.9, -69.9, 40.1], version="test-1",
        source_name="Synthetic regional fixture", attribution="Original test geometry",
        license="Test fixture only",
    )
    image_path = tmp_path / "test-reference.png"
    Image.new("RGB", (8, 8), "green").save(image_path)
    image_asset = publish_map(
        source.parent / "published-maps", image_path,
        map_id="test-reference", title="TEST FIXTURE map image",
        coverage="Test region", version="test-1",
        source_name="Synthetic image fixture", attribution="Original test pixels",
        license="Test fixture only",
    )

    page, context, calls = portal_page
    page.goto(url, wait_until="networkidle")
    assert not any("/api/" in call for call in calls)
    portal_browser._connect(page)
    expect(page.locator("#mapCatalog .map-card")).to_have_count(3)
    before_filter = len(calls)
    page.locator("#mapKind").select_option(label="Prepared regional maps")
    card = page.locator("#mapCatalog .map-card")
    expect(card).to_have_count(1)
    expect(card.locator("h3")).to_have_text(asset["title"])
    expect(card).to_contain_text("Prepared regional map (.ffmap)")
    expect(card).to_contain_text("Local display and search")
    expect(card).to_contain_text("not a routing graph")
    expect(card).to_contain_text(asset["sha256"])
    page.get_by_role("checkbox", name=f"Add {asset['title']} to download list", exact=True).check()
    page.locator("#mapKind").select_option("image")
    expect(page.locator("#mapCatalog .map-card h3")).to_have_text(image_asset["title"])
    page.get_by_role("checkbox", name=f"Add {image_asset['title']} to download list", exact=True).check()
    page.locator("#mapKind").select_option("mbtiles")
    expect(page.locator("#mapCatalog .map-card h3")).to_have_text(overview["title"])
    page.get_by_role("checkbox", name=f"Add {overview['title']} to download list", exact=True).check()
    page.locator("#mapKind").select_option("regional")
    expect(page.locator("#downloadListTotal")).to_contain_text("3 maps")
    assert len(calls) == before_filter

    screenshot = os.environ.get("FIELDFORGE_REGIONAL_PORTAL_SCREENSHOT")
    if screenshot:
        destination = Path(screenshot)
        destination.parent.mkdir(parents=True, exist_ok=True)
        page.locator("#mapsTitle").evaluate("node => node.scrollIntoView({block: 'start'})")
        page.screenshot(path=str(destination))

    # Native browser downloads deliver the file; checked installation is below.
    with page.expect_download() as captured:
        page.get_by_role("link", name=f"Download {asset['title']}", exact=True).click()
    browser_path = tmp_path / "browser-regional.ffmap"
    captured.value.save_as(browser_path)
    assert captured.value.suggested_filename == asset["filename"]
    assert browser_path.read_bytes() == original_bytes

    context.set_offline(True)
    expect(page.locator("#connectionBadge")).to_have_text("Offline")
    before_offline_filters = len(calls)
    page.locator("#mapFilter").fill("synthetic regional")
    expect(card.locator("h3")).to_have_text(asset["title"])
    expect(card.locator(".download-link")).to_have_attribute("aria-disabled", "true")
    assert card.locator(".download-link").get_attribute("href") is None
    for width in (390, 1280):
        page.set_viewport_size({"width": width, "height": 844})
        portal_browser._assert_no_horizontal_overflow(page)
    assert len(calls) == before_offline_filters
    with page.expect_download() as exported:
        page.locator("#saveDownloadList").click()
    selection = tmp_path / "browser-regional-list.json"
    exported.value.save_as(selection)
    document = load_download_list(selection)
    assert document["portal"] == url
    assert document["total_bytes"] == sum(item["bytes"] for item in (asset, image_asset, overview))
    assert {item["format"] for item in document["maps"]} == {"ffmap", "png", "mbtiles"}
    assert next(item for item in document["maps"] if item["format"] == "ffmap") == asset

    client = PortalClient(document["portal"])
    assert not client.connected
    client.connect()
    try:
        downloaded = download_maps(client, document, tmp_path / "installed-maps")
    finally:
        client.disconnect()
    installed = next(path for path in downloaded if path.suffix == ".ffmap")
    manifest = json.loads(installed.with_name(installed.name + ".fieldforge.json").read_bytes())
    assert installed.read_bytes() == original_bytes
    assert hashlib.sha256(installed.read_bytes()).hexdigest() == asset["sha256"]
    assert manifest["asset"] == asset

    def network_forbidden(*args, **kwargs):
        raise AssertionError("Regional reopen/search must remain offline")

    # Scope the network trap to local map operations, leaving fixture cleanup intact.
    with monkeypatch.context() as offline:
        offline.setattr(socket, "create_connection", network_forbidden)
        reopened = regional.inspect_index(installed)
        assert reopened.metadata == prepared.metadata
        assert len(regional.search_index(reopened, "Map Street").features) == 2
