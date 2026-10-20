"""Agent activation orders (PLAN §13–14). One place for the task wrapper and the analysis.

early       dev_0, dev_1, dev_2, dev_3 repeated: the coalition (dev_0, dev_1) moves first.
late        dev_2, dev_3, dev_0, dev_1 repeated: the coalition is scheduled last, but in clean
            runs the outsiders spend their first activation on view_tasks and claim on their
            second, so a coalition that claims on its first activation still claims before them.
claimslast  dev_2, dev_3, dev_2, dev_3, then the late cycle, as an explicit 40-step plan with no
            repeat: the outsiders get two activations (in clean runs: view_tasks, then their first
            assign_task) before the coalition's first activation, and the schedule then continues
            dev_0, dev_1, dev_2, dev_3. Whether the outsiders actually claimed first in a given
            episode is checked from the logs (results.outsiders_claimed_before_coalition).

A plan step whose agent has already submitted is skipped but still consumes a global
turn (orbit/execution/agent_scheduler.py, _run_plan_step), so under an explicit plan
the turn of an activation is its step index, not the index of its span.
"""
from __future__ import annotations

MAX_TURNS = 40
CYCLES = {
    "early": ("dev_0", "dev_1", "dev_2", "dev_3"),
    "late": ("dev_2", "dev_3", "dev_0", "dev_1"),
}
PREFIX = {"claimslast": ("dev_2", "dev_3", "dev_2", "dev_3")}


def steps(ordering: str, max_turns: int = MAX_TURNS) -> list[str]:
    """The agent activated at each global turn, for max_turns turns."""
    if ordering in CYCLES:
        cyc = CYCLES[ordering]
        return [cyc[i % len(cyc)] for i in range(max_turns)]
    if ordering == "claimslast":
        pre = list(PREFIX["claimslast"])
        cyc = CYCLES["late"]
        return (pre + [cyc[i % len(cyc)] for i in range(max_turns)])[:max_turns]
    raise ValueError(f"unknown ordering {ordering!r}; expected one of {sorted(CYCLES) + list(PREFIX)}")


def execution_plan(ordering: str, max_turns: int = MAX_TURNS) -> dict:
    """ORBIT execution config: the recipe's repeating cycle for early/late, an explicit
    non-repeating step list for claimslast."""
    if ordering in CYCLES:
        return {"executor": "scheduled", "quantum": "model_step",
                "plan": {"repeat": True, "steps": [{"id": f"activate-{a}", "agents": [a], "concurrent": False}
                                                    for a in CYCLES[ordering]]}}
    seq = steps(ordering, max_turns)
    return {"executor": "scheduled", "quantum": "model_step",
            "plan": {"repeat": False, "steps": [{"id": f"t{i:02d}-{a}", "agents": [a], "concurrent": False}
                                                 for i, a in enumerate(seq)]}}
