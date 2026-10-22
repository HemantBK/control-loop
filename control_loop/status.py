"""``python -m control_loop.status [root ...] [--json] [--phase NAME]``: every run.jsonl under the roots (default: results)."""
from __future__ import annotations

import argparse
import json
import sys

from control_loop.runlog import format_table, iter_runs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="*", default=["results"])
    ap.add_argument("--json", action="store_true", help="one JSON object per run")
    ap.add_argument("--phase", help="only runs whose phase equals this")
    ap.add_argument("--failed", action="store_true", help="only runs with a failed or stopped step")
    a = ap.parse_args(argv)
    runs = list(iter_runs(a.roots))
    if a.phase:
        runs = [r for r in runs if r.phase == a.phase]
    if a.failed:
        runs = [r for r in runs if r.failed or r.last_status in ("failed", "stopped")]
    if a.json:
        for r in runs:
            sys.stdout.write(json.dumps(r.row(), sort_keys=True) + "\n")
    else:
        print(format_table(runs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
