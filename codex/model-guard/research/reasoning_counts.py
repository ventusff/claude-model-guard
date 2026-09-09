#!/usr/bin/env python3
"""Read Codex response-usage records and emit aggregates only, without transcripts.

Usage: python3 reasoning_counts.py /explicit/session/date/directory [...]
Only structured token_usage_record records with response IDs are counted.
Older token_count snapshots are deliberately excluded from this audit.
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re


MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}\Z")
EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "unknown"}


def aggregate(paths):
    groups = defaultdict(Counter)
    seen = set()
    files = sorted({p for root in paths for p in ([root] if root.is_file() else root.rglob("*.jsonl"))})
    for path in files:
        model, effort = "unknown", "unknown"
        # Bound a read of an active session at its initial size.
        with path.open("rb") as stream:
            remaining = path.stat().st_size
            while remaining > 0:
                line = stream.readline(remaining)
                remaining -= len(line)
                if not line:
                    break
                if b'"turn_context"' not in line and b'"token_usage_record"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                body = row.get("payload") or {}
                if not isinstance(body, dict):
                    continue
                if row.get("type") == "turn_context":
                    model, effort = body.get("model", "unknown"), body.get("effort", "unknown")
                    model = model if isinstance(model, str) and MODEL.fullmatch(model) else "unknown"
                    effort = effort if isinstance(effort, str) and effort in EFFORTS else "unknown"
                elif row.get("type") == "token_usage_record":
                    rid = body.get("response_id")
                    usage = body.get("usage") or {}
                    tokens = usage.get("reasoning_output_tokens") if isinstance(usage, dict) else None
                    if not isinstance(rid, str) or rid in seen or type(tokens) is not int or tokens < 0:
                        continue
                    if not isinstance(model, str) or not isinstance(effort, str):
                        continue
                    seen.add(rid)
                    groups[(model, effort)][tokens] += 1
    rows = []
    for (model, effort), counts in sorted(groups.items()):
        n = sum(counts.values())
        rows.append({
            "requested_model": model, "effort": effort, "responses": n,
            "zero": counts[0], "exact_516": counts[516],
            "exact_1034": counts[1034], "exact_1552": counts[1552],
            "ladder_hits": sum(count for value, count in counts.items() if value >= 516 and (value + 2) % 518 == 0),
            "mean_reasoning_tokens": round(sum(value * count for value, count in counts.items()) / n, 2),
            "top_counts": counts.most_common(5),
        })
    return {"files": len(files), "source": "token_usage_record; response_id deduplicated",
            "groups": rows, "backend_identity_verified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="+")
    args = parser.parse_args()
    for path in args.paths:
        if not path.exists():
            parser.error("An input path does not exist")
    print(json.dumps(aggregate(args.paths), ensure_ascii=False, indent=2))
