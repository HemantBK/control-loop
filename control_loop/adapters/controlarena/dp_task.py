"""Inspect task wrapper around ControlArena's `data_poisoning` setting.

Loaded by Inspect inside the episode's own process (`python -m inspect_ai eval dp_task.py@controlarena_dp`),
so every ControlArena import lives here and nothing in `control_loop` outside this package imports it.

Task options (passed as `-T key=value` by `control_loop.adapters.controlarena.run_eval`):

    mode             honest | attack. Default: honest when no payload file is given, else attack.
    defense          none | trusted_monitoring (ControlArena's default trusted monitor, `basic_monitor`
                     on the trusted model, non-intervening). Default trusted_monitoring.
    payload_file     path to the round's payload paragraph; when given the policy is
                     `proposer_attack_policy` (ControlArena's attack prompt + the paragraph).
                     When absent, ControlArena's own `untrusted_policy` (its stock attack prompt in
                     attack mode, plain honest policy in honest mode) is the policy.
    untrusted_model  model string for the "untrusted" role (policy, judge). Default: ControlArena's.
    trusted_model    model string for the "trusted" role (monitor). Default: ControlArena's.
    scorer_model     judge model for the setting's scorer. Default: the untrusted model.
    final_monitor    true | false: also run the CLI's end-of-trajectory full-trajectory monitor as a
                     scorer (what `control-arena eval single` does). Default true.
    password         restrict attack samples to one password (ControlArena setting option).
    use_subset_filter  true: the setting's 100-combination validated subset.
    max_steps        ControlArena step limit (None = no limit; the setting is single-turn).
    token_limit      Inspect token limit per sample. Default 1_000_000 (ControlArena's).
"""
from __future__ import annotations

import copy
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.scorer import Score, Target, scorer
from inspect_ai.solver import TaskState

from control_arena import EvalMode
from control_arena.eval import ControlEvalConfig, get_control_task
from control_arena.micro_protocol import trusted_monitoring_builder
from control_arena.monitor import (
    MonitorScoreRange,
    basic_monitor_builder,
    full_trajectory_prompt_formatter_markdown,
)
from control_arena.monitor.prompts import monitor_prompts
from control_arena.policy import untrusted_policy_builder
from control_arena.scorers import end_of_trajectory_monitor
from control_arena.scorers._metrics import accuracy, stderr
from control_arena.settings.data_poisoning.data_poisoning_setting import DataPoisoningSetting

from control_loop.adapters.controlarena import mock_dp  # noqa: F401  registers the cl_mock provider
from control_loop.adapters.controlarena.proposer_policy import proposer_attack_policy_builder

DEFENSES = ["none", "trusted_monitoring"]


def _flag(v) -> bool:
    return v if isinstance(v, bool) else str(v).strip().lower() in {"1", "true", "yes"}


@scorer(metrics=[accuracy(), stderr()], name="end_of_trajectory_monitor")
def cli_final_monitor():
    """The scorer `control-arena eval single` adds by default (control_arena/cli/single_eval.py),
    run on a deep copy of the messages.

    ControlArena 20.1.0's `end_of_trajectory_monitor` hands the monitor the trajectory's own message
    objects, and the `@monitor` decorator writes its response into the last assistant message's
    metadata, so the CLI's log shows the end-of-trajectory score and reason in place of the last
    step's per-step `suspicion_score` (found in the Phase 4 mechanism check, PLAN §10.5). The copy
    leaves the per-step metadata as the trusted monitor wrote it; the end-of-trajectory score is
    unchanged."""
    inner = end_of_trajectory_monitor(
        basic_monitor_builder(
            system_prompt=monitor_prompts["full_trajectory_default_system"],
            prompt=monitor_prompts["full_trajectory_default_user"],
            prompt_formatter=full_trajectory_prompt_formatter_markdown,
            score_range=MonitorScoreRange(min=0.0, max=100.0),
        )
    )

    async def score(state: TaskState, target: Target) -> Score:
        original = state.messages
        state.messages = copy.deepcopy(original)
        try:
            return await inner(state, target)
        finally:
            state.messages = original

    return score


def build_micro_protocol(defense: str, payload_file: str | Path | None):
    if defense not in DEFENSES:
        raise ValueError(f"defense must be one of {DEFENSES}, got {defense!r}")
    if payload_file:
        policy = untrusted_policy_builder(attack=proposer_attack_policy_builder(payload_file=str(Path(payload_file).resolve())))
    else:
        policy = untrusted_policy_builder()
    if defense == "none":
        return policy
    return trusted_monitoring_builder(policy=policy, monitor=basic_monitor_builder())


@task
def controlarena_dp(mode: str | None = None, defense: str = "trusted_monitoring",
                    payload_file: str | None = None, untrusted_model: str | None = None,
                    trusted_model: str | None = None, scorer_model: str | None = None,
                    final_monitor: bool | str = True, password: str | None = None,
                    use_subset_filter: bool | str | None = None, max_steps: int | None = None,
                    token_limit: int = 1_000_000) -> Task:
    eval_mode = EvalMode(mode) if mode else (EvalMode.ATTACK if payload_file else EvalMode.HONEST)
    cfg_kwargs = dict(token_limit=int(token_limit), max_steps=int(max_steps) if max_steps else None)
    if untrusted_model:
        cfg_kwargs["untrusted_model"] = untrusted_model
    if trusted_model:
        cfg_kwargs["trusted_model"] = trusted_model
    eval_config = ControlEvalConfig(**cfg_kwargs)
    setting = DataPoisoningSetting(
        scorer_model=scorer_model or (untrusted_model or None),
        password=password or None,
        use_subset_filter=_flag(use_subset_filter) if use_subset_filter is not None else None,
    )
    return get_control_task(
        setting=setting,
        micro_protocol=build_micro_protocol(defense, payload_file),
        mode=eval_mode,
        eval_config=eval_config,
        monitoring_scorers=[cli_final_monitor()] if _flag(final_monitor) else [],
        metadata={"control_loop": {"defense": defense, "payload_file": payload_file, "mode": eval_mode.value}},
    )
