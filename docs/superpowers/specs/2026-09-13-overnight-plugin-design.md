# overnight — Unattended Superpowers Runs on Claude Code's Built-in `/goal`: Design

**Date:** 2026-09-13 · **Status:** design approved in brainstorming; pending spec review
**Owner:** Dimitris Mitsis · **Repo:** `~/Documents/Projects/overnight` (GitHub repo not created yet — visibility decided before pushing)

## 1. Purpose and scope

`overnight` is a Claude Code plugin that runs a Superpowers project build **fully unattended** — typically overnight — from a written brief, using Claude Code's **built-in `/goal` command** as the engine. It works for any project built with Superpowers. Its first real use is the `agna-skills` build launched live at the end of Day 1 of the AGNA course (17 September 2026).

**In scope:** brief validation, project preparation for unattended Superpowers work, construction of an evidence-based `/goal` condition, a watchdog that keeps the goal alive until it is met or a stop time is reached, and status/stop commands.

**Out of scope (decided):**
- BMAD. The BMAD build (`agna-answers`) stays on its proven path: headless planning chain + BMad Loop.
- An attended mode (designing with a human first). The run is unattended only; people shape the design by editing the brief.
- A custom loop engine. The built-in `/goal` is the engine; `overnight` only prepares for it and keeps it alive.

## 2. Verified facts this design relies on

From the Claude Code docs (https://code.claude.com/docs/en/goal) and probes run on Claude Code 2.1.270 on 2026-09-13:

1. `/goal <condition>` sets a session goal. After every turn a separate evaluator model (Haiku by default) reads the transcript and returns met / not met with a reason; on "not met", Claude continues with the reason as guidance. The evaluator **cannot run tools**; it judges only what is visible in the transcript.
2. `/goal` requires a trusted workspace and hooks that are not disabled (`disableAllHooks`, `allowManagedHooksOnly`).
3. If the context window overflows and compaction cannot recover, the goal is **cleared** and waits for someone to run `/goal` again.
4. **Probe 1:** `/goal` works in headless mode: `claude -p "/goal <condition>"` set the goal, did the work, and the transcript recorded `goal_status` with `met: true`, the evaluator's reason, `iterations`, `durationMs`, and `tokens`.
5. **Probe 2:** on a toy brief, Superpowers brainstorming under `/goal` with **no** unattended instructions stopped once to ask a question; the evaluator caught it and pushed Claude on (2 iterations, 7m10s, decisions buried in the spec). **With** a short "Unattended run" section in `CLAUDE.md`, it never stopped (1 iteration, 6m03s), logged 16 timestamped decisions to `JOURNAL.md`, and committed spec and plan separately.
6. The goal condition doubles as the task prompt: a session started with only `/goal <condition>` begins working immediately.
7. The user's settings carry `"fastMode": true` and `"model": "opus[1m]"`; `--settings '<json>'` applies per-session overrides and `--model` selects the session model.

## 3. Commands

Plugin skills are namespaced: `/overnight:start`, `/overnight:status`, `/overnight:stop`. All run inside an interactive Claude Code session opened in the project directory (which also establishes workspace trust).

### 3.1 `/overnight:start <brief-path> [--until HH:MM] [--model NAME]`

Runs these steps in order and stops at the first failure with a specific message:

1. **Validate the brief** (section 4). Report every missing or unusable section at once. The brief may live anywhere; `start` copies it into the project root as `BRIEF.md`, so the project is self-contained, and records the source path in `.overnight/config.json`.
2. **Check prerequisites:**
   - the current directory is the project: the top level of its own git repository with a clean working tree, or an empty directory that is not inside another repository (then `start` runs `git init`);
   - the Superpowers plugin is installed and enabled;
   - `tmux` and `python3` (3.9+) are on `PATH`;
   - every CLI the brief's constraints or guardrails depend on is authenticated — detected from the brief (e.g., Cloudflare → `wrangler whoami`; GitHub → `gh auth status`);
   - a stop time is known (from the brief or `--until`).
3. **Review done-criteria for provability** (section 6.2). Where a criterion cannot be proven by command output in the transcript, propose an agent-provable rewording and ask the human to accept or edit it. This is the only interactive step, and it happens before launch.
4. **Prepare the project** (section 5): write the unattended rules into `CLAUDE.md`, create `JOURNAL.md` and `.overnight/`, commit.
5. **Write the goal condition** to `.overnight/goal.txt` (section 6).
6. **Launch the watchdog** in a detached tmux session named `overnight-<directory-name>`, then print: the tmux attach command, `/overnight:status`, `/overnight:stop`, and the stop time. Before starting tmux, `launch` checks that the Claude binary exists (on `PATH`, or executable when given as a path) and fails with `claude binary not found: …` otherwise. When `caffeinate` is available (macOS), the whole watchdog runs under `caffeinate -i`, so the machine stays awake through sessions and usage-limit waits; elsewhere the command is unchanged. tmux execs `/bin/sh -c <command>` directly, so the user's login shell (fish, for example) never parses it. After tmux returns, `launch` waits up to 15 seconds for `.overnight/state.json` to show a `run_started_epoch` from this launch; if none appears, it captures the last 20 lines of the tmux pane, kills that session, and fails with that output instead of reporting success.

`--model` defaults to the user's configured model. Fast mode is always forced off for the run.

### 3.2 `/overnight:status`

Prints, from `.overnight/state.json`, the transcripts, git, and tmux:
- run status (`running`, `done`, `stopped`, `failed`), start time, stop time; while the status is `running`, if the recorded watchdog process is gone or its heartbeat (section 7.5) is more than 5 minutes old, the line reads `status: running — WATCHDOG NOT RESPONDING (last heartbeat HH:MM)`;
- the tmux session: `alive`, `not running`, or `open; watchdog finished` when the run has ended (`done`, `stopped`, `failed`) but the session's shell is still open. Run health is judged from the status line, not from tmux, because the shell stays open after the watchdog exits;
- the evaluator's latest verdict and reason;
- relaunch count;
- commits since start;
- the last 15 lines of `JOURNAL.md`.

### 3.3 `/overnight:stop`

Creates `.overnight/STOP`. The watchdog sees it within its poll interval, ends the working session, and runs the wrap-up (section 7.4). Prints the tmux attach command for watching the wrap-up.

## 4. Brief contract

A brief is a markdown file. Required sections (matched by heading text, case-insensitive; synonyms in parentheses):

| Section | Requirement |
|---|---|
| Mission | Non-empty. |
| Hard constraints (Constraints) | Non-empty list. |
| Must-have (Must-haves, Requirements) | Non-empty list. |
| Done-criteria (Done criteria, Definition of done) | Non-empty list; each item is one checkable statement. |
| Guardrails | Non-empty list. A stop time is the first `HH:MM` found here, unless `--until` overrides it. |

Optional sections are passed through untouched (e.g., Users and auth, Stretch, Method, Journal). Both AGNA course briefs already satisfy this contract.

The stop time is interpreted in local time; if it is earlier than the current time, it means the next day.

## 5. Project preparation

### 5.1 `CLAUDE.md` — "Unattended run" section

`start` appends this section (or replaces a previous `overnight` section, delimited by `<!-- overnight:begin -->` / `<!-- overnight:end -->` markers). `{approved_actions}` is filled in with the outside actions the brief's guardrails and constraints explicitly permit (e.g., deploying to Cloudflare, creating and pushing this project's GitHub repository).

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

### 5.2 Files

| Path | Written by | Committed |
|---|---|---|
| `BRIEF.md` — copy of the brief | start | yes |
| `JOURNAL.md` | start (header), Claude (entries), wrap-up (final entry) | yes |
| `.overnight/goal.txt` | start | yes |
| `.overnight/config.json` — brief path, stop time, model, start time, relaunch cap | start | yes |
| `.overnight/evidence.md` | Claude | yes |
| `.overnight/state.json` | watchdog | no (gitignored) |
| `.overnight/logs/` — watchdog log, one JSON result per session | watchdog | no (gitignored) |
| `.overnight/STOP` | stop command | no (gitignored) |

`start` adds the three gitignore entries.

## 6. The goal condition

### 6.1 Template

```
Every done-criterion for this project is proven in this conversation: (1) <criterion 1>. (2) <criterion 2>. ... Proven means: the most recent print of .overnight/evidence.md shows, for each numbered criterion, the command that was run and its actual output (not a claim), and JOURNAL.md has a final summary entry.
```

The condition is stored in `.overnight/goal.txt` as a single line, because slash-command arguments are passed on one line. Criteria are copied from the brief (after any accepted rewording) and numbered. The condition is also the first prompt of the session, so it points Claude at the brief implicitly through `CLAUDE.md`, which every session loads.

### 6.2 Provability review

For each criterion, `start` judges: can an agent prove this with a command whose output appears in the transcript? Criteria that need a human's senses or accounts (receiving an email PIN, visual judgment, a phone) are not provable. `start` proposes a provable proxy and records the original as a human morning check.

Example from `agna-skills`: "A fresh email address can sign in with a PIN" → proxy "A signed-out request to the live URL redirects to the Cloudflare Access login page (show the HTTP status and Location header)"; original kept as a morning check in `JOURNAL.md`'s header.

## 7. Watchdog

A single Python 3 standard-library script, `scripts/overnight_watchdog.py`, started by `start` inside tmux, run from the project root.

### 7.1 Session command

```
claude -p [--resume <session-id>] "/goal <contents of .overnight/goal.txt>"
  --permission-mode bypassPermissions
  --settings '{"fastMode": false}'
  [--model <model>]
  --output-format json
```

The watchdog runs it as a child process, polls every 15 seconds for `.overnight/STOP` and the stop time, and captures stdout (JSON result) and stderr to `.overnight/logs/session-<n>.json|.stderr`.

**Environment.** Every session (and the tmux server `launch` may start) runs without the identity of the Claude Code session that ran `/overnight:start`: `CLAUDECODE`, `CLAUDE_CODE_CHILD_SESSION`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_EFFORT`, `CLAUDE_CODE_SESSION_ATTENDED`, `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_CODE_EXECPATH`, `CLAUDE_PID`, `CLAUDE_CODE_MESSAGING_SOCKET`, `CLAUDE_CODE_MESSAGING_TOKEN`, `CLAUDE_CODE_BRIDGE_SESSION_ID`, `AI_AGENT`, `TRACEPARENT`, `CLAUDE_CODE_SSE_PORT`, `CLAUDE_AGENT_SDK_VERSION`, and `CLAUDE_AGENT_SDK_CLIENT_APP` are removed, and `launch` never forwards them into tmux, even when listed in `OVERNIGHT_FORWARD_ENV`. The messaging token is a secret that unattended commands could otherwise print into committed evidence. Everything else is kept (`PATH`, `CLAUDE_CONFIG_DIR`, `ANTHROPIC_*`, `CLAUDE_CODE_USE_BEDROCK`/`VERTEX`, `CLAUDE_CODE_OAUTH_TOKEN`, `AWS_*`, proxy and CA variables).

### 7.2 Outcome detection

After the child exits, the watchdog reads `session_id` from the JSON result and finds the transcript at `${CLAUDE_CONFIG_DIR:-~/.claude}/projects/*/<session_id>.jsonl`. The **last** `goal_status` attachment decides:
- `met: true` → status `done`.
- otherwise, or no JSON/transcript (process killed or crashed) → not met.

It also records the evaluator's latest `reason` in `state.json`.

### 7.3 Loop rules

| Situation | Action |
|---|---|
| Goal met | Set `done`, exit 0. No wrap-up needed. |
| Not met, session ended | Relaunch with `--resume <last session-id>` after 10 s. After 2 consecutive resumes that end without a new commit, start a fresh session without `--resume`; files carry the state. |
| Session ended within 60 s, three times in a row | Set `failed`, run wrap-up, exit 1. |
| Result or stderr matches a usage-limit message | Sleep until the reset time if one is stated (plus 2 minutes), else 30 minutes, never past the stop time; does not count as a crash. |
| Relaunch count exceeds the cap (default 10) | Set `failed`, run wrap-up, exit 1. |
| Stop time reached or `.overnight/STOP` present | Terminate the child (SIGINT, then SIGTERM after 30 s), set `stopped`, run wrap-up, exit 0. |

### 7.4 Wrap-up

A **fresh** session (no `--resume`, so no goal is attached and the evaluator cannot push it back into work), time-boxed to 15 minutes:

> The unattended run has ended (reason: {stop time | stop requested | failed}). Do not start new work. Rerun the checks for each numbered criterion in .overnight/goal.txt, update .overnight/evidence.md with the real current results, append a final JOURNAL.md entry listing what is done, what is not, and every needs-human item, then commit.

### 7.5 Health and crashes

- `state.json` records `watchdog_pid`, `run_started_epoch` (when `run` began), and `heartbeat_epoch`. The heartbeat is refreshed on every state save, and at most every 60 seconds while a session, a usage-limit wait, or the wrap-up is in progress. `status` uses the pid and heartbeat to detect a watchdog that died while the status still says `running`.
- Session output is read as UTF-8 with invalid bytes replaced, so unusual output cannot crash the watchdog.
- Any unexpected exception in the loop is logged with its traceback to `.overnight/logs/watchdog.log`, sets `failed` with `end_reason: "watchdog crashed: <ExceptionType>: <message>"`, attempts the wrap-up (a failing wrap-up is logged, never raised), and exits 1.

## 8. Packaging

```
overnight/
  .claude-plugin/plugin.json        name "overnight", version, description
  .claude-plugin/marketplace.json   single-plugin marketplace, so the repo can be added with /plugin marketplace add
  skills/start/SKILL.md
  skills/start/references/brief-contract.md
  skills/start/references/unattended-rules.md     the section 5.1 template
  skills/start/references/goal-condition.md       the section 6 template and provability review
  skills/status/SKILL.md
  skills/stop/SKILL.md
  scripts/overnight_brief.py                       brief parsing and validation (section 4)
  scripts/overnight_prepare.py                     project preparation and goal condition (sections 5-6)
  scripts/overnight_watchdog.py                    run, launch (tmux), and status
  tests/                                           unit tests, plus watchdog tests with a fake claude
  README.md
  docs/superpowers/specs/2026-09-13-overnight-plugin-design.md
```

Install after publishing: `/plugin marketplace add dimitris-am/overnight` then `/plugin install overnight@overnight`. The skills locate the watchdog via their own install path.

## 9. Testing

1. **Watchdog, automated** (`python3 -m unittest`): a fake `claude` executable on `PATH` writes controlled JSON results and transcripts to simulate every row of section 7.3: met on first run; crash then resume then met; three fast crashes; usage limit with and without a reset time; relaunch cap; stop time; STOP file; and the fresh-session fallback after two unproductive resumes. Each test asserts the final status, the sequence of `claude` invocations (flags included), and the wrap-up call.
2. **`start` checks:** run against both AGNA briefs (expect a pass, and a provability flag on each brief's sign-in-with-a-PIN criterion) and against a brief with no done-criteria and no stop time (expect both reported at once).
3. **End to end:** a full unattended build of the toy `tally` CLI brief through `/overnight:start` on Sonnet: spec, plan, code, passing tests, `goal_status met: true`, `.overnight/evidence.md`, a complete `JOURNAL.md`, and `status` reporting `done`.
4. **Install:** after the GitHub repo exists, install from the marketplace on this machine and run test 2 through the installed plugin.

The real `agna-skills` run belongs to the course rehearsal, not to this plugin's tests.

## 10. Course integration (outside this repo)

After the plugin works:
- `course-materials/overnight/agna-skills-brief.md`: runner line becomes `/overnight:start course-materials/overnight/agna-skills-brief.md`; the PIN done-criterion gains the provable proxy.
- Deck slides 27 and 28: the runner line shows `/overnight:start …`, run from inside the new `agna-skills` project directory (created empty just before ignition).
- `course-materials/run-of-show.md`: section 1 item 1 reflects `overnight` instead of a hand-built `/goal` runner.

## 11. Risks and open items

- **Fast-mode override:** `--settings '{"fastMode": false}'` is expected to override the user setting per session; confirmed by test 3's transcript or result metadata. If it does not, the watchdog sets the model to a non-Opus default and `start` warns.
- **Usage-limit exit format:** the exact wording of a limit message in headless mode is unverified; the watchdog's pattern is broad and falls back to a 30-minute wait.
- **Resuming a goal:** re-issuing `/goal` with `--resume` on a session whose goal was cleared is expected to work but is unverified; the fresh-session fallback covers it.
- **Workspace trust:** each new project must be trusted once; `start` running in an interactive session in that directory satisfies this.
- **Global plugins in unattended sessions:** the user's other plugins (context-mode, claude-mem, gstack hooks) inject instructions into every session. Probes 1 and 2 were not derailed by them; the end-to-end test watches for it.
- **Evaluator blind spots:** the evaluator only sees the transcript, so evidence must be printed near the end of a long session; the unattended rules require reprinting the evidence file on every "not met".
