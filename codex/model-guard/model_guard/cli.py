"""Native installation diagnostics and independent routing probes."""

import json
from pathlib import Path
import sys

from . import __version__


def main():
    from .launcher import data_home, find_codex, run

    args = sys.argv[1:]
    command = args.pop(0) if args else "help"
    try:
        if command == "run":
            return run(args)
        if command in ("status", "check"):
            print("Live routing evidence and 516 details are available in Codex with /status. Use probe for a separate request.")
            return 4
        if command == "probe":
            import argparse
            import asyncio
            from .check import format_result, probe

            parser = argparse.ArgumentParser(prog="model-guard-codex " + command)
            parser.add_argument("--json", action="store_true", help="Output shareable routing metadata without account identifiers")
            parser.add_argument("-m", "--model", help="Model for this separate probe only")
            parser.add_argument("-r", "--reasoning", choices=("minimal", "low", "medium", "high", "xhigh", "max", "ultra"))
            parser.add_argument("--timeout", type=int, default=120)
            opts = parser.parse_args(args)
            if not 1 <= opts.timeout <= 600:
                parser.error("--timeout must be between 1 and 600 seconds")
            if not opts.json:
                print("Running one separate read-only probe; this uses your configured provider and quota.", flush=True)
            result = asyncio.run(probe(find_codex(), model=opts.model, effort=opts.reasoning, timeout=opts.timeout))
            print(json.dumps(result, ensure_ascii=False, indent=2) if opts.json else format_result(result))
            return result["exit_code"]
        if command == "doctor":
            from .install import sha256
            state = json.loads((data_home() / "install.json").read_text())
            binary = Path(state["native_binary"])
            valid = sha256(binary) == state["binary_sha256"] and Path(state["entry"]).resolve() == binary
            print(f"Model Guard {__version__} · native TUI\nEntry: {state['entry']}\nRuntime verified: {valid}\nDetails: /status inside Codex")
            return 0 if valid else 1
        if command in ("--version", "version"):
            print(__version__)
            return 0
        if command == "remove":
            from .install import remove
            return remove()
        print("Model Guard for Codex\n\n  model-guard-codex run [Codex arguments]\n  model-guard-codex probe [--json] [-m MODEL] [-r EFFORT]\n  model-guard-codex doctor\n  model-guard-codex remove\n\nUse codex or cx normally, including resume and fork. Evidence details: /status.")
        return 0 if command in ("help", "--help", "-h") else 2
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(f"Model Guard: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
