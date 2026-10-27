"""No-network tests of the Phase 6 batch runner's rules (scripts/phase6/batch.py; PLAN Amendment (23) item 2): a failed
episode is recorded and the batch goes on; the same failure 3 times stops it; any cap stops it; the real back-end
refuses to run until it is written from the supervised episodes."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("batch", ROOT / "scripts" / "phase6" / "batch.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)

CAPS = {"gpu_usd": 150.0, "agent_usd": 25.0, "monitor_usd": 25.0, "proposer_usd": 5.0}


def fresh():
    return {"lanes": {}, "episodes": {}, "failures": {}, "spend": {}, "last_backup": 0, "done": False}


def test_one_failure_is_recorded_and_the_batch_goes_on():
    s = fresh()
    batch.record(s, "p6-a/ep01", "failed (x)", "setup step 3 exited 1", {})
    batch.record(s, "p6-a/ep02", "done", None, {"agent_usd": 1.2})
    assert s["failures"] == {"setup step 3 exited 1": 1} and batch.stop_reason(s, CAPS, None) is None


def test_the_same_failure_three_times_stops_the_batch():
    s = fresh()
    for i in range(2):
        batch.record(s, f"p6-a/ep0{i}", "failed", "rsync: connection reset", {})
    batch.record(s, "p6-b/ep01", "failed", "another failure", {})
    assert batch.stop_reason(s, CAPS, None) is None          # 2 + 1 different failures: go on
    batch.record(s, "p6-c/ep01", "failed", "rsync: connection reset", {})
    assert "the same failure 3 times: rsync: connection reset" == batch.stop_reason(s, CAPS, None)


@pytest.mark.parametrize("key,amount", [("agent_usd", 25.0), ("monitor_usd", 25.01), ("proposer_usd", 5.0)])
def test_each_model_cap_stops_the_batch(key, amount):
    s = fresh()
    batch.record(s, "p6-a/ep01", "done", None, {key: amount - 1})
    assert batch.stop_reason(s, CAPS, None) is None
    batch.record(s, "p6-a/ep02", "done", None, {key: 1})
    assert batch.stop_reason(s, CAPS, None).startswith(key.split("_")[0] + " cap")


def test_the_watchdogs_stop_file_is_the_gpu_cap():
    assert batch.stop_reason(fresh(), CAPS, "batch GPU spend $150.10 reached the cap $150.00\n").startswith("GPU cap")


def test_failure_signature_is_the_first_stderr_line():
    assert batch.failure_signature("\n  boom: step 3\nmore\n", 1) == "boom: step 3"
    assert batch.failure_signature("", 125) == "exit code 125 with no stderr"


def test_real_backend_refuses_to_run(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"batch_id": "b", "backend": "real"}))
    with pytest.raises(SystemExit, match="supervised episodes"):
        batch.Batch(tmp_path)


def test_fake_config_lanes_end_four_ways(tmp_path):
    batch.fake_config(tmp_path, 0.1)
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["backend"] == "fake" and len(cfg["lanes"]) == 4
    assert {l.get("then") for l in cfg["lanes"].values()} == {None, "idle", "delete"}
    assert cfg["lanes"]["p6-fake-b"]["fail"] and cfg["caps"]["gpu_usd"] == pytest.approx(0.47)


def test_safe_merge_never_deletes_or_overwrites_an_unbacked_up_result(tmp_path):
    """Amendment (25) item 2: a result file is replaced only when a verified pull holds its content (or git has it
    committed unchanged); otherwise the new content goes beside it. Nothing is deleted."""
    src, dst, logs = tmp_path / "src", tmp_path / "dst", []
    src.mkdir(); dst.mkdir()
    (src / "same.txt").write_text("a"); (dst / "same.txt").write_text("a")
    (src / "new.txt").write_text("n")
    (src / "changed.txt").write_text("v2"); (dst / "changed.txt").write_text("v1")
    (src / "pulled.txt").write_text("p2"); (dst / "pulled.txt").write_text("p1")
    (dst / "only_here.txt").write_text("keep me")
    verified = {(batch.copy_verify.sha256_file(dst / "pulled.txt"), str((dst / "pulled.txt").resolve()))}
    aside = batch.safe_merge(src, dst, logs.append, verified)
    assert aside == 1
    assert (dst / "changed.txt").read_text() == "v1"                       # not backed up: kept
    assert [p.read_text() for p in dst.glob("changed.txt.new-*")] == ["v2"]  # the new content beside it
    assert (dst / "pulled.txt").read_text() == "p2"                        # a verified pull holds p1: replaced
    assert (dst / "new.txt").read_text() == "n" and (dst / "only_here.txt").read_text() == "keep me"
    assert any("kept changed.txt unchanged" in l for l in logs)
