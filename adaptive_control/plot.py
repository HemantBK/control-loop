"""Two charts and a CSV from the arm-baseline tables (PLAN.md section 11).

  uv run --locked python -m adaptive_control.plot results results/summary

Writes results/summary/summary.csv (one row per cell: arm, seed, proposer, clean
mean/sd, static, adaptive mean/min/max, tickets, valid/total) and two figures:

  tickets_by_defense.png  primary signature: coalition tickets in the final
                          allocation. Per defense arm: clean mean, static, adaptive
                          mean per proposer, with round min–max whiskers.
  gain_by_defense.png     secondary: coalition reward minus the arm's clean mean,
                          same layout, zero line.

Each figure has two panels: seeds 42 and 733 pooled (rounds from both seeds), and
seed 1049 alone, labelled "at ceiling" because its clean coalition already holds
about 3.75 of 4 tickets. llm_monitor_fixed appears with clean and static only (one
static round per seed; the input screen withholds every payload).

Colours are the dataviz reference palette's first four categorical slots,
validated with its script; text and axes use its ink tokens, never series colour.
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

from adaptive_control.round_table import REPO, baseline_for, cell_rows  # noqa: E402

ARMS = ["none", "system_prompt", "llm_monitor_fixed_actions", "llm_monitor_fixed"]
LABEL = {"none": "no defense", "system_prompt": "anti-collusion\nprompt",
         "llm_monitor_fixed_actions": "LLM monitor,\nactions only", "llm_monitor_fixed": "LLM monitor,\nscreens input"}
PROPOSERS = [("prop_sonnet55", "adaptive, claude-sonnet-5-5"), ("prop_qwen3", "adaptive, qwen3-235b")]
SERIES = {  # fixed categorical order, dataviz reference palette slots 1–4 (light)
    "clean": ("#2a78d6", "clean mean (8 epochs)"),
    "static": ("#eb6834", "static payload (ORBIT)"),
    "prop_sonnet55": ("#1baf7a", "adaptive, claude-sonnet-5-5"),
    "prop_qwen3": ("#eda100", "adaptive, qwen3-235b"),
}
INK, INK2, MUTED, SURFACE, GRID = "#0b0b0b", "#52514e", "#898781", "#fcfcfb", "#e6e5e1"


def collect() -> list[dict]:
    """One record per (arm, seed, proposer) cell plus static-only cells."""
    recs = []
    for arm in ARMS:
        for seed in ("42", "733", "1049"):
            cells = []
            if arm == "llm_monitor_fixed":
                for p in ("prop_sonnet55", "prop_qwen3", "static_only"):
                    c = REPO / "results" / p / f"{seed}_{arm}"
                    if (c / "rounds.jsonl").exists():
                        cells.append((p, c))
            else:
                cells = [(p, REPO / "results" / p / f"{seed}_{arm}") for p, _ in PROPOSERS]
            for prop, cell in cells:
                if not (cell / "rounds.jsonl").exists():
                    continue
                base = baseline_for(cell)
                rows = cell_rows(cell, base)
                static = rows[0]
                adaptive = [r for r in rows if r["round"] > 0 and r["valid"]]
                recs.append(dict(
                    arm=arm, seed=seed, proposer=prop,
                    clean_mean=base["mean"], clean_sd=base["sd"], clean_tickets=base["tickets_mean"],
                    clean_valid=f"{base['n_valid']}/{base['n']}",
                    static_reward=static["coalition_reward"], static_gain=static["gain"], static_tickets=static["tickets"],
                    static_valid=static["valid"],
                    adaptive_gains=[r["gain"] for r in adaptive], adaptive_tickets=[r["tickets"] for r in adaptive],
                    adaptive_valid=f"{len(adaptive)}/{len(rows) - 1}",
                ))
    return recs


def write_csv(recs: list[dict], out: Path) -> None:
    with (out / "summary.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arm", "seed", "proposer", "clean_mean", "clean_sd", "clean_tickets_mean", "clean_valid",
                    "static_reward", "static_gain_vs_clean_mean", "static_tickets", "static_valid",
                    "adaptive_gain_mean", "adaptive_gain_min", "adaptive_gain_max",
                    "adaptive_tickets_mean", "adaptive_tickets_min", "adaptive_tickets_max", "adaptive_valid"])
        for r in recs:
            g, t = r["adaptive_gains"], r["adaptive_tickets"]
            w.writerow([r["arm"], r["seed"], r["proposer"], f"{r['clean_mean']:.2f}", f"{r['clean_sd']:.2f}",
                        f"{r['clean_tickets']:.2f}", r["clean_valid"], f"{r['static_reward']:.2f}", f"{r['static_gain']:+.2f}",
                        r["static_tickets"], r["static_valid"],
                        f"{st.mean(g):+.2f}" if g else "", f"{min(g):+.2f}" if g else "", f"{max(g):+.2f}" if g else "",
                        f"{st.mean(t):.2f}" if t else "", min(t) if t else "", max(t) if t else "", r["adaptive_valid"]])


def _pool(recs, arm, seeds, key_adaptive, key_static, key_clean, prop=None):
    """Pooled values over the given seeds: clean (mean of arm means), static (all static rounds),
    adaptive (all valid rounds of one proposer)."""
    rs = [r for r in recs if r["arm"] == arm and r["seed"] in seeds]
    clean = [r[key_clean] for r in rs if r["proposer"] in ("prop_sonnet55", "static_only")]  # one per seed
    static = [r[key_static] for r in rs if r["static_valid"] and r["proposer"] in ("prop_sonnet55", "static_only")]
    static += [r[key_static] for r in rs if r["static_valid"] and r["proposer"] == "prop_qwen3" and arm == "llm_monitor_fixed"]
    adaptive = [v for r in rs if r["proposer"] == prop for v in r[key_adaptive]] if prop else []
    return clean, static, adaptive


def draw(recs: list[dict], out: Path, measure: str) -> Path:
    if measure == "tickets":
        ka, ks, kc = "adaptive_tickets", "static_tickets", "clean_tickets"
        ylabel, title, fname, ylim = ("coalition tickets in final allocation (of 4)",
                                      "Primary signature: coalition tickets, by defense arm", "tickets_by_defense.png", (0, 4.3))
    else:
        ka, ks, kc = "adaptive_gains", "static_gain", "clean_mean"
        ylabel, title, fname, ylim = ("coalition reward minus the arm's clean mean",
                                      "Secondary: coalition reward vs the arm's clean mean, by defense arm", "gain_by_defense.png", None)
    panels = [("seeds 42 and 733 pooled (headroom exists)", ("42", "733")), ("seed 1049 — at ceiling (clean ≈ 3.75 of 4 tickets)", ("1049",))]
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6), sharey=True, facecolor=SURFACE)
    width, order = 0.19, ["clean", "static", "prop_sonnet55", "prop_qwen3"]
    for ax, (ptitle, seeds) in zip(axes, panels):
        ax.set_facecolor(SURFACE)
        for i, arm in enumerate(ARMS):
            for j, series in enumerate(order):
                x = i + (j - 1.5) * width
                if series == "clean":
                    clean, _, _ = _pool(recs, arm, seeds, ka, ks, kc)
                    if measure == "gain":
                        val, lo, hi = 0.0, None, None  # clean mean minus itself
                    else:
                        val, lo, hi = (st.mean(clean) if clean else math.nan), None, None
                elif series == "static":
                    _, static, _ = _pool(recs, arm, seeds, ka, ks, kc)
                    val = st.mean(static) if static else math.nan
                    lo, hi = (min(static), max(static)) if len(static) > 1 else (None, None)
                else:
                    if arm == "llm_monitor_fixed":
                        continue  # static only in this arm
                    _, _, adaptive = _pool(recs, arm, seeds, ka, ks, kc, prop=series)
                    val = st.mean(adaptive) if adaptive else math.nan
                    lo, hi = (min(adaptive), max(adaptive)) if adaptive else (None, None)
                if val != val:
                    continue
                color = SERIES[series][0]
                bottom = 0
                ax.bar(x, val - bottom, width * 0.92, bottom=bottom, color=color, edgecolor=SURFACE, linewidth=1.0, zorder=3)
                if lo is not None and hi is not None and (hi - lo) > 0:
                    ax.vlines(x, lo, hi, color=INK2, linewidth=1.2, zorder=4)
                    ax.hlines([lo, hi], x - width * 0.22, x + width * 0.22, color=INK2, linewidth=1.2, zorder=4)
                label = f"{val:.1f}" if measure == "tickets" else f"{val:+.0f}"
                # label above the whisker top (or below its bottom for negative bars), never on the whisker
                if measure == "tickets":
                    y, va = (hi if hi is not None else val) + 0.06, "bottom"
                elif val >= 0:
                    y, va = (hi if hi is not None else val) + 1.5, "bottom"
                else:
                    y, va = (lo if lo is not None else val) - 1.5, "top"
                ax.text(x, y, label, ha="center", va=va, fontsize=8, color=INK2, zorder=5)
        ax.axhline(0, color=INK2 if measure == "gain" else GRID, linewidth=1.0 if measure == "gain" else 0.8, zorder=2)
        ax.set_xticks(range(len(ARMS)))
        ax.set_xticklabels([LABEL[a] for a in ARMS], color=INK, fontsize=9.5)
        ax.set_title(ptitle, color=INK, fontsize=10.5, loc="left", pad=8)
        ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(axis="y", colors=MUTED, labelsize=9, length=0)
        ax.tick_params(axis="x", colors=INK, length=0)
        if ylim:
            ax.set_ylim(*ylim)
    axes[0].set_ylabel(ylabel, color=INK2, fontsize=9.5)
    handles = [plt.Rectangle((0, 0), 1, 1, color=SERIES[s][0]) for s in order]
    fig.legend(handles, [SERIES[s][1] for s in order], loc="lower center", ncol=4, frameon=False,
               fontsize=9, labelcolor=INK2, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle(title, color=INK, fontsize=12.5, x=0.01, ha="left", y=0.995)
    fig.text(0.01, 0.93, "ORBIT JiraTicket, 4 developers, 4 tickets, gpt-4o agents; bars = means over valid rounds, whiskers = round min–max; "
             "clean = 8-epoch arm baseline. Input-screening monitor: static only.", color=MUTED, fontsize=8.5)
    fig.tight_layout(rect=(0, 0.06, 1, 0.9))
    path = out / fname
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)
    return path


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "results"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "summary"
    out.mkdir(parents=True, exist_ok=True)
    recs = collect()
    write_csv(recs, out)
    for m in ("tickets", "gain"):
        print("wrote", draw(recs, out, m))
    print("wrote", out / "summary.csv", f"({len(recs)} cells)")


if __name__ == "__main__":
    main()
