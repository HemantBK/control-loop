#!/bin/bash
# p6run.sh <name> <command...>: start a long Phase 6/7 job from the repository root under nohup, record its pid and exit
# code, and return at once. Liveness is checked by pid (p6state.sh), never by matching command lines (2026-10-22: two
# watchers were fooled that way; phases/phase6_researcharena/FINDINGS.md "watcher failures").
# Tracked copy (2026-10-22, audits/RESPONSE.md A8) of the launcher the Phase 6 runs used from the session scratch
# directory; unchanged except that the job directory is $JOBS_DIR (default $HOME/jobs) and the repository root is this
# script's ../.. instead of a fixed path.
# Files: $JOBS_DIR/<name>.{pid,rc,log,started}.
set -u
[ $# -ge 2 ] || { echo "usage: p6run.sh <name> <command...>" >&2; exit 64; }
name="$1"; shift
d="${JOBS_DIR:-$HOME/jobs}"; mkdir -p "$d"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1
[ -f "$d/$name.pid" ] && kill -0 "$(cat "$d/$name.pid")" 2>/dev/null && { echo "job $name already running (pid $(cat "$d/$name.pid"))"; exit 2; }
cd "$repo" || exit 1
rm -f "$d/$name.rc"
nohup bash -c '"$@"; echo $? > '"$d/$name.rc" _ "$@" > "$d/$name.log" 2>&1 < /dev/null &
echo $! > "$d/$name.pid"; date -u +%Y-%m-%dT%H:%M:%SZ > "$d/$name.started"
echo "started $name pid $(cat "$d/$name.pid") log $d/$name.log"
