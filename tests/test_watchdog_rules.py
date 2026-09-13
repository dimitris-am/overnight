import datetime as dt
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
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
        if "raise" in step:
            raise step["raise"]
        self.clock.t += step.get("duration", 300)
        if step.get("commit"):
            self.heads["head"] = f"commit-{len(self.calls)}"
        sid = step.get("session_id", f"s{len(self.calls)}")
        self.outcomes[sid] = ow.SessionOutcome(sid, step.get("met", False), step.get("reason"), step.get("text", ""))
        stdout = step.get("stdout", json.dumps({"session_id": sid}))
        return step.get("exit", 0), stdout, step.get("stderr", ""), step.get("killed", False)


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

    def make(self, steps, interpreter=None):
        runner = FakeRunner(self.clock, steps, self.heads)
        dog = ow.Watchdog(
            self.project,
            claude_bin="claude",
            runner=runner,
            clock=self.clock,
            sleeper=self.clock.sleep,
            interpreter=interpreter or (lambda out, err: runner.outcomes[json.loads(out)["session_id"]]),
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
        reset_epoch = int(START) + 5400
        self.assertEqual(ow.usage_limit_wake(f"Claude AI usage limit reached|{reset_epoch}", START, settings), reset_epoch + 120)

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

    def test_clean_env_strips_parent_session_identity(self):
        expected_names = {
            "CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID", "CLAUDE_EFFORT",
            "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH", "CLAUDE_PID",
            "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_BRIDGE_SESSION_ID",
            "AI_AGENT", "TRACEPARENT", "CLAUDE_CODE_SSE_PORT", "CLAUDE_AGENT_SDK_VERSION", "CLAUDE_AGENT_SDK_CLIENT_APP",
        }
        self.assertEqual(set(ow.PARENT_SESSION_ENV_VARS), expected_names)
        environ = {name: "inherited" for name in expected_names}
        kept = {"PATH": "/usr/bin:/bin", "CLAUDE_CONFIG_DIR": "/tmp/claude-config", "CLAUDE_CODE_USE_BEDROCK": "1"}
        environ.update(kept)
        cleaned = ow.clean_env(environ)
        self.assertEqual(cleaned, kept)
        self.assertIn("CLAUDECODE", environ)  # the input mapping is not modified

    def test_watchdog_shell_command_with_and_without_caffeinate(self):
        project = Path("/tmp/my proj")
        script = str(Path(ow.__file__).resolve())
        watchdog = f"{shlex.quote(sys.executable)} {shlex.quote(script)} run --project '/tmp/my proj' --claude-bin '/opt/claude bin/claude'"
        plain = ow.watchdog_shell_command(project, "/opt/claude bin/claude", None)
        self.assertTrue(plain.startswith(watchdog + "; "), plain)
        self.assertNotIn("caffeinate", plain)
        awake = ow.watchdog_shell_command(project, "/opt/claude bin/claude", "/usr/bin/caffeinate")
        self.assertTrue(awake.startswith("/usr/bin/caffeinate -i " + watchdog + "; "), awake)
        self.assertEqual(shlex.split(awake)[:4], ["/usr/bin/caffeinate", "-i", sys.executable, script])

    def test_tmux_command_execs_posix_sh_directly(self):
        inner = ow.watchdog_shell_command(Path("/tmp/p"), "claude", "/usr/bin/caffeinate")
        cmd = ow.tmux_new_session_command("overnight-p", Path("/tmp/p"), ["-e", "PATH=/bin"], inner)
        self.assertEqual(cmd, ["tmux", "new-session", "-d", "-s", "overnight-p", "-c", "/tmp/p", "-e", "PATH=/bin", "/bin/sh", "-c", inner])
        self.assertEqual(subprocess.run(["/bin/sh", "-n", "-c", inner]).returncode, 0)

    def test_tmux_env_args_never_forward_parent_session_vars(self):
        environ = {"PATH": "/bin", "CLAUDECODE": "1", "CLAUDE_CODE_MESSAGING_TOKEN": "secret", "FOO": "bar"}
        self.assertEqual(
            ow.tmux_env_args(["PATH", "CLAUDECODE", "CLAUDE_CODE_MESSAGING_TOKEN", "FOO", "MISSING"], environ),
            ["-e", "PATH=/bin", "-e", "FOO=bar"],
        )


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
        outcome = ow.interpret_session(
            json.dumps({"session_id": "s3", "result": "Implemented per-IP rate limiting", "is_error": False}), "warn", self.config_dir,
        )
        self.assertEqual((outcome.session_id, outcome.met, outcome.reason), ("s3", True, "ok"))
        self.assertNotIn("rate limiting", outcome.text)  # the model's normal final message is not limit evidence
        self.assertIn("warn", outcome.text)
        error = ow.interpret_session(json.dumps({"session_id": "s3", "result": "Claude AI usage limit reached|1789999999", "is_error": True}), "", self.config_dir)
        self.assertIn("usage limit reached|1789999999", error.text)
        subtype = ow.interpret_session(json.dumps({"session_id": "s3", "subtype": "error_during_execution", "result": "boom"}), "", self.config_dir)
        self.assertIn("boom", subtype.text)

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

    def test_normal_result_mentioning_rate_limiting_does_not_wait(self):
        config_dir = Path(self.tmp.name).resolve() / "claude-config"
        (config_dir / "projects" / "p").mkdir(parents=True)
        (config_dir / "projects" / "p" / "s2.jsonl").write_text(
            json.dumps({"type": "attachment", "attachment": {"type": "goal_status", "met": True, "reason": "all proven"}}) + "\n"
        )
        normal = {"type": "result", "subtype": "success", "is_error": False, "session_id": "s1", "result": "Implemented per-IP rate limiting."}
        dog, runner = self.make(
            [{"commit": True, "stdout": json.dumps(normal)}, {"stdout": json.dumps({"type": "result", "is_error": False, "session_id": "s2", "result": "done"})}],
            interpreter=lambda out, err: ow.interpret_session(out, err, config_dir),
        )
        self.assertEqual(dog.run(), 0)
        self.assertEqual(self.state()["status"], "done")
        self.assertLess(sum(self.clock.sleeps), 1800)
        self.assertEqual(self.clock.sleeps, [ow.Settings().relaunch_delay_seconds])

    def test_usage_limit_wait_past_the_stop_time_ends_at_the_stop_time(self):
        deadline = dt.datetime(2026, 9, 18, 7, 30).timestamp()
        dog, runner = self.make([{"duration": 5, "text": "Usage limit reached. Your limit resets 9am"}])
        self.assertEqual(dog.run(), 0)
        self.assertEqual(self.clock.t, deadline)  # slept until the stop time, not until 09:02
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(self.state()["status"], "stopped")
        self.assertEqual(self.state()["end_reason"], "stop time")
        self.assertEqual(len(runner.wrapups), 1)

    def test_session_without_json_resumes_the_last_known_session(self):
        dog, runner = self.make([
            {"session_id": "s1", "commit": True},
            {"session_id": None, "stdout": "Traceback: crashed before any JSON"},
            {"met": True},
        ])
        dog.interpreter = lambda out, err: runner.outcomes[json.loads(out)["session_id"] if out.startswith("{") else None]
        self.assertEqual(dog.run(), 0)
        self.assertEqual(runner.calls[1][-2:], ["--resume", "s1"])
        self.assertIsNone(self.state()["sessions"][1]["session_id"])
        self.assertEqual(runner.calls[2][-2:], ["--resume", "s1"])  # the id-less session did not break the resume chain

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


class CrashAndHeartbeatTests(WatchdogTestCase):
    def watchdog_log(self):
        return (self.project / ".overnight" / "logs" / "watchdog.log").read_text()

    def test_runner_exception_fails_the_run_and_attempts_wrapup(self):
        dog, runner = self.make([{"raise": RuntimeError("boom")}])
        self.assertEqual(dog.run(), 1)
        state = self.state()
        self.assertEqual(state["status"], "failed")
        self.assertTrue(state["end_reason"].startswith("watchdog crashed:"), state["end_reason"])
        self.assertIn("RuntimeError: boom", state["end_reason"])
        self.assertEqual(len(runner.wrapups), 1)
        self.assertIn("Traceback", self.watchdog_log())

    def test_crash_survives_a_wrapup_that_raises_too(self):
        def runner(*args):
            raise FileNotFoundError("no such file: claude")

        dog = ow.Watchdog(self.project, runner=runner, clock=self.clock, sleeper=self.clock.sleep, head=lambda project: "x")
        self.assertEqual(dog.run(), 1)
        self.assertEqual(self.state()["status"], "failed")
        self.assertIn("FileNotFoundError", self.state()["end_reason"])
        self.assertIn("wrap-up failed", self.watchdog_log())

    def test_state_records_pid_run_start_and_heartbeat(self):
        seen = {}

        def runner(cmd, cwd, log_prefix, poll, should_stop, timeout, grace):
            if not cmd[cmd.index("-p") + 1].startswith("/goal "):
                return 0, "{}", "", False
            seen["first"] = self.state()
            self.clock.t += 30
            self.assertFalse(should_stop())
            seen["after_30s"] = self.state()["heartbeat_epoch"]
            self.clock.t += 60
            self.assertFalse(should_stop())
            seen["after_90s"] = self.state()["heartbeat_epoch"]
            return 0, json.dumps({"session_id": "s1"}), "", False

        dog = ow.Watchdog(
            self.project, runner=runner, clock=self.clock, sleeper=self.clock.sleep, head=lambda project: "x",
            interpreter=lambda out, err: ow.SessionOutcome("s1", True, "ok", ""),
        )
        self.assertEqual(dog.run(), 0)
        self.assertEqual(seen["first"]["watchdog_pid"], os.getpid())
        self.assertEqual(seen["first"]["run_started_epoch"], START)
        self.assertEqual(seen["first"]["heartbeat_epoch"], START)
        self.assertEqual(seen["after_30s"], START)  # at most one refresh every 60 s
        self.assertEqual(seen["after_90s"], START + 90)

    def test_heartbeat_continues_during_a_usage_limit_wait(self):
        dog, runner = self.make([{"duration": 5, "text": "Claude usage limit reached."}, {"met": True}])
        beats = []

        def sleeper(seconds):
            self.clock.sleep(seconds)
            beats.append(self.state()["heartbeat_epoch"])

        dog.sleeper = sleeper
        self.assertEqual(dog.run(), 0)
        self.assertGreaterEqual(max(beats), START + 1500)


class RunInProgressTests(unittest.TestCase):
    def test_only_a_running_state_with_a_live_pid_is_in_progress(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".overnight").mkdir()
            self.assertFalse(ow.run_in_progress(project))  # no state.json
            cases = [
                ({"status": "running", "watchdog_pid": os.getpid()}, True),
                ({"status": "running", "watchdog_pid": child.pid}, False),
                ({"status": "done", "watchdog_pid": os.getpid()}, False),
                ({"status": "running"}, False),
            ]
            for state, expected in cases:
                (project / ".overnight" / "state.json").write_text(json.dumps(state))
                self.assertEqual(ow.run_in_progress(project), expected, state)


class StatusReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name).resolve() / "proj"
        (self.project / ".overnight").mkdir(parents=True)
        (self.project / ".overnight" / "config.json").write_text(json.dumps({"stop_time": "07:30", "started_at": "2026-09-17T22:00:00"}))
        self.config_dir = Path(self.tmp.name).resolve() / "claude-config"
        (self.config_dir / "projects").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write_state(self, **fields):
        state = {"status": "running", "sessions": [], "relaunches": 0, "last_verdict": None}
        state.update(fields)
        (self.project / ".overnight" / "state.json").write_text(json.dumps(state))

    def report(self, tmux_alive=True):
        return ow.status_report(self.project, tmux_alive=lambda name: tmux_alive, config_dir=self.config_dir)

    def test_running_with_a_dead_watchdog_pid_is_not_responding(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        heartbeat = time.time() - 30
        self.write_state(watchdog_pid=child.pid, heartbeat_epoch=heartbeat, run_started_epoch=heartbeat)
        report = self.report()
        self.assertIn(f"status: running — WATCHDOG NOT RESPONDING (last heartbeat {dt.datetime.fromtimestamp(heartbeat):%H:%M})", report)

    def test_running_with_a_stale_heartbeat_is_not_responding(self):
        heartbeat = time.time() - 600
        self.write_state(watchdog_pid=os.getpid(), heartbeat_epoch=heartbeat, run_started_epoch=heartbeat)
        self.assertIn("WATCHDOG NOT RESPONDING", self.report())

    def test_running_and_healthy(self):
        now = time.time()
        self.write_state(watchdog_pid=os.getpid(), heartbeat_epoch=now, run_started_epoch=now)
        report = self.report()
        self.assertIn("status: running\n", report)
        self.assertNotIn("NOT RESPONDING", report)
        self.assertIn("tmux session: overnight-proj (alive)", report)

    def write_live_transcript(self, folder, sid, cwd, goal_statuses, mtime=None):
        path = self.config_dir / "projects" / folder / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        entries = [
            {"type": "queue-operation", "sessionId": sid, "timestamp": "2026-09-17T20:05:00.123Z"},
            {"type": "permission-mode", "sessionId": sid},
            {"type": "user", "cwd": cwd, "sessionId": sid, "timestamp": "2026-09-17T20:05:01.000Z"},
        ]
        entries += [{"type": "attachment", "cwd": cwd, "attachment": dict(status, type="goal_status")} for status in goal_statuses]
        path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def test_running_status_reports_the_live_transcript_verdict(self):
        now = time.time()
        self.write_state(watchdog_pid=os.getpid(), heartbeat_epoch=now, run_started_epoch=now - 3600)
        project = str(self.project)
        # an earlier run's transcript for this project, and a newer one for another project: both ignored
        self.write_live_transcript("old", "old", project, [{"met": True, "reason": "old run"}], mtime=now - 7200)
        self.write_live_transcript("live", "live", project, [{"met": False, "sentinel": True}, {"met": False, "reason": "evidence not printed"}], mtime=now - 60)
        self.write_live_transcript("other", "other", "/somewhere/else", [{"met": True, "reason": "other project"}], mtime=now - 5)
        report = self.report()
        started = dt.datetime.fromisoformat("2026-09-17T20:05:00.123+00:00").astimezone()
        self.assertIn("live goal check: not met — evidence not printed", report)
        self.assertIn(f"current session started: {started:%H:%M}", report)
        self.assertNotIn("old run", report)
        self.assertNotIn("other project", report)

    def test_live_transcript_without_a_verdict_yet(self):
        now = time.time()
        self.write_state(watchdog_pid=os.getpid(), heartbeat_epoch=now, run_started_epoch=now - 60)
        self.write_live_transcript("live", "live", str(self.project), [{"met": False, "sentinel": True}])
        report = self.report()
        self.assertIn("live goal check: none yet", report)
        self.assertIn("current session started:", report)

    def test_no_live_lines_without_a_matching_transcript(self):
        now = time.time()
        self.write_state(watchdog_pid=os.getpid(), heartbeat_epoch=now, run_started_epoch=now - 60)
        self.assertNotIn("live goal check", self.report())

    def test_finished_run_with_open_tmux_session(self):
        for status in ("done", "stopped", "failed"):
            self.write_state(status=status, watchdog_pid=os.getpid(), heartbeat_epoch=time.time() - 3600)
            report = self.report(tmux_alive=True)
            self.assertIn("tmux session: overnight-proj (open; watchdog finished)", report)
            self.assertNotIn("NOT RESPONDING", report)
        self.assertIn("tmux session: overnight-proj (not running)", self.report(tmux_alive=False))


if __name__ == "__main__":
    unittest.main()
