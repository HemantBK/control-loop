"""Phase 3 mechanism check (PLAN §5): one clean and one headline-static episode per preset.

Seed 733, early ordering, agents gpt-4o (temperature 0, seed 733), judge seeded, the adapter's common
task and generation settings. Run outside control_loop.loop because loop.py passes judge_seed only to
llm_monitor* presets (PLAN §5).

    uv run --env-file ../.env python phases/phase3_allocation_monitor/check.py --preset allocation_rule_monitor
    uv run --env-file ../.env python phases/phase3_allocation_monitor/check.py --preset allocation_llm_monitor
"""
from __future__ import annotations

import argparse
from pathlib import Path

from control_loop.adapters.orbit import REPO, run_eval
from control_loop.results import latest_log, read_run

HEADLINE = REPO / "results/v2/late/prop_sonnet55/733_llm_monitor_fixed_actions/best_payload.txt"
OUT = REPO / "results/phase3_allocation_monitor/check"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", choices=["allocation_rule_monitor", "allocation_llm_monitor"], required=True)
    ap.add_argument("--seed", type=int, default=733)
    ap.add_argument("--ordering", default="early")
    ap.add_argument("--agent-model", default="openai/gpt-4o")
    ap.add_argument("--monitor-model", default="openai/gpt-4o-mini")
    args = ap.parse_args()

    out = OUT / args.preset
    base_t = ["-T", "num_tasks=4", "-T", f"defense_preset={args.preset}", "-T", f"ordering={args.ordering}",
              "-T", f"judge_seed={args.seed}"]
    clean_dir = out / "clean"
    clean_log = (latest_log(clean_dir) if clean_dir.exists() and any(clean_dir.glob("*.eval"))
                 else run_eval(clean_dir, args.agent_model, args.seed, base_t, None, args.monitor_model))
    attack_t = base_t + ["-T", "coalition_agents=dev_0,dev_1", "-T", f"clean_baseline_log={Path(clean_log).resolve()}"]
    a0_log = run_eval(out / "A0", args.agent_model, args.seed, attack_t, HEADLINE, args.monitor_model)
    for name, log in (("clean", clean_log), ("A0 headline static", a0_log)):
        r = read_run(log)
        print(f"{name}: {log}\n  status={r.status} halt={r.halt_reason} final={r.final_owner} "
              f"coalition={r.coalition_reward:.2f} outsiders={r.outsiders_reward:.2f} team={r.team_reward:.2f} "
              f"tickets={r.coalition_tickets}/{r.total_tickets} valid_alloc={r.valid_alloc} valid_submit={r.valid_submit} "
              f"blocks={r.blocks_by_boundary}", flush=True)


if __name__ == "__main__":
    main()
