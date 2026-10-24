"""Self-match-safe process matching (PLAN Amendment 2026-10-23 (7); owner's ruling of 2026-10-23).

`pgrep -f PATTERN` / `pkill -f PATTERN` match every command line containing PATTERN, including the caller's own: a
watcher whose argv carries the pattern sees itself (the canary, 2026-10-22), and `bash -c "pkill -f PATTERN; ..."` kills
its own shell (the poller and the pkill incidents). This helper reads /proc directly (Linux) and never returns:

- the calling process (this one) and every ancestor of it (ppid from /proc/<pid>/stat, walked to pid 1);
- descendants of this process (the helper's own children), unless `include_own_children=True` is passed in-process;
- kernel threads (empty cmdline) and processes that vanish while being read.

PATTERN is a Python regular expression searched in the command line (argv joined by single spaces), as `pkill -f`
does with an ERE; `--fixed` matches it as a plain substring.

    python -m control_loop.adapters.researcharena.procs list PATTERN [--fixed] [-l]
    python -m control_loop.adapters.researcharena.procs kill PATTERN [--fixed] [--signal TERM]
    python -m control_loop.adapters.researcharena.procs kill-tree PATTERN [--fixed] [--signal TERM]
    python control_loop/adapters/researcharena/procs.py ...      (same; stdlib only, no package import)

`list` prints one pid per line (`-l`: pid and command line); `kill` sends the signal and prints `killed <pid> <cmdline>`
per process; `kill-tree` does the same for every matched process and all its descendants, descendants first
(2026-10-24: stopping an agent must also stop the tools it started). Exit status as pgrep/pkill: 0 if at least one process matched, 1 if none, 2 on a usage or /proc error.
scripts/jobs/pkill_safe.sh wraps `kill`.
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import sys

PROC = "/proc"


def ppid_of(pid: int) -> int | None:
    """Parent pid from /proc/<pid>/stat (the comm field may hold spaces and parentheses: split after the last ')')."""
    try:
        with open(f"{PROC}/{pid}/stat", "rb") as f:
            data = f.read().decode(errors="replace")
        return int(data.rsplit(")", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        return None


def ancestors(pid: int) -> list[int]:
    """`pid` and its ancestors up to (not including) pid 0, nearest first."""
    out, seen = [], set()
    cur: int | None = pid
    while cur and cur > 0 and cur not in seen:
        out.append(cur)
        seen.add(cur)
        if cur == 1:
            break
        cur = ppid_of(cur)
    return out


def cmdline(pid: int) -> str:
    try:
        with open(f"{PROC}/{pid}/cmdline", "rb") as f:
            raw = f.read()
    except OSError:
        return ""
    return raw.rstrip(b"\0").replace(b"\0", b" ").decode(errors="replace")


def all_pids() -> list[int]:
    if not os.path.isdir(PROC):
        raise OSError(f"{PROC} not found: procs needs Linux /proc")
    return sorted(int(n) for n in os.listdir(PROC) if n.isdigit())


def find(pattern: str, *, fixed: bool = False, include_own_children: bool = False,
         me: int | None = None) -> list[tuple[int, str]]:
    """[(pid, cmdline)] of processes whose command line matches `pattern`, never this process or its ancestors, and
    (unless include_own_children) never its descendants. `me` defaults to os.getpid()."""
    me = os.getpid() if me is None else me
    excluded = set(ancestors(me))
    rx = re.compile(re.escape(pattern) if fixed else pattern)
    out = []
    for pid in all_pids():
        if pid in excluded:
            continue
        cl = cmdline(pid)
        if not cl or not rx.search(cl):
            continue
        if not include_own_children and me in ancestors(pid)[1:]:
            continue
        out.append((pid, cl))
    return out


def kill(pattern: str, sig: int = signal.SIGTERM, *, fixed: bool = False,
         include_own_children: bool = False) -> list[tuple[int, str]]:
    """Send `sig` to every process `find` returns; returns those signalled (vanished ones are skipped)."""
    done = []
    for pid, cl in find(pattern, fixed=fixed, include_own_children=include_own_children):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            continue
        done.append((pid, cl))
    return done


def descendants(roots: set[int], me: int | None = None) -> list[int]:
    """Every live process that has one of `roots` among its ancestors, deepest first; never `me` or its ancestors."""
    me = os.getpid() if me is None else me
    excluded = set(ancestors(me))
    out = []
    for pid in all_pids():
        if pid in roots or pid in excluded:
            continue
        chain = ancestors(pid)
        for depth, a in enumerate(chain[1:], 1):
            if a in roots:
                out.append((depth, pid))
                break
    return [pid for _, pid in sorted(out, reverse=True)]


def kill_tree(pattern: str, sig: int = signal.SIGTERM, *, fixed: bool = False) -> list[tuple[int, str]]:
    """Signal every process `find` returns and all their descendants (deepest first, then the matched processes)."""
    roots = dict(find(pattern, fixed=fixed))
    done = []
    for pid in descendants(set(roots)) + list(roots):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            continue
        done.append((pid, roots.get(pid) or cmdline(pid)))
    return done


def _signal(name: str) -> int:
    n = name.upper()
    if n.isdigit():
        return int(n)
    return int(getattr(signal, n if n.startswith("SIG") else "SIG" + n))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="procs", description="pgrep/pkill -f that never match the caller or its ancestors")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "kill", "kill-tree"):
        p = sub.add_parser(name)
        p.add_argument("pattern")
        p.add_argument("--fixed", action="store_true", help="match PATTERN as a plain substring, not a regex")
        if name == "list":
            p.add_argument("-l", "--long", action="store_true", help="print the command line after the pid")
        else:
            p.add_argument("--signal", default="TERM", help="signal name or number (default TERM)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "list":
            got = find(a.pattern, fixed=a.fixed)
            for pid, cl in got:
                print(f"{pid} {cl}" if a.long else pid)
        else:
            fn = kill_tree if a.cmd == "kill-tree" else kill
            got = fn(a.pattern, _signal(a.signal), fixed=a.fixed)
            for pid, cl in got:
                print(f"killed {pid} {cl[:200]}")
    except (OSError, re.error, AttributeError, ValueError) as e:
        print(f"procs: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    sys.stdout.flush()
    return 0 if got else 1


if __name__ == "__main__":
    sys.exit(main())
