"""Check the distributable itself: self-containment, integrity and shared modules."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from build_offline_desk import MODULES, bundle_modules, export_offline
from build_hosted_preview import FAVICON

ROOT = Path(__file__).resolve().parent


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.elements, self.scripts, self.styles = [], [], []
        self.active = None
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        self.elements.append((tag, attrs))
        if tag in ("script", "style"):
            self.active = tag
            (self.scripts if tag == "script" else self.styles).append("")

    def handle_endtag(self, tag):
        if tag == self.active:
            self.active = None

    def handle_data(self, data):
        if self.active:
            group = self.scripts if self.active == "script" else self.styles
            group[-1] += data


class OfflineDeskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        cls.output = Path(cls.folder.name)
        portal = ROOT.parent / "fieldforge/online/portal.html"
        if not portal.exists():
            portal = ROOT / "snapshot/fieldforge/online/portal.html"
        export_offline(ROOT / "portal_preview", cls.output, portal.read_text(), "0" * 40, FAVICON)
        cls.raw = (cls.output / "fieldforge-offline.html").read_bytes()
        cls.text = cls.raw.decode()
        cls.doc = Document(cls.text)

    def test_page_has_no_external_resources_or_active_external_links(self):
        self.assertEqual(len(self.doc.scripts), 1)
        self.assertEqual(len(self.doc.styles), 1)
        for tag, attrs in self.doc.elements:
            self.assertNotIn("src", attrs)
            self.assertNotIn("srcset", attrs)
            self.assertFalse(any(key.startswith("on") for key in attrs))
            self.assertNotEqual(attrs.get("type"), "module")
            if "href" in attrs:
                self.assertTrue(attrs["href"].startswith(("#", "data:")), (tag, attrs))
        self.assertNotRegex(self.doc.styles[0], r"@import|url\(\s*['\"]?(?:https?:|//)")
        self.assertNotRegex(self.doc.scripts[0], r"^\s*(?:export|import)\b|\bimport\s*\(")
        self.assertNotRegex(self.doc.scripts[0], r"\b(?:fetch|XMLHttpRequest|WebSocket|sendBeacon)\s*\(")
        ids = [attrs["id"] for _, attrs in self.doc.elements if "id" in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        for _, attrs in self.doc.elements:
            for key in ("for", "aria-controls", "aria-labelledby", "aria-describedby"):
                for target in attrs.get(key, "").split():
                    self.assertIn(target, ids)
            if attrs.get("href", "").startswith("#"):
                self.assertIn(attrs["href"][1:], ids)
        self.assertIn('id="offlineTools" class="offline-tools" disabled', self.text)
        self.assertNotIn("OFFLINE_EDITION_ID", self.text)
        self.assertNotIn("<!--DESK-->", self.text)

    def test_emitted_script_and_styles_match_the_content_security_policy(self):
        policy = next(attrs["content"] for tag, attrs in self.doc.elements if tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy")
        for kind, value in (("script", self.doc.scripts[0]), ("style", self.doc.styles[0])):
            digest = base64.b64encode(hashlib.sha256(value.encode()).digest()).decode()
            self.assertIn(f"{kind}-src 'sha256-{digest}'", policy)
        self.assertIn("connect-src 'none'", policy)
        self.assertIn("worker-src blob:", policy)
        self.assertNotIn("unsafe-inline", policy)
        self.assertNotIn("unsafe-eval", policy)

    def test_download_metadata_matches_the_exact_file(self):
        metadata = json.loads((self.output / "offline-download.json").read_text())
        self.assertEqual(metadata["filename"], "fieldforge-offline.html")
        self.assertEqual(metadata["bytes"], len(self.raw))
        self.assertEqual(metadata["sha256"], hashlib.sha256(self.raw).hexdigest())
        self.assertFalse(metadata["contains_user_data"])
        self.assertFalse(metadata["includes_map_datasets"])
        self.assertIn(metadata["edition_id"], self.text)
        self.assertLess(len(self.raw), 3 * 1024 * 1024)  # Includes pinned offline SQLite worker.
        self.assertIn('download="FieldForge-Offline-Desk.html"', (ROOT / "portal_preview/desk.html").read_text())

    def test_build_uses_current_shared_sources_and_rejects_unknown_imports(self):
        self.assertEqual(self.doc.scripts[0], bundle_modules(ROOT / "portal_preview"))
        with tempfile.TemporaryDirectory() as folder:
            assets = Path(folder)
            for filename in MODULES:
                (assets / filename).write_text((ROOT / "portal_preview" / filename).read_text())
            for statement in ['import x from "remote";', 'import {unknown} from "./desk-core.mjs";', 'import {MAX_GPX_BYTES} from "./missing.mjs";', 'const lazy = import("./desk-core.mjs");']:
                (assets / "offline.mjs").write_text(statement)
                with self.assertRaises(ValueError):
                    bundle_modules(assets)


if __name__ == "__main__":
    unittest.main()
