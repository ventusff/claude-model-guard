"""Running Codex processes of the current user, read from /proc.

A process keeps the executable it started with. Replacing the `codex` symlink
changes what the next invocation runs and nothing about sessions already open,
so the installer names those sessions instead of leaving the difference to be
discovered later.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import unicodedata


PROC = Path("/proc")


@dataclass(frozen=True)
class Session:
    pid: int
    executable: str
    cwd: str
    command: str

    def runs(self, executable):
        try:
            return os.path.samefile(self.executable, executable)
        except OSError:
            return self.executable == str(executable)

    def inside(self, directory):
        try:
            Path(self.executable).relative_to(directory)
        except ValueError:
            return False
        return True


def _text(value, limit=80):
    return "".join(c for c in value if unicodedata.category(c)[0] != "C")[:limit]


def _processes():
    """(pid, executable) of this user's other processes; a vanished process is skipped."""
    uid = os.getuid()
    for entry in PROC.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            yield int(entry.name), os.readlink(entry / "exe")
        except OSError:
            continue


def executables():
    """Resolved executables of every process this user runs, deleted or not."""
    return [Path(exe.removesuffix(" (deleted)")) for _, exe in _processes()]


def running():
    """This user's processes whose executable is named `codex`, oldest first."""
    sessions = []
    for pid, executable in _processes():
        if Path(executable.removesuffix(" (deleted)")).name != "codex":
            continue
        try:
            argv = (PROC / str(pid) / "cmdline").read_bytes().split(b"\0")[1:]
            cwd = os.readlink(PROC / str(pid) / "cwd")
        except OSError:
            continue
        command = " ".join(_text(arg.decode(errors="replace")) for arg in argv if arg).strip()
        sessions.append(Session(pid, executable, cwd, command or "codex"))
    return sorted(sessions, key=lambda session: session.pid)


def not_running(executable):
    """Running sessions that use any executable other than `executable`."""
    return [session for session in running() if not session.runs(executable)]


def describe(sessions):
    """One line per session for a terminal; paths and arguments are stripped of control characters."""
    return "\n".join(f"  pid {session.pid} · {_text(session.cwd, 200)} · codex {session.command}" for session in sessions)
