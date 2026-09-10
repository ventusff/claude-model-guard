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


# Subcommands that never open the interactive TUI, and the flag of the sandbox
# helper the TUI re-executes itself as for each command it runs.
NOT_A_SESSION = {"exec", "app-server", "mcp-server", "mcp", "login", "logout", "completion",
                 "sandbox", "debug", "apply", "cloud", "features", "review", "--apply-seccomp-then-exec"}
# Top-level options that take the next token as their value.
VALUE_OPTIONS = {"-m", "--model", "-p", "--profile", "-c", "--config", "-C", "--cd", "-s", "--sandbox",
                 "-a", "--ask-for-approval", "-i", "--image", "--add-dir", "--remote", "--enable", "--disable",
                 "--local-provider", "--oss-provider"}


def _interactive(argv):
    """Whether argv opens a TUI session: no subcommand, `resume` or `fork`.

    The first bare token decides; a prompt given on the command line is such a
    token too, and it is not a subcommand, so it counts as a session.
    """
    if "--apply-seccomp-then-exec" in argv:
        return False
    skip = False
    for arg in argv:
        if skip:
            skip = False
            continue
        if arg in NOT_A_SESSION:
            return False
        if arg in VALUE_OPTIONS:
            skip = True
        elif not arg.startswith("-"):
            return True
    return True


def running():
    """This user's interactive Codex sessions, oldest first.

    Helpers Codex spawns from a session and non-interactive runs share the
    executable name but are not sessions anyone resumes, so they are left out.
    """
    sessions = []
    for pid, executable in _processes():
        if Path(executable.removesuffix(" (deleted)")).name != "codex":
            continue
        try:
            argv = [arg.decode(errors="replace") for arg in (PROC / str(pid) / "cmdline").read_bytes().split(b"\0")[1:] if arg]
            cwd = os.readlink(PROC / str(pid) / "cwd")
        except OSError:
            continue
        if not _interactive(argv):
            continue
        command = _text(" ".join(argv), 100)
        sessions.append(Session(pid, executable, cwd, command or "codex"))
    return sorted(sessions, key=lambda session: session.pid)


def not_running(executable):
    """Running sessions that use any executable other than `executable`."""
    return [session for session in running() if not session.runs(executable)]


def describe(sessions):
    """One line per session for a terminal; paths and arguments are stripped of control characters."""
    return "\n".join(f"  pid {session.pid} · {_text(session.cwd, 200)} · codex {session.command}" for session in sessions)
