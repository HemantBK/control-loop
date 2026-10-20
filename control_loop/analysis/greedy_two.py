"""Two-independent-greedy control, per agent (phases/phase2_claim_monitor/PLAN.md §16.12a).

For each cell directory (round 0 only, several epochs): every agent's reward minus its own
two-run clean mean, the pair sum, the outsiders' sum, coalition tickets, halt reason, validity under
both rules, and whether the two greedy agents collided on a first claim (a greedy agent's first
assign_task fails because the other greedy agent already holds the ticket; "blind" only when that
agent had not called view_tasks before it). Beside it, for the same (seed, ordering, arm):
the Phase 1 single-greedy pair gain and the coalition cell's Δcoal (passed in by hand from the Phase 1
tables, they are quoted, not recomputed).

    uv run --locked python -m control_loop.analysis.greedy_two <cell> [<cell> ...]
"""
from __future__ import annotations

import argparse
import re
import statistics as st
from pathlib import Path

from inspect_ai.log import read_eval_log

from control_loop.results import latest_log, read_run
from control_loop.round_table import RULES, baseline_for

AGENTS = ("dev_0", "dev_1", "dev_2", "dev_3")


_TAKEN = re.compile(r"already (?:been )?(?:assigned|claimed)(?: to (dev_\d+))?", re.I)


def first_claim_collisions(seq: list[tuple[str, str, str | None, str]], greedy=("dev_0", "dev_1")) -> list[dict]:
    """First-claim collisions between the greedy agents, from an ordered event sequence of
    (agent, tool function, task_id, result-or-error text).

    A collision is a greedy agent's FIRST assign_task attempt failing because the ticket is already
    held by the OTHER greedy agent (ORBIT's text: "Error: Task X is already assigned to dev_N."). It is
    labelled blind only if that agent made no view_tasks call before the attempt; otherwise it is a
    collision after viewing. A first claim that fails on a ticket an outsider holds is not counted."""
    viewed: set[str] = set()
    seen: set[str] = set()
    hit: list[dict] = []
    for agent, fn, task_id, text in seq:
        if agent not in greedy:
            continue
        if fn == "view_tasks":
            viewed.add(agent)
            continue
        if fn != "assign_task" or agent in seen:
            continue
        seen.add(agent)
        m = _TAKEN.search(text or "")
        if not m:
            continue
        owner = m.group(1)
        if owner is None or owner == agent or owner not in greedy:
            continue
        hit.append({"agent": agent, "task_id": task_id, "owner": owner, "blind": agent not in viewed})
    return hit


def fmt_collisions(hits: list[dict]) -> list[str]:
    return [f"{h['agent']}:{h['task_id']}" + ("" if h["blind"] else " (after view_tasks)") for h in hits]


def collisions(log, sample, greedy=("dev_0", "dev_1")) -> list[dict]:
    """first_claim_collisions over one sample's tool events (agent identity from the span turns)."""
    from control_loop.results import _span_turns
    turns = _span_turns(log, sample)
    seq = []
    for e in sample.events:
        if e.event != "tool" or e.function not in ("assign_task", "view_tasks"):
            continue
        agent = turns.get(e.span_id, ("?", None))[0]
        text = str(e.error.message) if e.error is not None else str(e.result or "")
        seq.append((agent, e.function, (e.arguments or {}).get("task_id"), text))
    return first_claim_collisions(seq, greedy)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cells", nargs="+")
    a = ap.parse_args()
    for rule in RULES:
        print(f"\n#### Validity rule: {rule}\n")
        print("| cell | valid | Δ dev_0 | Δ dev_1 | Δ dev_2 | Δ dev_3 | Δ(dev_0+dev_1) | Δout | coalition tickets | halt reasons | first-claim collisions with the other greedy agent, per epoch (blind unless marked) | team / opt |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for c in a.cells:
            cell = Path(c)
            base = baseline_for(cell)
            if not base:
                print(f"| {cell} | no baseline found | | | | | | | | | | |")
                continue
            pam = base["rules"][rule].get("per_agent_mean") or {}
            lp = latest_log(cell / "A0")
            full = read_eval_log(lp)
            rows, halts, colls = [], [], []
            for smp in sorted(full.samples or [], key=lambda x: x.epoch):
                r = read_run(lp, epoch=smp.epoch)
                halts.append(r.halt_reason or "?")
                colls.append(fmt_collisions(collisions(full, smp)))
                ok = r.valid_alloc if rule == "alloc" else r.valid_submit
                if ok:
                    rows.append(r)
            if not rows:
                print(f"| {cell.name} | 0/{len(full.samples or [])} | – | – | – | – | – | – | – | {', '.join(halts)} | {colls} | – |")
                continue
            d = {ag: st.mean(r.per_agent_reward.get(ag, 0.0) - pam.get(ag, 0.0) for r in rows) for ag in AGENTS}
            pair, out = d["dev_0"] + d["dev_1"], d["dev_2"] + d["dev_3"]
            tk = st.mean(sum(1 for o in r.final_owner.values() if o in ("dev_0", "dev_1")) for r in rows)
            topt = st.mean(r.team_reward / r.optimal_total_reward for r in rows if r.optimal_total_reward == r.optimal_total_reward)
            per_epoch = "; ".join(f"ep{r.log and i + 1}: {r.per_agent_reward.get('dev_0', 0) - pam.get('dev_0', 0):+.1f}/{r.per_agent_reward.get('dev_1', 0) - pam.get('dev_1', 0):+.1f}"
                                  for i, r in enumerate(rows))
            print(f"| {cell.name} | {len(rows)}/{len(full.samples or [])} | {d['dev_0']:+.1f} | {d['dev_1']:+.1f} | {d['dev_2']:+.1f} | {d['dev_3']:+.1f} | "
                  f"{pair:+.1f} | {out:+.1f} | {tk:.1f} | {', '.join(halts)} | {colls} | {topt * 100:.0f}% |")
            print(f"  per valid epoch Δdev_0/Δdev_1: {per_epoch}")


if __name__ == "__main__":
    main()
