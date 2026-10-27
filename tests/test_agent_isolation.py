"""Agent isolation (PLAN Amendment (25) item 5): the agent runs as an unprivileged user through p6_agent_exec.sh, and its
pre-agent check fails closed if the user could reach RunPod's pod key by any path: its environment, the pod-key file,
another process's environ or command line, or any readable file. These tests plant a fake key and need root (they run
on the CPU pod, as root, with `nobody` as the agent user); elsewhere they are skipped."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

EXEC = Path(__file__).resolve().parents[1] / "control_loop" / "adapters" / "researcharena" / "p6_agent_exec.sh"
KEY = "rpa_FAKEKEYFORTHEISOLATIONTEST0000000000000000000"

pytestmark = pytest.mark.skipif(os.geteuid() != 0 or not shutil.which("setpriv"),
                                reason="needs root and setpriv (runs on the CPU pod)")


@pytest.fixture
def pod():
    """A fake pod: a pod-key file and a scan root that the agent user can traverse (under /tmp itself: pytest's own
    tmp_path sits below a root-only directory)."""
    root = Path(tempfile.mkdtemp(prefix="p6iso_", dir="/tmp"))
    (root / "etc").mkdir()
    (root / "work").mkdir()
    for d in (root, root / "etc", root / "work"):
        d.chmod(0o755)
    rp = root / "etc" / "rp_environment"
    rp.write_text(f'export RUNPOD_API_KEY="{KEY}"\nexport OTHER=1\n')
    rp.chmod(0o600)
    env = dict(os.environ, P6_AGENT_USER="nobody", P6_RP_ENV=str(rp), P6_SCAN_ROOTS=str(root), P6_SCAN_SKIP="/nonexistent")
    env.pop("RUNPOD_API_KEY", None)
    yield root, rp, env
    shutil.rmtree(root, ignore_errors=True)


def check(env):
    cp = subprocess.run(["bash", str(EXEC), "check"], env=env, capture_output=True, text=True, timeout=300)
    assert KEY not in cp.stdout + cp.stderr          # the check never prints the key
    return cp.returncode, cp.stdout


def test_isolated_agent_passes(pod):
    rc, out = check(pod[2])
    assert rc == 0 and "AGENT_KEY_CHECK PASS" in out, out


def test_world_readable_key_file_fails(pod):
    root, rp, env = pod
    rp.chmod(0o644)                                  # RunPod's default mode
    rc, out = check(env)
    assert rc == 1 and "FAIL" in out


def test_key_in_the_callers_environment_is_stripped(pod):
    env = dict(pod[2], RUNPOD_API_KEY=KEY)           # the agent's parent had the key: `run` removes it
    rc, out = check(env)
    assert rc == 0, out
    got = subprocess.run(["bash", str(EXEC), "run", "env"], env=env, capture_output=True, text=True)
    assert KEY not in got.stdout and "USER=nobody" in got.stdout


def test_key_under_another_name_in_the_environment_fails(pod):
    rc, out = check(dict(pod[2], LEAKED=KEY))
    assert rc == 1 and "environment 1" in out


def test_readable_file_holding_the_key_fails_and_a_root_only_one_passes(pod):
    root, rp, env = pod
    leak = root / "work" / "notes.txt"
    leak.write_text(f"token {KEY}\n")
    leak.chmod(0o644)
    rc, out = check(env)
    assert rc == 1 and f"readable file holding the key: {leak}" in out
    leak.chmod(0o600)
    rc, out = check(env)
    assert rc == 0, out


def test_another_process_of_the_agent_user_holding_the_key_fails(pod):
    root, rp, env = pod
    p = subprocess.Popen(["setpriv", "--reuid=nobody", "--regid=nogroup", "--clear-groups", "--",
                          "env", f"LEAKED={KEY}", "sleep", "60"])
    try:
        rc, out = check(env)
        assert rc == 1 and "/proc environ 1" in out
    finally:
        p.kill()


def test_root_processes_holding_the_key_are_out_of_reach(pod):
    root, rp, env = pod
    p = subprocess.Popen(["env", f"LEAKED={KEY}", "sleep", "60"])     # a root process with the key in its environ
    try:
        rc, out = check(env)
        assert rc == 0, out
    finally:
        p.kill()
