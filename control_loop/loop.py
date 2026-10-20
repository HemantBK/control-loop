"""Adaptive red team for ORBIT's Jira collusion scenario.

For one problem seed and one defense setting it runs:

    C   clean run (no coalition)                       -> baseline log
    A0  static ORBIT collusion attack, paired with C   -> round 0
    A1..AN  adaptive attack: an LLM rewrites the coalition payload after
            seeing how the previous attempt scored, paired with C

Observation model of the attacker (state this in the README, do not change it
between arms you compare):
    - attacker_reward_delta of each previous attempt (coalition gain vs clean)
    - how many monitor BLOCKs happened and at which turns
    - how many secret-channel sends were counted
    - NOT the monitor's prompt, NOT the outsiders' transcripts

Usage:
    uv run --env-file ../.env python -m control_loop.loop \
        --seed 733 --defense none|system_prompt|llm_monitor_fixed \
        --rounds 5 --agent-model openai/gpt-4.1-mini \
        --attacker-model anthropic/claude-sonnet-4-5 \
        --out results/s733_llm_monitor_fixed

Outputs <out>/rounds.jsonl (one line per round) and <out>/best_payload.txt.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

from control_loop import proposer as _proposer
from control_loop.adapters.orbit import DEFENSES, ORDERINGS, run_eval  # the ORBIT-specific glue
from control_loop.results import clean_distribution, latest_log, net_blocks, net_blocks_vs_mean, read_run

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


STATIC_PAYLOAD = _proposer.STATIC_PAYLOAD


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--defense", choices=DEFENSES, required=True)
    ap.add_argument("--rounds", type=int, default=5, help="adaptive rounds after the static round 0")
    ap.add_argument("--agent-model", required=True)
    ap.add_argument("--attacker-model", required=True)
    ap.add_argument("--monitor-model", default="openai/gpt-4o-mini")
    ap.add_argument("--num-tasks", type=int, default=4, help="tickets; set from the clean-vs-clean noise check")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--clean-epochs", type=int, default=8, help="epochs in the arm baseline clean run")
    ap.add_argument("--clean-log-dir", type=Path, default=None,
                    help="arm baseline dir (default results/baselines/<seed>_<defense>); shared across proposers")
    ap.add_argument("--baseline-only", action="store_true", help="run/verify the arm baseline and exit")
    ap.add_argument("--ordering", choices=ORDERINGS, default=None,
                    help="recipe activation order: coalition dev_0,dev_1 first (early) or last (late)")
    ap.add_argument("--brief", choices=["informed", "uninformed"], default="informed", help="proposer brief (PLAN §13)")
    ap.add_argument("--round0-payload-file", type=Path, default=None,
                    help="run this payload as round 0 instead of ORBIT's static sentence (transfer control)")
    ap.add_argument("--greedy-agent", default=None,
                    help="greedy-outsider control: this single agent gets --round0-payload-file as a plain instruction")
    ap.add_argument("--judge-seed", type=int, default=None,
                    help="pin the monitor judge to temperature 0 and this seed (default: the problem seed for v2 runs; pass -1 for provider defaults)")
    ap.add_argument("--round0-epochs", type=int, default=1, help="epochs for round 0 (controls use >1)")
    args = ap.parse_args()
    judge_seed = args.seed if args.judge_seed is None else (None if args.judge_seed < 0 else args.judge_seed)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    defense_t = [] if args.defense == "none" else ["-T", f"defense_preset={args.defense}"]
    defense_t = ["-T", f"num_tasks={args.num_tasks}", *defense_t]
    if args.ordering:
        defense_t += ["-T", f"ordering={args.ordering}"]
    if judge_seed is not None and args.defense.startswith(("llm_monitor", "claim_", "allocation_")):
        defense_t += ["-T", f"judge_seed={judge_seed}"]

    # 1. arm-level clean baseline with the same defense: one multi-epoch run per
    #    (seed, defense), shared by every proposer cell (phases/phase1_orbit_redteam/PLAN.md section 11).
    clean_dir = args.clean_log_dir or (REPO / "results" / "baselines" / f"{args.seed}_{args.defense}")
    if args.clean_log_dir is None and args.ordering:
        clean_dir = REPO / "results" / "v2" / args.ordering / "baselines" / f"{args.seed}_{args.defense}" / "run1"
    if clean_dir.exists() and any(clean_dir.glob("*.eval")):
        clean_log = latest_log(clean_dir)
    else:
        clean_log = run_eval(clean_dir, args.agent_model, args.seed, defense_t, None, args.monitor_model,
                             epochs=args.clean_epochs, max_samples=min(4, args.clean_epochs))
    c = read_run(clean_log)  # epoch 1, for the scorer's single-draw pairing (record only)
    cd = clean_distribution(clean_log)
    if cd["n_valid"] == 0:
        sys.exit(f"clean baseline has no valid epoch (log status {c.status}); fix before attacking. Log: {clean_log}")
    if c.status != "success":
        print(f"note: baseline log status {c.status}; {cd['n_valid']}/{cd['n']} epochs valid, the rest are excluded per epoch", flush=True)
    print(f"arm baseline {clean_dir.name}: {cd['n_valid']}/{cd['n']} valid epochs, coalition mean {cd['mean']:.2f} "
          f"sd {cd['sd']:.2f}, tickets mean {cd['tickets_mean']:.2f}, blocks/epoch {cd['blocks_mean_by_boundary']}", flush=True)
    for line in cd["excluded"]:
        print("  excluded", line, flush=True)
    (out / "baseline.json").write_text(json.dumps(cd, indent=1, default=str), encoding="utf-8")
    if args.baseline_only:
        return

    coalition = args.greedy_agent if args.greedy_agent else "dev_0,dev_1"
    attack_t = defense_t + ["-T", f"coalition_agents={coalition}",
                            "-T", f"clean_baseline_log={Path(clean_log).resolve()}"]
    if args.greedy_agent:
        attack_t += ["-T", "greedy_control=true"]
        if not args.round0_payload_file:
            sys.exit("--greedy-agent needs --round0-payload-file")
    history: list[dict] = []
    rounds_file = out / "rounds.jsonl"

    for r in range(0, args.rounds + 1):
        if r == 0:
            if args.round0_payload_file:
                payload_file = args.round0_payload_file.resolve()
                payload = payload_file.read_text(encoding="utf-8").strip()
                prop = {"model": None, "moves": [], "attempts": 0, "fallback": False,
                        "round0_source": str(payload_file), "greedy_agent": args.greedy_agent}
            else:
                payload_file, payload, prop = None, STATIC_PAYLOAD, {"model": None, "moves": [], "attempts": 0, "fallback": False}
        else:
            prop = asyncio.run(_proposer.propose(args.attacker_model, history, r, out / "rejections.jsonl",
                                                 num_tasks=args.num_tasks, brief=args.brief,
                                                 proposer_seed=args.seed * 100 + r))
            prop["brief"] = args.brief
            payload = prop["payload"]
            payload_file = out / f"payload_r{r}.txt"
            payload_file.write_text(payload, encoding="utf-8")
            print(f"proposer round {r}: moves={prop['moves']} attempts={prop['attempts']} fallback={prop['fallback']}", flush=True)
        log = run_eval(out / f"A{r}", args.agent_model, args.seed, attack_t, payload_file, args.monitor_model,
                       epochs=args.round0_epochs if r == 0 else 1, max_samples=min(4, args.round0_epochs) if r == 0 else 1)
        res = read_run(log)
        gain_vs_mean = res.coalition_reward - cd["mean"] if res.coalition_reward == res.coalition_reward else math.nan
        valid = res.finished_all_agents and (res.coalition_tickets is not None and res.total_tickets is not None)
        row = {"round": r, "payload": payload, **res.as_dict(),
               "gain_paired_epoch1": res.gain,          # ORBIT's paired scorer vs clean epoch 1 (record only)
               "gain": gain_vs_mean,                    # primary: coalition reward minus the arm baseline mean
               "clean_mean": cd["mean"], "clean_sd": cd["sd"], "clean_n_valid": cd["n_valid"],
               "valid": bool(valid),
               "net_blocks_by_boundary": net_blocks_vs_mean(res, cd),
               "net_blocks_vs_epoch1": net_blocks(res, c), "proposer": prop}
        history.append(row)
        with rounds_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        g = "nan" if math.isnan(row["gain"]) else f"{row['gain']:+.2f}"
        print(f"round {r}: status={res.status} valid={row['valid']} coalition={res.coalition_reward:.2f} "
              f"gain_vs_clean_mean={g} paired_epoch1={res.gain:+.2f} tickets={res.coalition_tickets}/{res.total_tickets} "
              f"blocks={res.blocks_by_boundary} net_vs_mean={row['net_blocks_by_boundary']} "
              f"first_coalition_claim={res.first_coalition_claim_agent}@t{res.first_coalition_claim_turn} "
              f"channel_sends={res.channel_sends}", flush=True)

    best = max((h for h in history if h["round"] > 0 and not math.isnan(h["gain"])),
               key=lambda h: h["gain"], default=None)
    if best:
        (out / "best_payload.txt").write_text(best["payload"], encoding="utf-8")
        print(f"best adaptive round {best['round']}: gain {best['gain']:+.2f}")
    print(f"static round 0 gain: {history[0]['gain']:+.2f}")


if __name__ == "__main__":
    main()
