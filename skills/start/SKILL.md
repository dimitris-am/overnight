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

First, before any other check or change: if `.overnight/state.json` exists with `"status": "running"`, run `python3 "$SCRIPTS/overnight_watchdog.py" status --project "$PWD"`. Unless its status line says `WATCHDOG NOT RESPONDING`, stop with: "a run is already in progress here; use /overnight:status or /overnight:stop".

Then run all of these checks, report every failure together, and stop if any failed.

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
