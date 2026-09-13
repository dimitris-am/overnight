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
