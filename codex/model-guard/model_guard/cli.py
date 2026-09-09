"""Public commands and private entry points for the per-session terminal wrapper."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from . import __version__


def main():
    from .launcher import config, data_home, find_codex, read_snapshot, run
    from .state import render, tmux_band

    args = sys.argv[1:]
    command = args.pop(0) if args else "help"
    try:
        if command == "run":
            return run(args)
        if command == "_session":
            import asyncio
            from .launcher import session
            return asyncio.run(session(args[0], args[1], args[2:]))
        if command == "_band":
            cfg = config()
            band, _ = tmux_band(
                read_snapshot(args[0]), cfg["language"], os.environ.get("COLORTERM") in ("truecolor", "24bit"),
                row=int(args[1]), width=min(1000, max(1, int(args[2]))),
            )
            print(band)
            return 0
        if command == "status":
            runtime = os.environ.get("MODEL_GUARD_SESSION")
            paths = [Path(runtime)] if runtime else sorted(Path(os.environ.get("MODEL_GUARD_RUNTIME_DIR", tempfile.gettempdir())).glob("mg-*/owner"))
            snapshots = []
            for path in paths:
                if not runtime:
                    if path.stat().st_uid != os.getuid():
                        continue
                    path = path.parent
                snapshot = read_snapshot(path)
                snapshot["session"] = str(path)
                snapshots.append(snapshot)
            if "--json" in args:
                print(json.dumps(snapshots, ensure_ascii=False, indent=2))
            else:
                for snapshot in snapshots:
                    print(render(snapshot, config()["language"])[1])
                if not snapshots:
                    print("No guarded Codex session is running.")
            return 0
        if command in ("check", "probe"):
            import argparse
            import asyncio
            from .check import format_result, probe, verdict

            parser = argparse.ArgumentParser(prog="model-guard-codex " + command)
            parser.add_argument("--json", action="store_true", help="Output shareable routing metadata without account identifiers")
            if command == "check":
                parser.add_argument("--session", default=os.environ.get("MODEL_GUARD_SESSION"), help="Guard session directory; defaults to this terminal's session")
            else:
                parser.add_argument("-m", "--model", help="Model for this separate probe only")
                parser.add_argument("-r", "--reasoning", choices=("minimal", "low", "medium", "high", "xhigh", "max", "ultra"))
                parser.add_argument("--timeout", type=int, default=120, help="Deadline in seconds (1–600)")
            opts = parser.parse_args(args)
            if command == "check":
                result = verdict(read_snapshot(opts.session) if opts.session else {})
            else:
                if not 1 <= opts.timeout <= 600:
                    parser.error("--timeout must be between 1 and 600 seconds")
                if not opts.json:
                    print("Running one separate read-only probe; this uses your configured provider and quota.", flush=True)
                result = asyncio.run(probe(find_codex(), model=opts.model, effort=opts.reasoning, timeout=opts.timeout))
            print(json.dumps(result, ensure_ascii=False, indent=2) if opts.json else format_result(result))
            return result["exit_code"]
        if command == "doctor":
            official = find_codex()
            version = subprocess.check_output([official, "--version"], text=True).strip()
            print(f"Model Guard {__version__}\nOfficial CLI: {official}\n{version}\ntmux: {shutil.which('tmux') or 'MISSING'}\nInstall: {data_home()}")
            print("Evidence: server model metadata; absence is UNVERIFIED. No hidden-backend attestation.")
            return 0 if shutil.which("tmux") else 1
        if command in ("--version", "version"):
            print(__version__)
            return 0
        if command == "remove":
            from .install import remove
            return remove()
        if command == "demo":
            from .state import State
            state = State()
            t = state.thread("demo")
            state.selected = t.id
            state.health = "connected"
            t.settings({"model": "gpt-6-astra", "modelProvider": "openai", "effort": "high"})
            t.begin_turn("demo-turn")
            state.set_account({"type": "chatgpt", "email": "you@example.com", "planType": "pro"})
            for actual in (None, "gpt-6-astra", "gpt-4o"):
                if actual:
                    t.observe(actual, "synthetic-demo")
                print(render(state.snapshot(), config()["language"])[1])
            return 0
        print("Model Guard for Codex\n\n  model-guard-codex run [Codex arguments]\n  model-guard-codex check [--json] [--session DIRECTORY]\n  model-guard-codex probe [--json] [-m MODEL] [-r EFFORT]\n  model-guard-codex status [--json]\n  model-guard-codex doctor\n  model-guard-codex demo\n  model-guard-codex remove\n\nAfter installation, use codex normally in a new terminal.")
        return 0 if command in ("help", "--help", "-h") else 2
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"Model Guard: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
