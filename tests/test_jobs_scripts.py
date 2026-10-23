"""scripts/jobs/p6state.sh (PLAN Amendment 2026-10-23 (7)): with a results out dir, AGE follows the newest run log, not
the job's stdout log (smoke6b: the driver printed nothing for minutes while run.jsonl advanced). No network: a fake
`runpodctl` on PATH answers `pod list` with []."""
from __future__ import annotations

import os
import re
import stat
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
P6STATE = REPO / "scripts" / "jobs" / "p6state.sh"


def _env(tmp: Path) -> dict[str, str]:
    b = tmp / "bin"
    b.mkdir(exist_ok=True)
    rp = b / "runpodctl"
    rp.write_text("#!/bin/sh\necho '[]'\n", encoding="utf-8")
    rp.chmod(rp.stat().st_mode | stat.S_IXUSR)
    return dict(os.environ, JOBS_DIR=str(tmp / "jobs"), PATH=f"{b}:{os.environ['PATH']}")


def _state(tmp: Path, *args: str) -> str:
    cp = subprocess.run(["bash", str(P6STATE), *args], capture_output=True, text=True, env=_env(tmp), timeout=60)
    assert cp.returncode == 0 and len(cp.stdout.strip().splitlines()) == 1, cp
    return cp.stdout.strip()


def _age(line: str) -> int:
    return int(re.search(r"\bAGE=(\d+)s\b", line).group(1))


def _job(tmp: Path, name: str = "smoke6c") -> Path:
    jobs = tmp / "jobs"
    jobs.mkdir()
    log = jobs / f"{name}.log"
    log.write_text("", encoding="utf-8")                  # the driver's stdout: empty, 20 minutes old
    old = time.time() - 20 * 60
    os.utime(log, (old, old))
    (jobs / f"{name}.rc").write_text("0\n", encoding="utf-8")
    return log


def test_age_follows_run_jsonl_when_the_out_dir_is_given(tmp_path):
    _job(tmp_path)
    out = tmp_path / "results" / "smoke6c"
    out.mkdir(parents=True)
    old = time.time() - 15 * 60
    (out / "pods.jsonl").write_text("{}\n", encoding="utf-8")
    os.utime(out / "pods.jsonl", (old, old))
    (out / "run.jsonl").write_text("{}\n", encoding="utf-8")   # touched now
    line = _state(tmp_path, "smoke6c", str(out))
    assert _age(line) <= 5 and f"RUNLOG={out / 'run.jsonl'}" in line
    assert line.startswith("STATE=EXITED rc=0 ERR=0 AGE=") and "P6PODS=none" in line and "LAST=" in line
    # without the out dir: AGE from the job log, as before, and no RUNLOG field
    line = _state(tmp_path, "smoke6c")
    assert 20 * 60 - 5 <= _age(line) <= 20 * 60 + 60 and "RUNLOG=" not in line


def test_age_takes_the_newest_launch_run_log(tmp_path):
    _job(tmp_path, "sweep1")
    out = tmp_path / "sweep"
    (out / "launches" / "r1").mkdir(parents=True)
    old = time.time() - 10 * 60
    for f in (out / "run.jsonl", out / "pods.jsonl"):
        f.write_text("{}\n", encoding="utf-8")
        os.utime(f, (old, old))
    newest = out / "launches" / "r1" / "run.jsonl"
    newest.write_text("{}\n", encoding="utf-8")
    line = _state(tmp_path, "sweep1", str(out))
    assert _age(line) <= 5 and f"RUNLOG={newest}" in line


def test_out_dir_without_run_logs_falls_back_to_the_job_log(tmp_path):
    _job(tmp_path)
    (tmp_path / "empty").mkdir()
    line = _state(tmp_path, "smoke6c", str(tmp_path / "empty"))
    assert _age(line) >= 20 * 60 - 5 and "RUNLOG=none" in line
