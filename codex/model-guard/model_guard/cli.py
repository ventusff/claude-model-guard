"""Native installation diagnostics and independent routing probes."""

import argparse
import json
from pathlib import Path
import sys

from . import __version__, sessions
from .launcher import data_home, find_codex, run


EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")


def installed_state():
    path = data_home() / "install.json"
    if not path.is_file():
        raise RuntimeError("Model Guard is not installed; run scripts/install.py from the plugin checkout")
    return json.loads(path.read_text())


def command_probe(args):
    import asyncio
    from .check import format_result, probe

    if not args.json:
        print("Running one separate read-only probe; this uses your configured provider and quota.", flush=True)
    result = asyncio.run(probe(find_codex(), model=args.model, effort=args.reasoning, timeout=args.timeout))
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else format_result(result))
    return result["exit_code"]


def command_doctor(args):
    from .install import sha256

    state = installed_state()
    binary = Path(state["native_binary"])
    entry = Path(state["entry"])
    intact = binary.is_file() and sha256(binary) == state["binary_sha256"]
    active = entry.is_symlink() and entry.resolve() == binary
    print(f"Model Guard {__version__} · native Codex build\nEntry: {entry}\nRuntime intact: {intact}\nEntry active: {active}")
    stale = sessions.not_running(binary)
    if stale:
        print(f"{len(stale)} running Codex session(s) still use another executable; finish or /quit each one, then `codex resume` in its directory:")
        print(sessions.describe(stale))
    print("Live evidence: /status inside Codex")
    return 0 if intact and active else 1


def command_remove(args):
    from .install import remove

    return remove()


def command_redirect(args):
    print("Live routing evidence and 516 details are available in Codex with /status. Use probe for a separate request.")
    return 4


def parser():
    top = argparse.ArgumentParser(prog="model-guard-codex", description="Model Guard for Codex CLI. Use codex or cx normally, including resume and fork; evidence details are in /status.")
    top.add_argument("--version", action="version", version=__version__)
    commands = top.add_subparsers(dest="command", metavar="command")
    commands.add_parser("run", help="Execute the native Codex build with the given arguments", add_help=False)
    probe_command = commands.add_parser("probe", help="One separate ephemeral read-only routing probe (uses provider quota)")
    probe_command.add_argument("--json", action="store_true", help="Output shareable routing metadata without account identifiers")
    probe_command.add_argument("-m", "--model", help="Model for this separate probe only")
    probe_command.add_argument("-r", "--reasoning", choices=EFFORTS, help="Reasoning effort for this separate probe only")
    probe_command.add_argument("--timeout", type=int, default=120, choices=range(1, 601), metavar="SECONDS")
    probe_command.set_defaults(handler=command_probe)
    commands.add_parser("doctor", help="Verify the installed native executable and list sessions on another executable").set_defaults(handler=command_doctor)
    commands.add_parser("remove", help="Restore the original official Codex executable symlink").set_defaults(handler=command_remove)
    for legacy in ("status", "check"):
        commands.add_parser(legacy, help=argparse.SUPPRESS).set_defaults(handler=command_redirect)
    return top


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["run"]:
        try:
            return run(argv[1:])
        except (RuntimeError, OSError) as exc:
            print(f"Model Guard: {exc}", file=sys.stderr)
            return 1
    top = parser()
    args = top.parse_args(argv)
    if not args.command:
        top.print_help()
        return 0
    try:
        return args.handler(args)
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(f"Model Guard: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
