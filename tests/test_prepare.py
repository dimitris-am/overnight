import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES, GIT_ENV, SCRIPTS, git

import overnight_prepare as op


class GitEnvMixin:
    def setUp(self):
        self._saved_env = {k: os.environ.get(k) for k in GIT_ENV}
        os.environ.update(GIT_ENV)
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class PureFunctionTests(unittest.TestCase):
    def test_goal_condition_is_one_numbered_line(self):
        goal = op.build_goal_condition(["Tests pass.", "README  has\nusage"])
        self.assertNotIn("\n", goal)
        self.assertTrue(goal.startswith("Every done-criterion for this project is proven in this conversation: (1) Tests pass. (2) README has usage."))
        self.assertTrue(goal.endswith("and JOURNAL.md has a final summary entry."))
        self.assertIn("the most recent print of .overnight/evidence.md shows, for each numbered criterion, the command that was run and its actual output (not a claim)", goal)

    def test_goal_condition_needs_criteria(self):
        with self.assertRaises(op.PrepareError):
            op.build_goal_condition([])

    def test_render_rules_fills_actions(self):
        template = op.RULES_TEMPLATE.read_text(encoding="utf-8")
        rendered = op.render_rules(template, ["deploy to Cloudflare Workers.", "create and push this project's GitHub repository"])
        self.assertIn("Pre-approved outside actions: deploy to Cloudflare Workers; create and push this project's GitHub repository.", rendered)
        self.assertTrue(rendered.startswith(op.BEGIN))
        self.assertTrue(rendered.rstrip().endswith(op.END))

    def test_render_rules_without_actions(self):
        rendered = op.render_rules(op.RULES_TEMPLATE.read_text(encoding="utf-8"), [])
        self.assertIn("Pre-approved outside actions: none.", rendered)

    def test_render_rules_rejects_bad_template(self):
        with self.assertRaises(op.PrepareError):
            op.render_rules("no placeholder", [])

    def test_upsert_appends_and_preserves(self):
        result = op.upsert_section("# Project\n\nKeep me.\n", f"{op.BEGIN}\nA\n{op.END}")
        self.assertEqual(result, f"# Project\n\nKeep me.\n\n{op.BEGIN}\nA\n{op.END}\n")

    def test_upsert_replaces_existing_section(self):
        existing = f"top\n\n{op.BEGIN}\nold\n{op.END}\nbottom\n"
        result = op.upsert_section(existing, f"{op.BEGIN}\nnew\n{op.END}")
        self.assertEqual(result, f"top\n\n{op.BEGIN}\nnew\n{op.END}\nbottom\n")
        self.assertEqual(result.count(op.BEGIN), 1)

    def test_upsert_into_empty_file(self):
        self.assertEqual(op.upsert_section("", f"{op.BEGIN}\nA\n{op.END}\n"), f"{op.BEGIN}\nA\n{op.END}\n")


class PrepareTests(GitEnvMixin, unittest.TestCase):
    def run_prepare(self, project, **overrides):
        args = dict(
            project=project,
            brief_path=FIXTURES / "tally-brief.md",
            criteria=["python3 -m unittest discover -s tests passes"],
            approved_actions=[],
            morning_checks=["Try tally on a real file"],
            stop_time="06:00",
            model="sonnet",
            now=1789000000.0,
        )
        args.update(overrides)
        return op.prepare(**args)

    def test_prepare_empty_directory(self):
        project = self.base / "tally"
        project.mkdir()
        result = self.run_prepare(project)

        self.assertEqual(git(project, "log", "--format=%s", "-1"), "overnight: prepare unattended run")
        self.assertEqual(result["commit"], git(project, "rev-parse", "HEAD"))
        self.assertEqual((project / "BRIEF.md").read_text(), (FIXTURES / "tally-brief.md").read_text())
        claude_md = (project / "CLAUDE.md").read_text()
        self.assertIn(op.BEGIN, claude_md)
        self.assertIn("Pre-approved outside actions: none.", claude_md)
        self.assertIn("(1) python3 -m unittest discover -s tests passes.", (project / ".overnight" / "goal.txt").read_text())
        config = json.loads((project / ".overnight" / "config.json").read_text())
        self.assertEqual(config["stop_time"], "06:00")
        self.assertEqual(config["model"], "sonnet")
        self.assertEqual(config["started_at_epoch"], 1789000000.0)
        self.assertEqual(config["max_relaunches"], 10)
        self.assertEqual(config["brief_source"], str((FIXTURES / "tally-brief.md").resolve()))
        gitignore = (project / ".gitignore").read_text().splitlines()
        for entry in op.GITIGNORE_ENTRIES:
            self.assertIn(entry, gitignore)
        journal = (project / "JOURNAL.md").read_text()
        self.assertIn("# Journal: tally", journal)
        self.assertIn("- [ ] Try tally on a real file", journal)
        self.assertEqual(git(project, "status", "--porcelain"), "")

    def test_rules_keep_work_inside_the_project_and_secrets_out_of_records(self):
        project = self.base / "tally"
        project.mkdir()
        self.run_prepare(project)
        claude_md = (project / "CLAUDE.md").read_text()
        self.assertIn(
            "- Work only inside this project directory: never modify files outside it (your home directory, global git or "
            "shell configuration, other repositories) and never install tools globally.",
            claude_md,
        )
        self.assertIn(
            "- Never write secrets (tokens, keys, passwords, or environment variable values) into JOURNAL.md, "
            ".overnight/evidence.md, commits, or logs; redact them in any command output you record.",
            claude_md,
        )
        self.assertLess(claude_md.index("Pre-approved outside actions"), claude_md.index("Work only inside this project directory"))
        self.assertLess(claude_md.index("Never write secrets"), claude_md.index("**Record keeping:**"))

    def test_gitignore_covers_every_watchdog_file(self):
        self.assertEqual(op.GITIGNORE_ENTRIES, [".overnight/state.json", ".overnight/state.json.tmp", ".overnight/logs/", ".overnight/STOP"])
        project = self.base / "tally"
        project.mkdir()
        self.run_prepare(project)
        self.assertIn(".overnight/state.json.tmp", (project / ".gitignore").read_text().splitlines())
        (project / ".overnight" / "state.json.tmp").write_text("{}")
        self.assertEqual(git(project, "status", "--porcelain"), "")

    def test_prepare_ignores_ds_store_when_judging_empty(self):
        project = self.base / "tally"
        project.mkdir()
        (project / ".DS_Store").write_text("x")
        self.run_prepare(project)
        self.assertTrue((project / ".git").is_dir())

    def test_rerun_keeps_one_section_and_logs_restart(self):
        project = self.base / "tally"
        project.mkdir()
        self.run_prepare(project)
        self.run_prepare(project, now=1789003600.0)
        self.assertEqual((project / "CLAUDE.md").read_text().count(op.BEGIN), 1)
        self.assertIn("[milestone] Unattended run restarted; stop time 06:00.", (project / "JOURNAL.md").read_text())

    def test_rerun_removes_a_leftover_stop_file(self):
        project = self.base / "tally"
        project.mkdir()
        self.run_prepare(project)
        (project / ".overnight" / "STOP").write_text("")
        self.run_prepare(project, now=1789003600.0)
        self.assertFalse((project / ".overnight" / "STOP").exists())
        self.assertEqual(git(project, "status", "--porcelain"), "")

    def test_refuses_dirty_repository(self):
        project = self.base / "tally"
        project.mkdir()
        git(project, "init", "-q", "-b", "main")
        (project / "notes.txt").write_text("uncommitted")
        with self.assertRaisesRegex(op.PrepareError, "Working tree is not clean"):
            self.run_prepare(project)

    def test_refuses_non_empty_non_repository(self):
        project = self.base / "tally"
        project.mkdir()
        (project / "file.txt").write_text("x")
        with self.assertRaisesRegex(op.PrepareError, "not a git repository and not empty"):
            self.run_prepare(project)

    def test_refuses_directory_inside_another_repository(self):
        git(self.base, "init", "-q", "-b", "main")
        project = self.base / "nested"
        project.mkdir()
        with self.assertRaisesRegex(op.PrepareError, "inside another git repository"):
            self.run_prepare(project)

    def test_refuses_bad_stop_time(self):
        project = self.base / "tally"
        project.mkdir()
        with self.assertRaisesRegex(op.PrepareError, "stop_time must be HH:MM"):
            self.run_prepare(project, stop_time="6am")


class PrepareCliTests(GitEnvMixin, unittest.TestCase):
    def test_cli_round_trip(self):
        project = self.base / "tally"
        project.mkdir()
        input_file = self.base / "input.json"
        input_file.write_text(json.dumps({
            "brief": str(FIXTURES / "tally-brief.md"),
            "criteria": ["README.md documents usage with examples"],
            "approved_actions": [],
            "morning_checks": [],
            "stop_time": "06:00",
            "model": None,
        }))
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "overnight_prepare.py"), "--project", str(project), "--input", str(input_file)],
            capture_output=True, text=True, env={**os.environ, **GIT_ENV},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["ok"])
        self.assertTrue(Path(data["goal_file"]).is_file())

    def test_cli_reports_errors_as_json(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "overnight_prepare.py"), "--project", str(self.base), "--input", str(self.base / "missing.json")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
