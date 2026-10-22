"""Phase 5 sweep driver (phases/phase5_claim_protocol/PLAN.md §5, §7.1, §7.2 and the amendment of 2026-10-21).
One stream, one cell at a time, in the PLAN's order: P 733 early, C 733 early, P 512 early, C 512 early,
P 101 early, C 101 early (amendment (1): the third primary seed); the secondaries S1 (P and C late at 733 and
512), S2 (`claim_protocol_fcfs` 733 early) and S3 (`claim_protocol_ref_judged` 733 early) only with their flags,
after the primaries.

    uv run --locked --env-file ../.env python phases/phase5_claim_protocol/sweep.py              primary cells
    uv run --locked --env-file ../.env python phases/phase5_claim_protocol/sweep.py --s1 --s2    plus secondaries
    uv run --locked python phases/phase5_claim_protocol/sweep.py --dry-run [--s1 --s2 --s3]     commands and spend table only
    uv run --locked python -m control_loop.status results/phase5_claim_protocol                  status from run.jsonl

Per cell (§7.2):
  P   two independent clean runs of 8 epochs (Inspect --max-samples 8, run through the adapter's run_eval)
      under results/phase5_claim_protocol/<ordering>/baselines/<seed>_<preset>/run{1,2}; then the loop:
      round 0 = ORBIT's static payload, rounds 1-5 by anthropic/claude-sonnet-5-5 with --brief
      informed_protocol, paired with run1, under results/phase5_claim_protocol/<ordering>/prop_sonnet55/<seed>_<preset>.
      (run2's baseline.json is written by a --baseline-only pass that reads the existing log; no model call.)
  C   rounds 0-5 only, preset allocation_rule_autoallow with --brief informed_rule, --clean-log-dir pointing at
      Phase 3's run1 baseline (results/phase3_allocation_monitor/<ordering>/baselines/<seed>_allocation_rule_autoallow/run1;
      run2 is read by sweep_table.py), under .../prop_sonnet55/<seed>_allocation_rule_autoallow_brief. At seed 101
      Phase 3 ran no rule baseline, so C 101 first runs its own two clean runs under
      results/phase5_claim_protocol/early/baselines/101_allocation_rule_autoallow/run{1,2} (amendment (1)).
  Agents gpt-4o at temperature 0 with seed = problem seed, max_turns 40, token_limit 200000, --no-fail-on-error
  (adapter COMMON_T / COMMON_EVAL), --max-samples 8 on the clean runs (the attacked rounds are one epoch).

Spend guard (§5): before each cell the Phase 5 spend so far is recomputed from every .eval under
results/phase5_claim_protocol/ with control_loop.spend (cache reads priced) plus $0.15 per proposer cell so
far; the next cell is counted at its upper estimate (§5 table and amendment: P $5.65, C $1.05, C with its own
clean runs $4.25, S2 $5.65, S3 $5.90); the stream stops if the total would pass $48. After each cell, if that
cell's measured spend (its logs plus $0.15) exceeds the project's $15 single-cell stop, the stream stops and
writes STOP_<reason>.md under results/phase5_claim_protocol/ (the owner's stop-and-ask). Never two cells at
once. Completed cells are recorded in results/phase5_claim_protocol/sweep_state.json and skipped on resume.
The run refuses to start without --env-file (API keys in the environment; their values are never read or printed).

Observability (amendment (3)): every run directory this driver creates gets a run.jsonl through
control_loop.runlog.log_step (phase "phase5_claim_protocol"): the stream's own at results/phase5_claim_protocol/
(run_id "sweep", one step per cell), each cell's at its cell dir (steps clean_run1, clean_run2, run2_meta, loop,
then round0..5 and propose_r1..5 read back from rounds.jsonl with the measured cost of each round's log), and
each clean run's at its run dir. A dry run writes nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from control_loop import runlog
from control_loop.paths import rel, rel_text, write_json

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "results" / "phase5_claim_protocol"
P3_ROOT = REPO / "results" / "phase3_allocation_monitor"
STATE = ROOT / "sweep_state.json"
COMMAND = "uv run --locked --env-file ../.env python phases/phase5_claim_protocol/sweep.py"
PHASE = "phase5_claim_protocol"

P_PRESET = "claim_protocol_ref"
C_PRESET = "allocation_rule_autoallow"
AGENT_MODEL = "openai/gpt-4o"
ATTACKER_MODEL = "anthropic/claude-sonnet-5-5"
MONITOR_MODEL = "openai/gpt-4o-mini"
CLEAN_EPOCHS = 8
MAX_SAMPLES = 8
ROUNDS = 5
# (ordering, seed) pairs where Phase 3 ran the rule-alone clean baseline (reused by C; PLAN §1.4, §7.2)
P3_RULE_BASELINES = {("early", 733), ("early", 512), ("late", 733), ("late", 512)}

GUARD = 48.0              # §5: stop if the cumulative total would pass this
CELL_STOP = 15.0          # §5, §10: the project's single-cell stop (stop-and-ask under the $40 cell cap)
PROPOSER_PER_CELL = 0.15  # §5: flat upper estimate per proposer cell (usage not logged)
# §5 table and the 2026-10-21 amendment: (estimate, upper) per cell kind
BUDGET = {"P": (3.45, 5.65), "C": (0.75, 1.05), "C_own": (3.15, 4.25), "S2": (3.45, 5.65), "S3": (3.60, 5.90)}
CHECK_BUDGET = (0.30, 0.50)   # the mechanism check (§6), part of the "primary total"


@dataclass(frozen=True)
class Cell:
    kind: str        # "P" (protocol + rule) or "C" (matched rule-alone comparator)
    seed: int
    ordering: str
    preset: str
    group: str       # primary | S1 | S2 | S3

    @property
    def name(self) -> str:
        return f"{self.kind} {self.seed} {self.ordering} {self.preset}"

    @property
    def brief(self) -> str:
        return "informed_protocol" if self.kind == "P" else "informed_rule"

    @property
    def own_clean(self) -> bool:
        """P always runs its own two clean runs; C only where Phase 3 left no rule baseline (seed 101)."""
        return self.kind == "P" or (self.ordering, self.seed) not in P3_RULE_BASELINES

    @property
    def cell_dir(self) -> Path:
        tail = f"{self.seed}_{self.preset}" + ("_brief" if self.kind == "C" else "")
        return ROOT / self.ordering / "prop_sonnet55" / tail

    @property
    def baseline_dir(self) -> Path:
        if self.own_clean:
            return ROOT / self.ordering / "baselines" / f"{self.seed}_{self.preset}"
        return P3_ROOT / self.ordering / "baselines" / f"{self.seed}_{C_PRESET}"

    @property
    def out_file(self) -> Path:
        return ROOT / f"{self.ordering}_{self.seed}_{self.preset}{'_brief' if self.kind == 'C' else ''}.out"

    @property
    def budget(self) -> tuple[float, float]:
        if self.group in ("S2", "S3"):
            return BUDGET[self.group]
        return BUDGET["C_own" if (self.kind == "C" and self.own_clean) else self.kind]

    @property
    def upper(self) -> float:
        return self.budget[1]


def plan_cells(s1: bool = False, s2: bool = False, s3: bool = False) -> list[Cell]:
    """§7.1 plus amendment (1): primaries in order, then the selected secondaries."""
    cells = [Cell("P", 733, "early", P_PRESET, "primary"), Cell("C", 733, "early", C_PRESET, "primary"),
             Cell("P", 512, "early", P_PRESET, "primary"), Cell("C", 512, "early", C_PRESET, "primary"),
             Cell("P", 101, "early", P_PRESET, "primary"), Cell("C", 101, "early", C_PRESET, "primary")]
    if s1:
        cells += [Cell("P", 733, "late", P_PRESET, "S1"), Cell("C", 733, "late", C_PRESET, "S1"),
                  Cell("P", 512, "late", P_PRESET, "S1"), Cell("C", 512, "late", C_PRESET, "S1")]
    if s2:
        cells.append(Cell("P", 733, "early", "claim_protocol_fcfs", "S2"))
    if s3:
        cells.append(Cell("P", 733, "early", "claim_protocol_ref_judged", "S3"))
    return cells


# ── spend ──────────────────────────────────────────────────────────────────────────────────────────

def logs_cost(*roots: Path) -> float:
    """Dollars for every .eval under the given directories (control_loop.spend; cache reads priced)."""
    from inspect_ai.log import read_eval_log

    from control_loop.spend import log_cost

    total = 0.0
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.eval")):
            total += log_cost(read_eval_log(str(p), header_only=True))  # raises on an unknown model
    return total


def proposer_cells(root: Path = ROOT) -> int:
    return sum(1 for _ in root.glob("*/prop_sonnet55/*/rounds.jsonl")) if root.exists() else 0


def spend_so_far(root: Path = ROOT) -> float:
    return logs_cost(root) + PROPOSER_PER_CELL * proposer_cells(root)


def would_pass_guard(spent: float, next_upper: float, guard: float = GUARD) -> bool:
    """§5: the next cell counted at its upper estimate must not take the total past the guard."""
    return spent + next_upper > guard


def cell_over_stop(cell_spend: float, stop: float = CELL_STOP) -> bool:
    return cell_spend > stop


def cell_spend(cell: Cell) -> float:
    """Measured spend of one cell: its logs (its own clean runs when it runs them, and the loop; a C cell on
    Phase 3's baselines counts the loop only, Phase 3 paid the rest) plus the flat proposer estimate once
    rounds.jsonl exists."""
    roots = [cell.cell_dir] + ([cell.baseline_dir] if cell.own_clean else [])
    return logs_cost(*roots) + (PROPOSER_PER_CELL if (cell.cell_dir / "rounds.jsonl").exists() else 0.0)


# ── commands ───────────────────────────────────────────────────────────────────────────────────────

def defense_t(cell: Cell) -> list[str]:
    """The -T options control_loop.loop builds for this cell (judge_seed reaches claim_* and allocation_* presets)."""
    return ["-T", "num_tasks=4", "-T", f"defense_preset={cell.preset}", "-T", f"ordering={cell.ordering}",
            "-T", f"judge_seed={cell.seed}"]


def clean_command(cell: Cell, run: int) -> list[str]:
    """What control_loop.adapters.orbit.run_eval runs for one clean run (printed by --dry-run; the run
    itself goes through run_eval so the two cannot drift)."""
    from control_loop.adapters.orbit import COMMON_EVAL, COMMON_T, TASK

    log_dir = cell.baseline_dir / f"run{run}"
    return [sys.executable, "-m", "inspect_ai", "eval", TASK, "--model", AGENT_MODEL, "--log-dir", rel(log_dir),
            "--seed", str(cell.seed), "--epochs", str(CLEAN_EPOCHS), "--max-samples", str(MAX_SAMPLES),
            *COMMON_EVAL, *COMMON_T, "-T", f"seed={cell.seed}", *defense_t(cell)]


def loop_common(cell: Cell) -> list[str]:
    return [sys.executable, "-m", "control_loop.loop", "--seed", str(cell.seed), "--ordering", cell.ordering,
            "--defense", cell.preset, "--agent-model", AGENT_MODEL, "--attacker-model", ATTACKER_MODEL,
            "--monitor-model", MONITOR_MODEL, "--num-tasks", "4", "--clean-epochs", str(CLEAN_EPOCHS)]


def loop_commands(cell: Cell) -> list[tuple[str, list[str]]]:
    """(step name, command) for the loop invocations of one cell, after its clean runs exist."""
    cmds = []
    if cell.own_clean:
        cmds.append(("run2_meta", loop_common(cell) + ["--baseline-only", "--clean-log-dir", rel(cell.baseline_dir / "run2"),
                                                       "--out", rel(cell.baseline_dir / "_run2_meta")]))
    cmds.append(("loop", loop_common(cell) + ["--rounds", str(ROUNDS), "--brief", cell.brief,
                                              "--clean-log-dir", rel(cell.baseline_dir / "run1"), "--out", rel(cell.cell_dir)]))
    return cmds


def cell_commands(cell: Cell) -> list[list[str]]:
    cmds = [clean_command(cell, r) for r in (1, 2)] if cell.own_clean else []
    return cmds + [c for _, c in loop_commands(cell)]


# ── state and run logs ─────────────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"completed": [], "cells": {}}


def save_state(state: dict) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    write_json(STATE, state, indent=1)


def write_stop(reason: str, text: str) -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    p = ROOT / f"STOP_{reason}.md"
    p.write_text(f"# sweep stopped: {reason}\n\n{time.strftime('%Y-%m-%d %H:%M:%S %z')}\n\n{text}\n", encoding="utf-8")
    return p


def log_cell(cell: Cell, step: str, status: str, **kw) -> dict:
    return runlog.log_step(cell.cell_dir, phase=PHASE, run_id=cell.name, step=step, status=status, **kw)


def log_stream(step: str, status: str, **kw) -> dict:
    return runlog.log_step(ROOT, phase=PHASE, run_id="sweep", step=step, status=status, **kw)


def record_rounds(cell: Cell) -> int:
    """After the loop: one run.jsonl step per round (cost = that round's logs) and per proposer call, read back
    from rounds.jsonl. Returns the number of rounds found."""
    rf = cell.cell_dir / "rounds.jsonl"
    if not rf.exists():
        return 0
    rows = [json.loads(l) for l in rf.read_text(encoding="utf-8").splitlines() if l.strip()]
    for row in rows:
        r = int(row["round"])
        if r >= 1:
            prop = row.get("proposer") or {}
            log_cell(cell, f"propose_r{r}", "done", cost_usd=None, paths=[cell.cell_dir / f"payload_r{r}.txt"],
                     note=f"usage not logged; ${PROPOSER_PER_CELL:.2f} flat per cell in the guard; moves={prop.get('moves')} "
                          f"attempts={prop.get('attempts')} fallback={prop.get('fallback')}")
        log_dir = cell.cell_dir / f"A{r}"
        log_cell(cell, f"round{r}", "done" if row.get("status") == "success" else "failed", cost_usd=logs_cost(log_dir),
                 error=None if row.get("status") == "success" else f"log status {row.get('status')}",
                 paths=[row.get("log", "")], note=f"valid={row.get('valid')} halt={row.get('halt_reason')} "
                                                   f"coalition={row.get('coalition_reward')} lost={row.get('coalition_claims_lost')}")
    return len(rows)


# ── run ────────────────────────────────────────────────────────────────────────────────────────────

def run(cmd: list[str], log: Path) -> int:
    print("$", rel_text(" ".join(cmd)), f"> {rel(log)}", flush=True)  # no absolute path in a redirected .out
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        return subprocess.run(cmd, cwd=REPO, stdout=f, stderr=subprocess.STDOUT).returncode


def run_cell(cell: Cell) -> int:
    from control_loop.adapters.orbit import run_eval

    rc = 0
    if cell.own_clean:
        for r in (1, 2):
            d = cell.baseline_dir / f"run{r}"
            step = f"clean_run{r}"
            if d.exists() and any(d.glob("*.eval")):
                print(f"[{cell.name}] {rel(d)} exists; reusing", flush=True)
                log_cell(cell, step, "skipped", cost_usd=logs_cost(d), paths=[d], note="existing log reused")
                continue
            log_cell(cell, step, "started", paths=[d])
            runlog.log_step(d, phase=PHASE, run_id=f"{cell.name}/run{r}", step=step, status="started")
            try:
                log_path = run_eval(d, AGENT_MODEL, cell.seed, defense_t(cell), None, MONITOR_MODEL,
                                    epochs=CLEAN_EPOCHS, max_samples=MAX_SAMPLES)
            except Exception as ex:  # no log produced
                log_cell(cell, step, "failed", error=f"{type(ex).__name__}: {ex}"[:300], paths=[d])
                runlog.log_step(d, phase=PHASE, run_id=f"{cell.name}/run{r}", step=step, status="failed", error=str(ex)[:300])
                return 1
            cost = logs_cost(d)
            log_cell(cell, step, "done", cost_usd=cost, paths=[log_path])
            runlog.log_step(d, phase=PHASE, run_id=f"{cell.name}/run{r}", step=step, status="done", cost_usd=cost, paths=[log_path])
    for step, cmd in loop_commands(cell):
        log_cell(cell, step, "started", paths=[cell.out_file])
        rc = run(cmd, cell.out_file)
        if rc != 0:
            log_cell(cell, step, "failed", error=f"exit code {rc}; see {rel(cell.out_file)}", paths=[cell.out_file])
            print(f"[{cell.name}] command failed with rc={rc}; the cell is not marked complete", flush=True)
            if step == "loop":
                record_rounds(cell)
            return rc
        log_cell(cell, step, "done", cost_usd=(logs_cost(cell.cell_dir) if step == "loop" else 0.0), paths=[cell.out_file])
    n = record_rounds(cell)
    log_cell(cell, "cell", "done", cost_usd=None, note=f"{n} rounds; measured cell spend ${cell_spend(cell):.4f} incl. "
                                                     f"${PROPOSER_PER_CELL:.2f} proposer estimate")
    return rc


def check_cost() -> tuple[bool, float]:
    d = ROOT / "check"
    return (d.exists() and any(d.rglob("*.eval")), logs_cost(d))


def spend_table(cells: list[Cell], state: dict, spent: float) -> str:
    done_check, cost_check = check_cost()
    lines = ["| # | cell | group | status | estimate | upper | cumulative upper from here |", "|---|---|---|---|---|---|---|"]
    cum = spent
    if not done_check:
        cum += CHECK_BUDGET[1]
    lines.append(f"| 0 | mechanism check (§6) | check | {f'done (${cost_check:.2f})' if done_check else 'pending'} | "
                 f"${CHECK_BUDGET[0]:.2f} | ${CHECK_BUDGET[1]:.2f} | {'–' if done_check else f'${cum:.2f}'} |")
    for i, c in enumerate(cells, 1):
        done = c.name in state["completed"]
        est, up = c.budget
        if not done:
            cum += up
        lines.append(f"| {i} | {c.name} | {c.group} | {'complete' if done else 'pending'} | ${est:.2f} | ${up:.2f} | "
                     f"{'–' if done else f'${cum:.2f}'} |")
    prim = [c for c in cells if c.group == "primary"]
    lines.append(f"\nprimary total (check + {len(prim)} cells): estimate ${CHECK_BUDGET[0] + sum(c.budget[0] for c in prim):.2f}, "
                 f"upper ${CHECK_BUDGET[1] + sum(c.upper for c in prim):.2f}; all listed cells: estimate "
                 f"${CHECK_BUDGET[0] + sum(c.budget[0] for c in cells):.2f}, upper ${CHECK_BUDGET[1] + sum(c.upper for c in cells):.2f}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--s1", action="store_true", help="also P and C late at 733 and 512 (PLAN §7.1 S1)")
    ap.add_argument("--s2", action="store_true", help="also claim_protocol_fcfs 733 early (S2)")
    ap.add_argument("--s3", action="store_true", help="also claim_protocol_ref_judged 733 early (S3)")
    ap.add_argument("--dry-run", action="store_true", help="print the commands and the spend table; run nothing, write nothing")
    a = ap.parse_args()
    cells = plan_cells(a.s1, a.s2, a.s3)
    state = load_state()
    spent = spend_so_far()
    print(f"Phase 5 sweep: {len(cells)} cells; spend so far from the logs ${spent:.2f} "
          f"(+${PROPOSER_PER_CELL:.2f} x {proposer_cells()} proposer cells included); guard ${GUARD:.0f}, "
          f"single-cell stop ${CELL_STOP:.0f}", flush=True)
    print(spend_table(cells, state, spent), flush=True)
    if a.dry_run:
        for c in cells:
            print(f"\n## {c.name} ({c.group}; brief {c.brief}; upper ${c.upper:.2f}; "
                  f"{'own clean runs' if c.own_clean else 'Phase 3 clean runs reused'}; "
                  f"{'complete, would be skipped' if c.name in state['completed'] else 'pending'})")
            print(f"  logs: {rel(c.cell_dir)}  baseline: {rel(c.baseline_dir)}  out: {rel(c.out_file)}")
            for cmd in cell_commands(c):
                print("  $", rel_text(" ".join(cmd)))
        print("\ndry run: nothing was run.")
        return
    if not (os.environ.get("OPENAI_API_KEY") and os.environ.get("ANTHROPIC_API_KEY")):
        sys.exit(f"sweep.py refuses to run: no API keys in the environment; run as: {COMMAND}")
    log_stream("sweep", "started", note=f"{len(cells)} cells planned; spend so far ${spent:.2f}")
    for c in cells:
        if c.name in state["completed"]:
            print(f"[{c.name}] complete per {rel(STATE)}; skipping", flush=True)
            log_stream(f"cell:{c.name}", "skipped", note="complete per sweep_state.json")
            continue
        rf = c.cell_dir / "rounds.jsonl"
        if rf.exists() and sum(1 for l in rf.read_text().splitlines() if l.strip()) >= ROUNDS + 1:
            print(f"[{c.name}] {rel(c.cell_dir)} already has {ROUNDS + 1} rounds; marking complete", flush=True)
            state["completed"].append(c.name)
            state["cells"][c.name] = {"spend": round(cell_spend(c), 4), "note": "found complete on resume"}
            save_state(state)
            log_stream(f"cell:{c.name}", "skipped", cost_usd=cell_spend(c), note="found complete on resume")
            continue
        stops = sorted(ROOT.glob("STOP_*.md")) if ROOT.exists() else []
        if stops:
            msg = f"stop file present ({', '.join(rel(s) for s in stops)}); the owner must clear it before more cells run"
            print(msg)
            log_stream(f"cell:{c.name}", "stopped", error=msg)
            return
        spent = spend_so_far()
        print(f"[{c.name}] spend so far ${spent:.2f}; next cell upper ${c.upper:.2f}", flush=True)
        if would_pass_guard(spent, c.upper):
            msg = f"${spent:.2f} + upper ${c.upper:.2f} would pass the ${GUARD:.0f} guard; stopped before {c.name}"
            print(f"[{c.name}] budget guard: {msg}", flush=True)
            write_stop("budget_guard", msg)
            log_stream(f"cell:{c.name}", "stopped", error=msg)
            return
        log_stream(f"cell:{c.name}", "started", note=f"spend so far ${spent:.2f}; upper ${c.upper:.2f}")
        t0 = time.time()
        rc = run_cell(c)
        cs = cell_spend(c)
        state["cells"][c.name] = {"spend": round(cs, 4), "rc": rc, "seconds": round(time.time() - t0),
                                  "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        if rc == 0:
            state["completed"].append(c.name)
        save_state(state)
        print(f"[{c.name}] done: rc={rc}, measured cell spend ${cs:.2f}", flush=True)
        log_stream(f"cell:{c.name}", "done" if rc == 0 else "failed", cost_usd=cs, paths=[c.cell_dir],
                   error=None if rc == 0 else f"rc={rc}")
        if cell_over_stop(cs):
            msg = f"cell {c.name} measured ${cs:.2f} > ${CELL_STOP:.0f} single-cell stop (PLAN §5, §10); stream stopped"
            print(f"[{c.name}] {msg}", flush=True)
            write_stop("cell_over_15", msg)
            log_stream("sweep", "stopped", error=msg)
            return
        if rc != 0:
            print(f"[{c.name}] stopping the stream on the failed command", flush=True)
            log_stream("sweep", "stopped", error=f"{c.name} failed with rc={rc}")
            return
    total = spend_so_far()
    print(f"finished; spend ${total:.2f}")
    log_stream("sweep", "done", cost_usd=None, note=f"all planned cells complete; spend from the logs ${total:.2f}")


if __name__ == "__main__":
    main()
