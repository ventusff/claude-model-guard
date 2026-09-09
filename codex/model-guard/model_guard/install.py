"""Transactional activation and reversible shell integration; no Codex config/auth writes."""

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import uuid
import venv

from . import __version__
from .launcher import atomic_json, data_home


START = "# >>> model-guard-codex >>>"
END = "# <<< model-guard-codex <<<"
BLOCK = re.compile(r"(?m)^" + re.escape(START) + r"\n.*?^" + re.escape(END) + r"\n?", re.S)


def replace_block(text, block):
    if text.count(START) != text.count(END) or text.count(START) > 1:
        raise RuntimeError("Incomplete or duplicate Model Guard shell markers; repair that block before installing")
    if START in text:
        return BLOCK.sub(lambda _: block, text)
    if not block:
        return text
    return text + ("\n" if text and not text.endswith("\n") else "") + block


def shell_block(root):
    directory = str(root / "bin")
    return (
        START + "\n"
        + "case \":${PATH}:\" in\n"
        + "  *" + shlex.quote(":" + directory + ":") + "*) ;;\n"
        + "  *) export PATH=" + shlex.quote(directory) + ":\"${PATH}\" ;;\n"
        + "esac\n" + END + "\n"
    )


def atomic_text(path, text, mode=None):
    # Follow an existing dotfile symlink rather than replacing the user's dotfile link.
    path = path.resolve() if path.is_symlink() else path
    existing_mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    temporary = path.with_name(path.name + ".model-guard-" + uuid.uuid4().hex)
    try:
        temporary.write_text(text)
        temporary.chmod(mode if mode is not None else existing_mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def link(path, target):
    temporary = path.with_name(path.name + ".model-guard-" + uuid.uuid4().hex)
    try:
        temporary.symlink_to(target)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def install(source, language=None, modify_shell=True):
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11 or newer is required")
    if not shutil.which("tmux") or not shutil.which("codex"):
        raise RuntimeError("Install the official Codex CLI and tmux before Model Guard")
    root = data_home().expanduser().absolute()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    bindir = root / "bin"
    bindir.mkdir(exist_ok=True)
    for name in ("codex", "model-guard-codex"):
        path = bindir / name
        if path.exists() and "model-guard-codex managed launcher" not in path.read_text():
            raise RuntimeError(f"Refusing to replace unmanaged launcher: {path}")
    rc_paths = []
    if modify_shell:
        rc_paths = [Path.home() / ".bashrc", Path.home() / ".profile"]
        zsh = Path.home() / ".zshrc"
        if zsh.exists() or Path(os.environ.get("SHELL", "")).name == "zsh":
            rc_paths.append(zsh)
    changes = []
    for path in rc_paths:
        before = path.read_text() if path.exists() else ""
        after = replace_block(before, shell_block(root))
        changes.append((path, before, after))
    # Every upgrade gets its own venv. Activation is one symlink replacement;
    # a failed install cannot break a working version or its running sessions.
    environment = root / "envs" / (__version__ + "-" + uuid.uuid4().hex[:8])
    venv.create(environment, with_pip=True)
    python = environment / "bin/python"
    try:
        subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--require-hashes", "-r", str(source / "requirements.lock")], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", str(source)], check=True)
        subprocess.run([str(environment / "bin/model-guard-codex"), "--version"], check=True)
    except BaseException:
        shutil.rmtree(environment)
        raise
    backups = root / "backups"
    backups.mkdir(exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    for path, before, after in changes:
        if before != after:
            backup = backups / (path.name.lstrip(".") + "-" + stamp + ".bak")
            atomic_text(backup, before, 0o600)
    cfg_path = root / "config.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {"language": "en", "show_account": True}
    if language:
        cfg["language"] = language
    atomic_json(cfg_path, cfg)
    for name, suffix in (("codex", " run"), ("model-guard-codex", "")):
        text = "#!/bin/sh\n# model-guard-codex managed launcher\n"
        text += "export MODEL_GUARD_CODEX_HOME=" + shlex.quote(str(root)) + "\n"
        text += "exec " + shlex.quote(str(root / "current/bin/model-guard-codex")) + suffix + ' "$@"\n'
        atomic_text(bindir / name, text, 0o755)
    link(root / "current", environment)
    for path, before, after in changes:
        # Catch another session's intervening dotfile write instead of overwriting it.
        current = path.read_text() if path.exists() else ""
        if current != before:
            after = replace_block(current, shell_block(root))
        atomic_text(path, after)
    state_path = root / "install.json"
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    shell_files = sorted(set(previous.get("shell_files", [])) | {str(p) for p in rc_paths})
    atomic_json(state_path, {"version": __version__, "shell_files": shell_files})
    print(f"Installed Model Guard {__version__}. In a new terminal, use codex normally.\nCommands: {bindir / 'model-guard-codex'}\nSettings: {cfg_path}")
    return 0


def remove():
    root = data_home().expanduser().absolute()
    state_path = root / "install.json"
    if not state_path.exists():
        raise RuntimeError("No managed Model Guard installation record was found")
    state = json.loads(state_path.read_text())
    expected = shell_block(root)
    for name in state.get("shell_files", []):
        path = Path(name)
        if path.exists():
            content = path.read_text()
            match = BLOCK.search(content)
            if match and match[0] != expected:
                raise RuntimeError(f"Model Guard shell block was edited; inspect it before removal: {path}")
    for name in state.get("shell_files", []):
        path = Path(name)
        if path.exists():
            atomic_text(path, replace_block(path.read_text(), ""))
    for name in ("codex", "model-guard-codex"):
        path = root / "bin" / name
        if path.exists() and "model-guard-codex managed launcher" in path.read_text():
            path.unlink()
    # Preserve environments while existing Codex sessions may still execute them,
    # along with settings/backups. No processes or Codex-managed files are touched.
    print("Model Guard shell integration removed. New terminals use official Codex. Existing guarded sessions can finish normally; settings and backups are retained.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Install the model-guard Codex launcher")
    parser.add_argument("--language", choices=("en", "zh"))
    parser.add_argument("--no-shell", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    try:
        return install(source, args.language, not args.no_shell)
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Model Guard installation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
