"""Ban on raw command-line process matching (owner, 2026-10-24; PLAN Amendment (19) item 6). `pgrep -f` / `pkill -f`
match their caller's own command line; that self-match broke a run four times (canary, poller, pkill, fullrun2's waiter).
The one helper is control_loop/adapters/researcharena/procs.py (`list` / `kill`); scripts/jobs/pkill_safe.sh only execs it.

This test fails if `pgrep` or `pkill` with an -f flag appears in any code file of the repository (results/ holds past
logs and is not code), or in the pod-script directories named in $P6_EXTRA_SCRIPT_DIRS (colon-separated; the manager sets
it on the CPU pod for scripts kept outside the repository)."""
from __future__ import annotations

import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RAW = re.compile(r"\b(?:pgrep|pkill)\b(?:\s+-{1,2}[\w-]+(?:\s+(?!-)[^\s;|&]+)?)*?\s+(?:-[A-Za-z]*f[A-Za-z]*|--full)\b")
ALLOWED = {  # the helper, its wrapper and its tests describe the banned form
    "control_loop/adapters/researcharena/procs.py", "scripts/jobs/pkill_safe.sh", "tests/test_procs.py",
    "tests/test_no_raw_process_match.py",
}
SKIP_DIRS = {".git", ".venv", "__pycache__", "results", "node_modules", ".pytest_cache"}
CODE_EXT = {".py", ".sh", ".bash", ".zsh"}


def code_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            p = Path(dirpath) / f
            if p.suffix in CODE_EXT:
                yield p
            elif not p.suffix:
                try:
                    with open(p, "rb") as fh:
                        if fh.read(2) == b"#!":
                            yield p
                except OSError:
                    pass


def hits(root: Path, allowed=frozenset()):
    out = []
    for p in code_files(root):
        rel = p.relative_to(root).as_posix()
        if rel in allowed:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if RAW.search(line):
                out.append(f"{rel}:{i}: {line.strip()[:120]}")
    return out


def test_pattern_catches_the_raw_forms_and_spares_the_helper():
    for bad in ('pgrep -f "bash x.sh"', "pkill -f post.sh", "pkill -9 -f x", "pgrep -af x", "pkill --signal TERM -f x",
                'while pgrep -f "evaluate.py --mode full" > /dev/null; do', "sudo pkill -KILL -f x", "pgrep --full x"):
        assert RAW.search(bad), bad
    for ok in ("pgrep -x sshd", "pkill -u nobody", "python3 procs.py list 'bash x.sh'", "kill -0 $pid",
               "pkill_safe.sh post.sh", "echo pgrep"):
        assert not RAW.search(ok), ok


def test_no_raw_pgrep_pkill_f_in_repo_code():
    found = hits(REPO, ALLOWED)
    assert not found, "raw pgrep/pkill -f (use procs.py):\n" + "\n".join(found)


def test_no_raw_pgrep_pkill_f_in_pod_script_dirs():
    dirs = [Path(d) for d in os.environ.get("P6_EXTRA_SCRIPT_DIRS", "").split(":") if d]
    found = [f"{d}: {h}" for d in dirs if d.is_dir() for h in hits(d)]
    assert not found, "raw pgrep/pkill -f in pod scripts (use procs.py):\n" + "\n".join(found)
