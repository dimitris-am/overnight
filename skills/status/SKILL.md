---
name: status
description: Show the status of the unattended overnight run in the current project — run state, the /goal checker's latest verdict, relaunches, commits since start, and the journal tail. Use when the user runs /overnight:status or asks how the overnight build is going.
---

# overnight: status

`SCRIPTS` is `<this skill's base directory>/../../scripts`.

Run `python3 "$SCRIPTS/overnight_watchdog.py" status --project "$PWD"` and show its output as-is in a code block. Then add one or two plain sentences: whether the run is still going (status `running` with no `WATCHDOG NOT RESPONDING` on the status line), finished (`done`, or `stopped` at the stop time or on request), or needs attention (`failed`, or a status line that says `WATCHDOG NOT RESPONDING`). Do not judge the run by the tmux session: it stays open after the watchdog finishes. Do not start, stop, or change anything.
