"""PLAN §10.1 reproduction, run through the adapter's task wrapper (dp_task.py) rather than the CLI.

    uv run --no-sync --env-file ../.env python -m control_loop.adapters.controlarena.reproduce --limit 3

data_poisoning, trusted_monitoring (basic_monitor on the trusted model) + end-of-trajectory monitor,
ControlArena's default models, honest mode with its honest policy and attack mode with its stock
attack policy (no strategy paragraph). Writes <out>/{honest,attack}/*.eval and <out>/summary.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from control_loop.adapters import controlarena as ca

UNTRUSTED, TRUSTED = "anthropic/claude-opus-5-5", "anthropic/claude-sonnet-4-6"  # ControlArena 20.1.0 defaults


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--seed", type=int, default=733)
    ap.add_argument("--out", type=Path, default=ca.REPO / "results" / "phase4_controlarena" / "repro_limit3")
    args = ap.parse_args()
    from control_loop.adapters.controlarena.reader import control_metrics, cost_usd, read_log, step_table

    logs = {mode: ca.run_eval(args.out / mode, UNTRUSTED, args.seed, ["-T", f"mode={mode}"], None, TRUSTED,
                              max_samples=args.limit, limit=args.limit)
            for mode in ("honest", "attack")}
    results = {mode: read_log(p) for mode, p in logs.items()}
    flat = results["honest"] + results["attack"]
    summary = dict(logs=logs, untrusted=UNTRUSTED, trusted=TRUSTED, seed=args.seed, limit=args.limit,
                   control_metrics=control_metrics(logs["honest"], logs["attack"]),
                   cost_usd=round(cost_usd(flat), 4),
                   samples=[dict(mode=r.eval_mode, id=r.sample_id, main=r.main_task_success, side=r.side_task_success,
                                 eot=r.eot_suspicion, max_step=r.max_step_suspicion, halt=r.halt_reason, error=r.error,
                                 steps=[(s.step, s.tool_calls, s.suspicion_score, s.score_parsed, s.metadata_score,
                                         s.metadata_overwritten) for s in r.steps])
                            for r in flat])
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print("\n" + step_table(flat) + "\n")
    print("control metrics:", json.dumps(summary["control_metrics"], default=str))
    print(f"cost ${summary['cost_usd']:.4f}  ->  {args.out / 'summary.json'}")


if __name__ == "__main__":
    main()
