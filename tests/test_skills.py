import re
import unittest

from helpers import ROOT


class SkillFileTests(unittest.TestCase):
    def frontmatter(self, name):
        text = (ROOT / "skills" / name / "SKILL.md").read_text()
        match = re.match(r"^---\nname: (\S+)\ndescription: (.+?)\n---\n", text, re.DOTALL)
        self.assertIsNotNone(match, f"{name} frontmatter")
        return match.group(1), match.group(2), text

    def test_skill_names(self):
        for name in ("start", "status", "stop"):
            skill_name, description, _ = self.frontmatter(name)
            self.assertEqual(skill_name, name)
            self.assertGreater(len(description), 40)

    def test_start_uses_every_script(self):
        _, _, text = self.frontmatter("start")
        for needle in ('overnight_brief.py" validate', 'overnight_prepare.py" --project', 'overnight_watchdog.py" launch', "references/goal-condition.md", "AskUserQuestion"):
            self.assertIn(needle, text)

    def test_references_exist(self):
        for ref in ("brief-contract.md", "goal-condition.md", "unattended-rules.md"):
            self.assertTrue((ROOT / "skills" / "start" / "references" / ref).is_file(), ref)


if __name__ == "__main__":
    unittest.main()
