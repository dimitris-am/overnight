import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from helpers import FAKE_CLAUDE, GIT_ENV, SCRIPTS, git

import overnight_watchdog as ow

WATCHDOG = SCRIPTS / "overnight_watchdog.py"
FAST_FLAGS = ["--poll", "0.05", "--relaunch-delay", "0", "--fast-crash-seconds", "0", "--kill-grace", "2", "--wrapup-timeout", "10"]


class ProcessTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.project = base / "proj"
        self.project.mkdir()
        git(self.project, "init", "-q", "-b", "main")
        (self.project / "README.md").write_text("# proj\n")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", "init")
        overnight = self.project / ".overnight"
        overnight.mkdir()
        (overnight / "goal.txt").write_text("Every done-criterion is proven.\n")
        (overnight / "config.json").write_text(json.dumps({
            "stop_time": "23:59" if time.localtime().tm_hour < 23 else "00:30",
            "model": "sonnet",
            "started_at_epoch": time.time(),
            "max_relaunches": 10,
        }))
        self.state_dir = base / "fake-state"
        self.config_dir = base / "claude-config"
        self.scenario = base / "scenario.json"
        self.env = {
            **os.environ,
            **GIT_ENV,
            "FAKE_CLAUDE_STATE": str(self.state_dir),
            "FAKE_CLAUDE_SCENARIO": str(self.scenario),
            "CLAUDE_CONFIG_DIR": str(self.config_dir),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def set_scenario(self, steps):
        self.scenario.write_text(json.dumps(steps))

    def calls(self):
        path = self.state_dir / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def state(self):
        return json.loads((self.project / ".overnight" / "state.json").read_text())

    def watchdog(self, *args, **kwargs):
        return subprocess.run([sys.executable, str(WATCHDOG), *args], env=self.env, capture_output=True, text=True, timeout=60, **kwargs)


class RunCommandTests(ProcessTestCase):
    def test_met_on_first_run(self):
        self.set_scenario([{"met": True, "reason": "all proven"}])
        result = self.watchdog("run", "--project", str(self.project), "--claude-bin", str(FAKE_CLAUDE), *FAST_FLAGS)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state()["status"], "done")
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ["-p", "/goal Every done-criterion is proven."])
        self.assertIn('{"fastMode": false}', calls[0])
        self.assertTrue((self.project / ".overnight" / "logs" / "session-1.json").is_file())

    def test_resume_then_met(self):
        self.set_scenario([{"met": False, "session_id": "first", "commit": True}, {"met": True}])
        result = self.watchdog("run", "--project", str(self.project), "--claude-bin", str(FAKE_CLAUDE), *FAST_FLAGS)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertEqual(calls[1][-2:], ["--resume", "first"])

    def test_stop_file_interrupts_a_running_session(self):
        self.set_scenario([{"sleep": 30, "met": False}])
        proc = subprocess.Popen(
            [sys.executable, str(WATCHDOG), "run", "--project", str(self.project), "--claude-bin", str(FAKE_CLAUDE), *FAST_FLAGS],
            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        deadline = time.time() + 10
        while not self.calls() and time.time() < deadline:
            time.sleep(0.05)
        (self.project / ".overnight" / "STOP").write_text("")
        out, err = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, out + err)
        self.assertEqual(self.state()["status"], "stopped")
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertFalse(calls[1][1].startswith("/goal"))

    def test_stop_escalates_to_sigterm_when_session_ignores_sigint(self):
        self.set_scenario([{"sleep": 60, "met": False, "ignore_sigint": True}])
        proc = subprocess.Popen(
            [sys.executable, str(WATCHDOG), "run", "--project", str(self.project), "--claude-bin", str(FAKE_CLAUDE), *FAST_FLAGS],
            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        deadline = time.time() + 10
        while not self.calls() and time.time() < deadline:
            time.sleep(0.05)
        started = time.time()
        (self.project / ".overnight" / "STOP").write_text("")
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0, out + err)
        self.assertEqual(self.state()["status"], "stopped")
        self.assertLess(time.time() - started, 20)  # kill grace is 2 s in FAST_FLAGS, then SIGTERM
        self.assertEqual(len(self.calls()), 2)


class RunProcessTests(unittest.TestCase):
    def test_timeout_kills_the_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            started = time.time()
            code, out, err, killed = ow.run_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                Path(tmp), Path(tmp) / "logs" / "slow", 0.05, lambda: False, 0.5, 1.0,
            )
            self.assertTrue(killed)
            self.assertNotEqual(code, 0)
            self.assertLess(time.time() - started, 10)
            self.assertTrue((Path(tmp) / "logs" / "slow.json").is_file())

    def test_invalid_utf8_output_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err, killed = ow.run_process(
                [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'out \\xff'); sys.stderr.buffer.write(b'bad \\xfe\\xff bytes')"],
                Path(tmp), Path(tmp) / "logs" / "bytes", 0.05, lambda: False, 10.0, 1.0,
            )
        self.assertEqual(code, 0)
        self.assertIn("bad", err)
        self.assertIn("�", err)
        self.assertIn("out", out)

    def test_child_does_not_inherit_parent_session_env(self):
        names = ("CLAUDECODE", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CONFIG_DIR")
        saved = {name: os.environ.get(name) for name in names}
        os.environ.update({"CLAUDECODE": "1", "CLAUDE_CODE_MESSAGING_TOKEN": "secret-token", "CLAUDE_CONFIG_DIR": "/tmp/overnight-config"})
        probe = f"import os; print(','.join(n for n in {names!r} if n in os.environ))"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                code, out, err, killed = ow.run_process(
                    [sys.executable, "-c", probe], Path(tmp), Path(tmp) / "logs" / "env", 0.05, lambda: False, 10.0, 1.0,
                )
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "CLAUDE_CONFIG_DIR")


class StatusTests(ProcessTestCase):
    def test_status_after_done_run(self):
        self.set_scenario([{"met": True, "reason": "all proven"}])
        self.watchdog("run", "--project", str(self.project), "--claude-bin", str(FAKE_CLAUDE), *FAST_FLAGS)
        (self.project / "JOURNAL.md").write_text("# Journal\n- 01:00 [milestone] done\n")
        result = self.watchdog("status", "--project", str(self.project))
        self.assertEqual(result.returncode, 0)
        self.assertIn("status: done", result.stdout)
        self.assertIn("last goal check: met — all proven", result.stdout)
        self.assertIn("[milestone] done", result.stdout)

    def test_status_without_run(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        result = self.watchdog("status", "--project", str(empty))
        self.assertEqual(result.returncode, 1)
        self.assertIn("No overnight run", result.stdout)


@unittest.skipUnless(shutil.which("tmux"), "tmux not installed")
class LaunchTests(ProcessTestCase):
    def test_launch_runs_watchdog_in_tmux(self):
        self.set_scenario([{"met": True}])
        self.env["OVERNIGHT_FORWARD_ENV"] = "FAKE_CLAUDE_STATE,FAKE_CLAUDE_SCENARIO,GIT_AUTHOR_NAME,GIT_AUTHOR_EMAIL,GIT_COMMITTER_NAME,GIT_COMMITTER_EMAIL"
        name = ow.session_name(self.project)
        try:
            result = self.watchdog("launch", "--project", str(self.project), "--claude-bin", str(FAKE_CLAUDE))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(name, result.stdout)
            deadline = time.time() + 60
            while time.time() < deadline:
                state_file = self.project / ".overnight" / "state.json"
                if state_file.exists() and json.loads(state_file.read_text())["status"] == "done":
                    break
                time.sleep(0.5)
            self.assertEqual(self.state()["status"], "done")
            again = self.watchdog("launch", "--project", str(self.project), "--claude-bin", str(FAKE_CLAUDE))
            self.assertEqual(again.returncode, 1)
            self.assertIn("already exists", again.stdout + again.stderr)
        finally:
            subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)

    def test_launch_refuses_a_missing_or_non_executable_claude_binary(self):
        not_executable = self.project.parent / "claude-not-executable"
        not_executable.write_text("#!/bin/sh\n")
        not_executable.chmod(0o644)
        name = ow.session_name(self.project)
        try:
            for claude_bin in (str(not_executable), "overnight-no-such-claude-binary"):
                result = self.watchdog("launch", "--project", str(self.project), "--claude-bin", claude_bin)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("claude binary not found", result.stdout)
                self.assertNotEqual(subprocess.run(["tmux", "has-session", "-t", f"={name}"], capture_output=True).returncode, 0)
        finally:
            subprocess.run(["tmux", "kill-session", "-t", f"={name}"], capture_output=True)


if __name__ == "__main__":
    unittest.main()
