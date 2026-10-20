"""Per-claim report for the claim-time monitor (PLAN §16.8).

For each .eval log given: every assign_task call, per agent, with the exact context the judge
received (from the defense's `claim_time_judgement` event), the verdict and the reason; the
judge's own ModelEvent is matched to that prompt so the logged context is what the judge saw.
Then the context fields are checked against the problem definition rebuilt from the task args
(build_problem) and against the allocation implied by the preceding successful assign_task tool
events in the transcript. Per-agent judged/blocked counts close the report.

    uv run python -m adaptive_control.claim_report <log.eval> [<log.eval> ...] [--full]
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict

from inspect_ai.log import read_eval_log

from adaptive_control.results import _span_turns


def _problem(log):
    from orbit.scenarios.cooperative_allocation.jira_ticket.dataset_builder import build_problem

    a = log.eval.task_args or {}
    return build_problem(num_developers=int(a.get("num_developers", 4)), num_tasks=int(a.get("num_tasks", 6)),
                         scarcity=float(a.get("scarcity", 0.5)), seed=int(a.get("seed", 42)))


def _close(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


def report(path: str, full: bool) -> None:
    log = read_eval_log(path, resolve_attachments=True)  # long event strings are stored as attachment:// refs
    problem = _problem(log)
    tasks = {t.task_id: t for t in problem.tasks}
    devs = {d.name: d for d in problem.developers}
    coalition = (log.eval.task_args or {}).get("coalition_agents") or ""
    coalition = [c.strip() for c in coalition.split(",") if c.strip()] if isinstance(coalition, str) else list(coalition)
    print("=" * 100)
    print(f"LOG {path}\n  status={log.status} ordering={(log.eval.task_args or {}).get('ordering')} "
          f"seed={(log.eval.task_args or {}).get('seed')} defense_preset={(log.eval.task_args or {}).get('defense_preset')} "
          f"coalition={coalition or 'none (clean)'} payload_file={(log.eval.task_args or {}).get('coalition_payload_file')}")
    print("  problem definition (rebuilt from the task args):")
    for t in problem.tasks:
        print(f"    {t.task_id} \"{t.title}\": skill {t.skill_required}, priority {t.priority}, effort {t.estimated_effort:g} h")
    for d in problem.developers:
        print(f"    {d.name}: skills {d.skills}, availability {d.availability:g} h")
    for s in log.samples or []:
        slot_of_span = _span_turns(log, s)
        model_prompts = {}
        for e in s.events:
            if e.event == "model" and e.input:
                first = e.input[0]
                content = first.content if isinstance(first.content, str) else str(first.content)
                model_prompts.setdefault(content, []).append(e)
        judgements = [e for e in s.events if e.event == "info" and isinstance(e.data, dict) and e.data.get("event") == "claim_time_judgement"]
        interventions = [e for e in s.events if e.event == "info" and isinstance(e.data, dict)
                         and e.data.get("event") == "defense_intervention" and e.data.get("boundary") == "tool_call"
                         and e.data.get("tool") == "assign_task"]
        tool_calls = [e for e in s.events if e.event == "tool" and e.function == "assign_task"]
        tool_events = [e for e in s.events if e.event == "tool"]
        pos_of = {id(e): i for i, e in enumerate(tool_events)}
        viewed_by = []  # (position among tool events, agent) for allowed view_tasks calls
        for e in tool_events:
            if e.function == "view_tasks" and e.error is None:
                viewed_by.append((pos_of[id(e)], slot_of_span.get(e.span_id, (None, None))[0]))
        halt = None
        for e in s.events:
            if e.event == "info" and isinstance(e.data, str) and "halt_reason=" in e.data:
                halt = e.data.split("halt_reason=", 1)[1].split()[0].rstrip(".,")
        print(f"\n  SAMPLE epoch={s.epoch} error={s.error.message[:100] if s.error else None} halt_reason={halt} "
              f"judgements={len(judgements)} assign_task interventions={len(interventions)} assign_task tool events={len(tool_calls)}")
        # Allocation implied by the transcript. A tool event is placed in the transcript when the
        # call starts, before the judge's event for that same call, so judgement k is paired with
        # the k-th assign_task tool event and the allocation at judgement time is the set of
        # successful claims among the earlier tool events (both lists are in call order).
        results = []
        for e in tool_calls:
            m = re.match(r"Task (\S+) assigned to (\S+)\.", str(e.result or ""))
            results.append((m.group(1), m.group(2)) if m else None)
        if len(tool_calls) != len(judgements):
            print(f"  NOTE: {len(tool_calls)} assign_task tool events vs {len(judgements)} judgements; pairing by order may be off")
        counts = defaultdict(lambda: {"judged": 0, "blocked": 0})
        mismatches = []
        prior_by_agent = defaultdict(list)
        for k, j in enumerate(judgements):
            d = j.data
            agent, tid, ctx = d["agent"], d["task_id"], d["context"]
            counts[agent]["judged"] += 1
            if not d["allow"]:
                counts[agent]["blocked"] += 1
            matched = d["prompt"] in model_prompts
            own = tool_calls[k] if k < len(tool_calls) else None
            own_txt = (f"error: {own.error.message[:90]}" if own is not None and own.error else str(own.result)[:90]) if own is not None else "n/a"
            tag = "coalition" if agent in coalition else "outsider"
            print(f"\n  --- claim {k + 1}: {agent} ({tag}) assign_task({tid}) turn={d.get('turn')} -> "
                  f"{'ALLOW' if d['allow'] else 'BLOCK'}   [judge ModelEvent with this exact prompt: {'found' if matched else 'NOT FOUND'}]")
            print("  context the judge received:")
            for line in d["context_text"].splitlines():
                print("    | " + line)
            print(f"  tool result: {own_txt}")
            print("  judge response:")
            for line in d["response"].splitlines():
                print("    > " + line)
            if full:
                print("  full prompt:")
                for line in d["prompt"].splitlines():
                    print("    # " + line)
            # ── checks against the problem definition ──
            t = tasks.get(tid)
            if t is None:
                if ctx["ticket"] is not None:
                    mismatches.append(f"claim {k + 1}: ticket {tid} not in the problem but context has ticket fields")
            else:
                ct = ctx["ticket"] or {}
                for key, want in (("skill_required", t.skill_required), ("priority", t.priority),
                                  ("estimated_effort", t.estimated_effort), ("title", t.title)):
                    if not _close(ct.get(key), want):
                        mismatches.append(f"claim {k + 1}: ticket.{key} = {ct.get(key)!r}, problem says {want!r}")
            dv = devs.get(agent)
            prof = ctx["agent_profile"]
            if dv is None:
                mismatches.append(f"claim {k + 1}: agent {agent} not in the problem")
            else:
                if prof["skills"] != dv.skills:
                    mismatches.append(f"claim {k + 1}: skills {prof['skills']} vs problem {dv.skills}")
                if not _close(prof["availability"], dv.availability):
                    mismatches.append(f"claim {k + 1}: availability {prof['availability']} vs problem {dv.availability}")
                if t is not None and not _close(prof["proficiency_in_required_skill"], dv.skills.get(t.skill_required)):
                    mismatches.append(f"claim {k + 1}: proficiency {prof['proficiency_in_required_skill']} vs problem {dv.skills.get(t.skill_required)}")
                if t is not None:
                    skilled = sorted(n for n, x in devs.items() if t.skill_required in x.skills)
                    if ctx["developers_with_required_skill"] != skilled:
                        mismatches.append(f"claim {k + 1}: skilled devs {ctx['developers_with_required_skill']} vs problem {skilled}")
            # allocation at judgement time = successful claims whose tool event precedes this judgement
            alloc = {}
            for r in results[:k]:
                if r:
                    alloc[r[0]] = r[1]
            if ctx["current_allocation"] != alloc:
                mismatches.append(f"claim {k + 1}: allocation {ctx['current_allocation']} vs transcript {alloc}")
            held = sorted(tt for tt, o in alloc.items() if o == agent)
            if ctx["tickets_held"] != held:
                mismatches.append(f"claim {k + 1}: held {ctx['tickets_held']} vs transcript {held}")
            if dv is not None:
                workload = sum(tasks[tt].estimated_effort for tt in held if tt in tasks)
                if not _close(ctx["workload_hours"], workload) or not _close(ctx["remaining_hours"], dv.availability - workload):
                    mismatches.append(f"claim {k + 1}: workload/remaining {ctx['workload_hours']}/{ctx['remaining_hours']} "
                                      f"vs {workload}/{dv.availability - workload}")
                if t is not None and not _close(ctx["hours_after_claim"], dv.availability - workload - t.estimated_effort):
                    mismatches.append(f"claim {k + 1}: hours_after_claim {ctx['hours_after_claim']} vs {dv.availability - workload - t.estimated_effort}")
            # new fields (PLAN §16.9): fits_capacity, best-fit developer, called view_tasks before
            if t is not None and dv is not None:
                want_fits = (dv.availability - workload - t.estimated_effort) >= 0
                if ctx.get("fits_capacity") != want_fits:
                    mismatches.append(f"claim {k + 1}: fits_capacity {ctx.get('fits_capacity')} vs {want_fits}")
                best, bp = None, None
                for n in sorted(devs):
                    pr = devs[n].skills.get(t.skill_required)
                    if pr is not None and (bp is None or pr > bp):
                        best, bp = n, pr
                if ctx.get("best_fit_developer") != best or not _close(ctx.get("best_fit_proficiency"), bp):
                    mismatches.append(f"claim {k + 1}: best fit {ctx.get('best_fit_developer')}/{ctx.get('best_fit_proficiency')} vs {best}/{bp}")
            if own is not None:
                want_viewed = any(p < pos_of[id(own)] and a == agent for p, a in viewed_by)
                if bool(ctx.get("called_view_tasks_before")) != want_viewed:
                    mismatches.append(f"claim {k + 1}: called_view_tasks_before {ctx.get('called_view_tasks_before')} vs transcript {want_viewed}")
            unclaimed = [tt for tt in tasks if tt not in alloc]
            if ctx["unclaimed"] != unclaimed:
                mismatches.append(f"claim {k + 1}: unclaimed {ctx['unclaimed']} vs {unclaimed}")
            want_prior = [{"task_id": p["task_id"], "allow": p["allow"], "holds_now": alloc.get(p["task_id"]) == agent}
                          for p in prior_by_agent[agent]]
            if ctx["prior_claims"] != want_prior:
                mismatches.append(f"claim {k + 1}: prior claims {ctx['prior_claims']} vs expected {want_prior}")
            prior_by_agent[agent].append({"task_id": tid, "allow": d["allow"]})
            if not matched:
                mismatches.append(f"claim {k + 1}: no judge ModelEvent carries this exact prompt")
        # ── interventions vs judgements: every assign_task tool_call verdict should have a judgement ──
        if len(interventions) != len(judgements):
            mismatches.append(f"{len(interventions)} assign_task defense_intervention events vs {len(judgements)} judgements")
        for j, i in zip(judgements, interventions):
            if j.data["agent"] != i.data.get("agent") or j.data["allow"] != i.data.get("allow"):
                mismatches.append(f"judgement/intervention disagree: {j.data['agent']}/{j.data['allow']} vs {i.data.get('agent')}/{i.data.get('allow')}")
            if j.data.get("turn") != i.data.get("turn"):
                mismatches.append(f"turn differs: judgement {j.data.get('turn')} vs intervention {i.data.get('turn')}")
        print("\n  per-agent assign_task verdicts:")
        for agent in sorted(counts):
            c = counts[agent]
            tag = "coalition" if agent in coalition else "outsider"
            print(f"    {agent} ({tag}): judged {c['judged']}, blocked {c['blocked']}")
        other_blocks = defaultdict(int)
        for e in s.events:
            if e.event == "info" and isinstance(e.data, dict) and e.data.get("event") == "defense_intervention" and e.data.get("allow") is False:
                key = (e.data.get("agent"), e.data.get("boundary"), e.data.get("tool") or "-")
                other_blocks[key] += 1
        print("  all blocks by (agent, boundary, tool):", dict(sorted(other_blocks.items())) or "none")
        final = {}
        for r in results:
            if r:
                final[r[0]] = r[1]
        print("  final allocation from the transcript:", dict(sorted(final.items())))
        print(f"\n  CONTEXT CHECK against the problem definition and the transcript: "
              f"{len(judgements)} claims checked, {len(mismatches)} mismatches")
        for m in mismatches:
            print("    MISMATCH:", m)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--full", action="store_true", help="also print the full judge prompt per claim")
    args = ap.parse_args()
    for p in args.logs:
        report(p, args.full)


if __name__ == "__main__":
    main()
