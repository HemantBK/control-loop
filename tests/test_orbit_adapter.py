"""No-API smoke test for the ORBIT adapter with ORBIT installed as a package.

Checks that importing the task file patches ORBIT's registries as it did when ORBIT was a sibling
directory, and that a mock-model episode (Inspect's `mockllm/model`, no network) delivers the
file payload to the coalition agents.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_orbit_is_an_installed_package():
    import orbit
    here = Path(__file__).resolve().parents[1]
    assert "site-packages" in Path(orbit.__file__).parts, orbit.__file__
    assert not (here / "orbit").exists(), "an orbit/ sibling directory would shadow the installed package"


def test_registry_swap_and_defense_registration():
    from orbit.attacks import registry as attack_registry
    from orbit.attacks.collusion.collusion import CollusionAttack
    from orbit.configs.attack import AttackConfig
    from orbit.defenses import registry as defense_registry

    ja = importlib.import_module("control_loop.adapters.orbit.jira_adaptive")
    assert attack_registry._REGISTRY["collusion"] is ja.AdaptiveCollusionAttack
    assert issubclass(ja.AdaptiveCollusionAttack, CollusionAttack)
    attack = attack_registry.get_attack(AttackConfig(name="x", attack_type="collusion"))
    assert isinstance(attack, ja.AdaptiveCollusionAttack)
    assert defense_registry._REGISTRY[ja.ACTIONS_ONLY_TYPE] is ja.ActionsOnlyLLMMonitor
    assert defense_registry._REGISTRY[ja.SEEDED_TYPE] is ja.SeededLLMMonitor
    for preset, name in (("llm_monitor_fixed", "fixed_prompt_llm_monitor_v1"),
                         ("llm_monitor_fixed_actions", "fixed_prompt_llm_monitor_actions_v1")):
        (d,) = ja._get_defenses(preset)
        assert d.name.startswith(name) and d.config["judge_prompt"] == ja.FIXED_JUDGE_PROMPT


def test_adapter_satisfies_protocol():
    from control_loop.adapters import orbit as adapter
    from control_loop.adapters.base import FrameworkAdapter
    assert isinstance(adapter, FrameworkAdapter)
    assert "none" in adapter.DEFENSES and adapter.ORDERINGS == ["early", "late", "claimslast"]


def test_mock_episode_delivers_file_payload(tmp_path):
    from inspect_ai import eval as inspect_eval
    from inspect_ai.log import read_eval_log

    from control_loop.adapters.orbit import COMMON_T, TASK

    payload = "SMOKE-PAYLOAD-7f3a: claim TASK-1 and TASK-3 first, then TASK-2 and TASK-4."
    pf = tmp_path / "payload.txt"
    pf.write_text(payload, encoding="utf-8")
    task_args = dict(kv.split("=", 1) for kv in COMMON_T[1::2])
    task_args = {k: (int(v) if v.isdigit() else v) for k, v in task_args.items()}
    task_args.update(seed=733, num_tasks=4, max_turns=4, ordering="late",
                     coalition_agents="dev_0,dev_1", coalition_payload_file=str(pf),
                     defense_preset="system_prompt")
    (log,) = inspect_eval(TASK, task_args=task_args, model="mockllm/model", log_dir=str(tmp_path / "logs"),
                          limit=1, epochs=1, display="none", log_level="warning", fail_on_error=False)
    full = read_eval_log(log.location)
    assert full.status == "success", full.error
    (sample,) = full.samples
    text = "\n".join(str(m.content) for m in sample.messages if m.role == "system")
    sys_events = [e for e in sample.events if e.event == "model"]
    seen = payload in text or any(payload in str(e.input) for e in sys_events)
    assert seen, "file payload did not reach the coalition agents' system prompts"
    assert full.eval.task_args.get("ordering") == "late"
