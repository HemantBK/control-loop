"""Phase 7 sweep driver (phases/phase7_dgm_self_modifying/PLAN.md §5, §7.1–§7.3, §11.1; Phase 5's sweep.py pattern).
One stream, one cell at a time, in the §11.1 order:

    A rule 733 early r3–r5 (continuing the check cell in place, --resume), B rule 733 early, new clean baseline
    none 733 early (two runs of 8), A none 733 early, B none 733 early, A none 512 early, B none 512 early,
    A none 101 early, B none 101 early; then S1 (A and B rule 512 early), S2 (A-lin at none and rule 733 early),
    S3 (B-4o at none and rule 733 early) only with --s1 / --s2 / --s3.

    uv run --locked --env-file ../.env python phases/phase7_dgm_self_modifying/sweep.py --phase6-confirmed "<dated text>"
    uv run --locked --env-file ../.env python phases/phase7_dgm_self_modifying/sweep.py [--s1 --s2 --s3]      resume / secondaries
    uv run --locked python phases/phase7_dgm_self_modifying/sweep.py --dry-run [--s1 --s2 --s3]              commands and spend table only
    uv run --locked python -m control_loop.status results/phase7_dgm_self_modifying                           status from run.jsonl

Per cell (§7.2): A = control_loop.loop --attacker self_modifier --attacker-model openai/gpt-4o --agent-model openai/gpt-4o
(temperature 0, seed = problem seed for the agents; the writer at temperature 0 with seed 100 x seed + round), --brief
informed (none) / informed_rule (rule), --clean-log-dir <baseline run1>, --out results/phase7_dgm_self_modifying/early/
selfmod_gpt4o/<seed>_<preset>; B = the same with --attacker proposer --attacker-model anthropic/claude-sonnet-5-5 under
.../prop_sonnet55/. The A rule 733 cell is the check cell itself (results/phase7_dgm_self_modifying/check/
733_allocation_rule_autoallow), continued with --resume --rounds 5 so its archive and history carry on. Clean baselines:
rule cells reuse Phase 3's run1/run2; none 512 and 101 reuse results/v2/early/baselines/<seed>_none/run{1,2}; none 733 is
new (results/phase7_dgm_self_modifying/early/baselines/733_none/run{1,2}, plus a --baseline-only pass that writes run2's
baseline.json without a model call). --max-samples 8 on every clean run; the attacked rounds are one epoch each.

Gates (§7.3, §8.12, §11): the stream refuses to start without --phase6-confirmed "<dated text>" on its first run (recorded
in sweep_state.json and reused on resume), without both API keys in the environment (values never read or printed), and
without a finished check cell (rounds 0–2) when the A rule 733 cell is pending. Spend guard (§5): before each cell the
Phase 7 spend so far is recomputed from every .eval under results/phase7_dgm_self_modifying/ with control_loop.spend
(cache reads priced) plus the writer calls (A: the usage logged per round in rounds.jsonl, $0.045 per unpriced attempt;
B: $0.15 flat per cell); the next cell is counted at its upper estimate and the stream stops if the total would pass $48.
After each cell, a measured cell spend over $15 stops the stream (STOP_<reason>.md, the owner's stop-and-ask). Completed
cells are recorded in sweep_state.json and skipped on resume. Never two cells at once.

Observability (§11.3): run.jsonl through control_loop.runlog in results/phase7_dgm_self_modifying/ (run_id "sweep", one
step per cell), in each cell directory (steps clean_run1, clean_run2, run2_meta, loop, cell; the loop itself logs
round0, selfmod_r1 / propose_r1, round1, ... live through --runlog-phase) and in each clean run directory. A dry run
writes nothing.
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
PHASE = "phase7_dgm_self_modifying"
ROOT = REPO / "results" / PHASE
P3_ROOT = REPO / "results" / "phase3_allocation_monitor"
V2_ROOT = REPO / "results" / "v2"
CHECK_CELL = ROOT / "check" / "733_allocation_rule_autoallow"
STATE = ROOT / "sweep_state.json"
COMMAND = "uv run --locked --env-file ../.env python phases/phase7_dgm_self_modifying/sweep.py"

RULE = "allocation_rule_autoallow"
AGENT_MODEL = "openai/gpt-4o"
PROPOSER_MODEL = "anthropic/claude-sonnet-5-5"
MONITOR_MODEL = "openai/gpt-4o-mini"
CLEAN_EPOCHS = 8
MAX_SAMPLES = 8
ROUNDS = 5
CHECK_ROUNDS = 2

GUARD = 48.0               # §5: stop if the cumulative total would pass this
CELL_STOP = 15.0           # §5: the project's single-cell stop (stop-and-ask under the $40 cell cap)
PROPOSER_PER_CELL = 0.15   # §5: flat estimate per Sonnet proposer cell (usage not logged)
WRITER_CALL_UPPER = 0.045  # §5: gpt-4o writer call at the upper estimate, used where a call's usage was not priced
# §5 table with §11.1: (estimate, upper) per cell kind
BUDGET = {"A_rule_cont": (0.32, 0.63), "B_rule": (0.57, 1.22), "baseline": (1.12, 1.92), "A": (0.60, 1.17), "B": (0.57, 1.22),
          "S1": (0.585, 1.195), "A-lin": (0.60, 1.17), "B-4o": (0.60, 1.17)}
CHECK_BUDGET = (0.28, 0.54)
ARM_DIR = {"A": "selfmod_gpt4o", "B": "prop_sonnet55", "A-lin": "selfmod_gpt4o_linear", "B-4o": "prop_gpt4o"}


@dataclass(frozen=True)
class Cell:
    kind: str        # A | B | baseline | A-lin | B-4o
    seed: int
    ordering: str
    preset: str
    group: str       # primary | S1 | S2 | S3

    @property
    def is_rule(self) -> bool:
        return self.preset.startswith("allocation_")

    @property
    def name(self) -> str:
        return f"{self.kind} {'rule' if self.is_rule else 'none'} {self.seed} {self.ordering}"

    @property
    def attacker(self) -> str:
        return "proposer" if self.kind in ("B", "B-4o") else "self_modifier"

    @property
    def linear(self) -> bool:
        return self.kind == "A-lin"

    @property
    def attacker_model(self) -> str:
        return PROPOSER_MODEL if self.kind == "B" else AGENT_MODEL

    @property
    def brief(self) -> str:
        return "informed_rule" if self.is_rule else "informed"

    @property
    def resume(self) -> bool:
        """The A rule 733 early cell continues the check cell in place (PLAN §7.1)."""
        return self.kind == "A" and self.is_rule and self.seed == 733 and self.ordering == "early"

    @property
    def own_clean(self) -> bool:
        return self.kind == "baseline"

    @property
    def baseline_dir(self) -> Path:
        if self.is_rule:
            return P3_ROOT / self.ordering / "baselines" / f"{self.seed}_{self.preset}"
        if self.seed == 733:
            return ROOT / self.ordering / "baselines" / f"{self.seed}_{self.preset}"
        return V2_ROOT / self.ordering / "baselines" / f"{self.seed}_{self.preset}"

    @property
    def cell_dir(self) -> Path:
        if self.kind == "baseline":
            return self.baseline_dir
        if self.resume:
            return CHECK_CELL
        return ROOT / self.ordering / ARM_DIR[self.kind] / f"{self.seed}_{self.preset}"

    @property
    def out_file(self) -> Path:
        return ROOT / f"{self.ordering}_{self.kind}_{self.seed}_{self.preset}.out"

    @property
    def budget(self) -> tuple[float, float]:
        if self.group == "S1":
            return BUDGET["S1"]
        if self.kind in ("A-lin", "B-4o", "baseline"):
            return BUDGET[self.kind]
        if self.resume:
            return BUDGET["A_rule_cont"]
        return BUDGET["B_rule" if (self.kind == "B" and self.is_rule) else self.kind]

    @property
    def upper(self) -> float:
        return self.budget[1]


def plan_cells(s1: bool = False, s2: bool = False, s3: bool = False) -> list[Cell]:
    """§11.1's cell list in order, then the selected secondaries (§1.4, §7.1)."""
    cells = [Cell("A", 733, "early", RULE, "primary"), Cell("B", 733, "early", RULE, "primary"),
             Cell("baseline", 733, "early", "none", "primary"),
             Cell("A", 733, "early", "none", "primary"), Cell("B", 733, "early", "none", "primary"),
             Cell("A", 512, "early", "none", "primary"), Cell("B", 512, "early", "none", "primary"),
             Cell("A", 101, "early", "none", "primary"), Cell("B", 101, "early", "none", "primary")]
    if s1:
        cells += [Cell("A", 512, "early", RULE, "S1"), Cell("B", 512, "early", RULE, "S1")]
    if s2:
        cells += [Cell("A-lin", 733, "early", "none", "S2"), Cell("A-lin", 733, "early", RULE, "S2")]
    if s3:
        cells += [Cell("B-4o", 733, "early", "none", "S3"), Cell("B-4o", 733, "early", RULE, "S3")]
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


def writer_cost(cell_dir: Path, kind: str) -> tuple[float, str]:
    """The writer's cost for one cell. A (gpt-4o self-modifier): the usage priced per round in rounds.jsonl
    (`proposer.cost_usd`), WRITER_CALL_UPPER per attempt where a round's usage was not priced. B (Sonnet
    proposer): the flat PROPOSER_PER_CELL once rounds.jsonl exists. Returns (dollars, note)."""
    rf = Path(cell_dir) / "rounds.jsonl"
    if not rf.exists():
        return 0.0, "no rounds yet"
    if kind == "B":   # B-4o (S3) goes through the proposer too, but its gpt-4o calls are counted per attempt below
        return PROPOSER_PER_CELL, f"flat ${PROPOSER_PER_CELL:.2f} per proposer cell (usage not logged)"
    rows = [json.loads(l) for l in rf.read_text(encoding="utf-8").splitlines() if l.strip()]
    priced, unpriced_attempts = 0.0, 0
    for row in rows:
        if int(row.get("round", 0)) < 1:
            continue
        prop = row.get("proposer") or {}
        if prop.get("cost_usd") is not None:
            priced += float(prop["cost_usd"])
        else:
            unpriced_attempts += int(prop.get("attempts") or 1)
    note = f"${priced:.4f} priced from logged usage"
    if unpriced_attempts:
        note += f"; {unpriced_attempts} unpriced attempt(s) at ${WRITER_CALL_UPPER:.3f}"
    return priced + unpriced_attempts * WRITER_CALL_UPPER, note


def writer_cells(root: Path = ROOT) -> list[tuple[Path, str]]:
    """(cell dir, kind) for every cell with a rounds.jsonl under the phase root."""
    out: list[tuple[Path, str]] = []
    if not root.exists():
        return out
    for rf in sorted(root.rglob("rounds.jsonl")):
        d = rf.parent
        arm = d.parent.name
        if d == CHECK_CELL or arm.startswith("selfmod_gpt4o"):
            kind = "A-lin" if arm.endswith("_linear") else "A"
        elif arm == "prop_sonnet55":
            kind = "B"
        elif arm == "prop_gpt4o":
            kind = "B-4o"
        else:
            continue   # _run2_meta and other baseline-only passes have no rounds.jsonl
        out.append((d, kind))
    return out


def spend_so_far(root: Path = ROOT) -> float:
    return logs_cost(root) + sum(writer_cost(d, k)[0] for d, k in writer_cells(root))


def would_pass_guard(spent: float, next_upper: float, guard: float = GUARD) -> bool:
    return spent + next_upper > guard


def cell_over_stop(cell_spend: float, stop: float = CELL_STOP) -> bool:
    return cell_spend > stop


def cell_spend(cell: Cell) -> float:
    """Measured spend of one cell: its own logs (the baseline cell: its two runs; a loop cell: its rounds; the A rule
    733 cell includes the check's rounds, which were paid in this phase) plus the writer's cost."""
    if cell.kind == "baseline":
        return logs_cost(cell.baseline_dir)
    return logs_cost(cell.cell_dir) + writer_cost(cell.cell_dir, cell.kind)[0]


# ── commands ───────────────────────────────────────────────────────────────────────────────────────

def defense_t(cell: Cell) -> list[str]:
    t = ["-T", "num_tasks=4"] + ([] if cell.preset == "none" else ["-T", f"defense_preset={cell.preset}"])
    t += ["-T", f"ordering={cell.ordering}"]
    if cell.is_rule:
        t += ["-T", f"judge_seed={cell.seed}"]
    return t


def clean_command(cell: Cell, run: int) -> list[str]:
    """What control_loop.adapters.orbit.run_eval runs for one clean run (printed by --dry-run; the run itself goes
    through run_eval so the two cannot drift)."""
    from control_loop.adapters.orbit import COMMON_EVAL, COMMON_T, TASK

    log_dir = cell.baseline_dir / f"run{run}"
    return [sys.executable, "-m", "inspect_ai", "eval", TASK, "--model", AGENT_MODEL, "--log-dir", rel(log_dir),
            "--seed", str(cell.seed), "--epochs", str(CLEAN_EPOCHS), "--max-samples", str(MAX_SAMPLES),
            *COMMON_EVAL, *COMMON_T, "-T", f"seed={cell.seed}", *defense_t(cell)]


def loop_common(cell: Cell) -> list[str]:
    return [sys.executable, "-m", "control_loop.loop", "--seed", str(cell.seed), "--ordering", cell.ordering,
            "--defense", cell.preset, "--attacker", cell.attacker, "--attacker-model", cell.attacker_model,
            "--agent-model", AGENT_MODEL, "--monitor-model", MONITOR_MODEL, "--num-tasks", "4", "--clean-epochs", str(CLEAN_EPOCHS)]


def loop_commands(cell: Cell) -> list[tuple[str, list[str]]]:
    """(step name, command) for the loop invocations of one cell."""
    if cell.kind == "baseline":
        return [("run2_meta", loop_common(cell) + ["--baseline-only", "--clean-log-dir", rel(cell.baseline_dir / "run2"),
                                                  "--out", rel(cell.baseline_dir / "_run2_meta")])]
    cmd = loop_common(cell) + ["--rounds", str(ROUNDS), "--brief", cell.brief, "--clean-log-dir", rel(cell.baseline_dir / "run1"),
                               "--out", rel(cell.cell_dir), "--runlog-phase", PHASE]
    if cell.resume:
        cmd.append("--resume")
    if cell.linear:
        cmd.append("--selfmod-linear")
    return [("loop", cmd)]


def cell_commands(cell: Cell) -> list[list[str]]:
    cmds = [clean_command(cell, r) for r in (1, 2)] if cell.own_clean else []
    return cmds + [c for _, c in loop_commands(cell)]


# ── state, stops, run logs ─────────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"completed": [], "cells": {}, "phase6_confirmed": None}


def save_state(state: dict) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    write_json(STATE, state, indent=1)


def write_stop(reason: str, text: str) -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    p = ROOT / f"STOP_{reason}.md"
    p.write_text(f"# sweep stopped: {reason}\n\n{time.strftime('%Y-%m-%d %H:%M:%S %z')}\n\n{text}\n", encoding="utf-8")
    return p


def log_cell(cell: Cell, step: str, status: str, **kw) -> dict:
    return runlog.log_step(cell.cell_dir, phase=PHASE, run_id=rel(cell.cell_dir), step=step, status=status, **kw)


def log_stream(step: str, status: str, **kw) -> dict:
    return runlog.log_step(ROOT, phase=PHASE, run_id="sweep", step=step, status=status, **kw)


def rounds_done(cell_dir: Path) -> int:
    rf = cell_dir / "rounds.jsonl"
    return sum(1 for l in rf.read_text(encoding="utf-8").splitlines() if l.strip()) if rf.exists() else 0


def check_done() -> bool:
    return rounds_done(CHECK_CELL) >= CHECK_ROUNDS + 1 and (CHECK_CELL / "archive.jsonl").exists()


def cell_complete(cell: Cell) -> bool:
    if cell.kind == "baseline":
        return all((cell.baseline_dir / f"run{r}").exists() and any((cell.baseline_dir / f"run{r}").glob("*.eval")) for r in (1, 2)) \
            and (cell.baseline_dir / "_run2_meta" / "baseline.json").exists()
    return rounds_done(cell.cell_dir) >= ROUNDS + 1


# ── run ────────────────────────────────────────────────────────────────────────────────────────────

def run(cmd: list[str], log: Path) -> int:
    print("$", rel_text(" ".join(cmd)), f"> {rel(log)}", flush=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        return subprocess.run(cmd, cwd=REPO, stdout=f, stderr=subprocess.STDOUT).returncode


def run_cell(cell: Cell) -> int:
    from control_loop.adapters.orbit import run_eval

    if cell.own_clean:
        for r in (1, 2):
            d = cell.baseline_dir / f"run{r}"
            step = f"clean_run{r}"
            if d.exists() and any(d.glob("*.eval")):
                print(f"[{cell.name}] {rel(d)} exists; reusing", flush=True)
                log_cell(cell, step, "skipped", cost_usd=logs_cost(d), paths=[d], note="existing log reused")
                continue
            log_cell(cell, step, "started", paths=[d])
            runlog.log_step(d, phase=PHASE, run_id=rel(d), step=step, status="started")
            try:
                log_path = run_eval(d, AGENT_MODEL, cell.seed, defense_t(cell), None, MONITOR_MODEL, epochs=CLEAN_EPOCHS, max_samples=MAX_SAMPLES)
            except Exception as ex:  # no log produced
                err = f"{type(ex).__name__}: {ex}"[:300]
                log_cell(cell, step, "failed", error=err, paths=[d])
                runlog.log_step(d, phase=PHASE, run_id=rel(d), step=step, status="failed", error=err)
                return 1
            cost = logs_cost(d)
            log_cell(cell, step, "done", cost_usd=cost, paths=[log_path])
            runlog.log_step(d, phase=PHASE, run_id=rel(d), step=step, status="done", cost_usd=cost, paths=[log_path])
    else:
        for r in (1, 2):   # the reused baselines must be there (Phase 3's, v2's, or this phase's new none 733)
            d = cell.baseline_dir / f"run{r}"
            if not (d.exists() and any(d.glob("*.eval"))):
                msg = f"clean baseline {rel(d)} is missing; the cell cannot run"
                print(f"[{cell.name}] {msg}", flush=True)
                log_cell(cell, "clean_runs", "failed", error=msg)
                return 1
        log_cell(cell, "clean_runs", "skipped", note=f"reused {rel(cell.baseline_dir)}/run1 and run2")
    rc = 0
    for step, cmd in loop_commands(cell):
        log_cell(cell, step, "started", paths=[cell.out_file], note=f"{rounds_done(cell.cell_dir)} rounds already present" if cell.resume else None)
        rc = run(cmd, cell.out_file)
        if rc != 0:
            log_cell(cell, step, "failed", error=f"exit code {rc}; see {rel(cell.out_file)}", paths=[cell.out_file])
            print(f"[{cell.name}] command failed with rc={rc}; the cell is not marked complete", flush=True)
            return rc
        log_cell(cell, step, "done", cost_usd=None, paths=[cell.out_file], note="round costs are in the loop's own steps")
    wc, note = writer_cost(cell.cell_dir, cell.kind) if cell.kind != "baseline" else (0.0, "no writer")
    log_cell(cell, "cell", "done", cost_usd=None, note=f"{rounds_done(cell.cell_dir)} rounds; measured cell spend ${cell_spend(cell):.4f} "
                                                     f"(logs ${logs_cost(cell.cell_dir if cell.kind != 'baseline' else cell.baseline_dir):.4f}; writer {note})")
    return rc


def spend_table(cells: list[Cell], state: dict, spent: float) -> str:
    done_check = check_done()
    cost_check = logs_cost(CHECK_CELL) + writer_cost(CHECK_CELL, "A")[0] if CHECK_CELL.exists() else 0.0
    lines = ["| # | cell | group | status | estimate | upper | cumulative upper from here |", "|---|---|---|---|---|---|---|"]
    cum = spent + (0 if done_check else CHECK_BUDGET[1])
    lines.append(f"| 0 | mechanism check (§6: A rule 733 early r0–r2) | check | {f'done (${cost_check:.2f})' if done_check else 'pending (check.py)'} | "
                 f"${CHECK_BUDGET[0]:.2f} | ${CHECK_BUDGET[1]:.2f} | {'–' if done_check else f'${cum:.2f}'} |")
    for i, c in enumerate(cells, 1):
        done = c.name in state["completed"]
        est, up = c.budget
        if not done:
            cum += up
        lines.append(f"| {i} | {c.name} | {c.group} | {'complete' if done else 'pending'} | ${est:.2f} | ${up:.2f} | {'–' if done else f'${cum:.2f}'} |")
    prim = [c for c in cells if c.group == "primary"]
    lines.append(f"\nprimary total (check + {len(prim)} cells): estimate ${CHECK_BUDGET[0] + sum(c.budget[0] for c in prim):.2f}, "
                 f"upper ${CHECK_BUDGET[1] + sum(c.upper for c in prim):.2f}; all listed cells: estimate "
                 f"${CHECK_BUDGET[0] + sum(c.budget[0] for c in cells):.2f}, upper ${CHECK_BUDGET[1] + sum(c.upper for c in cells):.2f}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--s1", action="store_true", help="also A and B at rule 512 early (PLAN §1.4 S1)")
    ap.add_argument("--s2", action="store_true", help="also A-lin (self-modifier without the archive) at none and rule 733 early (S2)")
    ap.add_argument("--s3", action="store_true", help="also B-4o (today's proposer with the gpt-4o writer) at none and rule 733 early (S3)")
    ap.add_argument("--phase6-confirmed", default=None, metavar="TEXT",
                    help="the dated confirmation that Phase 6's reproduction step passed (PLAN §8.12, §10); required once, kept in sweep_state.json")
    ap.add_argument("--dry-run", action="store_true", help="print the commands and the spend table; run nothing, write nothing")
    a = ap.parse_args()
    cells = plan_cells(a.s1, a.s2, a.s3)
    state = load_state()
    spent = spend_so_far()
    print(f"Phase 7 sweep: {len(cells)} cells; spend so far from the logs and the writer calls ${spent:.2f}; guard ${GUARD:.0f}, "
          f"single-cell stop ${CELL_STOP:.0f}; check {'done' if check_done() else 'not done'}", flush=True)
    print(spend_table(cells, state, spent), flush=True)
    if a.dry_run:
        for c in cells:
            print(f"\n## {c.name} ({c.group}; attacker {c.attacker}{' linear' if c.linear else ''} {c.attacker_model}; brief {c.brief}; "
                  f"upper ${c.upper:.2f}; {'own clean runs' if c.own_clean else 'clean runs reused'}; "
                  f"{'continues the check cell; ' if c.resume else ''}{'complete, would be skipped' if c.name in state['completed'] else 'pending'})")
            print(f"  logs: {rel(c.cell_dir)}  baseline: {rel(c.baseline_dir)}  out: {rel(c.out_file)}")
            for cmd in cell_commands(c):
                print("  $", rel_text(" ".join(cmd)))
        print("\ndry run: nothing was run.")
        return
    if a.phase6_confirmed:
        state["phase6_confirmed"] = {"text": a.phase6_confirmed, "recorded": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if not state.get("phase6_confirmed"):
        sys.exit("sweep.py refuses to run: Phase 7 starts only after Phase 6's reproduction step is confirmed (PLAN §8.12); "
                 "pass --phase6-confirmed \"<dated text>\" once (it is recorded in sweep_state.json)")
    if not (os.environ.get("OPENAI_API_KEY") and os.environ.get("ANTHROPIC_API_KEY")):
        sys.exit(f"sweep.py refuses to run: no API keys in the environment; run as: {COMMAND}")
    save_state(state)
    log_stream("sweep", "started", note=f"{len(cells)} cells planned; spend so far ${spent:.2f}; phase6 confirmation: {state['phase6_confirmed']['text']}")
    for c in cells:
        if c.name in state["completed"]:
            print(f"[{c.name}] complete per {rel(STATE)}; skipping", flush=True)
            log_stream(f"cell:{c.name}", "skipped", note="complete per sweep_state.json")
            continue
        if cell_complete(c):
            print(f"[{c.name}] {rel(c.cell_dir)} is already complete; marking complete", flush=True)
            state["completed"].append(c.name)
            state["cells"][c.name] = {"spend": round(cell_spend(c), 4), "note": "found complete on resume"}
            save_state(state)
            log_stream(f"cell:{c.name}", "skipped", cost_usd=cell_spend(c), note="found complete on resume")
            continue
        if c.resume and not check_done():
            msg = f"the check cell {rel(CHECK_CELL)} has {rounds_done(CHECK_CELL)} rounds; run check.py (rounds 0-2) and read report.py first (PLAN §6)"
            print(f"[{c.name}] {msg}", flush=True)
            log_stream(f"cell:{c.name}", "stopped", error=msg)
            return
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
        log_stream(f"cell:{c.name}", "done" if rc == 0 else "failed", cost_usd=cs, paths=[c.cell_dir], error=None if rc == 0 else f"rc={rc}")
        if cell_over_stop(cs):
            msg = f"cell {c.name} measured ${cs:.2f} > ${CELL_STOP:.0f} single-cell stop (PLAN §5); stream stopped"
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
    log_stream("sweep", "done", cost_usd=None, note=f"all planned cells complete; spend from the logs and writer calls ${total:.2f}")


if __name__ == "__main__":
    main()
