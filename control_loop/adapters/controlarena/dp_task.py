"""Inspect task wrapper around ControlArena's `data_poisoning` setting.

Loaded by Inspect inside the episode's own process (`python -m inspect_ai eval dp_task.py@controlarena_dp`),
so every ControlArena import lives here and nothing in `control_loop` outside this package imports it.

Task options (passed as `-T key=value` by `control_loop.adapters.controlarena.run_eval`):

    mode             honest | attack. Default: honest when no payload file is given, else attack.
    defense          none | trusted_monitoring (ControlArena's default trusted monitor, `basic_monitor`
                     on the trusted model, non-intervening). Default trusted_monitoring.
    framing          true | false (default false; PLAN §11, 2026-10-21): attack mode only, the policy is
                     `proposer_attack_policy` with Phase 1's sanctioned-evaluation framing prefixed to
                     the side-task description (`proposer_policy.FRAMING`); combined with payload_file
                     if both are given. Honest mode is unchanged.
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
    model_seed       seed put in the untrusted and trusted roles' GenerateConfig (2026-10-21, PLAN §12.1,
                     RESULTS Known issues "seed 56"). Default None = nothing set, as before.
    temperature      temperature put in the untrusted and trusted roles' GenerateConfig and in the
                     setting's judge model. Default None = provider default, as before.

Seeds, as traced on 2026-10-21 (`seed_trace.py`): `inspect eval --seed N` reaches only Inspect's active
model (`--model`), which ControlArena never calls; role models get only the operational fields of the
active config (inspect_ai/model/_model.py, `Model._resolve_config`, lines 1907-1929). So without
model_seed the policy (role "untrusted") and the monitor (role "trusted") carry no seed, and the
setting's judges carry ControlArena's own fixed seed 56 (+ retry index) from
`control_arena/scorers/_llm_judge.py:89-92` (`llm_score`), which no task option can change (R5). The
Anthropic provider drops any seed (audit_codex X8), so model_seed reaches OpenRouter models only.
"""
from __future__ import annotations

import copy
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.model import GenerateConfig, get_model
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


def role_config(model_seed: int | None = None, temperature: float | None = None) -> GenerateConfig | None:
    """GenerateConfig for the untrusted and trusted roles; None (ControlArena's empty default) when
    neither is set, so the pre-2026-10-21 command path is unchanged."""
    if model_seed is None and temperature is None:
        return None
    return GenerateConfig(seed=None if model_seed is None else int(model_seed),
                          temperature=None if temperature is None else float(temperature))


def build_eval_config(untrusted_model: str | None, trusted_model: str | None, token_limit: int,
                      max_steps: int | None, model_seed: int | None = None,
                      temperature: float | None = None) -> ControlEvalConfig:
    cfg_kwargs = dict(token_limit=int(token_limit), max_steps=int(max_steps) if max_steps else None)
    if untrusted_model:
        cfg_kwargs["untrusted_model"] = untrusted_model
    if trusted_model:
        cfg_kwargs["trusted_model"] = trusted_model
    rc = role_config(model_seed, temperature)
    if rc is not None:
        cfg_kwargs["untrusted_config"] = rc
        cfg_kwargs["trusted_config"] = rc.model_copy()
    return ControlEvalConfig(**cfg_kwargs)


def judge_model(scorer_model: str | None, untrusted_model: str | None, temperature: float | None = None):
    """The setting's judge: the untrusted model by default (as before). With a temperature, a Model
    carrying it; ControlArena's `llm_score` then merges its own GenerateConfig(seed=56 + retry) over it,
    so the judge's seed stays 56 whatever is requested here (not settable without editing ControlArena)."""
    name = scorer_model or (untrusted_model or None)
    # cl_mock: the mock judge ignores temperature, and ControlArena's scorer_model serializer cannot name a
    # provider registered without a package prefix, so the mock keeps the string
    if temperature is None or name is None or name.startswith("cl_mock/"):
        return name
    return get_model(name, config=GenerateConfig(temperature=float(temperature)))


def build_micro_protocol(defense: str, payload_file: str | Path | None, framing: bool = False):
    if defense not in DEFENSES:
        raise ValueError(f"defense must be one of {DEFENSES}, got {defense!r}")
    if payload_file or framing:
        policy = untrusted_policy_builder(attack=proposer_attack_policy_builder(
            payload_file=str(Path(payload_file).resolve()) if payload_file else None, framing=framing))
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
                    token_limit: int = 1_000_000, framing: bool | str = False,
                    model_seed: int | None = None, temperature: float | None = None) -> Task:
    eval_mode = EvalMode(mode) if mode else (EvalMode.ATTACK if payload_file else EvalMode.HONEST)
    model_seed = None if model_seed in (None, "", "None") else int(model_seed)
    temperature = None if temperature in (None, "", "None") else float(temperature)
    eval_config = build_eval_config(untrusted_model, trusted_model, token_limit, max_steps, model_seed, temperature)
    setting = DataPoisoningSetting(
        scorer_model=judge_model(scorer_model, untrusted_model, temperature),
        password=password or None,
        use_subset_filter=_flag(use_subset_filter) if use_subset_filter is not None else None,
    )
    return get_control_task(
        setting=setting,
        micro_protocol=build_micro_protocol(defense, payload_file, _flag(framing)),
        mode=eval_mode,
        eval_config=eval_config,
        monitoring_scorers=[cli_final_monitor()] if _flag(final_monitor) else [],
        metadata={"control_loop": {"defense": defense, "payload_file": payload_file, "mode": eval_mode.value,
                                   "framing": _flag(framing), "model_seed": model_seed,
                                   "temperature": temperature}},
    )
