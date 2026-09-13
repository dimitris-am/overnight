import json
import subprocess
import sys
import unittest

from helpers import FIXTURES, SCRIPTS

import overnight_brief as ob


class ValidateBriefTests(unittest.TestCase):
    def read(self, name):
        return (FIXTURES / name).read_text(encoding="utf-8")

    def test_agna_skills_brief_is_valid(self):
        brief = ob.validate(self.read("agna-skills-brief.md"))
        self.assertEqual(brief.errors, [])
        self.assertEqual(len(brief.done_criteria), 6)
        self.assertEqual(brief.done_criteria[1], "A fresh email address can sign in with a PIN")
        self.assertEqual(brief.stop_time, "07:30")

    def test_agna_answers_brief_is_valid(self):
        brief = ob.validate(self.read("agna-answers-brief.md"))
        self.assertEqual(brief.errors, [])
        self.assertEqual(len(brief.done_criteria), 5)
        self.assertEqual(brief.stop_time, "07:30")

    def test_broken_brief_reports_every_problem_at_once(self):
        brief = ob.validate(self.read("broken-brief.md"))
        self.assertEqual(
            brief.errors,
            [
                "Missing section: Done-criteria",
                "No stop time: add an HH:MM time to Guardrails or pass --until HH:MM",
            ],
        )

    def test_until_supplies_the_stop_time(self):
        brief = ob.validate(self.read("tally-brief.md"), until="05:45")
        self.assertEqual(brief.errors, [])
        self.assertEqual(brief.stop_time, "05:45")
        self.assertEqual(len(brief.done_criteria), 4)

    def test_until_must_be_24_hour_hh_mm(self):
        brief = ob.validate(self.read("tally-brief.md"), until="7pm")
        self.assertEqual(brief.errors, ["--until must be HH:MM (24-hour), got '7pm'"])

    def test_heading_suffixes_and_synonyms(self):
        text = (
            "# T\n\n## Mission\n\nDo it.\n\n## Constraints\n\n- a\n\n## Requirements\n\n1. b\n\n"
            "## Definition of done (strict)\n\n- c\n\n## Method — Superpowers\n\nprose\n\n"
            "## Guardrails\n\n- stop at 23:15\n"
        )
        brief = ob.validate(text)
        self.assertEqual(brief.errors, [])
        self.assertEqual(brief.done_criteria, ["c"])
        self.assertEqual(brief.stop_time, "23:15")

    def test_empty_sections_are_errors(self):
        text = "## Mission\n\n## Hard constraints\n\n- a\n\n## Must-have\n\nprose only\n\n## Done-criteria\n\n- c\n\n## Guardrails\n\n- until 06:00\n"
        brief = ob.validate(text)
        self.assertEqual(
            brief.errors,
            ["Section 'Mission' is empty", "Section 'Must-have' has no list items"],
        )

    def test_single_digit_hour_is_normalized(self):
        text = "## Mission\n\nx\n\n## Hard constraints\n\n- a\n\n## Must-have\n\n- b\n\n## Done-criteria\n\n- c\n\n## Guardrails\n\n- stop at 6:05\n"
        self.assertEqual(ob.validate(text).stop_time, "06:05")

    def test_ascii_dash_heading_suffix(self):
        text = "## Mission - v2\n\nx\n\n## Hard constraints\n\n- a\n\n## Must-have\n\n- b\n\n## Done-criteria - strict\n\n- c\n\n## Guardrails - nightly\n\n- stop at 05:00\n"
        brief = ob.validate(text)
        self.assertEqual(brief.errors, [])
        self.assertEqual(brief.done_criteria, ["c"])
        self.assertEqual(brief.stop_time, "05:00")


class ValidateCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "overnight_brief.py"), "validate", *args],
            capture_output=True,
            text=True,
        )

    def test_cli_ok(self):
        result = self.run_cli(str(FIXTURES / "agna-skills-brief.md"))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["stop_time"], "07:30")

    def test_cli_failure(self):
        result = self.run_cli(str(FIXTURES / "broken-brief.md"))
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["ok"])

    def test_cli_missing_file(self):
        result = self.run_cli("/nonexistent/brief.md")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Cannot read brief", json.loads(result.stdout)["errors"][0])


if __name__ == "__main__":
    unittest.main()
