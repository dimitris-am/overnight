---
name: stop
description: Ask the unattended overnight run in the current project to stop early and write its wrap-up. Use when the user runs /overnight:stop or asks to stop or cancel the overnight build.
---

# overnight: stop

`SCRIPTS` is `<this skill's base directory>/../../scripts`.

1. If `.overnight/config.json` does not exist, say there is no overnight run here and stop.
2. Create the stop file: `touch .overnight/STOP`.
3. Run `python3 "$SCRIPTS/overnight_watchdog.py" status --project "$PWD"` and show the output.
4. Tell the user that the watchdog sees the stop file within about 15 seconds, ends the working session, then runs a wrap-up session (up to 15 minutes) that updates `.overnight/evidence.md` and writes a final `JOURNAL.md` entry. To watch it, give `tmux attach -t <name>`, where `<name>` is the session name from the `tmux session:` line of the status output (for example `overnight-my-project`); if that line says `not running`, there is no session to watch.
