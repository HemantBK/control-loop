"""Fisher exact tests behind README §4 and §6.1 (coalition against outsider claim block rates).

Written 2026-10-22 (p14-corrections; SOP §4: every number traces to a script). No API call. Recomputes
the pooled 2×2 counts from the logs with the same functions as `control_loop.analysis.claim_rates`
(blocked / judged `assign_task` calls, coalition dev_0+dev_1 against outsiders dev_2+dev_3, adaptive
rounds A1..A5 pooled over the rounds valid under the allocation rule and under the completion
(submit) rule), then applies `scipy.stats.fisher_exact` (two-sided) to each pool. The claims are
not independent (they cluster within one seeded episode per round), so the p-values describe the
counts and are not a test of the cells; README §6.1 says so.

    uv run --locked python phases/phase2_claim_monitor/fisher.py            # from the repository root

Expected output: one row per (cell, pool) with the counts and p; the counts equal README §6.1 and the
p-values equal README §4 / §6.1 to two decimals (early mini 0.11 / 0.09, late mini 0.31 / 0.41,
early rule 0.54 (allocation; no submit-valid round), late rule 0.12 / 0.25, early gpt-4o 0.001).
"""
from __future__ import annotations

from pathlib import Path

from inspect_ai.log import read_eval_log
from scipy.stats import fisher_exact

from control_loop.analysis.claim_rates import _logs, counts_for_sample, validity_pools
from control_loop.results import read_run

ROOT = Path("results/phase2_claim_monitor")
CELLS = [
    ("early mini", ROOT / "early/prop_sonnet55/733_claim_time_monitor"),
    ("early gpt-4o", ROOT / "early/prop_sonnet55/733_claim_time_monitor_4o"),
    ("early rule", ROOT / "early/prop_sonnet55/733_claim_rule_monitor"),
    ("late mini", ROOT / "late/prop_sonnet55/733_claim_time_monitor"),
    ("late rule", ROOT / "late/prop_sonnet55/733_claim_rule_monitor"),
]
COALITION = ["dev_0", "dev_1"]


def adaptive_rows(cell: Path) -> list[dict]:
    rows = []
    for sub in sorted(cell.glob("A*"), key=lambda p: int(p.name[1:])):
        if sub.name == "A0":
            continue
        for lp in _logs(sub):
            log = read_eval_log(lp)
            for s in log.samples or []:
                r = read_run(lp, epoch=s.epoch)
                rows.append({"id": f"{sub.name} ep{s.epoch}", "counts": counts_for_sample(s),
                             "valid_alloc": bool(r.valid_alloc), "valid_submit": bool(r.valid_submit)})
    return rows


def main() -> None:
    print("cell | pool | rounds | coalition blocked/judged | outsiders blocked/judged | Fisher two-sided p")
    for name, cell in CELLS:
        rows = adaptive_rows(cell)
        for label, ids, p in validity_pools(rows, COALITION):
            if label == "all rounds":
                continue
            c, o = p["coalition"], p["outsiders"]
            if not ids or (c["judged"] + o["judged"]) == 0:
                print(f"{name} | {label} | none | – | – | no valid round")
                continue
            table = [[c["blocked"], c["judged"] - c["blocked"]], [o["blocked"], o["judged"] - o["blocked"]]]
            _, pval = fisher_exact(table, alternative="two-sided")
            print(f"{name} | {label} | {len(ids)} ({', '.join(i.split()[0] for i in ids)}) | "
                  f"{c['blocked']}/{c['judged']} | {o['blocked']}/{o['judged']} | {pval:.3f}")


if __name__ == "__main__":
    main()
