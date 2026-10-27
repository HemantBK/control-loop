"""Cell 733 under the three readings of an agent's last `[agent]` line (PLAN Amendment (36) item 2). V2 needs every
episode of a round to have ended by budget or by exit 0 and compiled (PLAN §4). The readings differ only in when an
episode counts as ended:
- `last_rc`: the last `[agent]` line that carries an exit code decides (the reading cell 733's REPORT.md used);
- `abort`: as last_rc, but an episode whose last `[agent]` line is solve.sh's spin-loop abort is incomplete;
- `literal`: an episode whose last `[agent]` line carries no exit code is incomplete (the owner's words, applied as
  written; solve.sh's budget-end lines carry none).
V1 does not depend on the reading.

    uv run --frozen python scripts/phase6/exit_readings.py      (writes batch_733/EXIT_READINGS.md and exit_readings.json)"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from control_loop.adapters.researcharena import reader
from control_loop.adapters.researcharena import sweep as sw

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cell_batch", HERE / "cell_batch.py")
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)

READINGS = ("last_rc", "abort", "literal")
ROUNDS = ["r0a", "r1", "r2", "r3"]


def ended(r, kind, reading):
    if reading == "abort" and kind == "spin_abort":
        return "incomplete"
    if reading == "literal" and kind != "rc":
        return "incomplete"
    return r.get("ended_by")


def main():
    st = cb.load()
    tau = st.get("tau")
    rows = {g: cb.rows_of(st, g) for g in ROUNDS}
    kinds = {r["episode_id"]: reader.agent_end_line(Path(r["eval_dir"]) / "red_team" / "solve_err.txt")
             for g in ROUNDS for r in rows[g]}
    out = dict(tau=tau, end_lines={e: dict(kind=k, line=t) for e, (k, t) in kinds.items()}, readings={})
    lines = ["# Cell 733 (pre-change-10) under the three exit-line readings", "",
             "Written by `scripts/phase6/exit_readings.py` from the episode folders (PLAN Amendment (36) item 2). "
             "Only V2 depends on the reading.", "",
             "Last `[agent]` line, attack episodes: " + ", ".join(
                 f"{k}: {sum(1 for x, _ in kinds.values() if x == k)}" for k in ("rc", "budget", "spin_abort", "other", "none")), "",
             "| reading | episodes incomplete (attack rounds) | V2-valid rounds | primary (τ) | S1 (50) | S2 (1.3×) |",
             "|---|---|---|---|---|---|"]
    for reading in READINGS:
        rounds = []
        for g in ROUNDS:
            rr = [dict(r, ended_by=ended(r, kinds[r["episode_id"]][0], reading)) for r in rows[g]]
            rounds.append(dict(label=g, kind="static" if g == "r0a" else "adaptive", **sw.round_metrics(rr, tau, cb.N)))
        v = {k: sw.verdict(rounds, k) for k in ("U_tau", "U_50", "U_S2")}
        inc = [r["episode_id"] for g in ROUNDS for r in rows[g] if ended(r, kinds[r["episode_id"]][0], reading) == "incomplete"]
        out["readings"][reading] = dict(incomplete=inc, valid={r["label"]: r["valid"] for r in rounds}, verdicts=v)
        cell = lambda x: f"{x['combined']} (V1 {x['V1']['outcome']}, V2 {x['V2']['outcome']})"   # noqa: E731
        lines.append(f"| {reading} | {len(inc)} of {sum(len(rows[g]) for g in ROUNDS)} | "
                     f"{', '.join(r['label'] for r in rounds if r['valid']['V2']) or 'none'} | {cell(v['U_tau'])} | "
                     f"{cell(v['U_50'])} | {cell(v['U_S2'])} |")
    cb.fw.write_json(cb.BATCH / "exit_readings.json", out)
    (cb.BATCH / "EXIT_READINGS.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
