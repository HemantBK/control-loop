import json

from control_loop import runlog
from control_loop.status import main as status_main


def test_log_step_appends_and_status_reads(tmp_path, capsys):
    d = tmp_path / "results" / "phaseX" / "cell1"
    runlog.log_step(d, phase="phaseX", run_id="cell1", step="clean_run1", status="started")
    from control_loop.paths import REPO
    runlog.log_step(d, phase="phaseX", run_id="cell1", step="clean_run1", status="done", cost_usd=0.5, paths=[REPO / "results" / "phaseX" / "a.eval"])
    runlog.log_step(d, phase="phaseX", run_id="cell1", step="round1", status="failed", cost_usd=0.25, error="boom")
    lines = (d / "run.jsonl").read_text().strip().splitlines()
    assert len(lines) == 3
    recs = [json.loads(l) for l in lines]
    assert recs[1]["paths"] == ["results/phaseX/a.eval"]
    assert recs[2]["error"] == "boom"
    s = runlog.summarize(runlog.read_run(d), str(d))
    assert s.steps == 3 and s.failed == 1 and abs(s.cost_usd - 0.75) < 1e-9 and s.last_status == "failed"
    assert status_main([str(tmp_path / "results")]) == 0
    out = capsys.readouterr().out
    assert "cell1" in out and "round1" in out and "0.75" in out
    assert status_main([str(tmp_path / "results"), "--json", "--failed"]) == 0
    rows = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines()]
    assert len(rows) == 1 and rows[0]["last_error"] == "boom"


def test_bad_status_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        runlog.log_step(tmp_path, phase="p", run_id="r", step="s", status="nope")


def test_status_empty(tmp_path, capsys):
    assert status_main([str(tmp_path)]) == 0
    assert "no run.jsonl" in capsys.readouterr().out


def test_status_total_counts_leaf_runs_only(tmp_path, capsys):
    cell = tmp_path / "results" / "p" / "cell"
    runlog.log_step(cell, phase="p", run_id="cell", step="spend", status="done", cost_usd=0.3)
    runlog.log_step(cell / "A0", phase="p", run_id="cell/A0", step="episode", status="done", cost_usd=0.1)
    runlog.log_step(cell / "A1", phase="p", run_id="cell/A1", step="episode", status="done", cost_usd=0.2)
    assert status_main([str(tmp_path / "results")]) == 0
    out = capsys.readouterr().out
    assert "total cost_usd 0.3000 over 2 leaf runs (3 rows" in out
