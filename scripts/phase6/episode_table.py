"""Cell 733, one row per episode (write-up, 2026-10-27): the reader's fields for the 24 episodes, plus how many agent
commands opencode's shell tool killed at its 120 s default (PLAN Amendment (34)), counted in the episode's raw
`red_team/` files. Read from the episode folders under results/phase6_researcharena/batch_733/ as the cell's report is.

    uv run --frozen python scripts/phase6/episode_table.py      (writes batch_733/EPISODES.md and episodes.json)"""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cell_batch", HERE / "cell_batch.py")
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)

GROUPS = ["clean_run1", "clean_run2", "r0a", "r1", "r2", "r3"]
KILL = "shell tool terminated command after exceeding timeout 120000 ms"
FIELDS = ("side_task_score", "compile_status", "main_task_score", "main_task_success", "suspicion_score", "ended_by",
          "agent_rc", "red_team_time_s", "n_tool_calls", "n_bench_runs", "V1", "V2")


def kills(eval_dir):
    """Distinct tool results carrying the 120 s kill text, in the no-CoT transcript (one line per tool result)."""
    p = Path(eval_dir) / "red_team" / "solve_parsed_no_cot.txt"   # repo-relative, as the reader gives it
    return sum(1 for line in p.read_text(errors="replace").splitlines() if KILL in line) if p.is_file() else None


def main():
    st = cb.load()
    rows = []
    for g in GROUPS:
        for r in cb.rows_of(st, g):
            rows.append(dict({k: r.get(k) for k in FIELDS}, group=g, episode_id=r["episode_id"],
                             kills_120s=kills(r["eval_dir"])))
    cb.fw.write_json(cb.BATCH / "episodes.json", dict(rows=rows, kill_text=KILL))
    n_kill = sum(1 for r in rows if r["kills_120s"])
    head = ("| episode | group | side score | compile | main score | main pass | suspicion | ended by (rc) | agent s | "
            "tool calls | bench runs | 120 s kills | V1 | V2 |")
    lines = ["# Cell 733, per episode", "",
             "Written by `scripts/phase6/episode_table.py` from the episode folders through the reader (`rows_of` in "
             "`scripts/phase6/cell_batch.py`). Main pass = compile PASS and main score >= 1.0 (PLAN §4); main score rounded to 4 decimals here, unrounded in `episodes.json`. Clean "
             "episodes carry no side score (-1 in results.json). 120 s kills = transcript lines with "
             f"\"{KILL}\".", "",
             f"- Episodes with at least one 120 s kill: {n_kill}/{len(rows)}.", "", head, "|" + "---|" * 14]
    for r in rows:
        lines.append(f"| {r['episode_id']} | {r['group']} | {r['side_task_score']} | {r['compile_status']} | "
                     f"{'-' if r['main_task_score'] is None else round(r['main_task_score'], 4)} | {r['main_task_success']} | {r['suspicion_score']} | "
                     f"{r['ended_by']} ({r['agent_rc']}) | {r['red_team_time_s']} | {r['n_tool_calls']} | "
                     f"{r['n_bench_runs']} | {r['kills_120s']} | {r['V1']} | {r['V2']} |")
    (cb.BATCH / "EPISODES.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
