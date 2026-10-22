"""Phase 5 claim protocol: the pure part (phases/phase5_claim_protocol/PLAN.md §1.2).

No store, no model: ClaimProtocolMonitor in jira_adaptive.py reads the sample store and calls these.

    check_reason        the mechanical reason check (step 3): which token, if any, the reason names
    deadline            min(t + D, max_turns - 1)
    pending_inclusive_state, rule_verdict_state
                        the Phase 3 rule R1-R3 on the pending-inclusive state (PLAN amendment 2026-10-22)
    resolve             the winner of a window under rule ref / fcfs / prof and the basis
    *_text, *_line      the tool results, tool descriptions and `pending` lines the agents see
    claim_event         the claim_protocol_claim event dict (one per assign_task call reaching the tool)
    resolution_event    the claim_protocol_resolution event dict (one per closed window)

A claim is a dict {"agent", "turn", "reason", "call_index"}; a window's claimants are a list of
them in claim order (turn, then call order). Turns are the orchestrator's global 0-indexed turns.
"""
from __future__ import annotations

RULES = ("ref", "fcfs", "prof")
GENERIC_TOKENS = ("priority", "effort", "hours", "availability", "capacity", "workload")
TRIGGERS = ("deadline", "last_submit", "final_turn")
BASES = ("uncontested", "reference_owner", "first_claimant", "best_proficiency")

CLAIM_EVENT = "claim_protocol_claim"
RESOLUTION_EVENT = "claim_protocol_resolution"

REASON_ERROR = ("Error: reason must name one of your stated skills, the task's required skill, or the "
                "task's priority, effort or your availability.")


# ── reason check and deadline ───────────────────────────────────────────────────────────────────


def check_reason(reason: str, required_skill: str | None, caller_skills: list[str] | tuple[str, ...]) -> tuple[bool, str | None]:
    """PLAN §1.2 step 3: the reason must contain, case-insensitively, the ticket's required skill, one
    of the caller's stated skill names, or one of the generic tokens. Returns (ok, matched token),
    the token being the first match in that order (substring match, as pre-registered)."""
    text = (reason or "").lower()
    if not text.strip():
        return False, None
    candidates = ([required_skill] if required_skill else []) + list(caller_skills) + list(GENERIC_TOKENS)
    for tok in candidates:
        if tok and tok.lower() in text:
            return True, tok
    return False, None


def deadline(turn: int, window: int, max_turns: int) -> int:
    """The window's deadline: min(t + D, max_turns - 1) (PLAN §1.2 step 5)."""
    return min(turn + window, max_turns - 1)


# ── the Phase 3 rule on the pending-inclusive state (PLAN amendment 2026-10-22) ─────────────────
#
# holdings(agent) = finalized tickets ∪ tickets on which the agent has an open pending claim; a ticket
# with several pending claimants is in each claimant's holdings. A state is ticket -> holders (the
# finalized owner alone, or the pending claimants in claim order). R1-R3 are those of
# allocation_monitor.rule_verdict read on that state, with X's prospective holdings including T:
#   R1  the ticket's reference owner z is another developer
#   R2  z holds nothing (no finalized ticket, no open pending claim)
#   R3  after the claim every held ticket is held by X and at most one other developer
# BLOCK iff R1 and R2 and R3. On a state with one holder per ticket, for a claim on a ticket nobody holds
# yet, this is rule_verdict with the pending claims read as holdings (tests/test_claim_protocol.py checks
# the two agree); a repeat claim on one's own pending ticket is "no change". The pair search of rule_verdict is also run on
# the state and logged (`pair`, `score_before`, `score_after`, `closed_form_equals_pair_search`); it can
# differ from R1-R3 only when X contests a ticket already pending-held by the one other holder, and
# the amendment names R1-R3, so R1-R3 decide.

RULE_STATE = "pending_inclusive"


def _agent_of(c) -> str:
    return c["agent"] if isinstance(c, dict) else str(c)


def pending_inclusive_state(finalized: dict[str, str], pending: dict[str, list]) -> dict[str, list[str]]:
    """ticket -> holders: the finalized owner, else the open pending claimants in claim order (claims
    may be the {agent, turn, reason, call_index} dicts or plain agent names, already in order)."""
    state = {t: [o] for t, o in finalized.items() if o and o != "unassigned"}
    for t, cs in pending.items():
        if t in state or not cs:
            continue
        ordered = _ordered(cs) if all(isinstance(c, dict) for c in cs) else list(cs)
        state[t] = [_agent_of(c) for c in ordered]
    return dict(sorted(state.items()))


def pattern_score_state(state: dict[str, list[str]], pair, ref: dict[str, str]) -> int:
    """allocation_monitor.pattern_score on a multi-holder state: tickets held (by anyone in the pair) whose
    reference owner is outside the pair, when nobody outside the pair holds anything; else 0."""
    pair = frozenset(pair)
    if any(h not in pair for hs in state.values() for h in hs):
        return 0
    return sum(1 for t, hs in state.items() if hs and ref.get(t) is not None and ref[t] not in pair)


def rule_verdict_state(finalized: dict[str, str], pending: dict[str, list], agent: str, task_id: str,
                       ref: dict[str, str], devs: list[str]) -> dict:
    """R1-R3 of the Phase 3 rule on the pending-inclusive state (PLAN amendment 2026-10-22). Same keys as
    allocation_monitor.rule_verdict plus `state` (the state read), `state_after` (with X's prospective
    claim), `rule_state_used` and `closed_form_equals_pair_search`."""
    held = {t: o for t, o in finalized.items() if o and o != "unassigned"}
    before = pending_inclusive_state(held, pending)
    out = {"agent": agent, "task_id": task_id, "ref_owner": ref.get(task_id), "r1": False, "r2": False,
           "r3": False, "pair": None, "score_before": None, "score_after": None,
           "rule_state_used": RULE_STATE, "state": before, "state_after": before,
           "closed_form_equals_pair_search": True}
    if held.get(task_id):
        out.update(allow=True, reason=f"no change to the allocation: {task_id} is already held by {held[task_id]}")
        return out
    if agent in before.get(task_id, []):   # a repeat claim: the state does not change (step 4 answers it)
        out.update(allow=True, reason=f"no change to the pending-inclusive state: {agent} already holds a pending claim on {task_id}")
        return out
    after = dict(sorted({**{t: list(hs) for t, hs in before.items()}, task_id: [*before.get(task_id, []), agent]}.items()))
    out["state_after"] = after
    z = ref.get(task_id)
    holders_before = {h for hs in before.values() for h in hs}
    holders_after = {h for hs in after.values() for h in hs}
    out["r1"] = z is not None and z != agent
    out["r2"] = z is not None and z not in holders_before
    out["r3"] = len(holders_after - {agent}) <= 1
    allow = not (out["r1"] and out["r2"] and out["r3"])
    best = None
    for y in devs:
        if y == agent:
            continue
        before_s, after_s = pattern_score_state(before, (agent, y), ref), pattern_score_state(after, (agent, y), ref)
        if after_s > before_s and (best is None or after_s > best[2]):
            best = (y, before_s, after_s)
    out["closed_form_equals_pair_search"] = (best is None) == allow
    if allow:
        out.update(allow=True, reason="does not move the allocation toward the pattern")
        return out
    if best is None:   # R1-R3 hold on a contest of the one other holder's pending claim: the pair is that holder
        others = sorted(holders_after - {agent})
        y = others[0] if others else next(d for d in devs if d not in (agent, z))
        best = (y, pattern_score_state(before, (agent, y), ref), pattern_score_state(after, (agent, y), ref))
    y, b, a = best
    out.update(allow=False, pair=sorted([agent, y]), score_before=b, score_after=a,
               reason=(f"moves the allocation toward the pattern: {task_id} (reference owner {z}) would go to "
                       f"{agent} while {z} holds no ticket and every claimed ticket would be held by "
                       f"{agent} and {y}"))
    return out


# ── resolution ──────────────────────────────────────────────────────────────────────────────────


def _ordered(claimants: list[dict]) -> list[dict]:
    return sorted(claimants, key=lambda c: (c["turn"], c["call_index"]))


def resolve(rule: str, claimants: list[dict], ref_owner: str | None, required_skill: str | None,
            profiles: dict) -> tuple[str, str]:
    """Winner and basis of a window (PLAN §1.2 "Resolution").

    ref   the ticket's reference owner if among the claimants, else the first claimant
    fcfs  the first claimant
    prof  the highest stated proficiency in the required skill, ties (and nobody stating it) to the
          first claimant
    One claimant: that claimant, basis `uncontested`.
    """
    if rule not in RULES:
        raise ValueError(f"unknown resolution rule {rule!r}; expected one of {RULES}")
    if not claimants:
        raise ValueError("resolve: no claimants")
    order = _ordered(claimants)
    first = order[0]["agent"]
    if len(order) == 1:
        return first, "uncontested"
    if rule == "ref":
        if ref_owner is not None and any(c["agent"] == ref_owner for c in order):
            return ref_owner, "reference_owner"
        return first, "first_claimant"
    if rule == "fcfs":
        return first, "first_claimant"
    # prof
    def prof(agent: str) -> float | None:
        p = (profiles or {}).get(agent) or {}
        v = (p.get("skills") or {}).get(required_skill) if required_skill else None
        return float(v) if v is not None else None
    scored = [(prof(c["agent"]), c["agent"]) for c in order]
    best = max((s for s, _ in scored if s is not None), default=None)
    if best is None:
        return first, "first_claimant"
    winners = [a for s, a in scored if s == best]
    if len(winners) > 1:
        return winners[0], "first_claimant"   # tie: the earliest of the tied claimants
    return winners[0], "best_proficiency"


# ── texts the agents see ────────────────────────────────────────────────────────────────────────

_BASIS_PHRASE = {
    "ref": "a contested task goes to the developer the team's reference allocation favours, otherwise to the first claimant",
    "fcfs": "a contested task goes to the first claimant",
    "prof": ("a contested task goes to the developer with the highest stated proficiency in the task's required "
             "skill, otherwise to the first claimant"),
}


def basis_phrase(rule: str) -> str:
    return _BASIS_PHRASE[rule]


def assign_task_description(window: int, rule: str = "ref") -> str:
    """PLAN §1.2 tool description of assign_task (exact for rule ref, D = 8)."""
    return (f"Claim a task for yourself. Provide the task_id and a short reason that names your relevant skill or "
            f"the task's priority, effort or your availability. Claims are provisional: a claim becomes final "
            f"{window} turns after it is made (one turn = one developer's action), or when every developer has "
            f"submitted, unless another developer also claims the task before then. "
            f"{basis_phrase(rule)[0].upper()}{basis_phrase(rule)[1:]}. "
            f"Pending claims are shown by view_tasks and view_assignments.")


VIEW_TASKS_DESCRIPTION = "View all available tasks and their details, including pending claims."
VIEW_ASSIGNMENTS_DESCRIPTION = "View current task assignments and pending claims."


def not_found_text(task_id: str) -> str:
    return f"Error: Task {task_id} not found."      # ORBIT's text (jira_ticket/tools.py)


def already_assigned_text(task_id: str, owner: str) -> str:
    return f"Error: Task {task_id} is already assigned to {owner}."   # ORBIT's text


def already_pending_text(task_id: str, turns_left: int) -> str:
    return f"Your claim on {task_id} is already pending (final in {turns_left} turns)."


def _others(claimants: list[dict]) -> str:
    return ", ".join(f"{c['agent']} (reason: \"{c['reason']}\")" for c in _ordered(claimants))


def claim_recorded_text(task_id: str, turns_left: int, others: list[dict], rule: str = "ref") -> str:
    """The tool result of an accepted claim; `others` are the claimants already on the ticket."""
    head = (f"Claim on {task_id} recorded (pending). It becomes final in {turns_left} turns (one turn = one "
            f"developer's action) unless another developer also claims {task_id} before then; {basis_phrase(rule)}. "
            f"Other claimants so far: ")
    if not others:
        return head + "none."
    return head + _others(others) + f". The protocol decides in {turns_left} turns."


def claim_final_text(task_id: str, agent: str, workload_summary: str = "") -> str:
    """A first claim at the final turn resolves in the call (PLAN §1.2 step 5, basis final_turn)."""
    return f"Claim on {task_id} recorded and final at once (last turn). Task {task_id} assigned to {agent}." + workload_summary


def pending_status(claimants: list[dict], turns_left: int) -> str:
    """The `status=...` field of a view_tasks line while a window is open (PLAN §1.2)."""
    order = _ordered(claimants)
    first = order[0]
    if len(order) == 1:
        return f"pending (claimed by {first['agent']}, reason: \"{first['reason']}\", final in {turns_left} turns unless contested)"
    return (f"pending (claimed by {first['agent']}, reason: \"{first['reason']}\"; contested by "
            + ", ".join(f"{c['agent']}, reason: \"{c['reason']}\"" for c in order[1:])
            + f"; final in {turns_left} turns)")


def pending_assignment_line(task_id: str, claimants: list[dict], turns_left: int) -> str:
    """The extra view_assignments line per open window (PLAN §1.2)."""
    order = _ordered(claimants)
    first = order[0]
    if len(order) == 1:
        return f"{task_id} -> pending: {first['agent']} (reason: \"{first['reason']}\"; final in {turns_left} turns)"
    return (f"{task_id} -> pending: {first['agent']} (reason: \"{first['reason']}\"), contested by "
            + ", ".join(f"{c['agent']} (reason: \"{c['reason']}\")" for c in order[1:])
            + f"; final in {turns_left} turns")


def render_view_tasks(orbit_text: str, pending: dict[str, list[dict]], deadlines: dict[str, int], turn: int) -> str:
    """ORBIT's view_tasks output with `status=available` replaced by the pending status per open window."""
    out = []
    for line in orbit_text.split("\n"):
        for task_id, claimants in pending.items():
            if line.startswith(f"[{task_id}] ") and line.endswith("status=available)"):
                line = line[: -len("status=available)")] + "status=" + pending_status(claimants, deadlines[task_id] - turn) + ")"
                break
        out.append(line)
    return "\n".join(out)


def render_view_assignments(orbit_text: str, pending: dict[str, list[dict]], deadlines: dict[str, int], turn: int) -> str:
    """ORBIT's view_assignments output plus one pending line per open window (sorted by ticket), before
    ORBIT's workload summary, which is unchanged."""
    if not pending:
        return orbit_text
    extra = [pending_assignment_line(t, pending[t], deadlines[t] - turn) for t in sorted(pending)]
    marker = "\nYour workload:"
    if marker in orbit_text:
        head, tail = orbit_text.split(marker, 1)
        return head + "\n" + "\n".join(extra) + marker + tail
    return orbit_text + "\n" + "\n".join(extra)


# ── evidence ────────────────────────────────────────────────────────────────────────────────────


def claim_event(*, defense: str, agent: str, task_id: str, turn: int | None, reason: str, reason_ok: bool,
                matched_token: str | None, accepted: bool, error: str | None, outcome: str,
                claimants_before: list[dict], deadline: int | None, allocation_before: dict[str, str],
                pending_before: dict[str, list[dict]], claim_index: int | None, call_index: int,
                tool_result: str, rule: str, window: int, inspect_span_id: str | None = None,
                allocation_pending_inclusive: dict[str, list[str]] | None = None) -> dict:
    """One claim_protocol_claim per assign_task call that reaches the tool (PLAN §1.2 "Evidence").

    PLAN amendment 2026-10-22: the event also carries the two states the rule saw, `allocation_finalized`
    (= allocation_before) and `allocation_pending_inclusive` (ticket -> holders before this call; computed
    from allocation_before and pending_before when not given), so a reader can replay the verdict."""
    finalized = {t: o for t, o in allocation_before.items() if o and o != "unassigned"}
    if allocation_pending_inclusive is None:
        allocation_pending_inclusive = pending_inclusive_state(finalized, pending_before)
    return {
        "event": CLAIM_EVENT, "version": 1, "defense": defense, "tool": "assign_task",
        "agent": agent, "task_id": task_id, "turn": turn, "reason": reason,
        "reason_ok": reason_ok, "matched_token": matched_token, "accepted": accepted, "error": error,
        "outcome": outcome,   # pending | contest | final | reason_rejected | already_pending | not_found | already_assigned
        "claimants_before": [dict(c) for c in _ordered(claimants_before)], "deadline": deadline,
        "allocation_before": dict(sorted(allocation_before.items())),
        "allocation_finalized": dict(sorted(finalized.items())),
        "allocation_pending_inclusive": {t: list(hs) for t, hs in sorted(allocation_pending_inclusive.items())},
        "pending_before": {t: [dict(c) for c in _ordered(cs)] for t, cs in sorted(pending_before.items())},
        "claim_index": claim_index, "call_index": call_index, "tool_result": tool_result,
        "resolution_rule": rule, "window": window, "inspect_span_id": inspect_span_id,
    }


def resolution_event(*, defense: str, task_id: str, open_turn: int, deadline: int, turn: int | None, trigger: str,
                     claimants: list[dict], rule: str, winner: str, basis: str, ref_owner: str | None,
                     rule_at_resolution: dict, allocation_before: dict[str, str], allocation_after: dict[str, str],
                     inspect_span_id: str | None = None) -> dict:
    """One claim_protocol_resolution per closed window (PLAN §1.2 "Evidence")."""
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}")
    if basis not in BASES:
        raise ValueError(f"unknown basis {basis!r}")
    return {
        "event": RESOLUTION_EVENT, "version": 1, "defense": defense,
        "task_id": task_id, "open_turn": open_turn, "deadline": deadline, "turn": turn, "trigger": trigger,
        "claimants": [dict(c) for c in _ordered(claimants)], "resolution_rule": rule,
        "winner": winner, "basis": basis, "ref_owner": ref_owner,
        "rule_at_resolution": dict(rule_at_resolution),
        "allocation_before": dict(sorted(allocation_before.items())),
        "allocation_after": dict(sorted(allocation_after.items())),
        "inspect_span_id": inspect_span_id,
    }
