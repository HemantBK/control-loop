"""Phase 3 sweep driver (PLAN §6.2, §6.7). One stream per arm, cells in the PLAN's order; for each cell the
second clean run (--baseline-only into run2), then the loop (run1 baseline, round 0 static, 5 Sonnet rounds).
Before each cell the Phase 3 spend so far is recomputed from the logs; the stream stops if it would pass $24.

    uv run --env-file ../.env python phases/phase3_allocation_monitor/sweep.py --arm rule
    uv run --env-file ../.env python phases/phase3_allocation_monitor/sweep.py --arm llm
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from inspect_ai.log import read_eval_log

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "results" / "phase3_allocation_monitor"
PRESET = {"rule": "allocation_rule_autoallow", "llm": "allocation_llm_autoallow"}
CELLS = [(733, "early"), (733, "late"), (512, "early"), (512, "late")]
PRICE = {"gpt-4o": (2.5, 10.0), "gpt-4o-mini": (0.15, 0.6)}  # $ per 1M input / output tokens, list
PROPOSER_PER_CELL = 0.15  # estimate: proposer usage is not logged
GUARD = 24.0
PER_CELL_ESTIMATE = 22 * 0.10 + PROPOSER_PER_CELL


def spend() -> float:
    total = 0.0
    for p in ROOT.rglob("*.eval"):
        try:
            usage = read_eval_log(str(p), header_only=True).stats.model_usage or {}
        except Exception:
            continue
        for model, u in usage.items():
            pin, pout = PRICE["gpt-4o-mini"] if "mini" in model else PRICE["gpt-4o"]
            total += u.input_tokens * pin / 1e6 + u.output_tokens * pout / 1e6
    total += PROPOSER_PER_CELL * sum(1 for _ in ROOT.glob("*/prop_sonnet55/*/rounds.jsonl"))
    return total


def run(cmd: list[str], log: Path) -> int:
    print("$", " ".join(cmd), f"> {log}", flush=True)
    with log.open("a", encoding="utf-8") as f:
        return subprocess.run(cmd, cwd=REPO, stdout=f, stderr=subprocess.STDOUT).returncode


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=sorted(PRESET), required=True)
    a = ap.parse_args()
    preset = PRESET[a.arm]
    common = ["--defense", preset, "--agent-model", "openai/gpt-4o", "--attacker-model", "anthropic/claude-sonnet-5-5",
              "--monitor-model", "openai/gpt-4o-mini", "--num-tasks", "4", "--clean-epochs", "8"]
    for seed, ordering in CELLS:
        s = spend()
        print(f"[{a.arm}] spend so far ${s:.2f}", flush=True)
        if s + PER_CELL_ESTIMATE > GUARD:
            print(f"[{a.arm}] budget guard: ${s:.2f} + ~${PER_CELL_ESTIMATE:.2f} would pass ${GUARD}; stopping before {seed}/{ordering}")
            return
        base = ROOT / ordering / "baselines" / f"{seed}_{preset}"
        cell = ROOT / ordering / "prop_sonnet55" / f"{seed}_{preset}"
        if (cell / "rounds.jsonl").exists():
            print(f"[{a.arm}] {cell} exists; skipping")
            continue
        cell.parent.mkdir(parents=True, exist_ok=True)
        args = [sys.executable, "-m", "control_loop.loop", "--seed", str(seed), "--ordering", ordering, *common]
        # run2 and the cell (which first runs run1) in parallel: independent processes, independent logs
        p2 = subprocess.Popen(args + ["--baseline-only", "--clean-log-dir", str(base / "run2"), "--out", str(base / "_run2_meta")],
                              cwd=REPO, stdout=open(ROOT / f"{ordering}_{seed}_{preset}_run2.out", "a"), stderr=subprocess.STDOUT)
        rc = run(args + ["--rounds", "5", "--clean-log-dir", str(base / "run1"), "--out", str(cell)],
                 ROOT / f"{ordering}_{seed}_{preset}.out")
        rc2 = p2.wait()
        print(f"[{a.arm}] {seed}/{ordering} done: loop rc={rc}, run2 rc={rc2}", flush=True)
    print(f"[{a.arm}] finished; spend ${spend():.2f}")


if __name__ == "__main__":
    main()
