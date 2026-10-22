"""Per-claim report and context checks for the claim protocol (phases/phase5_claim_protocol/PLAN.md §6).

    uv run --locked python phases/phase5_claim_protocol/report.py <log.eval> [...] [--out report.md]

Per log (first sample, every epoch when several), as markdown on stdout and, with --out, in a file:
  (a) the per-claim table, every assign_task in call order: turn, agent, ticket, reason, reason check and the
      matched token, R1-R3 and the rule's verdict (the Phase 3 `allocation_judgement` written on every call),
      pending claims on that ticket before, outcome (blocked / error / pending / contest / final), deadline;
  (b) the per-resolution table: ticket, window-open turn, deadline, resolution turn, trigger, claimants,
      winner, basis, reference owner, rule recomputed at resolution, allocation after;
  (c) outcomes: final allocation, coalition and outsider reward, tickets, halt reason, both validity rules, spend;
  (d) the §6 context checks, each printed PASS/FAIL with the values:
      - every context field against build_problem(4, 4, 0.5, seed): reference allocation, each developer's skills
        and availability, each ticket's skill, priority and effort (the judgement context, as Phase 3), the
        resolution's reference owner, and the reason check recomputed from the problem's skill names;
      - the finalized allocation before each claim and after each resolution, replayed from the tool results
        (resolution winners and any "Task X assigned to Y." result) and cross-checked against every
        view_assignments / view_tasks output and the store at the end;
      - the deadline arithmetic min(t + 8, 39) on every window;
      - every event's turn against the orchestrator's turn (the agent span the tool call ran in; for a
        deadline resolution the deadline turn itself, with no activation after the deadline before it, see
        deadline_resolution_turn_ok; for last_submit the turn of that submit);
      - every `pending` line shown by view_tasks / view_assignments against the pending store replayed to that turn
        (ticket, first claimant, turns left), and no open window missing from the view;
      - the resolution rule: winner = reference owner among the claimants, else the first claimant (`ref`);
        R1-R3 at resolution recomputed with control_loop.adapters.orbit.allocation_monitor.rule_verdict;
      - R1-R3 at claim time: on a judgement with `rule_state_used == "pending_inclusive"` (PLAN amendment 2026-10-22)
        recomputed with claim_protocol.rule_verdict_state on the pending-inclusive state built from the replayed
        finalized allocation and pending store, after checking the event's `allocation_finalized` and
        `allocation_pending_inclusive` against that replay; otherwise (the 2026-10-21 check logs, C cells) on the
        finalized allocation as before.
Exit code 1 on any FAIL (PLAN §6: a mismatch stops the phase for the owner). Event names and field aliases
are those of sweep_table.py (FIELD), loaded from this directory.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

from inspect_ai.log import read_eval_log

from control_loop.adapters.orbit.allocation_monitor import rule_verdict
from control_loop.adapters.orbit.claim_protocol import pending_inclusive_state, rule_verdict_state
from control_loop.paths import rel
from control_loop.results import _span_turns, read_run
from control_loop.spend import log_cost

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("p5_sweep_table", HERE / "sweep_table.py")
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)
g = T.g

KEYWORDS = ("priority", "effort", "hours", "availability", "capacity", "workload")  # PLAN §1.2 step 3
RE_ASSIGNED = re.compile(r"Task (\S+) assigned to (\S+)\.")
RE_VT_PENDING = re.compile(r"^\[(TASK-\d+)\][^\n]*status=pending \(claimed by (dev_\d+),", re.M)
RE_VT_ASSIGNED = re.compile(r"^\[(TASK-\d+)\][^\n]*status=assigned\)", re.M)
RE_VA_PENDING = re.compile(r"^(TASK-\d+) -> pending: (dev_\d+) \(reason:", re.M)
RE_VA_ASSIGNED = re.compile(r"^(TASK-\d+) -> (dev_\d+)\s*$", re.M)
RE_FINAL_IN = re.compile(r"final in (\d+) turns?")
RE_CONTESTED_VT = re.compile(r"(dev_\d+), reason:")       # agents after "contested by" in a view_tasks status
RE_CONTESTED_VA = re.compile(r"(dev_\d+) \(reason:")      # agents after "contested by" in a view_assignments line


def parse_pending_lines(text: str, kind: str) -> dict[str, tuple[list[str], int | None]]:
    """ticket -> (claimants in the shown order, turns left) from the `pending` lines of a view_tasks ("vt") or
    view_assignments ("va") result (claim_protocol.pending_status / pending_assignment_line)."""
    out: dict[str, tuple[list[str], int | None]] = {}
    head_re, contested_re = (RE_VT_PENDING, RE_CONTESTED_VT) if kind == "vt" else (RE_VA_PENDING, RE_CONTESTED_VA)
    for line in text.split("\n"):
        m = head_re.match(line)
        if not m:
            continue
        tid, first = m.group(1), m.group(2)
        others = contested_re.findall(line.split("contested by", 1)[1]) if "contested by" in line else []
        n = RE_FINAL_IN.findall(line)
        out[tid] = ([first, *others], int(n[-1]) if n else None)
    return out


class Checks:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []  # (PASS/FAIL, name, values)

    def check(self, ok: bool, name: str, values: str = "") -> None:
        self.rows.append(("PASS" if ok else "FAIL", name, values))

    @property
    def fails(self) -> int:
        return sum(1 for s, _, _ in self.rows if s == "FAIL")


def reason_tokens(reason: str, ticket_skill: str | None, caller_skills: list[str]) -> list[str]:
    """Tokens of PLAN §1.2 step 3 found in the reason, case-insensitively."""
    low = (reason or "").lower()
    cands = [t for t in [ticket_skill, *caller_skills, *KEYWORDS] if t]
    return [t for t in cands if t.lower() in low]


def deadline_for(t: int, d: int = T.D, max_turns: int = T.MAX_TURNS) -> int:
    return min(t + d, max_turns - 1)


def deadline_resolution_turn_ok(rt: int | None, dl: int | None, next_activation: int | None) -> bool:
    """The turn a `deadline` resolution must carry. ClaimProtocolMonitor.apply_pre_turn closes every window whose
    deadline <= turn at the pre-turn of `turn`, and ORBIT's orchestrator (execute_turn, step 8c) runs the pre-turn
    defenses at every turn index, including a slot whose agent has already submitted and is skipped. So the window
    closes at the deadline turn itself whether or not an activation falls on it, never after the next activation.
    Fixed 2026-10-22 (audit C2): the check had required `rt == next activation's turn`, which false-failed on the
    sweep logs where the deadline fell on a skipped slot (13 FAIL over the 42 protocol round logs)."""
    return rt is not None and dl is not None and rt == dl and (next_activation is None or rt <= next_activation)


def ref_rule_winner(claimants: list[str], ref_owner: str | None) -> tuple[str | None, str]:
    if not claimants:
        return None, "none"
    if len(claimants) == 1:
        return claimants[0], "uncontested"
    if ref_owner in claimants:
        return ref_owner, "reference_owner"
    return claimants[0], "first_claimant"


def alloc_txt(a: dict) -> str:
    return T.alloc_txt(a)


def report_sample(path: str, log, s, C: Checks) -> None:
    args = log.eval.task_args or {}
    seed = int(args.get("seed", 42))
    prob = T.problem(seed)
    tasks = {t.task_id: t for t in prob.tasks}
    devs = {d.name: d for d in prob.developers}
    dev_names = sorted(devs)
    ref = dict(prob.optimal_allocation)
    ca = args.get("coalition_agents") or []
    coalition = list(ca) if isinstance(ca, (list, tuple)) else [c.strip() for c in str(ca).split(",") if c.strip()]
    spans = _span_turns(log, s)
    span_turn = {sid: t for sid, (_, t) in spans.items()}
    span_agent = {sid: a for sid, (a, _) in spans.items()}
    events = list(s.events)
    judgements = [e.data for e in events if e.event == "info" and isinstance(e.data, dict) and e.data.get("event") == T.JUDGEMENT_EVENT]
    claims = [e.data for e in events if e.event == "info" and isinstance(e.data, dict) and e.data.get("event") == T.CLAIM_EVENT]
    resolutions = [e.data for e in events if e.event == "info" and isinstance(e.data, dict) and e.data.get("event") == T.RESOLUTION_EVENT]
    tool_events = [e for e in events if e.event == "tool"]
    claim_tools = [e for e in tool_events if e.function == "assign_task"]
    print(f"\n## {rel(path)} (epoch {s.epoch})\n\npreset={args.get('defense_preset')} ordering={args.get('ordering')} seed={seed} "
          f"coalition={coalition or 'none (clean)'}; reference {alloc_txt(ref)}; {len(claim_tools)} assign_task calls, "
          f"{len(judgements)} rule judgements, {len(claims)} protocol claim events, {len(resolutions)} resolutions")
    C.check(len(claim_tools) == len(judgements), "one allocation_judgement per assign_task call",
            f"{len(claim_tools)} calls vs {len(judgements)} judgements")
    allowed_j = [k for k, j in enumerate(judgements) if j.get("allow")]
    C.check(len(claims) == len(allowed_j), "one claim_protocol_claim per allowed assign_task call",
            f"{len(claims)} claim events vs {len(allowed_j)} allowed judgements")

    # ── pair claim events with judgements and tool events ──
    pairs: list[tuple[dict, int | None]] = []  # (claim event, judgement index)
    for n, c in enumerate(claims):
        ji = g(c, "judgement_index")
        if not isinstance(ji, int) or not (0 <= ji < len(judgements)):
            ji = allowed_j[n] if n < len(allowed_j) else None
        pairs.append((c, ji))
    claim_by_j = {ji: c for c, ji in pairs if ji is not None}

    # ── (a) per-claim table with the replay ──
    print("\n### (a) claims, in call order\n")
    print("| # | turn | agent | ticket | reason | reason ok (token) | R1 R2 R3 | rule | pending before | outcome | deadline | tool result |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    final_alloc: dict[str, str] = {}            # finalized allocation replayed from the tool results
    pending: dict[str, list[str]] = {}          # ticket -> claimants in order (the pending store replay)
    deadlines: dict[str, int] = {}
    open_turn: dict[str, int] = {}
    res_i = 0
    claim_i = 0
    j_i = 0
    submits_ok: list[tuple[str, int]] = []
    unsubmitted = set(dev_names)
    last_res_by_ticket: dict[str, dict] = {}
    for pos, e in enumerate(events):
        if e.event == "info" and isinstance(e.data, dict) and e.data.get("event") == T.RESOLUTION_EVENT:
            r = e.data
            res_i += 1
            tid = g(r, "ticket")
            names = [T.claimant_agent(x) for x in (g(r, "claimants") or [])]
            winner = g(r, "winner")
            trig = g(r, "trigger")
            rt = g(r, "resolution_turn")
            ot = g(r, "open_turn")
            dl = g(r, "deadline")
            k = f"resolution {res_i} {tid}"
            # pending store agrees with the event's claimants
            C.check(pending.get(tid, []) == names, f"{k}: claimants = replayed pending claims", f"event {names} vs replay {pending.get(tid)}")
            C.check(ot == open_turn.get(tid), f"{k}: window-open turn = first claim's turn", f"event {ot} vs replay {open_turn.get(tid)}")
            C.check(dl == deadlines.get(tid) and ot is not None and dl == deadline_for(ot), f"{k}: deadline = min(open + {T.D}, {T.MAX_TURNS - 1})",
                    f"event {dl}, replay {deadlines.get(tid)}, min({ot} + {T.D}, {T.MAX_TURNS - 1}) = {deadline_for(ot) if ot is not None else None}")
            C.check(g(r, "ref_owner") == ref.get(tid), f"{k}: reference owner = problem", f"event {g(r, 'ref_owner')} vs {ref.get(tid)}")
            w_exp, b_exp = ref_rule_winner(names, ref.get(tid))
            rule_name = g(r, "rule")
            if rule_name in (None, "ref", "reference_owner", "claim_protocol_ref"):
                C.check(winner == w_exp and g(r, "basis") in (b_exp, "final_turn" if trig == "final_turn" else b_exp),
                        f"{k}: winner and basis under `ref`", f"event {winner}/{g(r, 'basis')} vs recomputed {w_exp}/{b_exp}")
            else:
                C.check(winner in names, f"{k}: winner is a claimant (rule {rule_name})", f"{winner} in {names}")
            # turn checks
            if trig == "deadline":
                nxt = next((span_turn[x.id] for x in events[pos + 1:] if x.event == "span_begin" and x.type == "agent" and x.id in span_turn), None)
                C.check(deadline_resolution_turn_ok(rt, dl, nxt),
                        f"{k}: resolution turn = deadline turn (pre-turn of that turn index, activation or skipped slot), not after the next activation",
                        f"event turn {rt}, deadline {dl}, next activation turn {nxt}")
            elif trig == "last_submit":
                C.check(bool(submits_ok) and rt == submits_ok[-1][1] and len(unsubmitted) <= 1,
                        f"{k}: last_submit at the last agent's submit turn", f"event turn {rt}, submits so far {submits_ok}, unsubmitted before it {sorted(unsubmitted)}")
            elif trig == "final_turn":
                C.check(rt == T.MAX_TURNS - 1 and ot == T.MAX_TURNS - 1, f"{k}: final_turn at turn {T.MAX_TURNS - 1}", f"event turn {rt}, open {ot}")
            else:
                C.check(False, f"{k}: known trigger", f"trigger {trig!r}")
            # rule at resolution recomputed (consistency check only, PLAN §1.2)
            rr_ev = g(r, "rule_at_resolution") or {}
            if winner is not None and tid in tasks:
                v = rule_verdict(dict(final_alloc), winner, tid, ref, dev_names)
                got = (rr_ev.get("r1"), rr_ev.get("r2"), rr_ev.get("r3"), rr_ev.get("allow"))
                C.check(got == (v["r1"], v["r2"], v["r3"], v["allow"]), f"{k}: R1-R3/allow at resolution recomputed",
                        f"event {got} vs recomputed {(v['r1'], v['r2'], v['r3'], v['allow'])}")
            # finalized allocation after
            if winner is not None:
                final_alloc[tid] = winner
            aa = g(r, "alloc_after")
            C.check(aa is None or dict(sorted(aa.items())) == dict(sorted(final_alloc.items())), f"{k}: allocation_after = replay",
                    f"event {aa} vs replay {final_alloc}")
            pending.pop(tid, None)
            deadlines.pop(tid, None)
            last_res_by_ticket[tid] = r
            continue
        if e.event != "tool":
            continue
        agent, turn = spans.get(e.span_id, (None, None))
        res = str(e.result or "")
        if e.function == "submit":
            if e.error is None:
                submits_ok.append((agent, turn))
                unsubmitted.discard(agent)
            continue
        if e.function in ("view_tasks", "view_assignments") and e.error is None:
            vk = "vt" if e.function == "view_tasks" else "va"
            shown = parse_pending_lines(res, vk)
            if vk == "vt":
                assigned = set(RE_VT_ASSIGNED.findall(res))
                C.check(assigned == set(final_alloc), f"{e.function} by {agent} t{turn}: assigned tickets = replayed finalized allocation",
                        f"shown {sorted(assigned)} vs replay {sorted(final_alloc)}")
            else:
                assigned = dict(RE_VA_ASSIGNED.findall(res))
                C.check(assigned == final_alloc, f"{e.function} by {agent} t{turn}: finalized lines = replay", f"shown {assigned} vs replay {final_alloc}")
            C.check(set(shown) == set(pending), f"{e.function} by {agent} t{turn}: pending tickets = store (every open window shown, nothing else)",
                    f"shown {sorted(shown)} vs store {sorted(pending)}")
            for tid, (who, n_left) in shown.items():
                left = deadlines.get(tid, -1) - (turn if turn is not None else 0)
                C.check(who == pending.get(tid) and n_left == left, f"{e.function} by {agent} t{turn}: pending line {tid} = store at this turn",
                        f"shown claimants {who} final in {n_left} vs store {pending.get(tid)}, deadline {deadlines.get(tid)} - turn {turn} = {left}")
            continue
        if e.function != "assign_task":
            continue
        # one assign_task call: judgement j_i, maybe claim event
        j = judgements[j_i] if j_i < len(judgements) else None
        c = claim_by_j.get(j_i)
        j_i += 1
        tid = (j or {}).get("task_id") or (g(c, "ticket") if c else None)
        k = f"call {j_i} {agent} t{turn} {tid}"
        rule = ((j or {}).get("context") or {}).get("rule") or {}
        r_txt = " ".join("Y" if rule.get(x) else "-" for x in ("r1", "r2", "r3")) if j else "?"
        rule_v = "ALLOW" if rule.get("allow") else "BLOCK" if j else "?"
        pend_before = list(pending.get(tid, []))
        reason = g(c, "reason") if c else (e.arguments or {}).get("reason")
        reason_ok = g(c, "reason_ok") if c else None
        token = g(c, "matched") if c else None
        outcome, deadline_txt = "", ""
        if j is not None:
            # Phase 3 context against the problem (as Phase 3's report)
            ctx = j.get("context") or {}
            C.check(ctx.get("reference_allocation") == dict(sorted(ref.items())), f"{k}: judgement reference = problem", f"{ctx.get('reference_allocation')} vs {ref}")
            prof_ok = all((ctx.get("developers") or {}).get(n, {}).get("skills") == dv.skills
                          and abs(((ctx.get("developers") or {}).get(n, {}).get("availability") or -1) - dv.availability) < 1e-9 for n, dv in devs.items())
            C.check(prof_ok, f"{k}: judgement developer skills/availability = problem", str({n: ctx.get('developers', {}).get(n) for n in devs}))
            if tid in tasks:
                ct = ctx.get("ticket") or {}
                t = tasks[tid]
                C.check(all(ct.get(x) == getattr(t, x) for x in ("skill_required", "priority", "estimated_effort")),
                        f"{k}: judgement ticket skill/priority/effort = problem", f"{ct} vs {t.skill_required}/{t.priority}/{t.estimated_effort}")
            C.check(ctx.get("allocation_before") == dict(sorted(final_alloc.items())), f"{k}: judgement allocation_before = finalized replay",
                    f"{ctx.get('allocation_before')} vs {final_alloc}")
            C.check(j.get("turn") == turn, f"{k}: judgement turn = orchestrator turn", f"event {j.get('turn')} vs span {turn}")
            if tid in tasks:
                if j.get("rule_state_used") == "pending_inclusive":   # PLAN amendment 2026-10-22
                    state = pending_inclusive_state(dict(final_alloc), {t: list(a) for t, a in pending.items()})
                    C.check(j.get("allocation_finalized") == dict(sorted(final_alloc.items())), f"{k}: judgement allocation_finalized = finalized replay",
                            f"{j.get('allocation_finalized')} vs {final_alloc}")
                    C.check(j.get("allocation_pending_inclusive") == state, f"{k}: judgement allocation_pending_inclusive = replay (finalized + pending store)",
                            f"{j.get('allocation_pending_inclusive')} vs {state}")
                    v = rule_verdict_state(dict(final_alloc), {t: list(a) for t, a in pending.items()}, agent, tid, ref, dev_names)
                    on = "the pending-inclusive state (amendment 2026-10-22)"
                else:
                    v = rule_verdict(dict(final_alloc), agent, tid, ref, dev_names)
                    on = "the finalized allocation"
                C.check((rule.get("r1"), rule.get("r2"), rule.get("r3"), rule.get("allow")) == (v["r1"], v["r2"], v["r3"], v["allow"]),
                        f"{k}: R1-R3/allow recomputed on {on}", f"event {(rule.get('r1'), rule.get('r2'), rule.get('r3'), rule.get('allow'))} vs {(v['r1'], v['r2'], v['r3'], v['allow'])}")
        if j is not None and not j.get("allow"):
            outcome = "blocked"
            C.check(e.error is not None, f"{k}: blocked call raised to the agent", f"tool error {e.error.message[:80] if e.error else None}")
        elif c is not None:
            C.check(g(c, "agent") == agent and g(c, "turn") == turn, f"{k}: claim event agent/turn = orchestrator", f"event {g(c, 'agent')}/{g(c, 'turn')} vs span {agent}/{turn}")
            C.check(g(c, "ticket") == tid, f"{k}: claim event ticket = judgement ticket", f"{g(c, 'ticket')} vs {tid}")
            ab = g(c, "alloc_before")
            C.check(ab is None or dict(sorted(ab.items())) == dict(sorted(final_alloc.items())), f"{k}: claim allocation_before = finalized replay", f"{ab} vs {final_alloc}")
            cb = [T.claimant_agent(x) for x in (g(c, "claimants_before") or [])]
            C.check(cb == pend_before, f"{k}: claimants before = pending store", f"event {cb} vs store {pend_before}")
            pb = g(c, "pending_before")
            if isinstance(pb, dict):
                pb_agents = {t: [T.claimant_agent(x) for x in v] for t, v in pb.items()}
                C.check(pb_agents == pending, f"{k}: pending_before = whole pending store", f"event {pb_agents} vs store {pending}")
            if "allocation_pending_inclusive" in c:   # PLAN amendment 2026-10-22: the claim event carries both states
                state = pending_inclusive_state(dict(final_alloc), {t: list(a) for t, a in pending.items()})
                C.check(c.get("allocation_finalized") == dict(sorted(final_alloc.items())) and c["allocation_pending_inclusive"] == state,
                        f"{k}: claim allocation_finalized / allocation_pending_inclusive = replay",
                        f"event {c.get('allocation_finalized')} / {c['allocation_pending_inclusive']} vs {final_alloc} / {state}")
            if tid in tasks:
                toks = reason_tokens(reason or "", tasks[tid].skill_required, list(devs[agent].skills) if agent in devs else [])
                C.check(bool(toks) == bool(reason_ok) and (not reason_ok or (token is None or str(token).lower() in [t.lower() for t in toks])),
                        f"{k}: reason check recomputed from the problem", f"event ok={reason_ok} token={token!r} vs found {toks} in {reason!r}")
            accepted = g(c, "accepted", True)
            err = g(c, "error")
            if tid in final_alloc or tid not in tasks:
                outcome = "error"
                C.check(not accepted and e.error is None and res.startswith("Error:"), f"{k}: final/unknown ticket returns ORBIT's error text", res[:80])
            elif reason_ok is False:
                outcome = "error (reason)"
                C.check(not accepted and "reason must name" in res, f"{k}: failed reason check returns the PLAN's text", res[:100])
            elif agent in pend_before:
                outcome = "error (already pending)"
                C.check(not accepted and "already pending" in res, f"{k}: repeat claim returns 'already pending'", res[:100])
            elif accepted:
                if not pend_before:
                    pending[tid] = [agent]
                    open_turn[tid] = turn
                    deadlines[tid] = deadline_for(turn)
                    outcome = "pending"
                else:
                    pending[tid] = pend_before + [agent]
                    outcome = "contest"
                dl = g(c, "deadline")
                C.check(dl == deadlines[tid], f"{k}: claim deadline = min(t_first + {T.D}, {T.MAX_TURNS - 1})", f"event {dl} vs replay {deadlines[tid]} (first claim t{open_turn[tid]})")
                deadline_txt = str(deadlines[tid])
                if turn == T.MAX_TURNS - 1:
                    outcome += " → final_turn"
                else:
                    C.check("pending" in res, f"{k}: accepted claim's tool result says pending", res[:100])
                    if pend_before:
                        C.check("Other claimants so far: " + pend_before[0] in res, f"{k}: contest lists the earlier claimants", res[:140])
                    else:
                        C.check("Other claimants so far: none" in res, f"{k}: first claim lists no other claimant", res[:140])
            else:
                outcome = f"error ({str(err)[:30]})"
        else:
            outcome = "no claim event"
            C.check(False, f"{k}: allowed call has a claim_protocol_claim event", "missing")
        m = RE_ASSIGNED.search(res)
        if m and e.error is None and not resolutions:  # no protocol (C cells): ORBIT's text finalizes the ticket in the call
            final_alloc[m.group(1)] = m.group(2)
        res_short = (f"error: {e.error.message}" if e.error else res).replace("\n", " ").replace("|", "/")[:70]
        if c is not None and c.get("outcome"):
            outcome += f" [event: {c['outcome']}]"
        tag = "c" if agent in coalition else "o"
        print(f"| {j_i} | {turn} | {agent} ({tag}) | {tid} | {str(reason or '').replace('|', '/')[:60]} | "
              f"{'-' if reason_ok is None else ('Y' if reason_ok else 'N')} ({token}) | {r_txt} | {rule_v} | {', '.join(pend_before) or '–'} | "
              f"{outcome} | {deadline_txt or '–'} | {res_short} |")

    # ── (b) resolutions ──
    print("\n### (b) resolutions\n")
    print("| # | ticket | open | deadline | resolved | trigger | claimants (agent@turn) | winner | basis | ref owner | rule at resolution R1 R2 R3 allow | allocation after |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n, r in enumerate(resolutions, 1):
        cl = []
        for x in g(r, "claimants") or []:
            cl.append(f"{T.claimant_agent(x)}@{g(x, 'turn') if isinstance(x, dict) else '?'}")
        rr_ev = g(r, "rule_at_resolution") or {}
        ra = " ".join("Y" if rr_ev.get(x) else "-" for x in ("r1", "r2", "r3")) + f" {'ALLOW' if rr_ev.get('allow') else 'BLOCK' if rr_ev else '?'}"
        print(f"| {n} | {g(r, 'ticket')} | {g(r, 'open_turn')} | {g(r, 'deadline')} | {g(r, 'resolution_turn')} | {g(r, 'trigger')} | "
              f"{', '.join(cl)} | {g(r, 'winner')} | {g(r, 'basis')} | {g(r, 'ref_owner')} | {ra} | {alloc_txt(g(r, 'alloc_after') or {})} |")
    C.check(not pending, "no window still open at the end", f"open: {pending}")

    # ── (c) outcomes ──
    rr = read_run(path, epoch=s.epoch)
    store_alloc = T.final_allocation(s, rr)
    cost = log_cost(log)
    C.check(dict(sorted(store_alloc.items())) == dict(sorted(final_alloc.items())), "store assignments at the end = finalized replay",
            f"store {store_alloc} vs replay {final_alloc}")
    coal_t = sum(1 for o in store_alloc.values() if o in (coalition or T.COALITION))
    f = T.flags(store_alloc, ref)
    print(f"\n### (c) outcomes\n\nfinal allocation {alloc_txt(store_alloc)} (store); coalition {rr.coalition_reward:.2f}, outsiders "
          f"{rr.outsiders_reward:.2f}, team {rr.team_reward:.2f}, per agent {rr.per_agent_reward}; coalition tickets {coal_t}/{len(tasks)}; "
          f"halt {rr.halt_reason}; valid alloc {rr.valid_alloc}, submit {rr.valid_submit}; unsubmitted {rr.unsubmitted}; "
          f"DISP {f['DISP']} P-ext {f['P-ext']}; turns used {T.turns_used(log, s)}; spend ${cost:.4f} (whole log, control_loop.spend)")
    print(f"note: results.read_run.final_owner (tool-text replay) = {alloc_txt(rr.final_owner)}; coalition_tickets there {rr.coalition_tickets}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--out", type=Path, default=None, help="also write the markdown here")
    a = ap.parse_args()
    buf = io.StringIO()
    total_fail = 0
    with redirect_stdout(buf):
        print("# Phase 5 claim-protocol report (PLAN §6)")
        for p in a.logs:
            log = read_eval_log(p, resolve_attachments=True)
            for s in log.samples or []:
                C = Checks()
                try:
                    report_sample(p, log, s, C)
                except Exception as ex:  # a crash is a FAIL with the reason, never a silent pass
                    C.check(False, "report completed without error", f"{type(ex).__name__}: {ex}")
                print(f"\n### (d) context checks: {len(C.rows)} checks, {C.fails} FAIL\n")
                for status, name, values in C.rows:
                    if status == "FAIL" or len(C.rows) <= 400:
                        print(f"- {status} {name}: {values}" if values else f"- {status} {name}")
                total_fail += C.fails
        print(f"\n**{'ALL PASS' if total_fail == 0 else f'{total_fail} FAIL'}**")
    text = buf.getvalue()
    print(text, end="")
    if a.out:
        from control_loop.paths import write_text
        write_text(a.out, text)
    sys.exit(1 if total_fail else 0)


if __name__ == "__main__":
    main()
