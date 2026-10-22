"""Phase 7 mechanism check (phases/phase7_dgm_self_modifying/PLAN.md §6): arm A at rule 733 early, rounds 0–2.

    uv run --locked --env-file ../.env python phases/phase7_dgm_self_modifying/check.py
    uv run --locked python phases/phase7_dgm_self_modifying/check.py --dry-run        the command only; nothing runs

One loop run: round 0 (ORBIT's static sentence), self-modify r1, round 1, self-modify r2, round 2; then stop.
Settings: seed 733, early ordering, preset allocation_rule_autoallow, agents openai/gpt-4o at temperature 0 with seed
733 (run_eval passes `--seed 733 --temperature 0`), judge_seed=733 (no judge call under this preset; passed for the
record), max_turns 40, token_limit 200000 (adapter COMMON_T / COMMON_EVAL), Inspect --max-samples 8 on the clean run
(reused here: results/phase3_allocation_monitor/early/baselines/733_allocation_rule_autoallow/run1, run2 read by
sweep_table.py); the writer is the agent model itself, --attacker self_modifier --attacker-model openai/gpt-4o, brief
informed_rule, temperature 0 with seed 73301 / 73302 requested and, on the OpenAI path, sent. Logs go under
results/phase7_dgm_self_modifying/check/733_allocation_rule_autoallow/{A0,A1,A2}/ with archive.jsonl, selfmod_log.jsonl,
rejections.jsonl (if any), payload_r{1,2}.txt, rounds.jsonl, baseline.json and run.jsonl (the loop's own steps through
--runlog-phase) in that directory; the loop's stdout in results/phase7_dgm_self_modifying/check_733_allocation_rule_autoallow.out.
The sweep later continues this very cell to r5 with --resume (PLAN §7.1).

The script refuses to run when
  * the caller did not pass --env-file (no OPENAI_API_KEY in the environment; the key's value is never read, printed or written),
  * the Phase 3 clean baselines run1/run2 are missing,
  * the check directory already exists (the check runs once; delete by hand to rerun),
  * tests/test_self_modifier.py or tests/test_e2e_self_modifier.py is missing or does not pass (run first through pytest; no API call).
Afterwards it prints each round's line and the spend from the logs (control_loop.spend, cache reads priced) plus the
writer's logged usage, and the report command:

    uv run --locked python phases/phase7_dgm_self_modifying/report.py

PLAN §6: a FAIL in (a), (c) or (d) of that report stops the phase for the owner; no sweep, no commit. Observability
(§11.3): run.jsonl through control_loop.runlog in results/phase7_dgm_self_modifying/check/ (run_id
"check_733_allocation_rule_autoallow"; steps tests, clean_run1, clean_run2, loop, spend).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from control_loop import runlog
from control_loop.paths import rel, rel_text

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PHASE = "phase7_dgm_self_modifying"
PRESET = "allocation_rule_autoallow"
SEED = 733
ORDERING = "early"
AGENT_MODEL = "openai/gpt-4o"
MONITOR_MODEL = "openai/gpt-4o-mini"
ROUNDS = 2
CHECK_ROOT = REPO / "results" / PHASE / "check"
CELL = CHECK_ROOT / f"{SEED}_{PRESET}"
BASELINE = REPO / "results" / "phase3_allocation_monitor" / ORDERING / "baselines" / f"{SEED}_{PRESET}"
OUT_FILE = REPO / "results" / PHASE / f"check_{SEED}_{PRESET}.out"
TESTS = [REPO / "tests" / "test_self_modifier.py", REPO / "tests" / "test_e2e_self_modifier.py"]
COMMAND = "uv run --locked --env-file ../.env python phases/phase7_dgm_self_modifying/check.py"
RUN_ID = f"check_{SEED}_{PRESET}"


def loop_command() -> list[str]:
    return [sys.executable, "-m", "control_loop.loop", "--seed", str(SEED), "--ordering", ORDERING, "--defense", PRESET,
            "--attacker", "self_modifier", "--attacker-model", AGENT_MODEL, "--agent-model", AGENT_MODEL,
            "--monitor-model", MONITOR_MODEL, "--num-tasks", "4", "--clean-epochs", "8", "--rounds", str(ROUNDS),
            "--brief", "informed_rule", "--clean-log-dir", rel(BASELINE / "run1"), "--out", rel(CELL), "--runlog-phase", PHASE]


def refuse(why: str) -> None:
    sys.exit(f"check.py refuses to run: {why}\n  run as: {COMMAND}")


def preflight(run_tests: bool = True) -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        refuse("no OPENAI_API_KEY in the environment; pass --env-file ../.env to uv")
    for r in (1, 2):
        d = BASELINE / f"run{r}"
        if not (d.exists() and any(d.glob("*.eval"))):
            refuse(f"Phase 3 clean baseline {rel(d)} is missing")
    if CELL.exists():
        refuse(f"{rel(CELL)} already exists; the check runs once (delete it by hand to rerun)")
    missing = [t for t in TESTS if not t.exists()]
    if missing:
        refuse(f"{', '.join(rel(t) for t in missing)} missing; the mock tests must pass first")
    if run_tests:
        rc = subprocess.run([sys.executable, "-m", "pytest", "-q", *map(str, TESTS)], cwd=REPO).returncode
        runlog.log_step(CHECK_ROOT, phase=PHASE, run_id=RUN_ID, step="tests", status="done" if rc == 0 else "failed",
                        error=None if rc == 0 else f"pytest exit {rc}", paths=TESTS)
        if rc != 0:
            refuse(f"mock tests failed (pytest exit {rc})")


def logs_cost(root: Path) -> float:
    from inspect_ai.log import read_eval_log

    from control_loop.spend import log_cost

    return sum(log_cost(read_eval_log(str(p), header_only=True)) for p in sorted(root.rglob("*.eval"))) if root.exists() else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the loop command; run nothing, write nothing")
    ap.add_argument("--skip-tests", action="store_true", help="do not re-run the mock tests first (they were run by hand)")
    a = ap.parse_args()
    cmd = loop_command()
    if a.dry_run:
        print("$", rel_text(" ".join(cmd)), f"> {rel(OUT_FILE)}")
        print("dry run: nothing was run.")
        return
    preflight(run_tests=not a.skip_tests)
    for r in (1, 2):
        runlog.log_step(CHECK_ROOT, phase=PHASE, run_id=RUN_ID, step=f"clean_run{r}", status="skipped",
                        cost_usd=0.0, paths=[BASELINE / f"run{r}"], note="Phase 3 baseline reused (paid in Phase 3)")
    runlog.log_step(CHECK_ROOT, phase=PHASE, run_id=RUN_ID, step="loop", status="started", paths=[CELL, OUT_FILE],
                    note=f"rounds 0-{ROUNDS}; writer {AGENT_MODEL} = agent model; brief informed_rule")
    print("$", rel_text(" ".join(cmd)), f"> {rel(OUT_FILE)}", flush=True)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("a", encoding="utf-8") as f:
        rc = subprocess.run(cmd, cwd=REPO, stdout=f, stderr=subprocess.STDOUT).returncode
    rows = [json.loads(l) for l in (CELL / "rounds.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] if (CELL / "rounds.jsonl").exists() else []
    ok = rc == 0 and len(rows) == ROUNDS + 1
    runlog.log_step(CHECK_ROOT, phase=PHASE, run_id=RUN_ID, step="loop", status="done" if ok else "failed", paths=[CELL / "rounds.jsonl"],
                    error=None if ok else f"rc={rc}, {len(rows)} rounds; see {rel(OUT_FILE)}")
    for row in rows:
        prop = row.get("proposer") or {}
        print(f"round {row['round']}: {row.get('log')} status={row.get('status')} valid={row.get('valid')} coalition={row.get('coalition_reward')} "
              f"gain={row.get('gain')} tickets={row.get('coalition_tickets')}/{row.get('total_tickets')} blocks={row.get('blocks_by_boundary')} "
              f"parent={row.get('parent_id')} fallback={row.get('fallback')} refused={row.get('refused')} moves={prop.get('moves')} "
              f"attempts={prop.get('attempts')} sent_seed={prop.get('sent_seed')} sent_T={prop.get('sent_temperature')}", flush=True)
    episodes = logs_cost(CELL)
    writer = sum(float((r.get("proposer") or {}).get("cost_usd") or 0.0) for r in rows)
    unpriced = [r["round"] for r in rows if r["round"] >= 1 and (r.get("proposer") or {}).get("cost_usd") is None]
    print(f"check spend from the logs (control_loop.spend, cache reads priced): episodes ${episodes:.4f}; writer calls from logged usage ${writer:.4f}"
          + (f" (rounds {unpriced} unpriced)" if unpriced else ""))
    runlog.log_step(CHECK_ROOT, phase=PHASE, run_id=RUN_ID, step="spend", status="done", cost_usd=None,
                    note=f"episodes ${episodes:.4f} + writer ${writer:.4f} (already counted in the cell's own run.jsonl steps)")
    print(f"next: uv run --locked python phases/phase7_dgm_self_modifying/report.py {rel(CELL)} --out {rel(CELL / 'report.md')}")
    if not ok:
        sys.exit(rc or 1)


if __name__ == "__main__":
    main()
