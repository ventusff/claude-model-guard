import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from model_guard.install import replace_block, shell_block
from model_guard.launcher import atomic_json, normalize_args, read_snapshot, server_options, should_wrap


class LauncherTests(unittest.TestCase):
    def wrap(self, args):
        with patch.dict(os.environ, {}, clear=True), patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True):
            return should_wrap(args)

    def test_only_interactive_commands_are_wrapped(self):
        for args in ([], ["-m", "exec", "explain this"], ["--", "exec"]):
            self.assertTrue(self.wrap(args), args)
        for args in (["exec", "task"], ["-c", "model='gpt-6-astra'", "review"], ["plugin", "add", "test"], ["resume", "--last"], ["fork", "a-thread"], ["resume", "--help"], ["--profile", "work"], ["--remote=unix://x"]):
            self.assertFalse(self.wrap(args), args)

    def test_noninteractive_passthrough(self):
        with patch("sys.stdin.isatty", return_value=False):
            self.assertFalse(should_wrap([]))

    def test_server_options_never_copy_prompt_as_configuration(self):
        args, cwd = server_options(["-c", "model='gpt-6-astra'", "--enable=test", "-C", "/tmp", "Look at --config secret", "--disable=irrelevant"])
        self.assertEqual(args, ["-c", "model='gpt-6-astra'", "--enable", "test", "--disable", "irrelevant"])
        self.assertEqual(cwd, "/tmp")

    def test_relative_cwd_is_normalized_before_tmux_changes_directory(self):
        for flags in (["-C", "project"], ["--cd=project"], ["-Cproject"]):
            with patch("os.getcwd", return_value="/work"):
                args = normalize_args([*flags, "fix this"])
            self.assertEqual(args[1], "/work/project")
            with patch("os.getcwd", return_value="/work/project"):
                self.assertEqual(server_options(args)[1], "/work/project")

    def test_flags_after_resume_id_reach_the_server(self):
        args, _ = server_options(["resume", "thread-uuid", "--config", "model_provider='custom'", "-cmodel_providers.custom.name='Custom'"])
        self.assertEqual(args, ["--config", "model_provider='custom'", "-c", "model_providers.custom.name='Custom'"])
        self.assertEqual(server_options(["--", "-c", "ignored=true"])[0], [])

    def test_codex_delimiter_is_preserved(self):
        from model_guard.cli import main
        with patch("sys.argv", ["model-guard-codex", "run", "--", "exec"]), patch("model_guard.launcher.run", return_value=0) as run:
            self.assertEqual(main(), 0)
            run.assert_called_once_with(["--", "exec"])

    def test_shell_setup_idempotent_and_removal_preserves_edits(self):
        original = "# user's config\nexport EDITOR=vim\n"
        block = shell_block(Path("/tmp/a path with 'quotes'"))
        installed = replace_block(original, block)
        self.assertEqual(replace_block(installed, block), installed)
        installed += "export NEW_SETTING=yes\n"
        self.assertEqual(replace_block(installed, ""), original + "export NEW_SETTING=yes\n")
        self.assertEqual(replace_block("unchanged", ""), "unchanged")

    def test_broken_markers_are_not_overwritten(self):
        with self.assertRaises(RuntimeError):
            replace_block("# >>> model-guard-codex >>>\n", "")

    def test_dead_observer_never_leaves_green_band(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.json"
            atomic_json(path, {"health": "connected", "updated_at": time.time() - 10})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(read_snapshot(temp)["health"], "observer heartbeat expired")
            path.write_text("{broken")
            self.assertEqual(read_snapshot(temp)["health"], "observer unavailable")


if __name__ == "__main__":
    unittest.main()
