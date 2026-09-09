import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from model_guard.launcher import atomic_json, run


class LauncherTests(unittest.TestCase):
    def test_all_arguments_reach_native_codex_without_terminal_or_transport_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "codex"
            binary.touch()
            atomic_json(root / "install.json", {"native_binary": str(binary)})
            for args in ([], ["resume", "--last"], ["fork", "a-thread"], ["--profile", "work"], ["--remote", "unix://x"], ["--", "exec"]):
                with self.subTest(args=args), patch.dict(os.environ, {"MODEL_GUARD_CODEX_HOME": temp}), patch("os.execv") as execute:
                    run(args)
                    execute.assert_called_once_with(str(binary), [str(binary), *args])
