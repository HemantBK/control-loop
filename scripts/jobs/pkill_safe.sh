#!/bin/bash
# pkill_safe.sh <pattern> [--fixed] [--signal TERM]: `pkill -f` that never kills its caller, the caller's ancestors (this
# shell, a `bash -c` around it, the poller that ran it) or its own children (PLAN Amendment 2026-10-23 (7); the
# self-match bug hit the canary, a poller and a pkill). Calls control_loop/adapters/researcharena/procs.py (stdlib only)
# by path, so it needs no venv. Exit status as pkill: 0 if a process was signalled, 1 if none matched, 2 on error.
[ $# -ge 1 ] || { echo "usage: pkill_safe.sh <pattern> [--fixed] [--signal TERM]" >&2; exit 2; }
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 2
exec python3 "$repo/control_loop/adapters/researcharena/procs.py" kill "$@"
