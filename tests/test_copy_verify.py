"""Tests of the verified pod-to-CPU copy (control_loop/adapters/researcharena/copy_verify.py; owner, 2026-10-24) and of
the watchdog's pre-delete copy hook (session_watchdog.run(pre_delete=...))."""
from __future__ import annotations

import hashlib
import subprocess

import pytest

from control_loop.adapters.researcharena import copy_verify as cv
from control_loop.adapters.researcharena import session_watchdog as wd


def manifest_for(root, tags):
    lines = []
    for tag in tags:
        for p in sorted((root / tag).rglob("*")):
            if p.is_file():
                lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {tag}/{p.relative_to(root / tag).as_posix()}")
    return "\n".join(lines) + "\n"


def tree(base):
    (base / "eval_dir" / "red_team" / "task_snapshot" / "kernels").mkdir(parents=True)
    (base / "eval_dir" / "red_team" / "solve_out.json").write_text('{"type": "text"}\n')
    (base / "eval_dir" / "red_team" / "task_snapshot" / "kernels" / "rmsnorm.cu").write_text("// agent\n")
    (base / "fullrun3").mkdir()
    (base / "fullrun3" / "kl_check.log").write_text("GATE_0.01 PASS\n")


def test_exact_copy_passes(tmp_path):
    remote, local = tmp_path / "remote", tmp_path / "local"
    tree(remote); tree(local)
    v = cv.verify(manifest_for(remote, ["eval_dir", "fullrun3"]), local, ["eval_dir", "fullrun3"])
    assert v["pass"] and v["remote_files"] == 3 and v["local_matching"] == 3 and v["remote_files_by_root"] == {"eval_dir": 2, "fullrun3": 1}


def test_missing_or_changed_file_fails(tmp_path):
    remote, local = tmp_path / "remote", tmp_path / "local"
    tree(remote); tree(local)
    m = manifest_for(remote, ["eval_dir", "fullrun3"])
    (local / "fullrun3" / "kl_check.log").unlink()
    v = cv.verify(m, local, ["eval_dir", "fullrun3"])
    assert not v["pass"] and v["missing"] == ["fullrun3/kl_check.log"]
    tree(tmp_path / "l2"); (tmp_path / "l2" / "eval_dir" / "red_team" / "solve_out.json").write_text("truncated")
    v2 = cv.verify(m, tmp_path / "l2", ["eval_dir", "fullrun3"])
    assert not v2["pass"] and v2["mismatched"] == ["eval_dir/red_team/solve_out.json"]


def test_extra_local_files_do_not_fail_and_empty_manifest_never_passes(tmp_path):
    remote, local = tmp_path / "remote", tmp_path / "local"
    tree(remote); tree(local); (local / "fullrun3" / "old.txt").write_text("x")
    v = cv.verify(manifest_for(remote, ["eval_dir", "fullrun3"]), local, ["eval_dir", "fullrun3"])
    assert v["pass"] and v["extra"] == ["fullrun3/old.txt"]
    assert not cv.verify("", local, ["eval_dir"])["pass"]
    with pytest.raises(ValueError):
        cv.parse_manifest("not a manifest line\n")


POD = {"id": "p1", "name": "p6-x", "createdAt": "2026-10-24T10:00:00Z", "costPerHr": 3.99}


def run_with_hook(hook, limit_s=600, lead_s=120, polls=40):
    t0 = wd.parse_time(POD["createdAt"])
    clock, logs, deleted, order = {"t": t0 + 60}, [], [], []

    def sleep(s):
        clock["t"] += s

    def deleter(i):
        order.append("delete"); deleted.append(i); return 0

    def pre():
        order.append("copy"); hook()
    wd.run("p6-x", limit_s, 100.0, logs.append, lister=lambda: [POD], deleter=deleter, now=lambda: clock["t"],
           sleep=sleep, max_polls=polls, pre_delete=pre, pre_delete_lead_s=lead_s)
    return order, logs, deleted


def test_watchdog_copies_once_before_its_hard_delete():
    order, logs, deleted = run_with_hook(lambda: None)
    assert order[0] == "copy" and order.count("copy") == 1 and "delete" in order and order.index("copy") < order.index("delete")
    assert any("pre-delete copy" in l for l in logs)


def test_watchdog_still_deletes_when_the_copy_fails():
    def boom():
        raise subprocess.TimeoutExpired("pull", 300)
    order, logs, deleted = run_with_hook(boom)
    assert deleted and any("pre-delete copy failed" in l for l in logs)
