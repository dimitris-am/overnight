# overnight Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `overnight` Claude Code plugin: `/overnight:start`, `/overnight:status`, `/overnight:stop`, which run a Superpowers build unattended from a brief on Claude Code's built-in `/goal`, kept alive by a watchdog.

**Architecture:** Three Python standard-library scripts do all mechanical work and are fully unit-tested: `overnight_brief.py` parses and validates briefs, `overnight_prepare.py` writes the project files and the goal condition, and `overnight_watchdog.py` runs, launches, and reports the `claude -p "/goal …"` loop. Three thin skills orchestrate them; the only model judgment is the provability review and the approved-actions list inside `start`. The watchdog's decision loop takes injected runner/clock/sleeper/interpreter functions so every rule is tested without real sessions, and a fake `claude` executable covers the subprocess layer.

**Tech Stack:** Python 3.9+ standard library (`unittest`, `subprocess`, `json`, `argparse`), git 2.28+, tmux 3.0+, Claude Code plugin format (`.claude-plugin/plugin.json`, `skills/<name>/SKILL.md`).

**Spec:** `docs/superpowers/specs/2026-09-13-overnight-plugin-design.md`

## Global Constraints

- Python 3.9+ standard library only. No third-party packages. Every module starts with `from __future__ import annotations`.
- American English in all prose. Author: Dimitris Mitsis (never "Dim").
- Plugin name `overnight`; skills `start`, `status`, `stop` (invoked as `/overnight:start`, `/overnight:status`, `/overnight:stop`).
- Session command flags, exactly: `claude -p "/goal <condition>" --permission-mode bypassPermissions --settings '{"fastMode": false}' --output-format json`, plus `--model <model>` when a model is configured and `--resume <session-id>` when resuming.
- Project files: `BRIEF.md`, `JOURNAL.md`, `CLAUDE.md` (marked section), `.overnight/goal.txt`, `.overnight/config.json`, `.overnight/evidence.md`, `.overnight/state.json`, `.overnight/logs/`, `.overnight/STOP`. Gitignored: `.overnight/state.json`, `.overnight/logs/`, `.overnight/STOP`.
- `CLAUDE.md` section markers: `<!-- overnight:begin -->` and `<!-- overnight:end -->`.
- `.overnight/goal.txt` holds the condition on a single line.
- tmux session name: `overnight-` + the project directory name with every character outside `[A-Za-z0-9_-]` replaced by `-`.
- Watchdog defaults: poll 15 s; a session ending within 60 s counts as a fast crash, 3 in a row fails the run; relaunch delay 10 s; relaunch cap 10; usage-limit fallback wait 30 min, plus 2 min after a stated reset time; SIGINT, then SIGTERM after 30 s, then SIGKILL; wrap-up time box 15 min; 2 consecutive resumes without a new commit switch to a fresh session.
- A project directory must be the top level of its own git repository with a clean tree, or an empty directory not inside another repository (`.DS_Store` is ignored when judging emptiness).
- Never create or push a GitHub repository without Dimitris's explicit approval of the repository name and visibility.
- Tests run from the repo root with `python3 -m unittest discover -s tests -v`.
- Every commit message ends with these two trailer lines:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_018Hi54vjRdkSEgdDuq3QrTL`

## File Structure

| Path | Responsibility |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest |
| `.claude-plugin/marketplace.json` | Single-plugin marketplace so the repo installs with `/plugin marketplace add` |
| `.gitignore` | Python caches |
| `README.md` | What it does, install, usage, brief contract summary |
| `scripts/overnight_brief.py` | Parse a brief into sections; validate the contract; find the stop time; CLI `validate` |
| `scripts/overnight_prepare.py` | Goal condition, rules rendering, `CLAUDE.md` upsert, journal, gitignore, config, git init/commit; CLI |
| `scripts/overnight_watchdog.py` | Deadline and usage-limit math, transcript reading, decision loop, subprocess runner, CLI `run` / `launch` / `status` |
| `skills/start/SKILL.md` | Orchestrates validate → prerequisites → provability review → prepare → launch |
| `skills/start/references/brief-contract.md` | Brief contract for the model and for users |
| `skills/start/references/unattended-rules.md` | The exact `CLAUDE.md` section template (read by `overnight_prepare.py`) |
| `skills/start/references/goal-condition.md` | Provability review guidance |
| `skills/status/SKILL.md` | Runs `status` and relays it |
| `skills/stop/SKILL.md` | Creates `.overnight/STOP` and reports |
| `tests/helpers.py` | Paths, git env, shared fixtures |
| `tests/fixtures/*.md` | Two AGNA briefs, a broken brief, the tally brief |
| `tests/bin/claude` | Fake `claude` executable for subprocess tests |
| `tests/test_brief.py`, `tests/test_prepare.py`, `tests/test_watchdog_rules.py`, `tests/test_watchdog_process.py` | Tests per script |

---

### Task 1: Plugin scaffold, fixtures, and test harness

**Files:**
- Create: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.gitignore`, `README.md`
- Create: `tests/helpers.py`, `tests/test_scaffold.py`
- Create: `tests/fixtures/agna-answers-brief.md`, `tests/fixtures/agna-skills-brief.md`, `tests/fixtures/broken-brief.md`, `tests/fixtures/tally-brief.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `tests/helpers.py` exporting `ROOT: Path`, `SCRIPTS: Path`, `FIXTURES: Path`, `GIT_ENV: dict[str, str]`, `git(cwd, *args) -> str`; importing `helpers` puts `scripts/` on `sys.path`. The four fixture files.

- [ ] **Step 1: Write the failing scaffold test**

`tests/test_scaffold.py`:

```python
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
```

- [ ] **Step 2: Create the test helpers**

`tests/helpers.py`:

```python
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "tests" / "fixtures"
FAKE_CLAUDE = ROOT / "tests" / "bin" / "claude"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Overnight Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Overnight Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(cwd, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV},
    )
    return result.stdout.strip()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL: `FileNotFoundError` for `.claude-plugin/plugin.json`

- [ ] **Step 4: Create the manifests, gitignore, and README**

`.claude-plugin/plugin.json`:

```json
{
  "name": "overnight",
  "version": "0.1.0",
  "description": "Run a Superpowers build unattended from a brief, on Claude Code's built-in /goal, with a watchdog that keeps the goal alive until it is met or the stop time arrives.",
  "author": {
    "name": "Dimitris Mitsis"
  },
  "license": "MIT",
  "keywords": ["goal", "superpowers", "unattended", "overnight", "autonomous"]
}
```

`.claude-plugin/marketplace.json`:

```json
{
  "name": "overnight",
  "owner": {
    "name": "Dimitris Mitsis"
  },
  "description": "Unattended Superpowers runs on Claude Code's built-in /goal.",
  "plugins": [
    {
      "name": "overnight",
      "displayName": "overnight",
      "source": "./",
      "description": "Run a Superpowers build unattended from a brief, on the built-in /goal.",
      "version": "0.1.0",
      "author": {
        "name": "Dimitris Mitsis"
      }
    }
  ]
}
```

`.gitignore`:

```
__pycache__/
*.pyc
.DS_Store
```

`README.md`:

````markdown
# overnight

Run a Superpowers build unattended from a written brief, using Claude Code's built-in `/goal`.

`/overnight:start` checks the brief, prepares the project for work without a human, writes a `/goal` condition that demands printed evidence for every done-criterion, and starts a watchdog in tmux. The watchdog keeps the goal alive: it resumes sessions that end early, waits out usage limits, and stops at the brief's stop time with an honest wrap-up in `JOURNAL.md`.

## Requirements

- Claude Code with the Superpowers plugin installed
- Python 3.9+, git 2.28+, tmux 3.0+

## Install

```text
/plugin marketplace add dimitris-am/overnight
/plugin install overnight@overnight
```

## Use

Open Claude Code in the project's own directory (a new empty directory is fine), then:

```text
/overnight:start path/to/brief.md [--until HH:MM] [--model NAME]
/overnight:status
/overnight:stop
```

## Brief contract

A brief needs these sections: **Mission**, **Hard constraints**, **Must-have**, **Done-criteria** (one checkable statement per item), and **Guardrails** (including a stop time as `HH:MM`, unless you pass `--until`). See `skills/start/references/brief-contract.md`.

## Development

```bash
python3 -m unittest discover -s tests -v
```
````

- [ ] **Step 5: Create the fixtures**

Copy the two AGNA briefs verbatim:

```bash
cp /Users/dim/Documents/Projects/agna-prospectus/course-materials/overnight/agna-answers-brief.md tests/fixtures/agna-answers-brief.md
cp /Users/dim/Documents/Projects/agna-prospectus/course-materials/overnight/agna-skills-brief.md tests/fixtures/agna-skills-brief.md
```

`tests/fixtures/broken-brief.md`:

```markdown
# Brief: broken

## Mission

Build something useful.

## Hard constraints

- Standard library only

## Must-have

- One command

## Guardrails

- Commit often
```

`tests/fixtures/tally-brief.md`:

```markdown
# Brief: tally

## Mission

Build `tally`, a small command-line tool in Python (standard library only) that counts lines, words, and characters in one or more files, like `wc`.

## Hard constraints

- Python 3.9+ standard library only; no third-party packages
- No network access

## Must-have

1. `tally FILE...` prints lines, words, and characters per file, plus a total row when more than one file is given
2. `--json` prints the same data as JSON
3. A missing file prints a clear error to stderr and exits non-zero

## Done-criteria

- `python3 -m unittest discover -s tests` passes
- `python3 tally.py README.md BRIEF.md` prints two rows and a total row
- `python3 tally.py --json README.md` prints valid JSON with lines, words, and characters
- README.md documents usage with examples

## Guardrails

- Work only inside this repository
- Commit after every passing milestone; never force-push
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: 3 tests, all PASS

- [ ] **Step 7: Validate the manifests with Claude Code**

Run: `claude plugin validate .`
Expected: exit code 0. Warnings are acceptable. If the only error is that the plugin has no skills or components yet, note it in the commit message body and move on; Task 6 re-runs the validator with skills present and must pass cleanly there.

- [ ] **Step 8: Commit**

```bash
git add .claude-plugin .gitignore README.md tests
git commit -m "feat: scaffold overnight plugin, fixtures, and test harness

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018Hi54vjRdkSEgdDuq3QrTL"
```

---

### Task 2: Brief parser and validator

**Files:**
- Create: `scripts/overnight_brief.py`
- Test: `tests/test_brief.py`

**Interfaces:**
- Consumes: `tests/helpers.py` (`FIXTURES`, `SCRIPTS`).
- Produces: in `overnight_brief`:
  - `validate(text: str, until: Optional[str] = None) -> Brief`
  - `Brief` dataclass with `sections: Dict[str, str]`, `done_criteria: List[str]`, `guardrails: List[str]`, `stop_time: Optional[str]` ("HH:MM"), and `errors: List[str]`
  - `STRICT_TIME_RE` (compiled regex for "HH:MM")
  - CLI `python3 scripts/overnight_brief.py validate BRIEF [--until HH:MM]` printing JSON `{"ok", "errors", "done_criteria", "guardrails", "stop_time", "sections"}`; exit 0 when ok, else 1.

- [ ] **Step 1: Write the failing tests**

`tests/test_brief.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL: `ModuleNotFoundError: No module named 'overnight_brief'`

- [ ] **Step 3: Implement the parser and validator**

`scripts/overnight_brief.py`:

```python
#!/usr/bin/env python3
"""Parse and validate an overnight brief (a markdown file)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# key, display name, accepted heading names (lowercase, before any "(" or dash suffix)
SECTIONS = [
    ("mission", "Mission", ("mission",)),
    ("constraints", "Hard constraints", ("hard constraints", "constraints")),
    ("must_have", "Must-have", ("must-have", "must-haves", "must have", "requirements")),
    ("done_criteria", "Done-criteria", ("done-criteria", "done criteria", "definition of done")),
    ("guardrails", "Guardrails", ("guardrails",)),
]
LIST_KEYS = {"constraints", "must_have", "done_criteria", "guardrails"}

HEADING_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$")
HEADING_SUFFIX_RE = re.compile(r"\s+[(—–]")
ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.+?)\s*$")
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
STRICT_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass
class Brief:
    sections: Dict[str, str] = field(default_factory=dict)
    done_criteria: List[str] = field(default_factory=list)
    guardrails: List[str] = field(default_factory=list)
    stop_time: Optional[str] = None
    errors: List[str] = field(default_factory=list)


def heading_key(heading: str) -> Optional[str]:
    name = HEADING_SUFFIX_RE.split(heading, maxsplit=1)[0].strip().lower()
    for key, _display, names in SECTIONS:
        if name in names:
            return key
    return None


def split_sections(text: str) -> Dict[str, str]:
    collected: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match:
            current = heading_key(match.group(1))
            if current is not None:
                collected.setdefault(current, [])
            continue
        if current is not None:
            collected[current].append(line)
    return {key: "\n".join(lines).strip() for key, lines in collected.items()}


def list_items(body: str) -> List[str]:
    items = []
    for line in body.splitlines():
        match = ITEM_RE.match(line)
        if match:
            items.append(match.group(1))
    return items


def validate(text: str, until: Optional[str] = None) -> Brief:
    brief = Brief(sections=split_sections(text))
    for key, display, _names in SECTIONS:
        body = brief.sections.get(key)
        if body is None:
            brief.errors.append(f"Missing section: {display}")
        elif key in LIST_KEYS:
            if not list_items(body):
                brief.errors.append(f"Section '{display}' has no list items")
        elif not body:
            brief.errors.append(f"Section '{display}' is empty")
    brief.done_criteria = list_items(brief.sections.get("done_criteria", ""))
    brief.guardrails = list_items(brief.sections.get("guardrails", ""))
    if until is not None:
        if STRICT_TIME_RE.match(until):
            brief.stop_time = until
        else:
            brief.errors.append(f"--until must be HH:MM (24-hour), got '{until}'")
    else:
        match = TIME_RE.search(brief.sections.get("guardrails", ""))
        if match:
            brief.stop_time = f"{int(match.group(1)):02d}:{match.group(2)}"
        else:
            brief.errors.append("No stop time: add an HH:MM time to Guardrails or pass --until HH:MM")
    return brief


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="overnight_brief")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate", help="validate a brief and print a JSON report")
    check.add_argument("brief")
    check.add_argument("--until")
    args = parser.parse_args(argv)
    try:
        text = Path(args.brief).read_text(encoding="utf-8")
    except OSError as error:
        print(json.dumps({"ok": False, "errors": [f"Cannot read brief: {error}"]}))
        return 1
    brief = validate(text, args.until)
    report = {
        "ok": not brief.errors,
        "errors": brief.errors,
        "done_criteria": brief.done_criteria,
        "guardrails": brief.guardrails,
        "stop_time": brief.stop_time,
        "sections": sorted(brief.sections),
    }
    print(json.dumps(report, indent=2))
    return 0 if not brief.errors else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: all tests PASS (3 scaffold + 11 brief)

- [ ] **Step 5: Commit**

```bash
git add scripts/overnight_brief.py tests/test_brief.py
git commit -m "feat: parse and validate overnight briefs

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018Hi54vjRdkSEgdDuq3QrTL"
```

---

### Task 3: Project preparation, unattended rules, and goal condition

**Files:**
- Create: `skills/start/references/unattended-rules.md`
- Create: `scripts/overnight_prepare.py`
- Test: `tests/test_prepare.py`

**Interfaces:**
- Consumes: `tests/helpers.py` (`FIXTURES`, `GIT_ENV`, `git`, `SCRIPTS`, `ROOT`).
- Produces: in `overnight_prepare`:
  - `class PrepareError(Exception)`
  - `build_goal_condition(criteria: List[str]) -> str` (a single line)
  - `render_rules(template: str, approved_actions: List[str]) -> str`
  - `upsert_section(existing: str, section: str) -> str`
  - `ensure_gitignore(path: Path, entries: List[str]) -> None`
  - `check_project_dir(project: Path) -> bool` (True when `git init` is needed)
  - `prepare(project: Path, brief_path: Path, criteria: List[str], approved_actions: List[str], morning_checks: List[str], stop_time: str, model: Optional[str], now: Optional[float] = None) -> Dict[str, str]` returning `{"goal_file", "config_file", "commit"}`
  - constants `BEGIN`, `END`, `GITIGNORE_ENTRIES`, `MAX_RELAUNCHES = 10`, `RULES_TEMPLATE: Path`
  - `.overnight/config.json` keys: `brief_source`, `stop_time`, `model`, `started_at` (ISO, seconds), `started_at_epoch` (float), `max_relaunches`, `morning_checks`
  - CLI `python3 scripts/overnight_prepare.py --project DIR --input INPUT.json`, where the input has `brief`, `criteria`, `approved_actions`, `morning_checks`, `stop_time`, and `model`; prints `{"ok": true, ...result}` (exit 0) or `{"ok": false, "error"}` (exit 1).

- [ ] **Step 1: Create the rules template**

`skills/start/references/unattended-rules.md` (the entire file is the template; `overnight_prepare.py` requires `{approved_actions}` to appear exactly once):

```markdown
<!-- overnight:begin -->
## Unattended run

This project is being built unattended under /goal. No human is present and nobody will answer.
BRIEF.md is the human's approval of the direction. Read it first.

**Superpowers, without a human:**
- brainstorming: answer every clarifying question yourself from BRIEF.md; take the recommended approach; check each design section against BRIEF.md instead of waiting for approval; skip the visual companion. Replace the spec review gate with a fresh-context subagent that compares the spec against BRIEF.md; fix what it finds, then continue.
- writing-plans: always choose subagent-driven development.
- subagent-driven-development and every other skill: work directly on `main` in this repository; no worktrees. Skip finishing-a-development-branch.
- Pre-approved outside actions: {approved_actions}. Anything else that a skill would stop to ask about: log it as `needs-human` in JOURNAL.md, skip it, and continue with other work. Never force-push, spend money, or delete resources this run did not create.

**Record keeping:**
- JOURNAL.md: one line per event, `- HH:MM [decision|setback|milestone|needs-human] text`. Log every question you answered and every choice you made.
- Commit after every milestone.

**Proof of done:**
- Before claiming the goal is met, write `.overnight/evidence.md`: for each numbered done-criterion in .overnight/goal.txt, the exact command you ran and its actual output. Then print that file in the conversation.
- If the goal check says "not met", fix the gap, rerun the affected commands, update and reprint the evidence.

**Stopping:** if `.overnight/STOP` exists, stop starting new work.
<!-- overnight:end -->
```

- [ ] **Step 2: Write the failing tests**

`tests/test_prepare.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL: `ModuleNotFoundError: No module named 'overnight_prepare'`

- [ ] **Step 4: Implement preparation**

`scripts/overnight_prepare.py`:

```python
#!/usr/bin/env python3
"""Prepare a project for an unattended overnight run: brief copy, CLAUDE.md rules,
journal, goal condition, config, gitignore, and a commit."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
RULES_TEMPLATE = PLUGIN_ROOT / "skills" / "start" / "references" / "unattended-rules.md"
BEGIN = "<!-- overnight:begin -->"
END = "<!-- overnight:end -->"
GITIGNORE_ENTRIES = [".overnight/state.json", ".overnight/logs/", ".overnight/STOP"]
IGNORABLE_ENTRIES = {".DS_Store"}
MAX_RELAUNCHES = 10
STRICT_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class PrepareError(Exception):
    pass


def build_goal_condition(criteria: List[str]) -> str:
    cleaned = [" ".join(item.split()).rstrip(".") for item in criteria if item.strip()]
    if not cleaned:
        raise PrepareError("No done-criteria to build a goal from")
    numbered = " ".join(f"({index}) {item}." for index, item in enumerate(cleaned, 1))
    return (
        "Every done-criterion for this project is proven in this conversation: "
        + numbered
        + " Proven means: the most recent print of .overnight/evidence.md shows, for each numbered "
        "criterion, the command that was run and its actual output (not a claim), and JOURNAL.md "
        "has a final summary entry."
    )


def render_rules(template: str, approved_actions: List[str]) -> str:
    if template.count("{approved_actions}") != 1:
        raise PrepareError("unattended-rules template must contain {approved_actions} exactly once")
    actions = "; ".join(a.strip().rstrip(".") for a in approved_actions if a.strip()) or "none"
    return template.replace("{approved_actions}", actions).strip() + "\n"


def upsert_section(existing: str, section: str) -> str:
    start = existing.find(BEGIN)
    end = existing.find(END)
    if start != -1 and end > start:
        return existing[:start] + section.strip() + existing[end + len(END):]
    base = existing.rstrip()
    return (base + "\n\n" if base else "") + section.strip() + "\n"


def ensure_gitignore(path: Path, entries: List[str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    missing = [entry for entry in entries if entry not in lines]
    if missing:
        path.write_text("\n".join(lines + missing) + "\n", encoding="utf-8")


def _git(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(project), capture_output=True, text=True)


def _git_checked(project: Path, *args: str) -> str:
    result = _git(project, *args)
    if result.returncode != 0:
        raise PrepareError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def check_project_dir(project: Path) -> bool:
    if not project.is_dir():
        raise PrepareError(f"Project directory does not exist: {project}")
    inside = _git(project, "rev-parse", "--is-inside-work-tree")
    if inside.returncode == 0 and inside.stdout.strip() == "true":
        top = Path(_git_checked(project, "rev-parse", "--show-toplevel")).resolve()
        if top != project.resolve():
            raise PrepareError(
                f"{project} is inside another git repository ({top}); run overnight from the "
                "project's own repository or from an empty directory outside any repository"
            )
        if _git_checked(project, "status", "--porcelain"):
            raise PrepareError("Working tree is not clean; commit or stash changes first")
        return False
    entries = [p for p in project.iterdir() if p.name not in IGNORABLE_ENTRIES]
    if entries:
        raise PrepareError(f"{project} is not a git repository and not empty")
    return True


def journal_header(project_name: str, started: dt.datetime, stop_time: str, morning_checks: List[str]) -> str:
    lines = [
        f"# Journal: {project_name}",
        "",
        f"Unattended run started {started:%Y-%m-%d %H:%M}; stop time {stop_time}.",
        "",
    ]
    if morning_checks:
        lines += ["## Morning checks (need a human)", ""]
        lines += [f"- [ ] {check}" for check in morning_checks]
        lines += [""]
    lines += ["## Log", ""]
    return "\n".join(lines) + "\n"


def prepare(
    project: Path,
    brief_path: Path,
    criteria: List[str],
    approved_actions: List[str],
    morning_checks: List[str],
    stop_time: str,
    model: Optional[str],
    now: Optional[float] = None,
) -> Dict[str, str]:
    project = Path(project).resolve()
    brief_path = Path(brief_path).resolve()
    if not STRICT_TIME_RE.match(stop_time or ""):
        raise PrepareError(f"stop_time must be HH:MM (24-hour), got '{stop_time}'")
    if not brief_path.is_file():
        raise PrepareError(f"Brief not found: {brief_path}")
    needs_init = check_project_dir(project)
    goal = build_goal_condition(criteria)
    rules = render_rules(RULES_TEMPLATE.read_text(encoding="utf-8"), approved_actions)
    started = time.time() if now is None else now
    started_dt = dt.datetime.fromtimestamp(started)

    if needs_init:
        _git_checked(project, "init", "-q", "-b", "main")
    target_brief = project / "BRIEF.md"
    if brief_path != target_brief.resolve():
        shutil.copyfile(brief_path, target_brief)

    claude_md = project / "CLAUDE.md"
    existing = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
    claude_md.write_text(upsert_section(existing, rules), encoding="utf-8")

    journal = project / "JOURNAL.md"
    if journal.exists():
        with journal.open("a", encoding="utf-8") as handle:
            handle.write(f"- {started_dt:%H:%M} [milestone] Unattended run restarted; stop time {stop_time}.\n")
    else:
        journal.write_text(journal_header(project.name, started_dt, stop_time, morning_checks), encoding="utf-8")

    overnight_dir = project / ".overnight"
    overnight_dir.mkdir(exist_ok=True)
    goal_file = overnight_dir / "goal.txt"
    goal_file.write_text(goal + "\n", encoding="utf-8")
    config_file = overnight_dir / "config.json"
    config = {
        "brief_source": str(brief_path),
        "stop_time": stop_time,
        "model": model,
        "started_at": started_dt.isoformat(timespec="seconds"),
        "started_at_epoch": started,
        "max_relaunches": MAX_RELAUNCHES,
        "morning_checks": morning_checks,
    }
    config_file.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    ensure_gitignore(project / ".gitignore", GITIGNORE_ENTRIES)

    _git_checked(project, "add", "-A")
    _git_checked(project, "commit", "-q", "-m", "overnight: prepare unattended run")
    return {
        "goal_file": str(goal_file),
        "config_file": str(config_file),
        "commit": _git_checked(project, "rev-parse", "HEAD"),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="overnight_prepare")
    parser.add_argument("--project", required=True)
    parser.add_argument("--input", required=True, help="JSON: brief, criteria, approved_actions, morning_checks, stop_time, model")
    args = parser.parse_args(argv)
    try:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = prepare(
            project=Path(args.project),
            brief_path=Path(data["brief"]),
            criteria=list(data["criteria"]),
            approved_actions=list(data.get("approved_actions", [])),
            morning_checks=list(data.get("morning_checks", [])),
            stop_time=data["stop_time"],
            model=data.get("model"),
        )
    except (PrepareError, KeyError, ValueError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    print(json.dumps({"ok": True, **result}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add skills/start/references/unattended-rules.md scripts/overnight_prepare.py tests/test_prepare.py
git commit -m "feat: prepare projects for unattended runs and build the goal condition

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018Hi54vjRdkSEgdDuq3QrTL"
```

---

### Task 4: Watchdog decision loop

**Files:**
- Create: `scripts/overnight_watchdog.py` (core: math, transcript reading, commands, `Watchdog` loop)
- Test: `tests/test_watchdog_rules.py`

**Interfaces:**
- Consumes: the `.overnight/config.json` keys and `.overnight/goal.txt` from Task 3.
- Produces: in `overnight_watchdog`:
  - `Settings` dataclass with fields `poll_seconds=15.0`, `fast_crash_seconds=60.0`, `fast_crash_limit=3`, `relaunch_delay_seconds=10.0`, `wrapup_timeout_seconds=900.0`, `limit_fallback_seconds=1800.0`, `limit_margin_seconds=120.0`, `kill_grace_seconds=30.0`, `unproductive_resume_limit=2`
  - `SessionOutcome` dataclass `(session_id: Optional[str], met: bool, reason: Optional[str], text: str)`
  - `compute_deadline(stop_time: str, started_at: float) -> float`
  - `usage_limit_wake(text: str, now: float, settings: Settings) -> Optional[float]`
  - `claude_config_dir() -> Path`, `find_transcript(session_id: str, config_dir: Path) -> Optional[Path]`, `last_goal_status(transcript: Path) -> Tuple[bool, Optional[str]]`
  - `interpret_session(stdout: str, stderr: str, config_dir: Path) -> SessionOutcome`
  - `goal_command(claude_bin: str, goal: str, model: Optional[str], resume_id: Optional[str]) -> List[str]`
  - `wrapup_command(claude_bin: str, reason: str, model: Optional[str]) -> List[str]`
  - `git_head(project: Path) -> str`
  - `session_name(project: Path) -> str`
  - `Runner` type: `(cmd, cwd, log_prefix, poll_seconds, should_stop, timeout, kill_grace) -> Tuple[int, str, str, bool]`
  - `Watchdog(project, claude_bin="claude", settings=None, runner=None, clock=time.time, sleeper=time.sleep, interpreter=None, head=None)` with `run() -> int` (0 done/stopped, 1 failed) and `stop_reason() -> Optional[str]`
  - `.overnight/state.json` keys: `status`, `started_at_epoch`, `deadline_epoch`, `relaunches`, `consecutive_fast_crashes`, `unproductive_resumes`, `last_session_id`, `next_resume_id`, `sessions` (list of `{n, session_id, exit_code, duration_s, met, reason, made_commit, resumed}`), `last_verdict` (`{met, reason}`), `end_reason`, `ended_at_epoch`

- [ ] **Step 1: Write the failing tests**

`tests/test_watchdog_rules.py`:

```python
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT  # noqa: F401  (puts scripts/ on sys.path)

import overnight_watchdog as ow

START = dt.datetime(2026, 9, 17, 22, 0).timestamp()


class FakeClock:
    def __init__(self, t):
        self.t = t
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


class FakeRunner:
    """Plays scripted sessions. Each step: session_id, duration, met, reason, commit, killed, text."""

    def __init__(self, clock, steps, heads):
        self.clock = clock
        self.steps = list(steps)
        self.heads = heads
        self.calls = []
        self.wrapups = []
        self.outcomes = {}

    def __call__(self, cmd, cwd, log_prefix, poll, should_stop, timeout, grace):
        prompt = cmd[cmd.index("-p") + 1]
        if not prompt.startswith("/goal "):
            self.wrapups.append(cmd)
            return 0, "{}", "", False
        self.calls.append(cmd)
        step = self.steps.pop(0)
        self.clock.t += step.get("duration", 300)
        if step.get("commit"):
            self.heads["head"] = f"commit-{len(self.calls)}"
        sid = step.get("session_id", f"s{len(self.calls)}")
        self.outcomes[sid] = ow.SessionOutcome(sid, step.get("met", False), step.get("reason"), step.get("text", ""))
        return step.get("exit", 0), json.dumps({"session_id": sid}), "", step.get("killed", False)


class WatchdogTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name).resolve() / "proj"
        (self.project / ".overnight").mkdir(parents=True)
        self.write_config()
        (self.project / ".overnight" / "goal.txt").write_text("Every done-criterion is proven.\n")
        self.clock = FakeClock(START)
        self.heads = {"head": "commit-0"}

    def tearDown(self):
        self.tmp.cleanup()

    def write_config(self, **overrides):
        config = {"stop_time": "07:30", "model": "sonnet", "started_at_epoch": START, "max_relaunches": 10}
        config.update(overrides)
        (self.project / ".overnight" / "config.json").write_text(json.dumps(config))

    def make(self, steps):
        runner = FakeRunner(self.clock, steps, self.heads)
        dog = ow.Watchdog(
            self.project,
            claude_bin="claude",
            runner=runner,
            clock=self.clock,
            sleeper=self.clock.sleep,
            interpreter=lambda out, err: runner.outcomes[json.loads(out)["session_id"]],
            head=lambda project: self.heads["head"],
        )
        return dog, runner

    def state(self):
        return json.loads((self.project / ".overnight" / "state.json").read_text())


class PureFunctionTests(unittest.TestCase):
    def test_deadline_later_same_night_and_next_morning(self):
        self.assertEqual(ow.compute_deadline("23:30", START), dt.datetime(2026, 9, 17, 23, 30).timestamp())
        self.assertEqual(ow.compute_deadline("07:30", START), dt.datetime(2026, 9, 18, 7, 30).timestamp())

    def test_usage_limit_wake(self):
        settings = ow.Settings()
        self.assertIsNone(ow.usage_limit_wake("all good", START, settings))
        self.assertEqual(ow.usage_limit_wake("Claude usage limit reached.", START, settings), START + 1800)
        three_am = dt.datetime(2026, 9, 18, 3, 0).timestamp()
        self.assertEqual(ow.usage_limit_wake("Usage limit reached. Your limit resets 3am (Europe/Tirane)", START, settings), three_am + 120)
        half_past_eleven = dt.datetime(2026, 9, 17, 23, 30).timestamp()
        self.assertEqual(ow.usage_limit_wake("rate limit hit; resets at 23:30", START, settings), half_past_eleven + 120)
        noon_next = dt.datetime(2026, 9, 18, 12, 0).timestamp()
        self.assertEqual(ow.usage_limit_wake("limit reached, resets at 12pm", START, settings), noon_next + 120)

    def test_goal_command_flags(self):
        self.assertEqual(
            ow.goal_command("claude", "G", None, None),
            ["claude", "-p", "/goal G", "--permission-mode", "bypassPermissions", "--settings", '{"fastMode": false}', "--output-format", "json"],
        )
        cmd = ow.goal_command("claude", "G", "sonnet", "abc")
        self.assertEqual(cmd[-4:], ["--model", "sonnet", "--resume", "abc"])

    def test_wrapup_command_has_no_goal_and_no_resume(self):
        cmd = ow.wrapup_command("claude", "stop time", "sonnet")
        prompt = cmd[cmd.index("-p") + 1]
        self.assertFalse(prompt.startswith("/goal"))
        self.assertIn("reason: stop time", prompt)
        self.assertNotIn("--resume", cmd)
        self.assertIn('{"fastMode": false}', cmd)

    def test_session_name_is_sanitized(self):
        self.assertEqual(ow.session_name(Path("/tmp/agna.skills v2")), "overnight-agna-skills-v2")


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.tmp.name)
        (self.config_dir / "projects" / "p").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write_transcript(self, sid, entries):
        path = self.config_dir / "projects" / "p" / f"{sid}.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in entries) + "not json\n")
        return path

    def test_last_goal_status_wins(self):
        path = self.write_transcript("s1", [
            {"type": "attachment", "attachment": {"type": "goal_status", "met": False, "sentinel": True}},
            {"type": "user", "message": {}},
            {"type": "attachment", "attachment": {"type": "goal_status", "met": True, "reason": "evidence shown"}},
        ])
        self.assertEqual(ow.last_goal_status(path), (True, "evidence shown"))

    def test_no_goal_status(self):
        path = self.write_transcript("s2", [{"type": "user"}])
        self.assertEqual(ow.last_goal_status(path), (False, None))

    def test_interpret_session_reads_transcript(self):
        self.write_transcript("s3", [{"type": "attachment", "attachment": {"type": "goal_status", "met": True, "reason": "ok"}}])
        outcome = ow.interpret_session(json.dumps({"session_id": "s3", "result": "done"}), "warn", self.config_dir)
        self.assertEqual((outcome.session_id, outcome.met, outcome.reason), ("s3", True, "ok"))
        self.assertIn("done", outcome.text)
        self.assertIn("warn", outcome.text)

    def test_interpret_session_handles_garbage(self):
        outcome = ow.interpret_session("Traceback: boom", "", self.config_dir)
        self.assertEqual((outcome.session_id, outcome.met), (None, False))
        self.assertIn("boom", outcome.text)


class LoopTests(WatchdogTestCase):
    def test_met_on_first_session(self):
        dog, runner = self.make([{"met": True}])
        self.assertEqual(dog.run(), 0)
        self.assertEqual(self.state()["status"], "done")
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.wrapups, [])

    def test_resumes_previous_session_until_met(self):
        dog, runner = self.make([{"commit": True}, {"commit": True}, {"met": True}])
        self.assertEqual(dog.run(), 0)
        self.assertNotIn("--resume", runner.calls[0])
        self.assertEqual(runner.calls[1][-2:], ["--resume", "s1"])
        self.assertEqual(runner.calls[2][-2:], ["--resume", "s2"])
        self.assertEqual(self.state()["relaunches"], 2)

    def test_three_fast_crashes_fail_the_run(self):
        dog, runner = self.make([{"duration": 10}, {"duration": 10}, {"duration": 10}])
        self.assertEqual(dog.run(), 1)
        self.assertEqual(self.state()["status"], "failed")
        self.assertEqual(len(runner.calls), 3)
        self.assertEqual(len(runner.wrapups), 1)

    def test_two_unproductive_resumes_switch_to_a_fresh_session(self):
        dog, runner = self.make([{}, {}, {}, {"met": True}])
        self.assertEqual(dog.run(), 0)
        self.assertNotIn("--resume", runner.calls[0])
        self.assertIn("--resume", runner.calls[1])
        self.assertIn("--resume", runner.calls[2])
        self.assertNotIn("--resume", runner.calls[3])

    def test_relaunch_cap(self):
        self.write_config(max_relaunches=2)
        dog, runner = self.make([{"commit": True}, {"commit": True}, {"commit": True}])
        self.assertEqual(dog.run(), 1)
        self.assertEqual(self.state()["end_reason"], "relaunch cap reached")
        self.assertEqual(len(runner.calls), 3)
        self.assertEqual(len(runner.wrapups), 1)

    def test_usage_limit_waits_and_does_not_count_as_crash(self):
        dog, runner = self.make([{"duration": 5, "text": "Claude usage limit reached."}, {"met": True}])
        self.assertEqual(dog.run(), 0)
        self.assertGreaterEqual(sum(self.clock.sleeps), 1800)
        self.assertEqual(self.state()["consecutive_fast_crashes"], 0)
        self.assertEqual(runner.calls[1][-2:], ["--resume", "s1"])

    def test_stop_time_ends_run_with_wrapup(self):
        self.clock.t = dt.datetime(2026, 9, 18, 7, 29).timestamp()
        dog, runner = self.make([{"duration": 120, "killed": True}])
        self.assertEqual(dog.run(), 0)
        self.assertEqual(self.state()["status"], "stopped")
        self.assertEqual(self.state()["end_reason"], "stop time")
        self.assertEqual(len(runner.wrapups), 1)

    def test_stop_file_before_start(self):
        (self.project / ".overnight" / "STOP").write_text("")
        dog, runner = self.make([])
        self.assertEqual(dog.run(), 0)
        self.assertEqual(runner.calls, [])
        self.assertEqual(len(runner.wrapups), 1)
        self.assertEqual(self.state()["end_reason"], "stop requested")

    def test_state_records_verdicts(self):
        dog, runner = self.make([{"commit": True, "reason": "tests not shown"}, {"met": True, "reason": "all proven"}])
        dog.run()
        state = self.state()
        self.assertEqual(state["last_verdict"], {"met": True, "reason": "all proven"})
        self.assertEqual([s["reason"] for s in state["sessions"]], ["tests not shown", "all proven"])
        self.assertTrue(state["sessions"][0]["made_commit"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL: `ModuleNotFoundError: No module named 'overnight_watchdog'`

- [ ] **Step 3: Implement the watchdog core**

`scripts/overnight_watchdog.py`:

```python
#!/usr/bin/env python3
"""overnight watchdog: keeps a built-in /goal session alive until the goal is met,
the stop time arrives, or the run fails."""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

FAST_MODE_OFF = '{"fastMode": false}'
LIMIT_RE = re.compile(r"(usage|rate)[ -]limit|limit (reached|resets)|hit your limit", re.IGNORECASE)
RESET_RE = re.compile(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.IGNORECASE)
WRAPUP_PROMPT = (
    "The unattended run has ended (reason: {reason}). Do not start new work. Rerun the checks for "
    "each numbered criterion in .overnight/goal.txt, update .overnight/evidence.md with the real "
    "current results, append a final JOURNAL.md entry listing what is done, what is not, and every "
    "needs-human item, then commit."
)

Runner = Callable[[List[str], Path, Path, float, Callable[[], bool], Optional[float], float], Tuple[int, str, str, bool]]


@dataclass
class Settings:
    poll_seconds: float = 15.0
    fast_crash_seconds: float = 60.0
    fast_crash_limit: int = 3
    relaunch_delay_seconds: float = 10.0
    wrapup_timeout_seconds: float = 900.0
    limit_fallback_seconds: float = 1800.0
    limit_margin_seconds: float = 120.0
    kill_grace_seconds: float = 30.0
    unproductive_resume_limit: int = 2


@dataclass
class SessionOutcome:
    session_id: Optional[str]
    met: bool
    reason: Optional[str]
    text: str


def compute_deadline(stop_time: str, started_at: float) -> float:
    hour, minute = (int(part) for part in stop_time.split(":"))
    start = dt.datetime.fromtimestamp(started_at)
    target = start.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= start:
        target += dt.timedelta(days=1)
    return target.timestamp()


def usage_limit_wake(text: str, now: float, settings: Settings) -> Optional[float]:
    if not LIMIT_RE.search(text):
        return None
    match = RESET_RE.search(text)
    if not match:
        return now + settings.limit_fallback_seconds
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return now + settings.limit_fallback_seconds
    base = dt.datetime.fromtimestamp(now)
    target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= base:
        target += dt.timedelta(days=1)
    return target.timestamp() + settings.limit_margin_seconds


def claude_config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))


def find_transcript(session_id: str, config_dir: Path) -> Optional[Path]:
    matches = glob.glob(str(config_dir / "projects" / "*" / f"{session_id}.jsonl"))
    return Path(matches[0]) if matches else None


def last_goal_status(transcript: Path) -> Tuple[bool, Optional[str]]:
    met, reason = False, None
    with transcript.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            attachment = entry.get("attachment") or {}
            if attachment.get("type") == "goal_status":
                met = bool(attachment.get("met"))
                reason = attachment.get("reason")
    return met, reason


def interpret_session(stdout: str, stderr: str, config_dir: Path) -> SessionOutcome:
    session_id: Optional[str] = None
    result_text = stdout
    try:
        data = json.loads(stdout) if stdout.strip() else {}
        if isinstance(data, dict):
            session_id = data.get("session_id")
            result_text = str(data.get("result") or "")
    except ValueError:
        pass
    met, reason = False, None
    if session_id:
        transcript = find_transcript(session_id, config_dir)
        if transcript is not None:
            met, reason = last_goal_status(transcript)
    return SessionOutcome(session_id, met, reason, f"{result_text}\n{stderr}")


def _base_flags(model: Optional[str]) -> List[str]:
    flags = ["--permission-mode", "bypassPermissions", "--settings", FAST_MODE_OFF, "--output-format", "json"]
    if model:
        flags += ["--model", model]
    return flags


def goal_command(claude_bin: str, goal: str, model: Optional[str], resume_id: Optional[str]) -> List[str]:
    cmd = [claude_bin, "-p", f"/goal {goal}"] + _base_flags(model)
    if resume_id:
        cmd += ["--resume", resume_id]
    return cmd


def wrapup_command(claude_bin: str, reason: str, model: Optional[str]) -> List[str]:
    return [claude_bin, "-p", WRAPUP_PROMPT.format(reason=reason)] + _base_flags(model)


def git_head(project: Path) -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(project), capture_output=True, text=True)
    return result.stdout.strip()


def session_name(project: Path) -> str:
    return "overnight-" + re.sub(r"[^A-Za-z0-9_-]", "-", Path(project).name)


class Watchdog:
    def __init__(
        self,
        project: Path,
        claude_bin: str = "claude",
        settings: Optional[Settings] = None,
        runner: Optional[Runner] = None,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
        interpreter: Optional[Callable[[str, str], SessionOutcome]] = None,
        head: Optional[Callable[[Path], str]] = None,
    ):
        self.project = Path(project).resolve()
        self.dir = self.project / ".overnight"
        self.logs = self.dir / "logs"
        self.config = json.loads((self.dir / "config.json").read_text(encoding="utf-8"))
        self.goal = (self.dir / "goal.txt").read_text(encoding="utf-8").strip()
        self.claude_bin = claude_bin
        self.settings = settings or Settings()
        self.runner = runner or run_process
        self.clock = clock
        self.sleeper = sleeper
        self.interpreter = interpreter or (lambda out, err: interpret_session(out, err, claude_config_dir()))
        self.head = head or git_head
        started = float(self.config.get("started_at_epoch") or self.clock())
        self.deadline = compute_deadline(self.config["stop_time"], started)
        self.state: Dict = {
            "status": "running",
            "started_at_epoch": started,
            "deadline_epoch": self.deadline,
            "relaunches": 0,
            "consecutive_fast_crashes": 0,
            "unproductive_resumes": 0,
            "last_session_id": None,
            "next_resume_id": None,
            "sessions": [],
            "last_verdict": None,
            "end_reason": None,
            "ended_at_epoch": None,
        }

    def stop_reason(self) -> Optional[str]:
        if (self.dir / "STOP").exists():
            return "stop requested"
        if self.clock() >= self.deadline:
            return "stop time"
        return None

    def run(self) -> int:
        self.logs.mkdir(parents=True, exist_ok=True)
        self._save()
        number = 0
        while True:
            reason = self.stop_reason()
            if reason:
                return self._end("stopped", reason, wrapup=True, code=0)
            number += 1
            resume_id = self.state["next_resume_id"]
            cmd = goal_command(self.claude_bin, self.goal, self.config.get("model"), resume_id)
            before = self.head(self.project)
            started = self.clock()
            self._log(f"session {number} starting (resume={resume_id})")
            exit_code, stdout, stderr, killed = self.runner(
                cmd,
                self.project,
                self.logs / f"session-{number}",
                self.settings.poll_seconds,
                lambda: self.stop_reason() is not None,
                None,
                self.settings.kill_grace_seconds,
            )
            duration = self.clock() - started
            outcome = self.interpreter(stdout, stderr)
            made_commit = self.head(self.project) != before
            self._record(number, outcome, exit_code, duration, made_commit, resume_id)
            self._log(f"session {number} ended: exit={exit_code} {duration:.0f}s met={outcome.met} commit={made_commit}")

            if outcome.met:
                return self._end("done", "goal met", wrapup=False, code=0)
            reason = self.stop_reason()
            if killed or reason:
                return self._end("stopped", reason or "stop requested", wrapup=True, code=0)

            wake = usage_limit_wake(outcome.text, self.clock(), self.settings)
            if wake is not None:
                self._log(f"usage limit: waiting until {dt.datetime.fromtimestamp(min(wake, self.deadline)):%H:%M}")
                if outcome.session_id:
                    self.state["next_resume_id"] = outcome.session_id
                self._save()
                self._sleep_until(min(wake, self.deadline))
                continue

            if duration < self.settings.fast_crash_seconds:
                self.state["consecutive_fast_crashes"] += 1
            else:
                self.state["consecutive_fast_crashes"] = 0
            if self.state["consecutive_fast_crashes"] >= self.settings.fast_crash_limit:
                return self._end("failed", "sessions keep ending within a minute", wrapup=True, code=1)

            self.state["relaunches"] += 1
            if self.state["relaunches"] > int(self.config.get("max_relaunches", 10)):
                return self._end("failed", "relaunch cap reached", wrapup=True, code=1)

            if made_commit:
                self.state["unproductive_resumes"] = 0
            elif resume_id:
                self.state["unproductive_resumes"] += 1
            if self.state["unproductive_resumes"] >= self.settings.unproductive_resume_limit:
                self.state["next_resume_id"] = None
                self.state["unproductive_resumes"] = 0
            else:
                self.state["next_resume_id"] = outcome.session_id or self.state["last_session_id"]
            self._save()
            self.sleeper(self.settings.relaunch_delay_seconds)

    def _sleep_until(self, wake: float) -> None:
        while self.clock() < wake and self.stop_reason() is None:
            self.sleeper(min(self.settings.poll_seconds, max(wake - self.clock(), 0.0)))

    def _record(self, number: int, outcome: SessionOutcome, exit_code: int, duration: float, made_commit: bool, resume_id: Optional[str]) -> None:
        if outcome.session_id:
            self.state["last_session_id"] = outcome.session_id
        self.state["last_verdict"] = {"met": outcome.met, "reason": outcome.reason}
        self.state["sessions"].append({
            "n": number,
            "session_id": outcome.session_id,
            "exit_code": exit_code,
            "duration_s": round(duration, 1),
            "met": outcome.met,
            "reason": outcome.reason,
            "made_commit": made_commit,
            "resumed": bool(resume_id),
        })
        self._save()

    def _end(self, status: str, reason: str, wrapup: bool, code: int) -> int:
        self._log(f"run {status}: {reason}")
        if wrapup:
            self._log("wrap-up session starting")
            self.runner(
                wrapup_command(self.claude_bin, reason, self.config.get("model")),
                self.project,
                self.logs / "wrapup",
                self.settings.poll_seconds,
                lambda: False,
                self.settings.wrapup_timeout_seconds,
                self.settings.kill_grace_seconds,
            )
        self.state.update({"status": status, "end_reason": reason, "ended_at_epoch": self.clock()})
        self._save()
        return code

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / "state.json.tmp"
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        tmp.replace(self.dir / "state.json")

    def _log(self, message: str) -> None:
        line = f"{dt.datetime.fromtimestamp(self.clock()):%Y-%m-%d %H:%M:%S} {message}"
        print(line, flush=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        with (self.logs / "watchdog.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def run_process(cmd, cwd, log_prefix, poll_seconds, should_stop, timeout, kill_grace):
    raise NotImplementedError("run_process is implemented in Task 5")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: all tests PASS. None of Task 4's tests call `run_process`.

- [ ] **Step 5: Commit**

```bash
git add scripts/overnight_watchdog.py tests/test_watchdog_rules.py
git commit -m "feat: watchdog decision loop for built-in /goal sessions

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018Hi54vjRdkSEgdDuq3QrTL"
```

---

### Task 5: Subprocess runner, CLI (`run` / `launch` / `status`), and fake-claude tests

**Files:**
- Modify: `scripts/overnight_watchdog.py` (replace the `run_process` stub; add `status_report`, `launch`, `main`)
- Create: `tests/bin/claude` (executable)
- Test: `tests/test_watchdog_process.py`

**Interfaces:**
- Consumes: everything Task 4 produced; `helpers.FAKE_CLAUDE`, `helpers.GIT_ENV`, `helpers.git`, `helpers.SCRIPTS`.
- Produces:
  - `run_process(cmd, cwd, log_prefix, poll_seconds, should_stop, timeout, kill_grace) -> Tuple[int, str, str, bool]`, which writes `<log_prefix>.json` and `<log_prefix>.stderr`
  - `status_report(project: Path) -> str`
  - `launch(project: Path, claude_bin: str, forward_env: List[str]) -> str` (returns the tmux session name)
  - CLI:
    - `run --project DIR [--claude-bin PATH] [--poll S] [--relaunch-delay S] [--fast-crash-seconds S] [--kill-grace S] [--wrapup-timeout S] [--limit-fallback-seconds S]`
    - `launch --project DIR [--claude-bin PATH]`, which forwards `PATH`, `CLAUDE_CONFIG_DIR`, and every variable named in `OVERNIGHT_FORWARD_ENV` (comma-separated) into tmux
    - `status --project DIR`

- [ ] **Step 1: Create the fake claude**

`tests/bin/claude` (then `chmod +x tests/bin/claude`):

```python
#!/usr/bin/env python3
"""Fake `claude` for overnight tests.

Goal sessions (prompt starts with "/goal ") consume steps from the JSON list in
$FAKE_CLAUDE_SCENARIO. Other prompts (wrap-up) exit 0 at once. Every invocation's
argv is appended to $FAKE_CLAUDE_STATE/calls.jsonl.
Step keys: sleep, exit, met (true/false/null), reason, result, stderr, commit, json.
"""
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path


def main() -> None:
    signal.signal(signal.SIGINT, lambda *_: sys.exit(130))
    state = Path(os.environ["FAKE_CLAUDE_STATE"])
    state.mkdir(parents=True, exist_ok=True)
    with (state / "calls.jsonl").open("a") as handle:
        handle.write(json.dumps(sys.argv[1:]) + "\n")
    prompt = sys.argv[sys.argv.index("-p") + 1] if "-p" in sys.argv else ""
    if not prompt.startswith("/goal "):
        print(json.dumps({"type": "result", "session_id": "wrapup", "result": "wrap-up done", "is_error": False}))
        sys.exit(0)

    counter = state / "goal_count"
    index = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(index + 1))
    steps = json.loads(Path(os.environ["FAKE_CLAUDE_SCENARIO"]).read_text())
    step = steps[min(index, len(steps) - 1)]

    time.sleep(step.get("sleep", 0))
    session_id = step.get("session_id") or f"fake-{uuid.uuid4().hex[:8]}"
    if step.get("commit"):
        Path(f"work-{index}.txt").write_text("work\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", f"work {index}"], check=True)
    if step.get("met") is not None:
        folder = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / "fake"
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / f"{session_id}.jsonl").open("w") as handle:
            handle.write(json.dumps({"type": "attachment", "attachment": {"type": "goal_status", "met": False, "sentinel": True}}) + "\n")
            handle.write(json.dumps({"type": "attachment", "attachment": {"type": "goal_status", "met": step["met"], "reason": step.get("reason", "fake verdict")}}) + "\n")
    if step.get("json", True):
        print(json.dumps({"type": "result", "session_id": session_id, "result": step.get("result", "ok"), "is_error": step.get("exit", 0) != 0}))
    sys.stderr.write(step.get("stderr", ""))
    sys.exit(step.get("exit", 0))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the failing tests**

`tests/test_watchdog_process.py`:

```python
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from helpers import FAKE_CLAUDE, GIT_ENV, SCRIPTS, git

import overnight_watchdog as ow

WATCHDOG = SCRIPTS / "overnight_watchdog.py"
FAST_FLAGS = ["--poll", "0.05", "--relaunch-delay", "0", "--fast-crash-seconds", "0", "--kill-grace", "2", "--wrapup-timeout", "10"]


class ProcessTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.project = base / "proj"
        self.project.mkdir()
        git(self.project, "init", "-q", "-b", "main")
        (self.project / "README.md").write_text("# proj\n")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", "init")
        overnight = self.project / ".overnight"
        overnight.mkdir()
        (overnight / "goal.txt").write_text("Every done-criterion is proven.\n")
        (overnight / "config.json").write_text(json.dumps({
            "stop_time": "23:59" if time.localtime().tm_hour < 23 else "00:30",
            "model": "sonnet",
            "started_at_epoch": time.time(),
            "max_relaunches": 10,
        }))
        self.state_dir = base / "fake-state"
        self.config_dir = base / "claude-config"
        self.scenario = base / "scenario.json"
        self.env = {
            **os.environ,
            **GIT_ENV,
            "FAKE_CLAUDE_STATE": str(self.state_dir),
            "FAKE_CLAUDE_SCENARIO": str(self.scenario),
            "CLAUDE_CONFIG_DIR": str(self.config_dir),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def set_scenario(self, steps):
        self.scenario.write_text(json.dumps(steps))

    def calls(self):
        path = self.state_dir / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def state(self):
        return json.loads((self.project / ".overnight" / "state.json").read_text())

    def watchdog(self, *args, **kwargs):
        return subprocess.run([sys.executable, str(WATCHDOG), *args], env=self.env, capture_output=True, text=True, timeout=60, **kwargs)


class RunCommandTests(ProcessTestCase):
    def test_met_on_first_run(self):
        self.set_scenario([{"met": True, "reason": "all proven"}])
        result = self.watchdog("run", "--project", str(self.project), "--claude-bin", str(FAKE_CLAUDE), *FAST_FLAGS)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state()["status"], "done")
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ["-p", "/goal Every done-criterion is proven."])
        self.assertIn('{"fastMode": false}', calls[0])
        self.assertTrue((self.project / ".overnight" / "logs" / "session-1.json").is_file())

    def test_resume_then_met(self):
        self.set_scenario([{"met": False, "session_id": "first", "commit": True}, {"met": True}])
        result = self.watchdog("run", "--project", str(self.project), "--claude-bin", str(FAKE_CLAUDE), *FAST_FLAGS)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertEqual(calls[1][-2:], ["--resume", "first"])

    def test_stop_file_interrupts_a_running_session(self):
        self.set_scenario([{"sleep": 30, "met": False}])
        proc = subprocess.Popen(
            [sys.executable, str(WATCHDOG), "run", "--project", str(self.project), "--claude-bin", str(FAKE_CLAUDE), *FAST_FLAGS],
            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        deadline = time.time() + 10
        while not self.calls() and time.time() < deadline:
            time.sleep(0.05)
        (self.project / ".overnight" / "STOP").write_text("")
        out, err = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, out + err)
        self.assertEqual(self.state()["status"], "stopped")
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertFalse(calls[1][1].startswith("/goal"))


class StatusTests(ProcessTestCase):
    def test_status_after_done_run(self):
        self.set_scenario([{"met": True, "reason": "all proven"}])
        self.watchdog("run", "--project", str(self.project), "--claude-bin", str(FAKE_CLAUDE), *FAST_FLAGS)
        (self.project / "JOURNAL.md").write_text("# Journal\n- 01:00 [milestone] done\n")
        result = self.watchdog("status", "--project", str(self.project))
        self.assertEqual(result.returncode, 0)
        self.assertIn("status: done", result.stdout)
        self.assertIn("last goal check: met — all proven", result.stdout)
        self.assertIn("[milestone] done", result.stdout)

    def test_status_without_run(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        result = self.watchdog("status", "--project", str(empty))
        self.assertEqual(result.returncode, 1)
        self.assertIn("No overnight run", result.stdout)


@unittest.skipUnless(shutil.which("tmux"), "tmux not installed")
class LaunchTests(ProcessTestCase):
    def test_launch_runs_watchdog_in_tmux(self):
        self.set_scenario([{"met": True}])
        self.env["OVERNIGHT_FORWARD_ENV"] = "FAKE_CLAUDE_STATE,FAKE_CLAUDE_SCENARIO,GIT_AUTHOR_NAME,GIT_AUTHOR_EMAIL,GIT_COMMITTER_NAME,GIT_COMMITTER_EMAIL"
        name = ow.session_name(self.project)
        try:
            result = self.watchdog("launch", "--project", str(self.project), "--claude-bin", str(FAKE_CLAUDE))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(name, result.stdout)
            deadline = time.time() + 60
            while time.time() < deadline:
                state_file = self.project / ".overnight" / "state.json"
                if state_file.exists() and json.loads(state_file.read_text())["status"] == "done":
                    break
                time.sleep(0.5)
            self.assertEqual(self.state()["status"], "done")
            again = self.watchdog("launch", "--project", str(self.project), "--claude-bin", str(FAKE_CLAUDE))
            self.assertEqual(again.returncode, 1)
            self.assertIn("already exists", again.stdout + again.stderr)
        finally:
            subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)


if __name__ == "__main__":
    unittest.main()
```

Note: `launch` uses the watchdog's default poll (15 s), so `test_launch_runs_watchdog_in_tmux` can take up to about 20 seconds.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests -v`
Expected: the new process tests FAIL or ERROR, because the watchdog script has no command-line entry point yet (no `state.json` is written, and `status` prints nothing). The Task 4 tests still pass.

- [ ] **Step 4: Implement the runner, status, launch, and CLI**

In `scripts/overnight_watchdog.py`, add `import argparse`, `import shlex`, `import shutil`, and `import signal` to the imports (keeping them alphabetical), then replace the `run_process` stub at the bottom of the file with:

```python
def _terminate(proc: subprocess.Popen, kill_grace: float) -> None:
    for sig, wait_seconds in ((signal.SIGINT, kill_grace), (signal.SIGTERM, 10.0)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=wait_seconds)
            return
        except subprocess.TimeoutExpired:
            continue
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_process(cmd, cwd, log_prefix, poll_seconds, should_stop, timeout, kill_grace):
    log_prefix = Path(log_prefix)
    log_prefix.parent.mkdir(parents=True, exist_ok=True)
    out_path = log_prefix.parent / f"{log_prefix.name}.json"
    err_path = log_prefix.parent / f"{log_prefix.name}.stderr"
    killed = False
    with out_path.open("w", encoding="utf-8") as out, err_path.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=out, stderr=err, start_new_session=True)
        started = time.time()
        while proc.poll() is None:
            if should_stop() or (timeout is not None and time.time() - started > timeout):
                killed = True
                _terminate(proc, kill_grace)
                break
            time.sleep(poll_seconds)
        exit_code = proc.wait()
    return exit_code, out_path.read_text(encoding="utf-8"), err_path.read_text(encoding="utf-8"), killed


def _tmux_alive(name: str) -> bool:
    if shutil.which("tmux") is None:
        return False
    return subprocess.run(["tmux", "has-session", "-t", name], capture_output=True).returncode == 0


def status_report(project: Path) -> str:
    project = Path(project).resolve()
    overnight = project / ".overnight"
    config_file = overnight / "config.json"
    if not config_file.exists():
        return f"No overnight run in {project}."
    config = json.loads(config_file.read_text(encoding="utf-8"))
    state_file = overnight / "state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    name = session_name(project)
    verdict = state.get("last_verdict")
    if verdict is None:
        verdict_text = "none yet"
    else:
        verdict_text = ("met" if verdict.get("met") else "not met") + " — " + (verdict.get("reason") or "no reason given")[:300]
    commits = subprocess.run(
        ["git", "rev-list", "--count", "HEAD", f"--since={config.get('started_at', '')}"],
        cwd=str(project), capture_output=True, text=True,
    ).stdout.strip() or "0"
    lines = [
        f"overnight run: {project.name}",
        f"status: {state.get('status', 'not started')}",
        f"started: {config.get('started_at', '?')}  stop time: {config.get('stop_time', '?')}",
        f"tmux session: {name} ({'alive' if _tmux_alive(name) else 'not running'})",
        f"sessions: {len(state.get('sessions', []))}  relaunches: {state.get('relaunches', 0)}",
        f"last goal check: {verdict_text}",
        f"commits since start: {commits}",
    ]
    if state.get("end_reason"):
        lines.append(f"end reason: {state['end_reason']}")
    journal = project / "JOURNAL.md"
    if journal.exists():
        tail = journal.read_text(encoding="utf-8").splitlines()[-15:]
        lines += ["", "JOURNAL.md (last 15 lines):"] + tail
    return "\n".join(lines)


class LaunchError(Exception):
    pass


def launch(project: Path, claude_bin: str, forward_env: List[str]) -> str:
    project = Path(project).resolve()
    if shutil.which("tmux") is None:
        raise LaunchError("tmux is not installed")
    if not (project / ".overnight" / "config.json").exists():
        raise LaunchError(f"No overnight run prepared in {project}; run /overnight:start first")
    name = session_name(project)
    if _tmux_alive(name):
        raise LaunchError(f"tmux session {name} already exists")
    script = Path(__file__).resolve()
    inner = (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} run "
        f"--project {shlex.quote(str(project))} --claude-bin {shlex.quote(claude_bin)}; "
        "echo '[overnight] watchdog exited'; exec \"${SHELL:-/bin/sh}\""
    )
    cmd = ["tmux", "new-session", "-d", "-s", name, "-c", str(project)]
    for var in forward_env:
        if var in os.environ:
            cmd += ["-e", f"{var}={os.environ[var]}"]
    cmd.append(inner)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise LaunchError(f"tmux failed: {result.stderr.strip()}")
    return name


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="overnight_watchdog")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="run the watchdog loop in the foreground")
    run_parser.add_argument("--project", required=True)
    run_parser.add_argument("--claude-bin", default="claude")
    run_parser.add_argument("--poll", type=float, default=Settings.poll_seconds)
    run_parser.add_argument("--relaunch-delay", type=float, default=Settings.relaunch_delay_seconds)
    run_parser.add_argument("--fast-crash-seconds", type=float, default=Settings.fast_crash_seconds)
    run_parser.add_argument("--kill-grace", type=float, default=Settings.kill_grace_seconds)
    run_parser.add_argument("--wrapup-timeout", type=float, default=Settings.wrapup_timeout_seconds)
    run_parser.add_argument("--limit-fallback-seconds", type=float, default=Settings.limit_fallback_seconds)

    launch_parser = sub.add_parser("launch", help="start the watchdog in a detached tmux session")
    launch_parser.add_argument("--project", required=True)
    launch_parser.add_argument("--claude-bin", default="claude")

    status_parser = sub.add_parser("status", help="print the run status")
    status_parser.add_argument("--project", required=True)

    args = parser.parse_args(argv)
    if args.command == "run":
        settings = Settings(
            poll_seconds=args.poll,
            relaunch_delay_seconds=args.relaunch_delay,
            fast_crash_seconds=args.fast_crash_seconds,
            kill_grace_seconds=args.kill_grace,
            wrapup_timeout_seconds=args.wrapup_timeout,
            limit_fallback_seconds=args.limit_fallback_seconds,
        )
        return Watchdog(Path(args.project), claude_bin=args.claude_bin, settings=settings).run()
    if args.command == "launch":
        forward = ["PATH", "CLAUDE_CONFIG_DIR"] + [v for v in os.environ.get("OVERNIGHT_FORWARD_ENV", "").split(",") if v]
        try:
            name = launch(Path(args.project), args.claude_bin, forward)
        except LaunchError as error:
            print(f"error: {error}")
            return 1
        print(name)
        return 0
    report = status_report(Path(args.project))
    print(report)
    return 1 if report.startswith("No overnight run") else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the full suite to verify it passes**

Run: `python3 -m unittest discover -s tests -v`
Expected: all tests PASS (the launch test is skipped only if tmux is missing)

- [ ] **Step 6: Commit**

```bash
git add scripts/overnight_watchdog.py tests/bin/claude tests/test_watchdog_process.py
git commit -m "feat: watchdog subprocess runner, tmux launch, and status

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018Hi54vjRdkSEgdDuq3QrTL"
```

---

### Task 6: Skills and references

**Files:**
- Create: `skills/start/SKILL.md`, `skills/start/references/brief-contract.md`, `skills/start/references/goal-condition.md`
- Create: `skills/status/SKILL.md`, `skills/stop/SKILL.md`
- Test: `tests/test_skills.py`

**Interfaces:**
- Consumes: the CLIs from Tasks 2, 3, and 5 (`overnight_brief.py validate`, `overnight_prepare.py --project --input`, `overnight_watchdog.py launch|status`); `skills/start/references/unattended-rules.md` from Task 3.
- Produces: the three user-facing skills.

- [ ] **Step 1: Write the failing test**

`tests/test_skills.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL: `FileNotFoundError` for `skills/start/SKILL.md`

- [ ] **Step 3: Write `skills/start/SKILL.md`**

````markdown
---
name: start
description: Start an unattended overnight build of the current project from a brief, using Superpowers and Claude Code's built-in /goal, watched by a tmux watchdog. Use when the user runs /overnight:start with a brief path, or asks to run a Superpowers build unattended or overnight.
---

# overnight: start

Prepare the current directory for an unattended Superpowers build and launch it. You do **not** build anything yourself: the watchdog runs `claude -p "/goal …"` sessions that do the work.

**Paths.** `SCRIPTS` is `<this skill's base directory>/../../scripts`. Resolve it to an absolute path first. The project is the current working directory.

**Arguments.** `<brief-path>` (required); optional `--until HH:MM` and `--model NAME`. If the brief path is missing, ask for it and stop.

Stop at the first failing step and report the exact problem. Never edit the brief's content.

## 1. Validate the brief

Run `python3 "$SCRIPTS/overnight_brief.py" validate "<brief-path>" [--until HH:MM]`. If `ok` is false, print every item in `errors` as a bullet list, point to `references/brief-contract.md`, and stop. Keep `done_criteria`, `guardrails`, and `stop_time`.

## 2. Check prerequisites

Run all checks, then report every failure together and stop if any failed.

- **Project directory:** `git rev-parse --show-toplevel` must equal the current directory with a clean `git status --porcelain`, **or** the directory must be empty (ignoring `.DS_Store`) and not inside another repository.
- **Superpowers:** `claude plugin list` shows a `superpowers@…` entry with status enabled.
- **Tools:** `tmux -V` succeeds; `python3 --version` is 3.9 or later.
- **CLIs the brief depends on:** if the brief's constraints or guardrails mention Cloudflare, Workers, Pages, D1, R2, or wrangler, then `npx wrangler whoami` must show a logged-in account. If they mention GitHub or pushing a repository, then `gh auth status` must succeed.

## 3. Provability review and approved actions (the only interactive step)

Read `references/goal-condition.md`. For every done-criterion, decide whether an agent can prove it with command output shown in the transcript. For each one that can't, write an agent-provable proxy, and keep the original as a morning check.

From the brief's constraints and guardrails, list the outside actions it explicitly permits (for example "deploy to Cloudflare Workers", "create and push this project's GitHub repository"). Include only what the brief clearly allows.

Show one summary:
- a table of criteria with a column saying "as written" or "proxy: …";
- the approved actions;
- the stop time;
- the model (or "your default model").

Then use AskUserQuestion with the options **Launch as shown (Recommended)**, **Edit criteria or actions**, and **Cancel**. On edit, apply the user's changes and ask again. On cancel, stop without changing anything.

## 4. Prepare the project

Write a JSON file in the system temp directory:

```json
{"brief": "<absolute brief path>", "criteria": ["<final criteria, in order>"], "approved_actions": ["..."], "morning_checks": ["<originals replaced by proxies>"], "stop_time": "HH:MM", "model": "<NAME or null>"}
```

Run `python3 "$SCRIPTS/overnight_prepare.py" --project "$PWD" --input <that file>`. If `ok` is false, report `error` and stop.

## 5. Launch

Run `python3 "$SCRIPTS/overnight_watchdog.py" launch --project "$PWD"`. It prints the tmux session name, or `error: …`.

## 6. Report

Tell the user, concisely:
- the run has started, and the first minutes are Superpowers brainstorming, answered from the brief;
- watch live: `tmux attach -t <session name>` (detach with Ctrl+B then D);
- check progress: `/overnight:status`; stop early: `/overnight:stop`;
- the stop time, and that any proxied criteria are listed as morning checks at the top of `JOURNAL.md`.
````

- [ ] **Step 4: Write the references**

`skills/start/references/brief-contract.md`:

```markdown
# Brief contract

A brief is a markdown file. `overnight` needs these sections (level-2 or level-3 headings; matching ignores case and any suffix after a space plus "(" or a dash):

| Section | Accepted headings | Requirement |
|---|---|---|
| Mission | Mission | Not empty |
| Hard constraints | Hard constraints, Constraints | At least one list item |
| Must-have | Must-have, Must-haves, Must have, Requirements | At least one list item |
| Done-criteria | Done-criteria, Done criteria, Definition of done | At least one list item; each item is one checkable statement |
| Guardrails | Guardrails | At least one list item; the first `HH:MM` here is the stop time, unless `--until HH:MM` is passed |

Other sections (Users and auth, Stretch, Method, Journal) are kept as they are and read by the build like any other part of the brief.

Write done-criteria that a command can prove: "`npm test` passes", "`curl -sI https://…` returns 302 to the Access login". Criteria that need a person (receiving an email, looking at a design) are converted to provable proxies at launch and kept as morning checks.
```

`skills/start/references/goal-condition.md`:

```markdown
# Goal condition and provability

The `/goal` checker is a separate small model that reads the conversation and cannot run anything. A criterion only counts as met when the conversation shows proof: the command that was run and its real output.

## Provable (keep as written)

- Test suites: "tests pass" → proven by the test command's output.
- Files and content: "README documents usage" → proven by printing the relevant section.
- Live deployments reachable without logging in: "live URL responds" → proven by `curl -sI <url>` output.
- CLI behavior: "`tally --json` prints valid JSON" → proven by the command and its output.

## Not provable by an agent (propose a proxy, keep the original as a morning check)

| Needs a human because… | Example criterion | Provable proxy |
|---|---|---|
| An email inbox or one-time PIN | "A fresh email address can sign in with a PIN" | "A signed-out request to the live URL redirects to the Cloudflare Access login page (show the HTTP status and Location header)" |
| A real person's account or device | "Works on a phone" | "The page's HTML includes a responsive viewport meta tag and passes an automated mobile-width render check" |
| Subjective judgment | "The design looks polished" | "The pages render without console errors in a headless browser, with screenshots saved to `.overnight/screenshots/`" |

Keep proxies as close to the original intent as possible, and never weaker than a check a skeptical reviewer would accept.
```

- [ ] **Step 5: Write the status and stop skills**

`skills/status/SKILL.md`:

```markdown
---
name: status
description: Show the status of the unattended overnight run in the current project — run state, the /goal checker's latest verdict, relaunches, commits since start, and the journal tail. Use when the user runs /overnight:status or asks how the overnight build is going.
---

# overnight: status

`SCRIPTS` is `<this skill's base directory>/../../scripts`.

Run `python3 "$SCRIPTS/overnight_watchdog.py" status --project "$PWD"` and show its output as-is in a code block. Then add one or two plain sentences: whether the run is still going (tmux session alive and status `running`), finished (`done`), or needs attention (`failed`, or `running` while the tmux session is not alive). Do not start, stop, or change anything.
```

`skills/stop/SKILL.md`:

```markdown
---
name: stop
description: Ask the unattended overnight run in the current project to stop early and write its wrap-up. Use when the user runs /overnight:stop or asks to stop or cancel the overnight build.
---

# overnight: stop

`SCRIPTS` is `<this skill's base directory>/../../scripts`.

1. If `.overnight/config.json` does not exist, say there is no overnight run here and stop.
2. Create the stop file: `touch .overnight/STOP`.
3. Run `python3 "$SCRIPTS/overnight_watchdog.py" status --project "$PWD"` and show the output.
4. Tell the user that the watchdog sees the stop file within about 15 seconds, ends the working session, then runs a wrap-up session (up to 15 minutes) that updates `.overnight/evidence.md` and writes a final `JOURNAL.md` entry. To watch it: `tmux attach -t overnight-<directory name>`.
```

- [ ] **Step 6: Run the tests and Claude Code's validator**

Run: `python3 -m unittest discover -s tests -v`
Expected: all tests PASS

Run: `claude plugin validate .`
Expected: exit code 0 and no errors; three skills listed.

- [ ] **Step 7: Smoke-test `start`'s failure path through Claude Code**

Run from a new empty temporary directory, so nothing real is touched:

```bash
SMOKE=$(mktemp -d) && cd "$SMOKE" && claude --plugin-dir /Users/dim/Documents/Projects/overnight -p "/overnight:start /Users/dim/Documents/Projects/overnight/tests/fixtures/broken-brief.md" --model sonnet --output-format json | python3 -c "import json,sys; print(json.load(sys.stdin)['result'])"; ls -A "$SMOKE"
```

Expected: the printed result names both problems ("Missing section: Done-criteria" and the missing stop time), and `ls -A` prints nothing (no `.overnight`, no `CLAUDE.md`).

- [ ] **Step 8: Commit**

```bash
cd /Users/dim/Documents/Projects/overnight
git add skills tests/test_skills.py
git commit -m "feat: start, status, and stop skills

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018Hi54vjRdkSEgdDuq3QrTL"
```

---

### Task 7: End-to-end unattended build of the tally brief

This task runs a real unattended build on Sonnet (about 30–90 minutes; it spends Claude usage). Nothing in the plugin changes unless a defect is found; defects get a regression test in the relevant test file and a fix commit.

**Files:**
- Create: `docs/e2e/2026-09-13-tally-run.md` (the run record)
- Modify: only if a defect is found (the failing script plus its test file)

**Interfaces:**
- Consumes: the complete plugin (Tasks 1–6).
- Produces: a verified run record.

- [ ] **Step 1: Confirm fast-mode override behavior (cheap probe)**

Run:

```bash
PROBE=$(mktemp -d) && cd "$PROBE" && claude -p "Reply with the single word ok." --model opus --settings '{"fastMode": false}' --output-format json > probe.json; python3 -c "import json; d=json.load(open('probe.json')); print(json.dumps({k: d.get(k) for k in ('is_error','result','modelUsage','usage')}, indent=1)[:1500])"
```

Expected: `is_error` false. Record in the run record whether the output shows any speed/fast indicator (for example `usage.speed`) and its value. If no indicator appears, record "fast-mode override not observable from -p output" as an open item. It is not a blocker.

- [ ] **Step 2: Create and trust the project directory**

```bash
E2E=$(mktemp -d)/tally && mkdir -p "$E2E" && echo "$E2E" > /tmp/overnight-e2e-path
tmux new-session -d -s overnight-e2e-driver -x 180 -y 50 -c "$E2E" "claude --plugin-dir /Users/dim/Documents/Projects/overnight --model sonnet"
```

Then poll `tmux capture-pane -p -t overnight-e2e-driver` until the folder-trust dialog appears, and send `Down` then `Enter` (the default option is "No, exit"). Poll until the Claude Code prompt shows.

- [ ] **Step 3: Start the run**

Compute a stop time 3 hours from now (`date -v+3H +%H:%M` on macOS) and type into the session:

```bash
UNTIL=$(date -v+3H +%H:%M)
tmux send-keys -t overnight-e2e-driver "/overnight:start /Users/dim/Documents/Projects/overnight/tests/fixtures/tally-brief.md --until $UNTIL --model sonnet" Enter
```

Poll the pane. When the AskUserQuestion summary appears, check that:
- all 4 tally criteria are "as written" (all are provable);
- approved actions are empty or "none";
- the stop time equals `$UNTIL`.

Accept **Launch as shown** (send `Enter`). Poll until the report shows a tmux session named `overnight-tally`.

- [ ] **Step 4: Watch the run to completion**

Every 5 minutes, run `python3 /Users/dim/Documents/Projects/overnight/scripts/overnight_watchdog.py status --project "$(cat /tmp/overnight-e2e-path)"`. Continue until the status is `done`, `stopped`, or `failed`, or 120 minutes pass. If a stall appears (status `running` while the tmux session is not alive, or no new journal lines for 30 minutes), capture the evidence (`tmux capture-pane -p -t overnight-tally`, `.overnight/logs/watchdog.log`), then stop with `touch .overnight/STOP` and debug using superpowers:systematic-debugging.

- [ ] **Step 5: Verify the outcome**

In the project directory, run each check and paste its output into the run record:

```bash
P=$(cat /tmp/overnight-e2e-path) && cd "$P"
python3 /Users/dim/Documents/Projects/overnight/scripts/overnight_watchdog.py status --project "$P"   # expect "status: done" and "last goal check: met — …"
python3 -m unittest discover -s tests                                                               # expect OK
python3 tally.py README.md BRIEF.md                                                                  # expect two rows plus a total
python3 tally.py --json README.md | python3 -m json.tool                                             # expect valid JSON
test -s .overnight/evidence.md && grep -c '^' .overnight/evidence.md                                 # expect a non-empty evidence file
grep -cE '^- [0-9]{2}:[0-9]{2} \[(decision|setback|milestone|needs-human)\]' JOURNAL.md               # expect at least 5 log lines
ls docs/superpowers/specs docs/superpowers/plans                                                     # expect a spec and a plan
git log --oneline | wc -l                                                                            # expect several commits
python3 -c "import json; s=json.load(open('.overnight/state.json')); print(s['status'], s['relaunches'], [x['met'] for x in s['sessions']])"
```

Expected: every check passes. Also scan the watchdog log and the session JSON results for signs that other installed plugins derailed the session (for example refusals or tool-routing detours), and note any findings.

- [ ] **Step 6: Clean up the driver session and write the run record**

```bash
tmux kill-session -t overnight-e2e-driver; tmux kill-session -t overnight-tally 2>/dev/null
```

`docs/e2e/2026-09-13-tally-run.md` records:
- date and Claude Code version (`claude --version`);
- model;
- start time, stop time, and end status;
- number of sessions and relaunches;
- the pasted outputs from Step 5;
- the fast-mode probe result from Step 1;
- any defects found and their fix commits;
- plugin-interference observations.

- [ ] **Step 7: Commit**

```bash
cd /Users/dim/Documents/Projects/overnight
git add docs/e2e
git commit -m "docs: record end-to-end unattended tally run

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018Hi54vjRdkSEgdDuq3QrTL"
```

---

### Task 8: Publish to GitHub and install from the marketplace

**Files:**
- Modify: `README.md` only if install instructions need correcting after the real install

**Interfaces:**
- Consumes: the tested plugin.
- Produces: `dimitris-am/overnight` on GitHub, installed on this machine from its marketplace.

- [ ] **Step 1: Get Dimitris's approval (STOP until answered)**

Ask Dimitris to confirm the repository name `dimitris-am/overnight` and whether it is **private** or **public**. Do not run any `gh repo create` or `git push` before an explicit answer.

- [ ] **Step 2: Create and push**

```bash
cd /Users/dim/Documents/Projects/overnight
gh repo create dimitris-am/overnight --<private|public> --source . --push --description "Unattended Superpowers runs on Claude Code's built-in /goal"
```

Expected: the repository URL is printed; `git status -sb` shows `main...origin/main`.

- [ ] **Step 3: Install from the marketplace**

```bash
claude plugin marketplace add dimitris-am/overnight
claude plugin install overnight@overnight
claude plugin list | grep -A3 'overnight@overnight'
```

Expected: `Status: ✔ enabled`, version `0.1.0`.

- [ ] **Step 4: Re-run the failure-path smoke test through the installed plugin**

```bash
SMOKE=$(mktemp -d) && cd "$SMOKE" && claude -p "/overnight:start /Users/dim/Documents/Projects/overnight/tests/fixtures/broken-brief.md" --model sonnet --output-format json | python3 -c "import json,sys; print(json.load(sys.stdin)['result'])"; ls -A "$SMOKE"
```

Expected: both problems named; the directory stays empty.

- [ ] **Step 5: Commit any README correction**

If Step 3 needed different commands than the README shows, fix the README and commit:

```bash
git add README.md
git commit -m "docs: correct install instructions

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018Hi54vjRdkSEgdDuq3QrTL"
git push
```

---

### Task 9: Course integration (agna-prospectus)

Files under `agna-prospectus/course-materials/` are **not committed**; Dimitris commits course materials himself.

**Files:**
- Modify: `/Users/dim/Documents/Projects/agna-prospectus/course-materials/overnight/agna-skills-brief.md` (line 3 runner line; the PIN done-criterion)
- Modify: `/Users/dim/Documents/Projects/agna-prospectus/course-materials/agna-claude-code-course-deck.html` (slide 28, lines 1232–1234)
- Modify: `/Users/dim/Documents/Projects/agna-prospectus/course-materials/run-of-show.md` (section 1, item 1)

**Interfaces:**
- Consumes: the published plugin commands.
- Produces: course materials consistent with `overnight`.

- [ ] **Step 1: Update the agna-skills brief**

On stage the brief is saved one level above the new, empty `agna-skills` directory, because `/overnight:start` requires the project directory to be empty or a clean repository.

Replace this exact line:

```markdown
**Runner:** `/goal course-materials/overnight/agna-skills-brief.md` — Superpowers: brainstorm → plan → execute, until done.
```

with:

```markdown
**Runner:** `/overnight:start ../agna-skills-brief.md`, run from a new, empty `agna-skills` directory next to this brief. Superpowers: brainstorm → plan → execute, on the built-in `/goal`, until done.
```

Replace this exact done-criterion line:

```markdown
- A fresh email address can sign in with a PIN
```

with:

```markdown
- A signed-out request to the live URL redirects to the Cloudflare Access login page (show the HTTP status and Location header); a fresh email signing in with a PIN is a morning check
```

- [ ] **Step 2: Verify the brief still validates**

Run: `python3 /Users/dim/Documents/Projects/overnight/scripts/overnight_brief.py validate /Users/dim/Documents/Projects/agna-prospectus/course-materials/overnight/agna-skills-brief.md`
Expected: `"ok": true`, 6 done-criteria, `"stop_time": "07:30"`

- [ ] **Step 3: Update slide 28's Superpowers lines**

In the deck, replace these exact lines:

```html
            <span class="p">$</span> claude<br>
            <span class="p">&gt;</span> /goal course-materials/overnight/agna-skills-brief.md<br>
            <span class="c">● Goal accepted — brainstorming…</span>
```

with:

```html
            <span class="p">$</span> mkdir agna-skills &amp;&amp; cd agna-skills &amp;&amp; claude<br>
            <span class="p">&gt;</span> /overnight:start ../agna-skills-brief.md<br>
            <span class="c">● Watchdog started · /goal set · brainstorming…</span>
```

Verify: `grep -c '/overnight:start ../agna-skills-brief.md' course-materials/agna-claude-code-course-deck.html` returns `1`, and `grep -c '<section class="slide' course-materials/agna-claude-code-course-deck.html` still returns `33`.

- [ ] **Step 4: Update run-of-show section 1, item 1**

In `course-materials/run-of-show.md`, replace the first sentence of item 1:

`1. **The two runners don't exist.** \`/goal\` and \`/bmad-loop\` appear on slide 28 and in both briefs.`

with:

`1. **Runners.** Superpowers: the \`overnight\` plugin (\`/overnight:start\`) runs \`agna-skills\` on the built-in \`/goal\`. It is built and tested end to end; see its repo. BMAD: \`agna-answers\` runs the headless planning chain, then BMad Loop.`

Keep the rest of item 1 unchanged.

- [ ] **Step 5: Report without committing**

List the three changed files and each change in one line for Dimitris. Do not `git add` or `git commit` anything under `course-materials/`.

---

## Self-review

**1. Spec coverage** (spec section → task):
- §3.1 start steps 1–6 → Task 6 `start` skill, backed by Task 2 (validate), Task 3 (prepare, including nested-repo and empty-dir rules), and Task 5 (launch).
- §3.2 status → Task 5 `status_report`, plus Task 6 skill.
- §3.3 stop → Task 6 skill, plus the Task 4 STOP handling.
- §4 brief contract → Task 2, plus Task 6 reference.
- §5.1 rules → Task 3 template and `render_rules` / `upsert_section`.
- §5.2 files and gitignore → Task 3.
- §6 condition (single line) and provability → Task 3 `build_goal_condition`, plus Task 6 `goal-condition.md` and step 3.
- §7.1 flags → Task 4 `goal_command`.
- §7.2 outcome detection → Task 4 `interpret_session`.
- §7.3 every rule → Task 4 loop tests (met, resume, fast crashes, fresh-after-2, cap, usage limit, stop time, STOP).
- §7.4 wrap-up → Task 4 `wrapup_command`, plus `_end`.
- §8 packaging → Tasks 1 and 6.
- §9 tests 1–4 → Tasks 4–5 (1), Task 2 plus Task 6 step 7 (2), Task 7 (3), Task 8 (4).
- §10 course integration → Task 9.
- §11 risks: fast-mode override → Task 7 step 1; plugin interference → Task 7 step 5.

**2. Placeholder scan:** no TBD/TODO. `<private|public>` in Task 8 step 2 is resolved by the approval gate in step 1.

**3. Type consistency:**
- `SessionOutcome(session_id, met, reason, text)` is used identically in Tasks 4 and 5 and in `FakeRunner`.
- The runner signature `(cmd, cwd, log_prefix, poll_seconds, should_stop, timeout, kill_grace)` matches `run_process` and `FakeRunner.__call__`.
- The config keys `stop_time`, `model`, `started_at`, `started_at_epoch`, and `max_relaunches` match between Task 3's writer and Tasks 4–5's readers.
- The `session_name` rule matches the Global Constraints and the `stop` skill text.
