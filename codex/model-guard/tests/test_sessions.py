import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from model_guard import sessions
from model_guard.install import prune


class SessionTests(unittest.TestCase):
    def test_own_process_is_listed_only_when_its_executable_is_codex(self):
        with patch("model_guard.sessions.PROC", Path("/proc")):
            pids = {session.pid for session in sessions.running()}
        self.assertNotIn(os.getpid(), pids)
        for session in sessions.running():
            self.assertEqual(Path(session.executable.removesuffix(" (deleted)")).name, "codex")
            self.assertNotIn("\x1b", session.command)

    def test_sessions_on_the_new_executable_are_not_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            new = Path(temp) / "new/bin/codex"
            old = Path(temp) / "old/bin/codex"
            for path in (new, old):
                path.parent.mkdir(parents=True)
                path.touch()
            listed = [sessions.Session(1, str(new), temp, ""), sessions.Session(2, str(old), temp, "resume")]
            with patch("model_guard.sessions.running", return_value=listed):
                stale = sessions.not_running(new)
            self.assertEqual([session.pid for session in stale], [2])
            self.assertIn("pid 2", sessions.describe(stale))

    def test_prune_keeps_active_and_in_use_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "guard"
            for name in ("envs/1.5.0-a", "envs/1.5.1-p/bin", "envs/1.6.0-b", "envs/1.7.0-c", "native/1.6.0-b/bin", "native/1.7.0-c/bin"):
                (root / name).mkdir(parents=True)
            (root / "native/1.6.0-b/bin/codex").touch()
            (root / "envs/1.5.1-p/bin/python").touch()
            (root / "current").symlink_to(root / "envs/1.5.0-a")
            elsewhere = Path(temp) / "elsewhere"
            elsewhere.mkdir()
            (root / "envs/linked").symlink_to(elsewhere, target_is_directory=True)
            in_use = [root / "native/1.6.0-b/bin/codex", root / "envs/1.5.1-p/bin/python", Path("/usr/bin/sh")]
            with patch("model_guard.sessions.executables", return_value=in_use):
                removed = prune(root, {(root / "envs/1.7.0-c").resolve(), (root / "native/1.7.0-c").resolve()})
            self.assertEqual([path.name for path in removed], ["1.5.0-a", "1.6.0-b"])
            self.assertTrue((root / "native/1.6.0-b/bin/codex").exists())
            self.assertTrue((root / "envs/1.5.1-p/bin/python").exists())
            self.assertTrue((root / "envs/1.7.0-c").exists())
            self.assertTrue(elsewhere.exists() and (root / "envs/linked").is_symlink())
            self.assertFalse((root / "current").exists())

    def test_prune_never_follows_a_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "guard"
            root.mkdir()
            data = Path(temp) / "data/old"
            data.mkdir(parents=True)
            (root / "envs").symlink_to(Path(temp) / "data", target_is_directory=True)
            with patch("model_guard.sessions.executables", return_value=[]):
                self.assertEqual(prune(root, set()), [])
            self.assertTrue(data.exists())

    def test_only_interactive_invocations_count_as_sessions(self):
        for argv, expected in [
            ([], True),
            (["--dangerously-bypass-approvals-and-sandbox"], True),
            (["resume", "--last"], True),
            (["-m", "gpt-6-astra", "fork", "abc"], True),
            (["--sandbox", "read-only", "Reply OK."], True),
            (["-c", "model='exec'", "resume"], True),
            (["exec", "--json", "Reply OK."], False),
            (["app-server", "--stdio"], False),
            (["--sandbox-policy-cwd", "/w", "--apply-seccomp-then-exec", "--", "/bin/bash"], False),
            (["login"], False),
        ]:
            with self.subTest(argv=argv):
                self.assertEqual(sessions._interactive(argv), expected)

    def test_described_directories_carry_no_control_characters(self):
        listed = [sessions.Session(3, "/x/codex", "/tmp/evil\x1b[2Jdir\n", "resume")]
        text = sessions.describe(listed)
        self.assertNotIn("\x1b", text)
        self.assertEqual(text.count("\n"), 0)


if __name__ == "__main__":
    unittest.main()
