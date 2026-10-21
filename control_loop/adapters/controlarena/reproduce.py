"""PLAN §10.1 reproduction, run through the adapter's task wrapper (dp_task.py) rather than the CLI.

    uv run --no-sync --env-file ../.env python -m control_loop.adapters.controlarena.reproduce --limit 3
        [--untrusted <model>] [--trusted <model>] [--token-limit N] [--max-samples N] [--framing]
        [--modes honest,attack] [--honest-log <existing honest .eval>] [--out <dir>]

data_poisoning, trusted_monitoring (basic_monitor on the trusted model) + end-of-trajectory monitor,
ControlArena's default models unless --untrusted/--trusted are given (PLAN §11), honest mode with its
honest policy and attack mode with its stock attack policy (no strategy paragraph). Writes <out>/{honest,attack}/*.eval and <out>/summary.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from control_loop.adapters import controlarena as ca

UNTRUSTED, TRUSTED = "anthropic/claude-opus-5-5", "anthropic/claude-sonnet-4-6"  # ControlArena 20.1.0 defaults


def _limit(value: str) -> int | str:
    """An int, or Inspect's sample range "M-N" (1-based, inclusive), kept as the string Inspect parses."""
    if "-" not in value:
        return int(value)
    lo, hi = (int(v) for v in value.split("-"))
    if not 1 <= lo <= hi:
        raise argparse.ArgumentTypeError(f"bad sample range {value!r}")
    return f"{lo}-{hi}"


def _n_samples(limit: int | str) -> int:
    if isinstance(limit, int):
        return limit
    lo, hi = (int(v) for v in limit.split("-"))
    return hi - lo + 1


def main() -> None:
    ap = argparse.ArgumentParser()
    # 2026-10-21 (PLAN §11, owner's amendment 2): also Inspect's 1-based inclusive range "M-N" (e.g. "3-3"
    # runs sample 3 only), passed through to `inspect eval --limit` unchanged.
    ap.add_argument("--limit", type=_limit, default=3)
    ap.add_argument("--seed", type=int, default=733)
    ap.add_argument("--out", type=Path, default=ca.REPO / "results" / "phase4_controlarena" / "repro_limit3")
    # 2026-10-21 (PLAN §11): the untrusted model (policy and, by ControlArena's default, the setting's
    # judges) is a parameter; the defaults reproduce the 2026-10-20 run. token_limit None = dp_task's
    # default (1,000,000, ControlArena's).
    ap.add_argument("--untrusted", default=UNTRUSTED)
    ap.add_argument("--trusted", default=TRUSTED)
    ap.add_argument("--token-limit", type=int, default=None)
    # Inspect's --max-samples (samples run in parallel); default = --limit, as on 2026-10-20. The
    # proposer sweep uses 8 (PLAN §11.8). It is an `inspect eval` option, passed by ca.run_eval, not a
    # dp_task option.
    ap.add_argument("--max-samples", type=int, default=None)
    # attack-mode only: Phase 1's sanctioned-evaluation framing (dp_task -T framing=true). Off by default.
    ap.add_argument("--framing", action="store_true")
    # run only these modes; with honest not run, --honest-log names an existing honest log for the
    # control metrics (its cost is not counted here).
    ap.add_argument("--modes", default="honest,attack")
    ap.add_argument("--honest-log", type=Path, default=None)
    args = ap.parse_args()
    from control_loop.adapters.controlarena.reader import (attempt_counts, control_metrics, cost_usd, read_log,
                                                           step_table)

    modes = [m for m in args.modes.split(",") if m]
    if not set(modes) <= {"honest", "attack"} or not modes:
        raise SystemExit(f"--modes must be a subset of honest,attack, got {args.modes!r}")
    extra = ["-T", f"token_limit={args.token_limit}"] if args.token_limit else []
    if args.framing:
        extra += ["-T", "framing=true"]
    max_samples = args.max_samples or _n_samples(args.limit)
    logs = {mode: ca.run_eval(args.out / mode, args.untrusted, args.seed, ["-T", f"mode={mode}", *extra], None,
                              args.trusted, max_samples=max_samples, limit=args.limit)
            for mode in modes}
    results = {mode: read_log(p) for mode, p in logs.items()}
    flat = [r for mode in modes for r in results[mode]]
    honest_log = logs.get("honest") or (str(args.honest_log) if args.honest_log else None)
    # requested_seed is `inspect eval --seed`; sent_settings is what the provider requests carried
    # (the Anthropic path sends no seed, audit_codex X8). Summaries before 2026-10-21 call it `seed`.
    summary = dict(logs=logs, reused_honest_log=None if "honest" in logs else honest_log,
                   untrusted=args.untrusted, trusted=args.trusted, requested_seed=args.seed,
                   token_limit=args.token_limit or 1_000_000, max_samples=max_samples, framing=args.framing,
                   sent_settings={mode: ca.sent_settings(p) for mode, p in logs.items()}, limit=args.limit,
                   control_metrics=(control_metrics(honest_log, logs["attack"])
                                    if honest_log and "attack" in logs else None),
                   attempts=attempt_counts(results["attack"]) if "attack" in results else None,
                   cost_usd=round(cost_usd(flat), 4),
                   samples=[dict(mode=r.eval_mode, id=r.sample_id, main=r.main_task_success, side=r.side_task_success,
                                 eot=r.eot_suspicion, max_step=r.max_step_suspicion, halt=r.halt_reason, error=r.error,
                                 attempt=r.attempt, policy_content_filter_calls=r.policy_content_filter_calls,
                                 steps=[(s.step, s.tool_calls, s.suspicion_score, s.score_parsed, s.metadata_score,
                                         s.metadata_overwritten) for s in r.steps])
                            for r in flat])
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print("\n" + step_table(flat) + "\n")
    print("control metrics:", json.dumps(summary["control_metrics"], default=str))
    print("attack attempts:", json.dumps(summary["attempts"]))
    print(f"cost ${summary['cost_usd']:.4f}  ->  {args.out / 'summary.json'}")


if __name__ == "__main__":
    main()
