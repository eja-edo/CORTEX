#!/usr/bin/env python3
"""
Query structured tool execution logs.

Reads from logs/tool-executions.jsonl (or TOOL_LOG_DIR env var).
Filters, aggregates, and prints results.

Usage:
    python -m scripts.query_tool_logs --tool search_notes --failed
    python -m scripts.query_tool_logs --user <uuid>  --from 2026-07-01 --stats
    python -m scripts.query_tool_logs --help
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Query tool execution logs")
    parser.add_argument("--tool", help="Filter by tool name")
    parser.add_argument("--user", help="Filter by user_id")
    parser.add_argument("--conv", help="Filter by conversation_id")
    parser.add_argument("--from", dest="from_ts", help="Start timestamp (ISO 8601, inclusive)")
    parser.add_argument("--to", dest="to_ts", help="End timestamp (ISO 8601, inclusive)")
    parser.add_argument("--failed", action="store_true", help="Show only failed calls")
    parser.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    parser.add_argument("--stats", action="store_true", help="Show aggregate statistics")
    parser.add_argument("--json", action="store_true", help="Raw JSONL output")
    args = parser.parse_args()

    log_dir = Path(os.getenv("TOOL_LOG_DIR", "logs"))
    log_file = log_dir / "tool-executions.jsonl"

    if not log_file.exists():
        print(f"No log file found at {log_file}", file=sys.stderr)
        sys.exit(1)

    entries = []
    with open(log_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    def matches(e: dict) -> bool:
        if args.tool and e.get("tool_name") != args.tool:
            return False
        if args.user and e.get("user_id") != args.user:
            return False
        if args.conv and e.get("conversation_id") != args.conv:
            return False
        if args.from_ts and e.get("timestamp", "") < args.from_ts:
            return False
        if args.to_ts and e.get("timestamp", "") > args.to_ts:
            return False
        if args.failed and e.get("success") is not False:
            return False
        return True

    filtered = [e for e in entries if matches(e)]
    results = filtered[-args.limit :]

    if args.stats:
        succeeded = sum(1 for e in filtered if e.get("success"))
        failed = len(filtered) - succeeded
        durations = [e.get("duration_ms", 0) for e in filtered]
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        by_tool = Counter(e.get("tool_name", "?") for e in filtered)

        print(
            json.dumps(
                {
                    "total_logs": len(entries),
                    "matched": len(filtered),
                    "succeeded": succeeded,
                    "failed": failed,
                    "avg_duration_ms": round(avg_duration, 1),
                    "by_tool": dict(by_tool),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.json:
        for e in results:
            print(json.dumps(e, ensure_ascii=False))
    else:
        print(f"Matched {len(filtered)} entries (showing last {len(results)}):\n")
        for e in results:
            status = "OK" if e.get("success") else "FAIL"
            err = e.get("error") or ""
            print(
                f"[{e.get('timestamp', '?')[:19]}] {status} "
                f"{e.get('tool_name', '?'):<16} "
                f"{e.get('duration_ms', 0):>8.1f}ms"
                + (f"  {err}" if err else "")
            )


if __name__ == "__main__":
    main()
