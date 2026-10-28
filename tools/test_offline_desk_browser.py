"""Exercise the downloadable desk in a native browser with networking disabled."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from build_hosted_preview import FAVICON
from build_offline_desk import export_offline

ROOT = Path(__file__).resolve().parent
GPX = b'''<gpx><wpt lat="60" lon="100"/><trk>
<trkseg><trkpt lat="0" lon="0"/><trkpt lat="0" lon="1"/><trkpt lat="0" lon="3"/></trkseg>
<trkseg><trkpt lat="0" lon="170"/></trkseg>
<trkseg><trkpt lat="0" lon="-10"/><trkpt lat="0" lon="-10"/></trkseg>
</trk></gpx>'''


@unittest.skipUnless(
    os.environ.get("FIELDFORGE_PORTAL_BROWSER_TESTS") == "1",
    "Set FIELDFORGE_PORTAL_BROWSER_TESTS=1 to require a native browser",
)
class OfflineDeskBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        cls.output = Path(cls.folder.name)
        portal = ROOT.parent / "fieldforge/online/portal.html"
        export_offline(ROOT / "portal_preview", cls.output, portal.read_text(), "0" * 40, FAVICON)
        cls.pack = cls.output / "fixture.mbtiles"
        cls.pack.write_bytes(subprocess.check_output([
            sys.executable, str(ROOT / "portal_preview/mbtiles-fixture.py"), "valid",
        ]))
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        engine = getattr(cls.playwright, os.environ.get("FIELDFORGE_BROWSER", "chromium"))
        options = {"headless": True}
        if executable := os.environ.get("FIELDFORGE_BROWSER_EXECUTABLE"):
            options["executable_path"] = executable
        cls.browser = engine.launch(**options)
        cls.addClassCleanup(cls.browser.close)

    def test_segment_navigation_and_local_map_at_desktop_and_phone_widths(self):
        from playwright.sync_api import expect

        for width in (1280, 390):
            with self.subTest(width=width), self.browser.new_context(
                viewport={"width": width, "height": 844}, offline=True,
            ) as context:
                requests, errors = [], []
                page = context.new_page()
                page.on("request", lambda request: requests.append(request.url))
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto((self.output / "fieldforge-offline.html").as_uri())
                expect(page.locator("#offlineTools")).to_be_enabled()
                page.locator("#traceTab").click()
                page.locator("#deskGpx").set_input_files({
                    "name": "segments.gpx", "mimeType": "application/gpx+xml", "buffer": GPX,
                })
                page.locator("#deskViewMap").click()
                group = page.get_by_label("Jump to a segment or waypoints")
                expect(group.locator("option")).to_have_count(4)
                expect(page.locator("#mbRouteDistance")).to_contain_text("333.6 km")
                # Keyboard selection updates both point navigation and its accessible readout.
                group.focus()
                group.press("ArrowDown")
                expect(page.locator("#mbRouteCoordinates")).to_have_text("0, 170")
                expect(page.locator("#mbRouteDistance")).to_contain_text("Isolated GPX point")
                expect(page.locator("#mbRoutePoint")).to_have_attribute(
                    "aria-valuetext", "Segment 2 · point 1",
                )
                expect(page.locator("#mbRouteCentre")).to_be_disabled()
                # Opening a local pack retains the snapshot and selected segment.
                page.locator("#mbFile").set_input_files(str(self.pack))
                expect(page.locator("#mbRouteCentre")).to_be_enabled()
                expect(group).to_have_value("1")
                group.select_option("0")
                page.locator("#mbRouteNext").click()
                expect(page.locator("#mbRouteDistance")).to_contain_text("111.2 km")
                expect(page.locator("#mbRouteDistance")).to_contain_text("222.4 km")
                group.select_option("3")
                expect(page.locator("#mbRouteDistance")).to_contain_text("Separate waypoint")
                expect(page.locator("#mbRouteNext")).to_be_disabled()
                self.assertTrue(page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth + 1"
                ))
                screenshot_dir = os.environ.get("FIELDFORGE_OFFLINE_SCREENSHOT_DIR")
                if screenshot_dir:
                    destination = Path(screenshot_dir)
                    destination.mkdir(parents=True, exist_ok=True)
                    group.select_option("0")
                    page.locator("#mbRouteCard").screenshot(
                        path=str(destination / f"gpx-segments-{width}.png"),
                    )
                page.locator("#mbRouteClear").click()
                expect(group.locator("option")).to_have_count(0)
                expect(page.locator("#mbRouteCard")).to_be_hidden()
                page.locator("#mbClose").click()
                self.assertFalse(errors)
                self.assertFalse([url for url in requests if re.match(r"(?:https?|wss?)://", url)])


if __name__ == "__main__":
    unittest.main()
