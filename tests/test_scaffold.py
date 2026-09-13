import json
import unittest

from helpers import FIXTURES, ROOT


class ScaffoldTests(unittest.TestCase):
    def test_plugin_manifest(self):
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["name"], "overnight")
        self.assertEqual(manifest["author"]["name"], "Dimitris Mitsis")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")

    def test_marketplace_lists_the_plugin(self):
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual(market["name"], "overnight")
        self.assertEqual([p["name"] for p in market["plugins"]], ["overnight"])
        self.assertEqual(market["plugins"][0]["source"], "./")

    def test_fixtures_exist(self):
        for name in ("agna-answers-brief.md", "agna-skills-brief.md", "broken-brief.md", "tally-brief.md"):
            self.assertTrue((FIXTURES / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
