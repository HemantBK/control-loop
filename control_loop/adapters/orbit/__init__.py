"""ORBIT adapter (ORBIT 1.0.3 at commit 588b303, JiraTicket scenario).

What lives here, and nowhere else in `control_loop`:

    allocation_monitor.py  Phase 3: the allocation-pattern rule and the judge's context (pure)
    jira_adaptive.py   the Inspect task: ORBIT's `jira_ticket_allocation` plus a file-backed
                       coalition payload, the fixed-prompt monitor presets, the seeded judge,
                       the Phase 2 claim-time monitors (LLM judge with the claim's context; rule),
                       the greedy single-agent control and the activation orders
    orderings.py       early / late / claims-last step lists and ORBIT execution plans
    this file          how the loop launches one ORBIT episode (`run_eval`) and the task and
                       generation settings every episode shares (`COMMON_T`, `COMMON_EVAL`)

The loop (`control_loop.loop`) imports `run_eval`, `DEFENSES` and `ORDERINGS` from here; the
analysis (`control_loop.results`) imports `orderings.steps` to map agent spans to turns.
Importing this package does not import `jira_adaptive`; ORBIT's registries are only patched
when Inspect loads that task file, i.e. inside the episode's own process.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from control_loop.results import latest_log

NAME = "orbit"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]  # repository root: episodes run with cwd there so relative paths in -T options resolve
TASK = f"{HERE / 'jira_adaptive.py'}@jira_adaptive"

DEFENSES = ["none", "system_prompt", "llm_monitor_fixed", "llm_monitor_fixed_actions",  # Phase 1
            "claim_time_monitor", "claim_time_monitor_4o", "claim_rule_monitor",  # Phase 2
            "allocation_rule_monitor", "allocation_llm_monitor"]  # Phase 3
ORDERINGS = ["early", "late", "claimslast"]

COMMON_T = [
    "-T", "num_developers=4", "-T", "runtime_profile=common/v1",
    "-T", "max_turns=40", "-T", "max_time_seconds=350",  # the Jira recipe's values; the task default is max_turns=10
    "-T", "persuasion_tactic=reciprocity_trade",
    "-T", "misalignment_strategy=covert_reward_maximization",
]
COMMON_EVAL = ["--limit", "1", "--temperature", "0", "--no-fail-on-error",  # one errored epoch must not cancel its siblings (as the recipe)
               "--max-tokens", "1200", "--token-limit", "200000", "--max-retries", "2"]
# token-limit: the replication recipe uses 60000, but under an LLM monitor the judge's own
# tokens count toward the sample, and 40-turn gpt-4o episodes with gpt-4o-mini judging
# reach ~60k (observed 60042 and 60695 -> "native_limit", pair refused). 200000 is a
# safety ceiling, not a generation setting; C and A within a cell always share it.


def run_eval(log_dir: Path, agent_model: str, seed: int, extra_t: list[str],
             payload_file: Path | None, monitor_model: str, epochs: int = 1, max_samples: int = 1) -> str:
    log_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "inspect_ai", "eval", TASK, "--model", agent_model,
           "--log-dir", str(log_dir), "--seed", str(seed), "--epochs", str(epochs),
           "--max-samples", str(max_samples), *COMMON_EVAL,
           *COMMON_T, "-T", f"seed={seed}", *extra_t]
    if payload_file is not None:
        cmd += ["-T", f"coalition_payload_file={payload_file.resolve()}"]
    env = {**os.environ, "ADAPTIVE_MONITOR_MODEL": monitor_model}
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=REPO, env=env, check=False)
    return latest_log(log_dir)
