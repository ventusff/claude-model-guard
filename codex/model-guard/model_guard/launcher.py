"""Locate Codex and execute it directly on the caller's terminal."""
import json
import os
from pathlib import Path
import shutil
import uuid


def data_home():
    return Path(os.environ.get("MODEL_GUARD_CODEX_HOME", Path.home() / ".local/share/model-guard-codex"))


def find_codex():
    candidate = os.environ.get("MODEL_GUARD_CODEX_BIN") or shutil.which("codex")
    if not candidate or not Path(candidate).is_file() or not os.access(candidate, os.X_OK):
        raise RuntimeError("A working Codex executable is required")
    return str(Path(candidate).absolute())


def atomic_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex)
    try:
        with temporary.open("x") as stream:
            temporary.chmod(0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def run(args):
    state = json.loads((data_home() / "install.json").read_text())
    binary = state.get("native_binary")
    if not binary or not Path(binary).is_file():
        raise RuntimeError("Install the native Model Guard package first")
    os.execv(binary, [binary, *args])
