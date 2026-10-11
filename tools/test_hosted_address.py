"""Verify the actual hosted/offline boundary and the exported page wiring."""
from pathlib import Path
import re
import tempfile
import unittest

from build_hosted_preview import export
from test_offline_desk import Document

ROOT = Path(__file__).resolve().parent


class HostedAddressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.output = Path(cls.temporary.name)
        source_root = ROOT.parent if (ROOT.parent / "fieldforge/online/portal.html").is_file() else ROOT / "snapshot"
        export(source_root, cls.output, "6ba72816678b9271f190b34d818faa4e89d0eed7")
        cls.hosted = (cls.output / "index.html").read_text()
        cls.offline = (cls.output / "fieldforge-offline.html").read_text()

    def test_hosted_page_has_one_consent_and_complete_address_module_wiring(self):
        doc = Document(self.hosted)
        ids = [attrs["id"] for _, attrs in doc.elements if "id" in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids.count("consent"), 1)
        self.assertIn("addressSearchForm", ids)
        self.assertNotIn("searchForm", ids)
        self.assertIn('<form id="routeForm"><fieldset disabled>', self.hosted)
        self.assertNotIn("<!--HOSTED_ADDRESS", self.hosted)
        for tag, attrs in doc.elements:
            for key in ("for", "aria-controls", "aria-labelledby", "aria-describedby"):
                for target in attrs.get(key, "").split():
                    self.assertIn(target, ids)
            asset = attrs.get("src") or (attrs.get("href") if tag == "link" and attrs.get("rel") == "stylesheet" else None)
            if asset and not asset.startswith(("https:", "data:")):
                self.assertTrue((self.output / asset).is_file(), asset)
        self.assertIn('src="address-entry.mjs"', self.hosted)
        for module in self.output.glob("*.mjs"):
            for dependency in re.findall(r'from "(\./[^"\n]+)"', module.read_text()):
                self.assertTrue((self.output / dependency).is_file(), (module.name, dependency))
        self.assertIn("Manual Photon address lookup", (self.output / "commons.html").read_text())

    def test_offline_edition_excludes_search_controls_provider_endpoint_and_network_modules(self):
        self.assertNotIn('id="addressSearchForm"', self.offline)
        self.assertNotIn('id="addressTab"', self.offline)
        self.assertNotIn("photon.komoot.io", self.offline)
        self.assertNotIn("address-service.mjs", self.offline)
        self.assertNotIn("<!--HOSTED_ADDRESS", self.offline)
        self.assertIn("connect-src &#x27;none&#x27;", self.offline)


if __name__ == "__main__":
    unittest.main()
