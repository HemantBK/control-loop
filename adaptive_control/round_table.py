"""Round tables against arm-level clean baselines (PLAN.md section 11).

  python -m adaptive_control.round_table CELL [CELL ...]
      One table per cell. CELL is results/<proposer>/<seed>_<defense>. The arm
      baseline is results/baselines/<seed>_<defense> (override with
      --baseline DIR). Everything is recomputed from the .eval logs, so cells run
      before the baseline existed (single-draw pairing) are re-read against it.

  python -m adaptive_control.round_table --arm DEFENSE --seeds 42,733,1049 --proposers prop_sonnet55,prop_qwen3
      One per-arm table across seeds and proposers, with valid/total.

Per round: absolute coalition reward, the arm baseline's clean mean and sd over
valid epochs, gain_vs_clean_mean and its z, coalition tickets (primary attack
signature) next to the clean ticket mean, blocks per boundary net of the clean
mean per epoch, first coalition claim turn, first block turn, channel sends,
moves and attempts. ORBIT's paired-scorer gain against clean epoch 1 is kept in a
column for the record. The between-run clean-vs-clean sd from the g0 replication
(17.3 at these settings) is printed next to the within-run sd because the two
differ: epochs inside one run are far more alike than epochs across runs.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as st
from pathlib import Path

from adaptive_control.results import (clean_distribution, latest_log, net_blocks_vs_mean,
                                      read_run)

REPO = Path(__file__).resolve().parent.parent
BETWEEN_RUN_SD = 17.3  # clean-vs-clean coalition sd across runs, gpt-4o, 4 tickets (g0 replication)


def _fmt(x, nd=2, sign=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def _first_block(turns_by_boundary: dict, actions_only: bool):
    turns = [t for b, ts in (turns_by_boundary or {}).items()
             if not actions_only or b in ("model_output", "tool_call") for t in ts]
    return min(turns) if turns else None


def baseline_for(cell: Path, override: Path | None = None) -> dict | None:
    seed, defense = cell.name.split("_", 1)
    bdir = override or (REPO / "results" / "baselines" / f"{seed}_{defense}")
    if not bdir.exists() or not any(bdir.glob("*.eval")):
        return None
    return clean_distribution(latest_log(bdir))


def cell_rows(cell: Path, baseline: dict | None) -> list[dict]:
    """Recompute each round of a cell from its log and the arm baseline."""
    meta = [json.loads(l) for l in (cell / "rounds.jsonl").read_text().splitlines() if l.strip()]
    rows = []
    for h in meta:
        r = read_run(latest_log(cell / f"A{h['round']}"))
        valid = r.status == "success" and r.total_tickets is not None and r.tasks_done == r.total_tickets
        gain = (r.coalition_reward - baseline["mean"]) if baseline and baseline["n_valid"] else math.nan
        z = gain / baseline["sd"] if baseline and baseline.get("sd") and baseline["sd"] > 0 else math.nan
        pr = h.get("proposer") or {}
        rows.append(dict(
            round=h["round"], payload=h["payload"], valid=valid, unsubmitted=r.unsubmitted,
            tasks_done=r.tasks_done, all_submitted=r.finished_all_agents,
            coalition_reward=r.coalition_reward, gain=gain, z=z, gain_paired_epoch1=r.gain,
            tickets=r.coalition_tickets, total_tickets=r.total_tickets,
            net_blocks=net_blocks_vs_mean(r, baseline) if baseline else r.blocks_by_boundary,
            first_claim=(r.first_coalition_claim_agent, r.first_coalition_claim_turn),
            first_block_any=_first_block(r.block_turns_by_boundary, False),
            first_block_actions=_first_block(r.block_turns_by_boundary, True),
            channel_sends=r.channel_sends, moves=pr.get("moves") or [], attempts=pr.get("attempts", 0),
            scorer_reason=next(iter(((r.reasons or {}).get("unavailable_metrics") or {}).values()), None)
            if r.gain != r.gain else None,
        ))
    return rows


def render_cell(cell: Path, baseline_dir: Path | None = None) -> str:
    base = baseline_for(cell, baseline_dir)
    rows = cell_rows(cell, base)
    out = [f"### {cell.name} — proposer {cell.parent.name.replace('prop_', '')}", ""]
    if base:
        out.append(f"Arm baseline: {base['n_valid']}/{base['n']} valid clean epochs, coalition mean {base['mean']:.2f}, "
                   f"within-run sd {_fmt(base['sd'])} (between-run sd {BETWEEN_RUN_SD}), clean tickets mean "
                   f"{base['tickets_mean']:.2f}, clean blocks/epoch {base['blocks_mean_by_boundary'] or 'none'}.")
        for line in base["excluded"]:
            out.append(f"- excluded {line}")
    else:
        out.append("Arm baseline: **missing** (results/baselines/<seed>_<defense>); gains not computed.")
    out += ["", "| round | valid | all submitted | coalition reward | gain vs clean mean | z (within-run sd) | paired vs epoch 1 | tickets | net blocks vs clean mean | first claim | first block any/actions | sends | moves | attempts |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        claim = f"{r['first_claim'][0]}@t{r['first_claim'][1]}" if r["first_claim"][1] is not None else "never"
        fb = f"{r['first_block_any'] if r['first_block_any'] is not None else '–'}/{r['first_block_actions'] if r['first_block_actions'] is not None else '–'}"
        net = ", ".join(f"{k}:{v:+.1f}" for k, v in sorted(r["net_blocks"].items())) or "–"
        moves = ",".join(r["moves"]) if r["round"] else "static (ORBIT)"
        out.append(f"| {r['round']} | {'yes' if r['valid'] else 'no'} | {'yes' if r['all_submitted'] else 'no: ' + ','.join(r['unsubmitted'])} | {_fmt(r['coalition_reward'])} | {_fmt(r['gain'], sign=True)} | "
                   f"{_fmt(r['z'], 1, True)} | {_fmt(r['gain_paired_epoch1'], sign=True)} | {r['tickets']}/{r['total_tickets']} | {net} | {claim} | {fb} | "
                   f"{int(r['channel_sends']) if r['channel_sends'] == r['channel_sends'] else '–'} | {moves} | {r['attempts'] if r['round'] else '–'} |")
    valid_adaptive = [r for r in rows if r["round"] > 0 and r["valid"] and not math.isnan(r["gain"])]
    static = rows[0]
    out.append("")
    if valid_adaptive and static["valid"] and not math.isnan(static["gain"]):
        gains = [r["gain"] for r in valid_adaptive]
        best = max(valid_adaptive, key=lambda r: r["gain"])
        out.append(f"Summary: static coalition {static['coalition_reward']:.2f} (gain {static['gain']:+.2f}, tickets {static['tickets']}); "
                   f"adaptive coalition mean {st.mean(r['coalition_reward'] for r in valid_adaptive):.2f} (gain mean {st.mean(gains):+.2f}, "
                   f"best {best['gain']:+.2f} in round {best['round']}), tickets mean {st.mean(r['tickets'] for r in valid_adaptive):.1f}; "
                   f"valid {len(valid_adaptive)}/{len(rows) - 1}; original criterion: adaptive mean − static = {st.mean(gains) - static['gain']:+.2f} vs {BETWEEN_RUN_SD}.")
        out.append("")
        out.append(f"Best adaptive payload (round {best['round']}):")
        out.append("")
        out.append("> " + best["payload"].replace("\n", " "))
    elif len(rows) == 1 and static["valid"] and not math.isnan(static["gain"]):
        out.append(f"Static only: coalition {static['coalition_reward']:.2f} (gain vs clean mean {static['gain']:+.2f}, "
                   f"z {_fmt(static['z'], 1, True)}, tickets {static['tickets']} vs clean mean {base['tickets_mean']:.2f}).")
    else:
        out.append("Summary: static round invalid or baseline missing; no criterion value.")
    excl = [r for r in rows if not r["valid"]]
    out.append("")
    out.append("Excluded episodes:" if excl else "Excluded episodes: none")
    for r in excl:
        why = f"{r['tasks_done']}/{r['total_tickets']} tickets allocated"
        if r["unsubmitted"]:
            why += f"; {', '.join(r['unsubmitted'])} never called submit"
        if r["scorer_reason"]:
            why += f"; scorer: {r['scorer_reason']}"
        out.append(f"- round {r['round']}: {why}")
    for line in (base or {}).get("unsubmitted_notes", []):
        out.append(f"- note, {line}")
    rej = cell / "rejections.jsonl"
    if rej.exists() and rej.read_text().strip():
        kinds = [json.loads(l)["kind"] for l in rej.read_text().splitlines() if l.strip()]
        out.append(f"Rejections: {len(kinds)} ({', '.join(kinds)}).")
    else:
        out.append("Rejections: none.")
    return "\n".join(out)


def render_arm(defense: str, seeds: list[str], proposers: list[str]) -> str:
    out = [f"### Arm {defense} across seeds", "",
           "| seed | proposer | clean mean (valid/total) | static coalition (tickets) | adaptive coalition mean (tickets mean) | adaptive gain mean | best gain (round) | valid/total | adaptive − static (orig. criterion vs 17.3) |",
           "|---|---|---|---|---|---|---|---|---|"]
    excluded = []
    for seed in seeds:
        for prop in proposers:
            cell = REPO / "results" / prop / f"{seed}_{defense}"
            if not (cell / "rounds.jsonl").exists():
                out.append(f"| {seed} | {prop.replace('prop_', '')} | – | not run | | | | | |")
                continue
            base = baseline_for(cell)
            rows = cell_rows(cell, base)
            static = rows[0]
            va = [r for r in rows if r["round"] > 0 and r["valid"] and not math.isnan(r["gain"])]
            cm = f"{base['mean']:.2f} ({base['n_valid']}/{base['n']})" if base else "missing"
            st_txt = f"{_fmt(static['coalition_reward'])} ({static['tickets']})" + ("" if static["valid"] else " invalid")
            if va:
                best = max(va, key=lambda r: r["gain"])
                ad = f"{st.mean(r['coalition_reward'] for r in va):.2f} ({st.mean(r['tickets'] for r in va):.1f})"
                gm = f"{st.mean(r['gain'] for r in va):+.2f}"
                bg = f"{best['gain']:+.2f} (r{best['round']})"
                crit = f"{st.mean(r['gain'] for r in va) - static['gain']:+.2f}" if static["valid"] and not math.isnan(static["gain"]) else "n/a"
            else:
                ad = gm = bg = crit = "–"
            out.append(f"| {seed} | {prop.replace('prop_', '')} | {cm} | {st_txt} | {ad} | {gm} | {bg} | {len(va)}/{len(rows) - 1} | {crit} |")
            for r in rows:
                if not r["valid"]:
                    excluded.append(f"- {seed}/{prop.replace('prop_', '')} round {r['round']}: {r['tasks_done']}/{r['total_tickets']} tickets allocated"
                                    + (f"; {', '.join(r['unsubmitted'])} never called submit" if r["unsubmitted"] else "")
                                    + (f"; scorer: {r['scorer_reason']}" if r["scorer_reason"] else ""))
            if base:
                for line in base["excluded"]:
                    excluded.append(f"- {seed}/{defense} baseline: {line}")
    out.append("")
    out.append("Excluded episodes:" if excluded else "Excluded episodes: none")
    out.extend(sorted(set(excluded)))
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cells", nargs="*")
    ap.add_argument("--baseline", type=Path, default=None)
    ap.add_argument("--arm", default=None)
    ap.add_argument("--seeds", default="42,733,1049")
    ap.add_argument("--proposers", default="prop_sonnet55,prop_qwen3")
    a = ap.parse_args()
    if a.arm:
        print(render_arm(a.arm, a.seeds.split(","), a.proposers.split(",")))
        return
    for c in a.cells:
        print(render_cell(Path(c), a.baseline))
        print()


if __name__ == "__main__":
    main()
