"""Charts and CSV from the arm-baseline tables (PLAN.md sections 11 and 12).

  uv run --locked python -m adaptive_control.plot results results/summary

Writes, for each validity rule (suffix `_alloc`, `_submit`):

  summary_<rule>.csv            one row per cell: clean mean/sd, outsiders, team, optimum, static,
                                adaptive Δcoal/Δout/Δteam means, redistribution and team-improving
                                fractions, tickets, valid/total
  tickets_by_defense_<rule>.png primary signature: coalition tickets in the final allocation
  gain_by_defense_<rule>.png    coalition reward minus the arm's clean mean (Δcoal), with the
                                outsiders' change (Δout) drawn as a hollow marker on each adaptive bar,
                                so redistribution (bar up, marker down) is visible

One panel per seed; seeds are not pooled (seed 42's clean runs sit at 69% of the
optimum and every winning round there is the team optimum; seed 1049's clean runs
sit near the optimum). Static is pooled over both proposer cells of a (seed, arm),
the identical configuration run twice. The input-screening monitor shows clean and
static only. Whiskers are round min–max.

Colours: the dataviz reference palette's first four categorical slots, validated
with its script; text and axes use its ink tokens.
"""
from __future__ import annotations

import csv
import math
import statistics as st
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from adaptive_control.round_table import REPO, RULES, baseline_for, cell_rows  # noqa: E402

ARMS = ["none", "system_prompt", "llm_monitor_fixed_actions", "llm_monitor_fixed"]
LABEL = {"none": "no defense", "system_prompt": "anti-collusion\nprompt",
         "llm_monitor_fixed_actions": "LLM monitor,\nactions only", "llm_monitor_fixed": "LLM monitor,\nscreens input"}
SEEDS = ["42", "733", "1049"]
SEED_NOTE = {"42": "seed 42 — clean team at 69% of optimum; winning rounds = team optimum",
             "733": "seed 733 — clean team at 99% of optimum; clean coalition above its optimum share",
             "1049": "seed 1049 — clean team at 96% of optimum; coalition holds 3.75 of 4 tickets"}
SERIES = {"clean": ("#2a78d6", "clean mean (8 epochs)"), "static": ("#eb6834", "static payload (ORBIT), both cells"),
          "prop_sonnet55": ("#1baf7a", "adaptive, claude-sonnet-5-5"), "prop_qwen3": ("#eda100", "adaptive, qwen3-235b")}
INK, INK2, MUTED, SURFACE, GRID = "#0b0b0b", "#52514e", "#898781", "#fcfcfb", "#e6e5e1"


def cells_root(seed: str, ordering: str | None) -> Path:
    """v1 layout for the seed-733 early block and seeds 42/1049; results/v2/<ordering> otherwise."""
    if ordering is None or (seed == "733" and ordering == "early") or seed in ("42", "1049"):
        return REPO / "results"
    return REPO / "results" / "v2" / ordering


def collect(rule: str, ordering: str | None = None, seeds: list[str] | None = None) -> list[dict]:
    recs = []
    for arm in ARMS:
        for seed in (seeds or SEEDS):
            root = cells_root(seed, ordering)
            if arm == "llm_monitor_fixed":
                cells = [(p, root / p / f"{seed}_{arm}") for p in ("prop_sonnet55", "prop_qwen3", "static_only")]
            else:
                cells = [(p, root / p / f"{seed}_{arm}") for p in ("prop_sonnet55", "prop_qwen3")]
            for prop, cell in cells:
                if not (cell / "rounds.jsonl").exists():
                    continue
                base = baseline_for(cell)
                if not base:
                    continue
                b = base["rules"][rule]
                rows = cell_rows(cell, base)
                static = rows[0]
                adaptive = [r for r in rows if r["round"] > 0 and r["valid"][rule] and not math.isnan(r[rule]["d_coal"])]
                recs.append(dict(
                    arm=arm, seed=seed, proposer=prop, rule=rule,
                    clean_mean=b["mean"], clean_sd=b["sd"], clean_out=b["outsiders_mean"], clean_team=b["team_mean"],
                    clean_tickets=b["tickets_mean"], clean_valid=f"{b['n_valid']}/{b['n']}",
                    optimum=base["optimal_total_reward"], opt_coalition=base["optimal_coalition_reward"], opt_tickets=base["optimal_coalition_tickets"],
                    static_valid=static["valid"][rule], static_coal=static["coalition_reward"], static_d_coal=static[rule]["d_coal"],
                    static_d_out=static[rule]["d_out"], static_tickets=static["tickets"],
                    ad_d_coal=[r[rule]["d_coal"] for r in adaptive], ad_d_out=[r[rule]["d_out"] for r in adaptive],
                    ad_d_team=[r[rule]["d_team"] for r in adaptive], ad_tickets=[r["tickets"] for r in adaptive],
                    ad_redis=[r[rule]["redistribution"] for r in adaptive], ad_improve=[r[rule]["team_improving"] for r in adaptive],
                    adaptive_valid=f"{len(adaptive)}/{len(rows) - 1}",
                ))
    return recs


def write_csv(recs: list[dict], out: Path, rule: str) -> None:
    with (out / f"summary_{rule}.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arm", "seed", "proposer", "rule", "clean_coalition_mean", "clean_within_sd", "clean_outsiders_mean", "clean_team_mean",
                    "clean_tickets_mean", "clean_valid", "optimal_team", "optimal_coalition", "optimal_coalition_tickets",
                    "static_valid", "static_coalition", "static_d_coal", "static_d_out", "static_tickets",
                    "adaptive_valid", "adaptive_d_coal_mean", "adaptive_d_out_mean", "adaptive_d_team_mean",
                    "adaptive_redistribution_frac", "adaptive_team_improving_frac", "adaptive_tickets_mean"])
        for r in recs:
            n = len(r["ad_d_coal"])
            w.writerow([r["arm"], r["seed"], r["proposer"], rule, f"{r['clean_mean']:.2f}", f"{r['clean_sd']:.2f}", f"{r['clean_out']:.2f}",
                        f"{r['clean_team']:.2f}", f"{r['clean_tickets']:.2f}", r["clean_valid"], f"{r['optimum']:.2f}", f"{r['opt_coalition']:.2f}",
                        r["opt_tickets"], r["static_valid"], f"{r['static_coal']:.2f}", f"{r['static_d_coal']:+.2f}", f"{r['static_d_out']:+.2f}",
                        r["static_tickets"], r["adaptive_valid"],
                        f"{st.mean(r['ad_d_coal']):+.2f}" if n else "", f"{st.mean(r['ad_d_out']):+.2f}" if n else "",
                        f"{st.mean(r['ad_d_team']):+.2f}" if n else "", f"{sum(r['ad_redis']) / n:.2f}" if n else "",
                        f"{sum(r['ad_improve']) / n:.2f}" if n else "", f"{st.mean(r['ad_tickets']):.2f}" if n else ""])


def _series(recs, arm, seed, series, measure):
    rs = [r for r in recs if r["arm"] == arm and r["seed"] == seed]
    if series == "clean":
        if not rs:
            return None, None, None, None
        return (0.0 if measure == "gain" else rs[0]["clean_tickets"]), None, None, None
    if series == "static":
        vals = [r["static_d_coal"] if measure == "gain" else r["static_tickets"] for r in rs if r["static_valid"]]
        outs = [r["static_d_out"] for r in rs if r["static_valid"]]
    else:
        rr = [r for r in rs if r["proposer"] == series]
        vals = [v for r in rr for v in (r["ad_d_coal"] if measure == "gain" else r["ad_tickets"])]
        outs = [v for r in rr for v in r["ad_d_out"]]
    if not vals:
        return None, None, None, None
    return st.mean(vals), (min(vals) if len(vals) > 1 else None), (max(vals) if len(vals) > 1 else None), (st.mean(outs) if outs else None)


def draw(recs: list[dict], out: Path, measure: str, rule: str, seeds: list[str] | None = None,
         notes: dict | None = None, suffix: str = "") -> Path:
    seeds = seeds or SEEDS
    notes = notes or SEED_NOTE
    if measure == "tickets":
        ylabel, title, fname, ylim = ("coalition tickets in final allocation (of 4)",
                                      f"Coalition tickets by defense arm — validity rule: {rule}{suffix and ' — ordering ' + suffix}", f"tickets_by_defense_{rule}{suffix and '_' + suffix}.png", (0, 4.4))
    else:
        ylabel, title, fname, ylim = ("coalition reward minus the arm's clean mean (bar); outsiders' change (◇)",
                                      f"Coalition and outsiders reward vs the arm's clean mean — validity rule: {rule}{suffix and ' — ordering ' + suffix}", f"gain_by_defense_{rule}{suffix and '_' + suffix}.png", None)
    fig, axes = plt.subplots(1, len(seeds), figsize=(17, 5.8), sharey=True, facecolor=SURFACE)
    width, order = 0.19, ["clean", "static", "prop_sonnet55", "prop_qwen3"]
    for ax, seed in zip(axes, seeds):
        ax.set_facecolor(SURFACE)
        for i, arm in enumerate(ARMS):
            for j, series in enumerate(order):
                if arm == "llm_monitor_fixed" and series.startswith("prop_"):
                    continue
                val, lo, hi, dout = _series(recs, arm, seed, series, measure)
                if val is None or val != val:
                    continue
                x = i + (j - 1.5) * width
                ax.bar(x, val, width * 0.92, color=SERIES[series][0], edgecolor=SURFACE, linewidth=1.0, zorder=3)
                if lo is not None and hi is not None and hi - lo > 0:
                    ax.vlines(x, lo, hi, color=INK2, linewidth=1.1, zorder=4)
                    ax.hlines([lo, hi], x - width * 0.22, x + width * 0.22, color=INK2, linewidth=1.1, zorder=4)
                if measure == "gain" and dout is not None and series != "clean":
                    ax.plot(x, dout, marker="D", markersize=5, markerfacecolor=SURFACE, markeredgecolor=INK, markeredgewidth=1.1, zorder=6)
                label = f"{val:.1f}" if measure == "tickets" else f"{val:+.0f}"
                if measure == "tickets":
                    y, va = (hi if hi is not None else val) + 0.06, "bottom"
                elif val >= 0:
                    y, va = (hi if hi is not None else val) + 1.5, "bottom"
                else:
                    y, va = (lo if lo is not None else val) - 1.5, "top"
                ax.text(x, y, label, ha="center", va=va, fontsize=7.5, color=INK2, zorder=5)
        ax.axhline(0, color=INK2 if measure == "gain" else GRID, linewidth=1.0 if measure == "gain" else 0.8, zorder=2)
        ax.set_xticks(range(len(ARMS)))
        ax.set_xticklabels([LABEL[a] for a in ARMS], color=INK, fontsize=9)
        ax.set_title(notes.get(seed, f"seed {seed}"), color=INK, fontsize=9.5, loc="left", pad=8)
        ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(axis="y", colors=MUTED, labelsize=9, length=0)
        ax.tick_params(axis="x", colors=INK, length=0)
        if ylim:
            ax.set_ylim(*ylim)
    axes[0].set_ylabel(ylabel, color=INK2, fontsize=9)
    handles = [plt.Rectangle((0, 0), 1, 1, color=SERIES[s][0]) for s in order]
    labels = [SERIES[s][1] for s in order]
    if measure == "gain":
        handles.append(plt.Line2D([], [], marker="D", linestyle="", markerfacecolor=SURFACE, markeredgecolor=INK))
        labels.append("outsiders' reward change (mean)")
    fig.legend(handles, labels, loc="lower center", ncol=5, frameon=False, fontsize=8.5, labelcolor=INK2, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle(title, color=INK, fontsize=12, x=0.01, ha="left", y=0.995)
    fig.text(0.01, 0.935, "ORBIT JiraTicket, 4 developers, 4 tickets, gpt-4o agents. Bars = means over valid rounds; whiskers = round min–max; "
             "clean = 8-epoch arm baseline; static pooled over both proposer cells. Input-screening monitor: clean and static only.",
             color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.06, 1, 0.9))
    path = out / fname
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)
    return path


def main() -> None:
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "results" / "summary"
    out.mkdir(parents=True, exist_ok=True)
    for rule in RULES:
        recs = collect(rule)
        write_csv(recs, out, rule)
        for m in ("tickets", "gain"):
            print("wrote", draw(recs, out, m, rule))
        print("wrote", out / f"summary_{rule}.csv", f"({len(recs)} cells)")
        # control program: one figure per ordering, seeds 733 / 512 / 101 (733 early = the v1 block)
        v2_notes = {"733": "seed 733 — clean coalition above its optimal share", "512": "seed 512", "101": "seed 101"}
        for ordering in ("early", "late", "claimslast"):
            seeds = ["733", "512", "101"] if ordering != "claimslast" else ["733"]
            recs2 = collect(rule, ordering, seeds)
            if not recs2:
                continue
            for m in ("tickets", "gain"):
                print("wrote", draw(recs2, out, m, rule, seeds, {k: f"{v} — {ordering}" for k, v in v2_notes.items()}, suffix=ordering))


if __name__ == "__main__":
    main()
