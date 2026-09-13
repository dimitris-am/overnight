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
