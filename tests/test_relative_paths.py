"""No-API tests: no file the adapters write under results/ carries the absolute repository root.

- control_loop.paths helpers (rel, rel_text, repo_path, write_json);
- ControlArena: the mock sweep (check then full, 1 adaptive round) into a temporary dir under the repo,
  given an absolute --out, with stdout/stderr captured to a .out file as a shell redirect would;
  then write_recompute (metric_fixed.json/.md); reproduce.py (summary.json) and mechanism_check
  (check.json, OUT monkeypatched) on the mock; every written text file is free of the root
  (.eval logs are Inspect's own zip format and are not checked);
- ORBIT: loop.py's baseline.json / rounds.jsonl / printed lines and orbit.run_eval's printed command
  and argv, with the episode, reader and subprocess stubbed (the mock agent gives no valid clean epoch).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from control_loop import paths
from control_loop.paths import REPO

ROOT = str(REPO)


def _env():
    return {k: v for k, v in os.environ.items()
            if k not in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")}


@pytest.fixture
def repo_tmp():
    d = Path(tempfile.mkdtemp(dir=REPO, prefix=".tmp_test_relpaths_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _offenders(root: Path) -> list[str]:
    bad = []
    for f in root.rglob("*"):
        if f.is_file() and f.suffix != ".eval" and ROOT in f.read_text(encoding="utf-8", errors="replace"):
            bad.append(str(f.relative_to(root)))
    return bad


# --- helpers ---------------------------------------------------------------------------------------

def test_helpers(tmp_path):
    assert paths.rel(REPO / "results" / "x.eval") == "results/x.eval"
    assert paths.rel("results/x.eval") == "results/x.eval"
    assert paths.rel("/elsewhere/x") == "/elsewhere/x"
    assert paths.repo_path("results/x") == REPO / "results" / "x"
    assert paths.repo_path("/elsewhere/x") == Path("/elsewhere/x")
    assert paths.rel_text(f"$ {ROOT}/.venv/bin/python -T payload_file={ROOT}/a b, cwd {ROOT}") == \
        "$ .venv/bin/python -T payload_file=a b, cwd ."
    paths.write_json(tmp_path / "s.json", dict(log=REPO / "results" / "a.eval", logs=[f"{ROOT}/b.eval"]))
    assert json.loads((tmp_path / "s.json").read_text()) == dict(log="results/a.eval", logs=["b.eval"])


# --- ControlArena -----------------------------------------------------------------------------------

def _sweep(out: Path, log: Path, *extra: str):
    cmd = [sys.executable, "-m", "control_loop.adapters.controlarena.sweep", *extra,
           "--untrusted", "cl_mock/dp", "--trusted", "cl_mock/dp", "--proposer", "cl_mock/dp",
           "--limit", "1", "--rounds", "1", "--out", str(out)]
    with log.open("a", encoding="utf-8") as f:
        r = subprocess.run(cmd, cwd=REPO, env=_env(), stdout=f, stderr=subprocess.STDOUT)
    assert r.returncode == 0, log.read_text()[-3000:]


def test_controlarena_sweep_writes_no_absolute_paths(repo_tmp):
    pytest.importorskip("control_arena")
    from control_loop.adapters.controlarena import sweep

    out = repo_tmp / "sweep" / "mock_733"          # absolute --out on purpose
    log = repo_tmp / "sweep" / "mock_733.out"
    log.parent.mkdir(parents=True)
    _sweep(out, log, "--stage", "check")
    _sweep(out, log, "--stage", "full", "--r2-verified")
    state = json.loads((out / "state.json").read_text())
    assert state["status"] == "complete"
    rel_out = out.relative_to(REPO).as_posix()
    assert all(p.startswith(rel_out + "/") for p in state["logs"].values()), state["logs"]
    for name in ("state.json", "spend.json", "check.json", "summary.json", "tables.md", "driver.log"):
        assert (out / name).exists(), name
    assert "\n$ " in log.read_text()            # run_eval's command echo reached the .out
    # metric_fixed.{json,md}: offline recompute from the (relative) logs in state.json, cwd = repo root
    cwd = os.getcwd()
    os.chdir(REPO)
    try:
        rc = sweep.write_recompute(out, with_controlarena=False)
    finally:
        os.chdir(cwd)
    assert rc["rounds"][0]["log"].startswith(rel_out + "/")
    assert (out / "metric_fixed.json").exists() and (out / "metric_fixed.md").exists()
    assert _offenders(repo_tmp) == []


def test_controlarena_baseline_from_stored_relative(repo_tmp):
    pytest.importorskip("control_arena")
    from control_loop.adapters.controlarena import sweep

    a = SimpleNamespace(untrusted="u", trusted="t", proposer="p", seed=1, limit=1, max_samples=1, rounds=1,
                        token_limit=1, temperature=0.0, audit_budget=1.0, brief="monitor_aware",
                        baseline_from=repo_tmp / "base")
    cfg = sweep.Cell.config(SimpleNamespace(a=a))
    assert cfg["baseline_from"] == (repo_tmp / "base").relative_to(REPO).as_posix()


def test_controlarena_reproduce_writes_no_absolute_paths(repo_tmp):
    pytest.importorskip("control_arena")
    out = repo_tmp / "repro"
    log = repo_tmp / "repro.out"
    with log.open("w", encoding="utf-8") as f:
        r = subprocess.run([sys.executable, "-m", "control_loop.adapters.controlarena.reproduce", "--limit", "1",
                            "--untrusted", "cl_mock/dp", "--trusted", "cl_mock/dp", "--out", str(out)],
                           cwd=REPO, env=_env(), stdout=f, stderr=subprocess.STDOUT)
    assert r.returncode == 0, log.read_text()[-3000:]
    summ = json.loads((out / "summary.json").read_text())
    assert summ["logs"]["attack"].startswith(out.relative_to(REPO).as_posix() + "/")
    assert _offenders(repo_tmp) == []


def test_controlarena_mechanism_check_writes_no_absolute_paths(repo_tmp, monkeypatch, capsys):
    pytest.importorskip("control_arena")
    from control_loop.adapters.controlarena import mechanism_check

    for k in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(mechanism_check, "OUT", repo_tmp / "mechanism_check")
    monkeypatch.setattr(sys, "argv", ["mechanism_check", "--backend", "mock"])
    monkeypatch.chdir(REPO)
    mechanism_check.main()
    printed = capsys.readouterr().out
    (repo_tmp / "mechanism_check_mock.out").write_text(printed, encoding="utf-8")
    assert json.loads((repo_tmp / "mechanism_check" / "mock" / "check.json").read_text())["honest"]["log"] \
        .startswith(".tmp_test_relpaths_")
    assert _offenders(repo_tmp) == []


# --- ORBIT ------------------------------------------------------------------------------------------

def test_orbit_run_eval_command_is_relative(repo_tmp, monkeypatch, capsys):
    import control_loop.adapters.orbit as orbit

    seen = {}
    monkeypatch.setattr(orbit.subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd, cwd=kw.get("cwd")))
    monkeypatch.setattr(orbit, "latest_log", lambda d: str(Path(d) / "x.eval"))
    pf = repo_tmp / "payload_r1.txt"
    pf.write_text("p", encoding="utf-8")
    orbit.run_eval(repo_tmp / "A1", "mockllm/model", 733, ["-T", "num_tasks=4"], pf, "openai/gpt-4o-mini")
    printed = capsys.readouterr().out
    assert ROOT not in printed and printed.startswith("$ ")
    assert seen["cwd"] == REPO
    tail = [x for x in seen["cmd"][5:] if ROOT in x]   # [0] python, [4] task file
    assert tail == [], tail                                       # only the interpreter and task file stay absolute
    assert f"coalition_payload_file={pf.relative_to(REPO).as_posix()}" in seen["cmd"]


def test_orbit_loop_writes_no_absolute_paths(repo_tmp, monkeypatch, capsys):
    from control_loop import loop

    absolute = lambda d: str((Path(d) / "x.eval").resolve())    # what results.latest_log returns
    monkeypatch.setattr(loop, "run_eval", lambda log_dir, *a, **kw: absolute(log_dir))
    res = SimpleNamespace(status="success", coalition_reward=1.0, gain=0.5, finished_all_agents=True,
                          coalition_tickets=2, total_tickets=4, blocks_by_boundary={},
                          first_coalition_claim_agent="dev_0", first_coalition_claim_turn=1, channel_sends=0.0)
    monkeypatch.setattr(loop, "read_run", lambda log: SimpleNamespace(**vars(res), as_dict=lambda: dict(log=log)))
    monkeypatch.setattr(loop, "clean_distribution", lambda log: dict(
        log=[log], n=1, n_valid=1, mean=0.5, sd=0.0, tickets_mean=2.0, blocks_mean_by_boundary={},
        excluded=[f"clean epoch 2: see {log}"]))
    monkeypatch.setattr(loop, "net_blocks", lambda a, b: {})
    monkeypatch.setattr(loop, "net_blocks_vs_mean", lambda a, b: {})
    p0 = repo_tmp / "round0.txt"
    p0.write_text("static", encoding="utf-8")
    out = repo_tmp / "cell"
    monkeypatch.setattr(sys, "argv", ["loop", "--seed", "733", "--defense", "none", "--rounds", "0",
                                      "--agent-model", "mockllm/model", "--attacker-model", "mockllm/model",
                                      "--out", str(out), "--clean-log-dir", str(repo_tmp / "base"),
                                      "--round0-payload-file", str(p0)])
    loop.main()
    (repo_tmp / "cell.out").write_text(capsys.readouterr().out, encoding="utf-8")
    row = json.loads((out / "rounds.jsonl").read_text().splitlines()[0])
    assert row["log"] == (out / "A0" / "x.eval").relative_to(REPO).as_posix()
    assert row["proposer"]["round0_source"] == p0.relative_to(REPO).as_posix()
    assert json.loads((out / "baseline.json").read_text())["log"][0].startswith(".tmp_test_relpaths_")
    assert _offenders(repo_tmp) == []
