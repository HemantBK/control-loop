"""Self-match-safe process matching (control_loop/adapters/researcharena/procs.py, scripts/jobs/pkill_safe.sh; PLAN
Amendment 2026-10-23 (7)). Each test reproduces one of the three incidents in which `pgrep -f` / `pkill -f` matched the
caller's own command line: (a) the canary, (b) the poller and the pkill inside `bash -c`; and (c) checks that a real
target carrying the pattern is still found and killed. Linux /proc only; no network."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import pytest

from control_loop.adapters.researcharena import procs

pytestmark = pytest.mark.skipif(not os.path.isdir("/proc/self"), reason="needs Linux /proc")

REPO = Path(__file__).resolve().parents[1]
PROCS_PY = REPO / "control_loop" / "adapters" / "researcharena" / "procs.py"
PKILL_SAFE = REPO / "scripts" / "jobs" / "pkill_safe.sh"
PY = sys.executable


def marker() -> str:
    return f"p6selfmatch-{uuid.uuid4().hex[:10]}"


def start_target(mark: str) -> subprocess.Popen:
    """`sleep 300` whose argv[0] carries the marker (bash `exec -a`); waits until /proc shows it."""
    p = subprocess.Popen(["bash", "-c", f"exec -a {mark}-target sleep 300"])
    for _ in range(200):
        if mark in procs.cmdline(p.pid):
            return p
        time.sleep(0.01)
    p.kill()
    raise AssertionError("target never showed the marker")


def stop(p: subprocess.Popen) -> None:
    if p.poll() is None:
        p.kill()
        p.wait(timeout=10)


def test_ancestors_walk_to_init():
    chain = procs.ancestors(os.getpid())
    assert chain[0] == os.getpid() and chain[-1] == 1 and os.getppid() in chain


def test_a_canary_with_the_pattern_in_its_own_argv_does_not_see_itself():
    """Incident (a), 2026-10-22: the canary's argv held the driver pattern, so `pgrep -f` always found the canary and it
    never saw the driver exit. Both the in-process call and the CLI from inside the canary must return nothing."""
    mark = marker()
    canary = textwrap.dedent(f"""
        import importlib.util, subprocess, sys
        spec = importlib.util.spec_from_file_location("procs", {str(PROCS_PY)!r})
        procs = importlib.util.module_from_spec(spec); spec.loader.exec_module(procs)
        print("INPROC", [p for p, _ in procs.find(sys.argv[1])])
        cp = subprocess.run([sys.executable, {str(PROCS_PY)!r}, "list", sys.argv[1]], capture_output=True, text=True)
        print("CLI", cp.returncode, cp.stdout.split())
        cp = subprocess.run(["bash", "-c", sys.executable + " " + {str(PROCS_PY)!r} + " list " + sys.argv[1]],
                            capture_output=True, text=True)
        print("SHELL", cp.returncode, cp.stdout.split())
    """)
    cp = subprocess.run([PY, "-c", canary, mark, "--driver-pattern", mark], capture_output=True, text=True, timeout=60)
    assert cp.returncode == 0, cp.stderr
    assert "INPROC []" in cp.stdout and "CLI 1 []" in cp.stdout and "SHELL 1 []" in cp.stdout, cp.stdout
    # with a real driver alive, the canary sees exactly the driver
    t = start_target(mark)
    try:
        cp = subprocess.run([PY, "-c", canary, mark], capture_output=True, text=True, timeout=60)
        assert f"INPROC [{t.pid}]" in cp.stdout and f"CLI 0 ['{t.pid}']" in cp.stdout and f"SHELL 0 ['{t.pid}']" in cp.stdout, cp.stdout
    finally:
        stop(t)


@pytest.mark.parametrize("how", ["file", "module", "wrapper"])
def test_b_kill_inside_bash_c_spares_its_own_shell(how):
    """Incidents (b), poller and pkill: `bash -c "pkill -f PATTERN; ..."` with PATTERN in the bash -c string killed the
    shell itself. With the helper the shell survives and prints "survived"."""
    mark = marker()
    cmd = {"file": f"{PY} {PROCS_PY} kill {mark}",
           "module": f"cd {REPO} && {PY} -m control_loop.adapters.researcharena.procs kill {mark}",
           "wrapper": f"{PKILL_SAFE} {mark}"}[how]
    cp = subprocess.run(["bash", "-c", f"{cmd}; echo rc=$?; echo survived"], capture_output=True, text=True, timeout=60)
    assert cp.returncode == 0 and "survived" in cp.stdout and "rc=1" in cp.stdout, (cp.stdout, cp.stderr)


@pytest.mark.parametrize("how", ["file", "wrapper"])
def test_c_a_real_target_is_found_and_killed_and_the_shell_survives(how):
    mark = marker()
    t = start_target(mark)
    try:
        cmd = f"{PY} {PROCS_PY} kill {mark}" if how == "file" else f"{PKILL_SAFE} {mark} --signal TERM"
        cp = subprocess.run(["bash", "-c", f"{cmd}; echo rc=$?; echo survived"], capture_output=True, text=True, timeout=60)
        assert "survived" in cp.stdout and "rc=0" in cp.stdout and f"killed {t.pid} {mark}-target 300" in cp.stdout, cp.stdout
        assert t.wait(timeout=10) == -signal.SIGTERM
    finally:
        stop(t)


def test_list_prints_pids_and_long_form():
    mark = marker()
    t = start_target(mark)
    try:
        cp = subprocess.run([PY, str(PROCS_PY), "list", mark], capture_output=True, text=True, timeout=60)
        assert cp.returncode == 0 and cp.stdout.split() == [str(t.pid)]
        cp = subprocess.run([PY, str(PROCS_PY), "list", "-l", f"{mark}-tar.et"], capture_output=True, text=True, timeout=60)
        assert cp.stdout.strip() == f"{t.pid} {mark}-target 300"                 # regex by default
        cp = subprocess.run([PY, str(PROCS_PY), "list", "--fixed", f"{mark}-tar.et"], capture_output=True, text=True, timeout=60)
        assert cp.returncode == 1 and cp.stdout == ""                                # --fixed: no regex
    finally:
        stop(t)


def test_own_children_excluded_in_process_unless_asked():
    """The helper never returns its own children; in-process, the caller's children are its own, so a caller that
    wants them passes include_own_children=True (the CLI, a separate process, sees them as siblings)."""
    mark = marker()
    t = start_target(mark)
    try:
        assert procs.find(mark) == []
        assert [p for p, _ in procs.find(mark, include_own_children=True)] == [t.pid]
        cp = subprocess.run([PY, str(PROCS_PY), "list", mark], capture_output=True, text=True, timeout=60)
        assert cp.stdout.split() == [str(t.pid)]
    finally:
        stop(t)


def test_bad_pattern_or_signal_exits_2():
    assert subprocess.run([PY, str(PROCS_PY), "list", "("], capture_output=True, text=True).returncode == 2
    assert subprocess.run([PY, str(PROCS_PY), "kill", marker(), "--signal", "NOPE"], capture_output=True,
                          text=True).returncode == 2
