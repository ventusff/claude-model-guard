"""Exercise the real tmux client and stock TUI in a PTY, without opening a desktop window."""

import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

from test_integration import ResponsesFixture


@unittest.skipUnless(os.environ.get("MODEL_GUARD_INTEGRATION") == "1", "requires stock Codex and tmux")
class TerminalTests(unittest.TestCase):
    def test_footer_survives_tui_render_and_resize(self):
        self.exercise("gpt-4o", marker=b"ROUTE DIFF")

    def test_516_warning_survives_tui_render_and_resize(self):
        self.exercise(None, reasoning=[516], marker=b"516 WATCH")

    def exercise(self, model, reasoning=None, marker=b"ROUTE DIFF"):
        with tempfile.TemporaryDirectory(prefix="mg-pty-") as temp, ResponsesFixture(model, reasoning) as api:
            home = Path(temp)
            codex = home / "codex"
            codex.mkdir()
            (codex / "config.toml").write_text(
                'model = "gpt-6-astra"\nmodel_provider = "fixture"\nmodel_reasoning_effort = "high"\n'
                'check_for_update_on_startup = false\n'
                '[model_providers.fixture]\nname = "Fixture"\nwire_api = "responses"\n'
                f'base_url = "http://127.0.0.1:{api.server.server_port}/v1"\n'
                'requires_openai_auth = false\nsupports_websockets = false\n'
            )
            env = {k: v for k, v in os.environ.items() if not k.startswith(("CODEX_", "OPENAI_", "MODEL_GUARD_", "TMUX"))}
            env.update(CODEX_HOME=str(codex), MODEL_GUARD_CODEX_HOME=str(home / "guard"), MODEL_GUARD_RUNTIME_DIR=temp,
                       TERM="xterm-256color", COLORTERM="truecolor", PYTHONPATH=str(Path(__file__).resolve().parents[1]))
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 140, 0, 0))
            process = subprocess.Popen([sys.executable, "-m", "model_guard.cli", "run", "-C", temp, "--sandbox", "read-only", "--ask-for-approval", "never", "Reply OK."], env=env,
                                       stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
            os.close(slave)
            output = bytearray()
            runtime = None
            try:
                deadline = time.monotonic() + 35
                last_enter = time.monotonic()
                while time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        try:
                            data = os.read(master, 65536)
                        except OSError:
                            break
                        output.extend(data)
                        # Answer standard terminal capability queries in this headless PTY.
                        if b"\x1b[6n" in data:
                            os.write(master, b"\x1b[1;1R")
                        if b"\x1b[c" in data or b"\x1b[0c" in data:
                            os.write(master, b"\x1b[?1;2c")
                        if b"\x1b[>c" in data or b"\x1b[>0c" in data:
                            os.write(master, b"\x1b[>0;136;0c")
                    states = list(home.glob("mg-*/state.json"))
                    if states:
                        runtime = states[0].parent
                    if runtime and not api.requests and time.monotonic() - last_enter > 4:
                        screen = subprocess.check_output(["tmux", "-S", str(runtime / "tmux.sock"), "capture-pane", "-p"], text=True)
                        if any(text in screen.lower() for text in ("press enter", "continue", "trust this", "trust the")):
                            os.write(master, b"\r")
                        last_enter = time.monotonic()
                    if marker in output and b"account unknown" in output:
                        break
                if marker not in output:
                    screen = subprocess.check_output(["tmux", "-S", str(runtime / "tmux.sock"), "capture-pane", "-p"], text=True) if runtime else "no tmux runtime"
                    self.fail("Footer did not report the expected warning. Terminal:\n" + screen[-2000:])
                self.assertIsNotNone(runtime)
                snapshot = json.loads((runtime / "state.json").read_text())
                self.assertEqual(snapshot["thread"]["observed"], model)
                if reasoning:
                    self.assertEqual(snapshot["thread"]["reasoning"]["last_tokens"], 516)
                # Resize while Codex owns the screen, then check the second footer row.
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 80, 0, 0))
                os.killpg(process.pid, signal.SIGWINCH)
                resized = bytearray()
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        resized.extend(os.read(master, 65536))
                    if marker in resized and b"account unknown" in resized:
                        break
                self.assertTrue(marker in resized and b"account unknown" in resized, "Both footer rows must survive resize to 80 columns")
                os.write(master, b"\x03")
                time.sleep(0.2)
                os.write(master, b"\x03")
                process.wait(timeout=10)
            finally:
                # Only terminate the test's unique tmux server/process, never other sessions.
                if runtime:
                    subprocess.run(["tmux", "-S", str(runtime / "tmux.sock"), "kill-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                os.close(master)


if __name__ == "__main__":
    unittest.main()
