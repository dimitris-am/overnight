#!/usr/bin/env python3
"""overnight watchdog: keeps a built-in /goal session alive until the goal is met,
the stop time arrives, or the run fails."""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import shlex
import shutil
import signal
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
    return subprocess.run(["tmux", "has-session", "-t", f"={name}"], capture_output=True).returncode == 0


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
