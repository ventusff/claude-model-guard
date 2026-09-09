"""Verify shell activation and reversible installation with isolated user homes."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from model_guard.install import install, remove, replace_block, shell_block


class InstallTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("fish"), "Fish is not installed")
    def test_fish_resolves_guard_once_and_restores_official_after_removal(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            root = home / "a path with 'quotes' and \\backslashes"
            official = home / "official"
            for directory in (root / "bin", official):
                directory.mkdir(parents=True)
                (directory / "codex").write_text("#!/bin/sh\nexit 0\n")
                (directory / "codex").chmod(0o755)
            rc = home / "config.fish"
            original = "# user's settings\nset -gx EDITOR vim\n"
            rc.write_text(replace_block(original, shell_block(root, fish=True)))
            env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / "config"),
                       GUARD_TEST_RC=str(rc), GUARD_TEST_BIN=str(root / "bin"),
                       GUARD_ORIGINAL_BIN=str(official))
            script = ('set -gx PATH "$GUARD_ORIGINAL_BIN" /usr/bin /bin "$GUARD_TEST_BIN"; '
                      'source "$GUARD_TEST_RC"; source "$GUARD_TEST_RC"; '
                      'command -v codex; printf "%s\\n" $PATH; '
                      'set -q -U fish_user_paths; and echo unexpected_universal; true')
            result = subprocess.run([shutil.which("fish"), "--no-config", "-c", script],
                                    env=env, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.splitlines()[0], str(root / "bin/codex"))
            self.assertEqual(result.stdout.splitlines()[1:].count(str(root / "bin")), 1)
            self.assertNotIn("unexpected_universal", result.stdout)
            self.assertEqual(result.stderr, "")
            atomic_state = {"version": "test", "shell_files": [str(rc)]}
            (root / "install.json").write_text(json.dumps(atomic_state))
            (root / "bin/codex").write_text("# model-guard-codex managed launcher\n")
            rc.write_text(rc.read_text() + "set -gx AFTER_INSTALL kept\n")
            with patch.dict(os.environ, {"MODEL_GUARD_CODEX_HOME": str(root)}):
                self.assertEqual(remove(), 0)
            self.assertEqual(rc.read_text(), original + "set -gx AFTER_INSTALL kept\n")
            result = subprocess.run([shutil.which("fish"), "--no-config", "-c", script],
                                    env=env, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.splitlines()[0], str(official / "codex"))

    def test_install_and_remove_fish_with_xdg_symlink_and_existing_edits(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as temp:
                home = Path(temp)
                root = home / "guard"
                xdg = home / "custom-config"
                rc = xdg / "fish/config.fish"
                target = home / "fish-dotfile"
                if existing:
                    rc.parent.mkdir(parents=True)
                    target.write_text("set -gx EDITOR vim\n")
                    target.chmod(0o600)
                    rc.symlink_to(target)
                env = {"MODEL_GUARD_CODEX_HOME": str(root), "XDG_CONFIG_HOME": str(xdg),
                       "SHELL": "/bin/bash" if existing else "/usr/bin/fish"}
                with patch.dict(os.environ, env), patch("pathlib.Path.home", return_value=home), \
                     patch("model_guard.install.shutil.which", return_value="/fake/tool"), \
                     patch("model_guard.install.venv.create"), patch("model_guard.install.subprocess.run"):
                    self.assertEqual(install(home / "source"), 0)
                    before = rc.read_text()
                    self.assertEqual(install(home / "source"), 0)
                    self.assertEqual(rc.read_text(), before)
                    self.assertIn("fish_add_path --path --move", before)
                    self.assertIn(str(rc), json.loads((root / "install.json").read_text())["shell_files"])
                    rc.write_text(before + "set -gx NEW_SETTING kept\n")
                    self.assertEqual(remove(), 0)
                expected = ("set -gx EDITOR vim\n" if existing else "") + "set -gx NEW_SETTING kept\n"
                self.assertEqual(rc.read_text(), expected)
                if existing:
                    self.assertTrue(rc.is_symlink())
                    self.assertEqual(target.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
