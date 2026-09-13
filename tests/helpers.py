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
