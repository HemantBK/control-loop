"""ControlArena adapter (control-arena 20.1.0, `data_poisoning` setting, trusted_monitoring).

What lives here, and nowhere else in `control_loop`:

    dp_task.py          the Inspect task: ControlArena's data_poisoning setting under
                        trusted_monitoring (basic_monitor on the trusted model) or no monitor, with
                        the CLI's end-of-trajectory monitor as a scorer
    proposer_policy.py  the red team: `proposer_attack_policy` (ControlArena's attack policy plus the
                        round's strategy paragraph) and `RedTeamPolicy` (Phase 1's proposer protocol
                        with a ControlArena brief, history from the red team's own trajectories)
    reader.py           .eval log reader: safety, usefulness, per-step monitor scores, halt reason
    mock_dp.py          `cl_mock/dp`, a deterministic no-API model for every role
    mechanism_check.py  the Phase 4 step-3 check (honest + red-team, mock then real, --limit 1)

`run_eval` satisfies `control_loop.adapters.base.FrameworkAdapter`. The loop's `agent_model` is the
untrusted model (policy and the setting's judges), `monitor_model` the trusted model (per-step and
end-of-trajectory monitors). A payload file means attack mode with the red-team policy; no file
means honest mode unless `extra_t` says `mode=attack` (then ControlArena's stock attack policy).
The setting has no turn order, so ORDERINGS is empty. Every ControlArena import is in dp_task.py,
proposer_policy.py, reader.py and mock_dp.py; importing this package imports none of them.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

NAME = "controlarena"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
TASK = f"{HERE / 'dp_task.py'}@controlarena_dp"

DEFENSES = ["none", "trusted_monitoring"]
ORDERINGS: list[str] = []

COMMON_EVAL = ["--no-fail-on-error", "--max-retries", "2", "--log-level", "warning"]


def run_eval(log_dir: Path, agent_model: str, seed: int, extra_t: list[str],
             payload_file: Path | None, monitor_model: str, epochs: int = 1, max_samples: int = 1,
             limit: int = 1, defense: str = "trusted_monitoring") -> str:
    from control_loop.paths import rel, rel_text
    from control_loop.results import latest_log

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    # The task's model roles carry the real models; --model is Inspect's required default model and
    # is unused by ControlArena. For the mock provider (registered when dp_task.py is imported, i.e.
    # after Inspect resolves --model) Inspect's own mockllm stands in.
    cli_model = "mockllm/model" if agent_model.startswith("cl_mock/") else agent_model
    cmd = [sys.executable, "-m", "inspect_ai", "eval", TASK, "--model", cli_model,
           "--log-dir", rel(log_dir), "--seed", str(seed), "--epochs", str(epochs),
           "--max-samples", str(max_samples), "--limit", str(limit), *COMMON_EVAL,
           "-T", f"untrusted_model={agent_model}", "-T", f"trusted_model={monitor_model}",
           "-T", f"defense={defense}", *extra_t]
    if payload_file is not None:
        # repo-relative where possible (the episode runs with cwd=REPO; dp_task resolves it), so
        # Inspect's task-args echo in a .out log carries no absolute path
        cmd += ["-T", f"payload_file={rel(Path(payload_file).resolve())}", "-T", "mode=attack"]
    print("$", rel_text(" ".join(cmd)), flush=True)
    subprocess.run(cmd, cwd=REPO, env=dict(os.environ), check=False)
    return latest_log(log_dir)


def sent_settings(log_path: str | Path) -> dict:
    """Per model, the seed and temperature the provider requests in an .eval log actually carried
    (each ModelEvent's call.request, via `control_loop.proposer.request_summary`), with the number of
    recorded calls. Added 2026-10-21 (audit_codex X8): `inspect eval --seed` is a request; Inspect
    0.3.263's Anthropic provider never sends seed and drops temperature for Claude 4.7+, so reports
    state what was sent instead of the requested seed alone. Reads the local log only."""
    from inspect_ai.event import ModelEvent
    from inspect_ai.log import read_eval_log

    from control_loop.proposer import request_summary

    out: dict[str, dict] = {}
    for sample in read_eval_log(str(log_path)).samples or []:
        for e in sample.events:
            if not isinstance(e, ModelEvent) or e.call is None or not e.call.request:
                continue
            sent = request_summary(e.call.request)
            row = out.setdefault(e.model, dict(calls=0, seed=set(), temperature=set()))
            row["calls"] += 1
            row["seed"].add(str(sent["seed"]))
            row["temperature"].add(str(sent["temperature"]))
    return {m: dict(calls=r["calls"], seed=sorted(r["seed"]), temperature=sorted(r["temperature"]))
            for m, r in out.items()}
