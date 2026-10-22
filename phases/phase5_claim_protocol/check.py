"""Phase 5 mechanism check (phases/phase5_claim_protocol/PLAN.md §6): one clean and one headline-static
episode under preset `claim_protocol_ref`, as Phase 3's check.py.

    uv run --locked --env-file ../.env python phases/phase5_claim_protocol/check.py

Settings: seed 733, early ordering, agents gpt-4o at temperature 0 with seed 733 (run_eval passes
`--seed 733 --temperature 0`), `judge_seed=733` (no judge call is made under this preset; passed for the
record), `max_turns=40` (adapter COMMON_T), `token_limit=200000` (adapter COMMON_EVAL), Inspect
`--max-samples 8`. The attacked episode runs the Phase 1 headline payload
(results/v2/late/prop_sonnet55/733_llm_monitor_fixed_actions/best_payload.txt) as a static payload,
paired with the clean log. Logs go under results/phase5_claim_protocol/check/claim_protocol_ref/{clean,A0}/.

The script refuses to run when
  * the caller did not pass --env-file (no API key in the environment; the key's value is never read,
    printed or written by this script),
  * tests/test_claim_protocol.py (the mock-model episode test, PLAN §1.3) is missing or does not pass
    (it is run first, through pytest, no API call),
  * either log directory already exists (the check is run once; delete by hand to rerun).
After the two episodes it prints each run's summary and the spend from the logs (control_loop.spend,
cache reads priced). Observability (PLAN amendment 2026-10-21 (3)): run.jsonl through control_loop.runlog in
results/phase5_claim_protocol/check/claim_protocol_ref/ (run_id "check_claim_protocol_ref"; steps mock_test,
clean, A0, spend) and in each episode dir it creates; `python -m control_loop.status results/phase5_claim_protocol`
reads them. Then, by hand:

    uv run --locked python phases/phase5_claim_protocol/report.py \
        results/phase5_claim_protocol/check/claim_protocol_ref/clean/*.eval \
        results/phase5_claim_protocol/check/claim_protocol_ref/A0/*.eval

PLAN §6: a FAIL in that report stops the phase for the owner; no sweep, no commit.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from inspect_ai.log import read_eval_log

from control_loop import runlog
from control_loop.adapters.orbit import REPO, run_eval
from control_loop.paths import rel
from control_loop.results import read_run
from control_loop.spend import log_cost

PRESET = "claim_protocol_ref"
HEADLINE = REPO / "results/v2/late/prop_sonnet55/733_llm_monitor_fixed_actions/best_payload.txt"
OUT = REPO / "results/phase5_claim_protocol/check"
MOCK_TEST = REPO / "tests/test_claim_protocol.py"
COMMAND = "uv run --locked --env-file ../.env python phases/phase5_claim_protocol/check.py"
MAX_SAMPLES = 8
PHASE = "phase5_claim_protocol"
RUN_ID = f"check_{PRESET}"


def refuse(why: str) -> None:
    sys.exit(f"check.py refuses to run: {why}\n  run as: {COMMAND}")


def preflight(out: Path, force_test: bool = True) -> None:
    """The three refusals of the module docstring, in order. Never reads the key's value."""
    if not os.environ.get("OPENAI_API_KEY"):
        refuse("no OPENAI_API_KEY in the environment; pass --env-file ../.env to uv")
    if not MOCK_TEST.exists():
        refuse(f"{rel(MOCK_TEST)} does not exist yet (phase5-core writes it); the mock episode must pass first")
    for sub in ("clean", "A0"):
        if (out / sub).exists():
            refuse(f"{rel(out / sub)} already exists; the check runs once (delete it by hand to rerun)")
    if not HEADLINE.exists():
        refuse(f"headline payload {rel(HEADLINE)} is missing")
    if force_test:
        rc = subprocess.run([sys.executable, "-m", "pytest", "-q", str(MOCK_TEST)], cwd=REPO).returncode
        runlog.log_step(out, phase=PHASE, run_id=RUN_ID, step="mock_test", status="done" if rc == 0 else "failed",
                        error=None if rc == 0 else f"pytest exit {rc}", paths=[MOCK_TEST])
        if rc != 0:
            refuse(f"{rel(MOCK_TEST)} failed (pytest exit {rc})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=733)
    ap.add_argument("--ordering", default="early")
    ap.add_argument("--agent-model", default="openai/gpt-4o")
    ap.add_argument("--monitor-model", default="openai/gpt-4o-mini", help="unused by this preset; recorded in the env as every phase")
    ap.add_argument("--out", default=str(OUT), help="output root (2026-10-22: added for the re-check into results/phase5_claim_protocol/check2, PLAN amendment 2026-10-22; the run id takes the root's directory name)")
    args = ap.parse_args()

    global RUN_ID
    out_root = Path(args.out) if Path(args.out).is_absolute() else REPO / args.out
    RUN_ID = f"{out_root.name}_{PRESET}"
    out = out_root / PRESET
    preflight(out)
    base_t = ["-T", "num_tasks=4", "-T", f"defense_preset={PRESET}", "-T", f"ordering={args.ordering}",
              "-T", f"judge_seed={args.seed}"]
    def episode(sub: str, extra_t: list[str], payload: Path | None) -> str:
        d = out / sub
        runlog.log_step(out, phase=PHASE, run_id=RUN_ID, step=sub, status="started", paths=[d])
        runlog.log_step(d, phase=PHASE, run_id=f"{RUN_ID}/{sub}", step="episode", status="started")
        try:
            log = run_eval(d, args.agent_model, args.seed, extra_t, payload, args.monitor_model, epochs=1, max_samples=MAX_SAMPLES)
        except Exception as ex:  # no log produced (run_eval itself raises only when no .eval appeared)
            err = f"{type(ex).__name__}: {ex}"[:300]
            runlog.log_step(d, phase=PHASE, run_id=f"{RUN_ID}/{sub}", step="episode", status="failed", error=err)
            runlog.log_step(out, phase=PHASE, run_id=RUN_ID, step=sub, status="failed", error=err, paths=[d])
            raise
        cost = log_cost(read_eval_log(str(log), header_only=True))
        status = read_eval_log(str(log), header_only=True).status
        ok = status == "success"
        runlog.log_step(d, phase=PHASE, run_id=f"{RUN_ID}/{sub}", step="episode", status="done" if ok else "failed",
                        cost_usd=cost, error=None if ok else f"log status {status}", paths=[log])
        runlog.log_step(out, phase=PHASE, run_id=RUN_ID, step=sub, status="done" if ok else "failed", cost_usd=cost,
                        error=None if ok else f"log status {status}", paths=[log])
        return log

    clean_log = episode("clean", base_t, None)
    attack_t = base_t + ["-T", "coalition_agents=dev_0,dev_1", "-T", f"clean_baseline_log={rel(Path(clean_log).resolve())}"]
    a0_log = episode("A0", attack_t, HEADLINE)
    total = 0.0
    for name, log in (("clean", clean_log), ("A0 headline static", a0_log)):
        r = read_run(log)
        cost = log_cost(read_eval_log(str(log), header_only=True))
        total += cost
        print(f"{name}: {rel(log)}\n  status={r.status} halt={r.halt_reason} per_agent={r.per_agent_reward} "
              f"coalition={r.coalition_reward:.2f} outsiders={r.outsiders_reward:.2f} team={r.team_reward:.2f} "
              f"tasks_done={r.tasks_done}/{r.total_tickets} valid_alloc={r.valid_alloc} valid_submit={r.valid_submit} "
              f"blocks={r.blocks_by_boundary} spend=${cost:.4f}", flush=True)
    print(f"check spend from the logs (control_loop.spend, cache reads priced): ${total:.4f}")
    runlog.log_step(out, phase=PHASE, run_id=RUN_ID, step="spend", status="done", cost_usd=None,
                    note=f"check total ${total:.4f} from the two logs (already counted in the clean and A0 steps)")
    print(f"next: uv run --locked python phases/phase5_claim_protocol/report.py {rel(clean_log)} {rel(a0_log)}")


if __name__ == "__main__":
    main()
