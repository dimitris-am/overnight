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
