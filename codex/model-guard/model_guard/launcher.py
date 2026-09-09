"""Run stock Codex in its own terminal session, with a private metadata observer."""

import asyncio
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import re
import subprocess
import sys
import tempfile
import time

from . import __version__
from .state import State


def data_home():
    return Path(os.environ.get("MODEL_GUARD_CODEX_HOME", Path.home() / ".local/share/model-guard-codex"))


def find_codex():
    override = os.environ.get("MODEL_GUARD_CODEX_BIN")
    if override:
        path = Path(override).expanduser().absolute()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError("MODEL_GUARD_CODEX_BIN must name an executable Codex binary")
        if path.resolve() == (data_home() / "bin/codex").resolve():
            raise RuntimeError("MODEL_GUARD_CODEX_BIN must point to official Codex, not the guard launcher")
        return str(path)
    own_bin = (data_home() / "bin").resolve()
    candidates = [p for p in os.get_exec_path() if Path(p).resolve() != own_bin]
    path = shutil.which("codex", path=os.pathsep.join(candidates))
    if not path:
        raise RuntimeError("Official Codex CLI was not found on PATH")
    return path


VALUE_OPTIONS = {
    "-c", "--config", "-m", "--model", "-p", "--profile", "-s", "--sandbox",
    "-a", "--ask-for-approval", "-C", "--cd", "-i", "--image", "--add-dir",
    "--enable", "--disable", "--local-provider", "--remote", "--remote-auth-token-env",
}
COMMANDS = {
    "agents", "exec", "e", "review", "login", "logout", "mcp", "plugin", "mcp-server",
    "app-server", "remote-control", "completion", "update", "doctor", "sandbox", "debug",
    "apply", "a", "queue", "archive", "delete", "migrate-rollouts", "unarchive", "cloud",
    "exec-server", "features", "help",
    "resume", "fork",
}


def arguments(args):
    """Yield (start, end, option, value); keep delimiters and positional text intact."""
    i = 0
    while i < len(args):
        start, arg = i, args[i]
        if arg == "--":
            yield i, i + 1, "--", None
            break
        key, equal, value = arg.partition("=")
        attached = bool(equal)
        if len(arg) > 2 and not arg.startswith("--") and arg[:2] in VALUE_OPTIONS:
            key, value, attached = arg[:2], arg[2:].removeprefix("="), True
        if key in VALUE_OPTIONS:
            if not attached:
                i += 1
                value = args[i] if i < len(args) else None
            yield start, min(i + 1, len(args)), key, value
        else:
            yield start, i + 1, arg, None
        i += 1


def normalize_args(args):
    result = list(args)
    # Normalize before changing directory. Splice backwards to preserve indices.
    for start, end, key, value in reversed(list(arguments(args))):
        if key in ("-C", "--cd") and value is not None:
            result[start:end] = [key, str(Path(value).expanduser().absolute())]
    return result


def should_wrap(args):
    if os.environ.get("MODEL_GUARD_ACTIVE") or not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    positional = None
    for _, _, key, value in arguments(args):
        if key == "--":
            break
        if key in ("--help", "-h", "--version", "-V", "--remote", "--profile", "-p", "--oss", "--local-provider"):
            return False
        if key not in VALUE_OPTIONS and not key.startswith("-") and positional is None:
            positional = key
    return positional not in COMMANDS


def server_options(args):
    """Forward config flags, never prompts, images or credentials parsed from config files."""
    result, cwd = [], os.getcwd()
    for _, _, key, value in arguments(args):
        if key in ("-c", "--config", "--enable", "--disable") and value is not None:
            result.extend([key, value])
        elif key in ("-C", "--cd") and value is not None:
            cwd = str(Path(value).expanduser().absolute())
        elif key == "--strict-config":
            result.append(key)
    return result, cwd


def config():
    path = data_home() / "config.json"
    if not path.exists():
        return {"language": "zh" if os.environ.get("LANG", "").startswith("zh") else "en", "show_account": True}
    value = json.loads(path.read_text())
    return {"language": "zh" if value.get("language") == "zh" else "en", "show_account": value.get("show_account", True) is True}


def atomic_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False))
    temp.chmod(0o600)
    temp.replace(path)


def run(args):
    official = find_codex()
    if not should_wrap(args):
        unsupported = any(key in ("--remote", "--profile", "-p", "--oss", "--local-provider", "resume", "fork") for _, _, key, _ in arguments(args))
        if sys.stdin.isatty() and sys.stdout.isatty() and not os.environ.get("MODEL_GUARD_ACTIVE") and unsupported:
            print("Model Guard: this resume/fork/profile/remote/local-model launch uses official Codex directly; the routing band is unavailable.", file=sys.stderr)
        os.execv(official, [official, *args])
    if not shutil.which("tmux"):
        raise RuntimeError("tmux is required for the model-guard band; install tmux or run the official Codex binary directly")
    version = subprocess.check_output([official, "--version"], text=True)
    match = re.search(r"codex-cli (\d+)\.(\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (0, 153, 4):
        raise RuntimeError("Model Guard requires official Codex 0.153.4 or newer")
    args = normalize_args(args)
    _, cwd = server_options(args)
    # Unix socket paths have a small platform limit; use a short, owner-only directory.
    runtime = Path(tempfile.mkdtemp(prefix="mg-", dir=os.environ.get("MODEL_GUARD_RUNTIME_DIR")))
    socket = runtime / "tmux.sock"
    cfg = config()
    atomic_json(runtime / "state.json", State(**cfg).snapshot())
    (runtime / "owner").write_text(str(os.getuid()))
    terminal = shutil.get_terminal_size((120, 40))
    truecolor = os.environ.get("COLORTERM") in ("truecolor", "24bit")
    lines = [
        "set -g status 2", "set -g status-position bottom", "set -g status-interval 1",
        "set -g status-style fg=colour231,bg=colour124", "set -g status-justify left",
        "set -g prefix None", "set -g prefix2 None", "set -g history-limit 10000",
        "set -g default-terminal tmux-256color", "set -g exit-empty on",
        "set -g set-clipboard on", "set -g allow-passthrough on",
    ]
    if truecolor:
        lines.append("set -as terminal-features ',*:RGB'")
    for row in range(2):
        command = shlex.join([sys.executable, "-I", "-m", "model_guard.cli", "_band", str(runtime), str(row)])
        command = command.replace("#", "##") + " #{client_width}"
        lines.append(f"set -g status-format[{row}] " + shlex.quote(f"#({command})"))
    (runtime / "tmux.conf").write_text("\n".join(lines) + "\n")
    tmux = ["tmux", "-S", str(socket)]
    env = dict(os.environ)
    # Only this child uses the nested server. Existing panes and keymaps are untouched.
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)
    command = [sys.executable, "-I", "-m", "model_guard.cli", "_session", str(runtime), official, *args]
    try:
        subprocess.run([
            *tmux, "-f", str(runtime / "tmux.conf"), "new-session", "-d", "-s", "guard",
            "-x", str(terminal.columns), "-y", str(terminal.lines), "-c", cwd, *command,
        ], env=env, check=True)
        code = subprocess.call([*tmux, "attach-session", "-t", "guard"], env=env)
        alive = subprocess.call([*tmux, "has-session", "-t", "guard"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
        if alive:
            print("Model Guard session is still running. Resume: " + shlex.join([*tmux, "attach", "-t", "guard"]))
            return code
        result = runtime / "exit-code"
        return int(result.read_text()) if result.exists() else 1
    except subprocess.CalledProcessError:
        raise RuntimeError("The private tmux session could not be started") from None
    finally:
        if not socket.exists():
            shutil.rmtree(runtime, ignore_errors=True)


async def session(runtime, official, args):
    from .relay import Relay

    runtime = Path(runtime)
    os.umask(0o077)
    os.environ["MODEL_GUARD_SESSION"] = str(runtime)
    os.environ["MODEL_GUARD_ACTIVE"] = "1"
    cfg = config()
    state = State(**cfg)
    options, cwd = server_options(args)
    relay = Relay([official, *options, "app-server", "--stdio"], state, cwd)
    ui = None

    async def publish():
        while True:
            atomic_json(runtime / "state.json", state.snapshot())
            relay.changed.clear()
            try:
                await asyncio.wait_for(relay.changed.wait(), 1)
                await asyncio.sleep(0.05)
            except asyncio.TimeoutError:
                pass

    publisher = asyncio.create_task(publish())
    try:
        await relay.start()
        endpoint = runtime / "rpc.sock"
        async with relay.serve(endpoint):
            env = dict(os.environ, MODEL_GUARD_ACTIVE="1", MODEL_GUARD_SESSION=str(runtime))
            ui = await asyncio.create_subprocess_exec(official, "--remote", "unix://" + str(endpoint), *args, env=env)
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGHUP):
                loop.add_signal_handler(sig, lambda s=sig: ui.send_signal(s) if ui.returncode is None else None)
            code = await ui.wait()
            (runtime / "exit-code").write_text(str(code))
            return code
    finally:
        if not (runtime / "exit-code").exists():
            (runtime / "exit-code").write_text("1")
        publisher.cancel()
        await asyncio.gather(publisher, return_exceptions=True)
        await relay.close()


def read_snapshot(runtime):
    path = Path(runtime) / "state.json"
    try:
        if path.stat().st_uid != os.getuid():
            raise ValueError("wrong owner")
        snapshot = json.loads(path.read_text())
        age = time.time() - snapshot["updated_at"]
        if age > 5 or age < -5:
            snapshot["health"] = "observer heartbeat expired"
        return snapshot
    except (OSError, ValueError, KeyError, TypeError):
        return {"health": "observer unavailable"}
