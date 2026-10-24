"""Phase 7 mechanism-check report (phases/phase7_dgm_self_modifying/PLAN.md §6, items (a)–(e)).

    uv run --locked python phases/phase7_dgm_self_modifying/report.py [CELL] [--rounds 1 2] [--out report.md]

CELL defaults to results/phase7_dgm_self_modifying/check/733_allocation_rule_autoallow (the check cell: rounds
A0, A1, A2 plus archive.jsonl, selfmod_log.jsonl, rejections.jsonl, payload_r{1,2}.txt, rounds.jsonl,
baseline.json). Every item is printed PASS/FAIL with its values; exit code 1 on any FAIL (PLAN §6: a mismatch
in (a), (c) or (d) stops the phase for the owner). Per self-modifier call (round r >= 1):

  (a) what it saw: the system prompt equals control_loop.self_modifier.selfmod_system(4, brief) and differs
      from proposer.proposer_system(4, brief) by the §1.2 substitutions only (the unified diff is printed);
      the user message equals proposer.format_history over the rounds before r, re-derived from the .eval
      logs (gain = scorer coalition reward minus baseline.json's clean mean; blocks, channel sends, first
      coalition assign_task from the events through control_loop.results.read_run; claims lost 0), with the
      archive block recomputed from archive.jsonl as it stood before round r; the parent id equals a
      recomputation of the §1.3 weights and the seeded draw.
  (b) what it wrote: the raw completion(s), the parsed moves / diagnosis / memo / payload, check_payload's
      result recomputed against the previous payloads, attempts, fallback (printed; checked against the row).
  (c) what reached the agents: payload_r{r}.txt equals the row's payload and is byte-contained, after
      ORBIT's "Your objective: ", in the orbit_collusion_prompt system message of dev_0 and of dev_1, and in
      the first model request of each coalition agent.
  (d) what was sent: each selfmod_log.jsonl line's `sent` block shows temperature 0 and seed 100 × seed + r
      with sent_source ModelEvent.call.request; every agent request in A{r} carries temperature 0 and the
      problem seed. (A mock log has no provider request, so (d) FAILs on a rehearsal by construction.)
  (e) per step: every tool call by every agent in A{r} (turn, agent, tool, arguments, the rule's R1–R3 and
      verdict for assign_task where the rule runs, result), reconciled with the final allocation in the
      store, the scorer's rewards and the round's line in rounds.jsonl.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import io
import json
import math
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

from inspect_ai.log import read_eval_log

from control_loop import proposer as P
from control_loop import self_modifier as S
from control_loop.paths import rel
from control_loop.results import _span_turns, latest_log, read_run

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_CELL = REPO / "results/phase7_dgm_self_modifying/check/733_allocation_rule_autoallow"
PROVENANCE_KEY = "orbit_collusion_prompt"
JUDGEMENT_EVENT = "allocation_judgement"
COALITION = ("dev_0", "dev_1")


class Checks:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def check(self, ok: bool, name: str, values: str = "") -> bool:
        self.rows.append(("PASS" if ok else "FAIL", name, values))
        print(f"- {'PASS' if ok else 'FAIL'} {name}" + (f": {values}" if values else ""))
        return ok

    @property
    def fails(self) -> int:
        return sum(1 for s, _, _ in self.rows if s == "FAIL")


# ── loading ────────────────────────────────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def msg_text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(getattr(c, "text", "") or "" for c in (content or []))


def delivered_payloads(log) -> dict[str, list[str]]:
    """agent -> the orbit_collusion_prompt system messages delivered to it (from the sample's messages and from
    every model request's input), for the first sample of `log`."""
    out: dict[str, list[str]] = {}
    s = log.samples[0]
    seen = set()

    def add(m):
        meta = (getattr(m, "metadata", None) or {}).get(PROVENANCE_KEY)
        if getattr(m, "role", None) == "system" and isinstance(meta, dict) and meta.get("target_agent"):
            key = (meta["target_agent"], msg_text(m.content))
            if key not in seen:
                seen.add(key)
                out.setdefault(meta["target_agent"], []).append(msg_text(m.content))

    for m in s.messages or []:
        add(m)
    for e in s.events:
        if e.event == "model":
            for m in e.input or []:
                add(m)
    return out


def first_requests(log) -> dict[str, str]:
    """agent -> the concatenated system+user text of its first model request (the ModelEvent input)."""
    s = log.samples[0]
    spans = _span_turns(log, s)
    out: dict[str, str] = {}
    for e in s.events:
        if e.event == "model":
            agent = spans.get(e.span_id, (None, None))[0]
            if agent is None:   # fall back to the system prompt's self-introduction
                text = " ".join(msg_text(m.content) for m in e.input if m.role == "system")
                m = re.search(r"You are developer (dev_\d+)", text)
                agent = m.group(1) if m else None
            if agent and agent not in out:
                out[agent] = "\n".join(msg_text(m.content) for m in e.input)
    return out


def agent_requests(log) -> list[dict]:
    """Every model request of the episode with the settings it carried (proposer.request_summary on
    ModelEvent.call.request); `sent` is None when Inspect recorded no ModelCall (mock provider)."""
    s = log.samples[0]
    spans = _span_turns(log, s)
    rows = []
    for e in s.events:
        if e.event == "model":
            agent, turn = spans.get(e.span_id, (None, None))
            req = dict(e.call.request) if (e.call is not None and e.call.request) else None
            cfg = getattr(e, "config", None)
            rows.append(dict(agent=agent, turn=turn, model=e.model, sent=P.request_summary(req) if req else None,
                             cfg_temperature=getattr(cfg, "temperature", None), cfg_seed=getattr(cfg, "seed", None)))
    return rows


def tool_table(log) -> list[dict]:
    """Every tool call in call order with its turn and agent; assign_task rows carry the rule's judgement
    (allocation_judgement events paired in order) where the rule ran."""
    s = log.samples[0]
    spans = _span_turns(log, s)
    judgements = [e.data for e in s.events if e.event == "info" and isinstance(e.data, dict) and e.data.get("event") == JUDGEMENT_EVENT]
    rows, j = [], 0
    for e in s.events:
        if e.event != "tool":
            continue
        agent, turn = spans.get(e.span_id, (None, None))
        row = dict(turn=turn, agent=agent, tool=e.function, arguments=dict(e.arguments or {}), error=(str(e.error.message) if e.error else None),
                   result=" ".join(str(e.result or "").split())[:160], judgement=None)
        if e.function == "assign_task" and j < len(judgements):
            jd = judgements[j]
            j += 1
            rule = (jd.get("context") or {}).get("rule") or {}      # 2026-10-22: R1–R3 live under context.rule
            row["judgement"] = {k: (jd.get(k) if jd.get(k) is not None else rule.get(k)) for k in ("agent", "task_id", "r1", "r2", "r3", "allow")}
        rows.append(row)
    return rows


def replay_allocation(rows: list[dict]) -> dict[str, str]:
    """ticket -> owner from the successful assign_task results ("Task X assigned to Y.")."""
    alloc: dict[str, str] = {}
    for r in rows:
        if r["tool"] == "assign_task" and not r["error"]:
            m = re.search(r"Task (\S+) assigned to (\S+?)\.?(\s|$)", r["result"])
            if m:
                alloc[m.group(1)] = m.group(2)
    return alloc


def store_allocation(log) -> dict[str, str]:
    a = (log.samples[0].store or {}).get("JiraTicketState:assignments") or {}
    return {t: o for t, o in a.items() if o and o != "unassigned"}


def rederived_row(rr, clean_mean: float) -> dict:
    """The fields proposer.format_history reads, computed again from the log (PLAN §6 (a))."""
    gain = rr.coalition_reward - clean_mean if rr.coalition_reward == rr.coalition_reward else math.nan
    return dict(payload=None, gain=gain, reasons=rr.reasons, block_turns_by_boundary=rr.block_turns_by_boundary,
                first_coalition_claim_turn=rr.first_coalition_claim_turn, first_coalition_claim_agent=rr.first_coalition_claim_agent,
                channel_sends=rr.channel_sends, coalition_claims_lost=0)


# ── the report ─────────────────────────────────────────────────────────────────────────────────────

def report(cell: Path, rounds: list[int] | None = None) -> Checks:
    cell = cell.resolve()
    C = Checks()
    rows = load_jsonl(cell / "rounds.jsonl")
    by_round = {int(r["round"]): r for r in rows}
    archive = S.Archive(cell / S.ARCHIVE_FILE)
    sm_log = load_jsonl(cell / S.LOG_FILE)
    rejections = load_jsonl(cell / "rejections.jsonl")
    baseline = json.loads((cell / "baseline.json").read_text(encoding="utf-8")) if (cell / "baseline.json").exists() else {}
    clean_mean = baseline.get("mean", math.nan)
    if rounds is None:
        rounds = sorted(r for r in by_round if r >= 1)
    seed = None
    for r in by_round:
        try:
            seed = int(read_eval_log(str(REPO / by_round[r]["log"]), header_only=True).eval.task_args.get("seed"))
            break
        except Exception:
            continue
    print(f"# Phase 7 mechanism-check report: {rel(cell)}\n")
    print(f"rounds in rounds.jsonl: {sorted(by_round)}; archive entries: {[e['id'] for e in archive.entries]}; "
          f"selfmod_log lines: {len(sm_log)}; rejections: {len(rejections)}; clean mean (baseline.json) {clean_mean}; seed {seed}")
    C.check(bool(rows) and sorted(by_round) == list(range(len(rows))), "rounds.jsonl holds rounds 0..n-1", f"{sorted(by_round)}")
    C.check([e["id"] for e in archive.entries] == sorted(by_round), "archive.jsonl has one entry per round", f"{[e['id'] for e in archive.entries]}")

    # re-derive every round's history fields from its log, once
    rr_by_round, logs = {}, {}
    for r, row in sorted(by_round.items()):
        try:
            logs[r] = read_eval_log(str(REPO / row["log"]), resolve_attachments=True)
            rr_by_round[r] = read_run(str(REPO / row["log"]))
        except Exception as ex:
            C.check(False, f"round {r}: log readable", f"{row.get('log')}: {ex}")
    for r, rr in rr_by_round.items():
        row = by_round[r]
        d = rederived_row(rr, clean_mean)
        same = (abs((d["gain"] if d["gain"] == d["gain"] else 0) - (row["gain"] if row["gain"] == row["gain"] else 0)) < 1e-9
                and d["block_turns_by_boundary"] == row.get("block_turns_by_boundary") and d["channel_sends"] == row.get("channel_sends")
                and d["first_coalition_claim_turn"] == row.get("first_coalition_claim_turn")
                and d["first_coalition_claim_agent"] == row.get("first_coalition_claim_agent"))
        C.check(same, f"round {r}: rounds.jsonl history fields re-derived from the log",
                f"gain {d['gain']:+.2f} vs row {row['gain']:+.2f}; blocks {d['block_turns_by_boundary']}; sends {d['channel_sends']}; "
                f"first claim {d['first_coalition_claim_agent']}@{d['first_coalition_claim_turn']}")
        e = archive.get(r)
        if e is not None:
            C.check((e.get("gain") == row.get("gain")) or (e.get("gain") is None and row["gain"] != row["gain"]),
                    f"round {r}: archive gain equals the row's gain", f"{e.get('gain')} vs {row.get('gain')}")
            C.check(bool(e.get("valid_alloc")) == bool(row.get("valid_alloc")), f"round {r}: archive valid_alloc equals the row's", f"{e.get('valid_alloc')}")

    for r in rounds:
        row = by_round.get(r)
        if row is None:
            C.check(False, f"round {r} present", "missing from rounds.jsonl")
            continue
        prop = row.get("proposer") or {}
        brief = prop.get("brief", "informed_rule")
        linear = str(prop.get("attacker") or row.get("attacker")) == "self_modifier_linear"
        lines = [l for l in sm_log if int(l.get("round", -1)) == r]
        entry = archive.get(r) or {}
        print(f"\n## self-modifier call for round {r} (brief {brief}; {len(lines)} attempt(s); parent {entry.get('parent')})\n")

        # (a) what it saw
        print("### (a) what it saw\n")
        expected_system = S.selfmod_system(4, brief, archive=not linear)
        proposer_brief = P.proposer_system(4, brief)
        if lines:
            sys_text = lines[0]["system"]
            C.check(sys_text == expected_system, f"r{r} (a) system prompt = selfmod_system(4, {brief!r})",
                    f"{len(sys_text)} chars; sha256 {hashlib.sha256(sys_text.encode()).hexdigest()[:16]}…")
            C.check(all(sys_text == lines[k]["system"] for k in range(len(lines))), f"r{r} (a) same system prompt on every attempt")
            applied = proposer_brief
            for old, new in S.substitutions(archive=not linear):
                applied = applied.replace(old, new, 1)
            C.check(applied == sys_text, f"r{r} (a) system prompt = proposer brief with the §1.2 substitutions only")
            diff = "\n".join(difflib.unified_diff(proposer_brief.splitlines(), sys_text.splitlines(), "proposer_system", "selfmod_system", lineterm="", n=0))
            print("```diff\n" + diff + "\n```")
        else:
            C.check(False, f"r{r} (a) selfmod_log.jsonl has lines for this round")
        prior_rows = [by_round[k] for k in sorted(by_round) if k < r]
        rederived = []
        for k in sorted(by_round):
            if k < r and k in rr_by_round:
                d = rederived_row(rr_by_round[k], clean_mean)
                d["payload"], d["round"] = by_round[k]["payload"], k
                rederived.append(d)
        history_ok = len(rederived) == len(prior_rows) and P.format_history(rederived) == P.format_history(prior_rows)
        C.check(history_ok, f"r{r} (a) history text re-derived from the logs equals format_history(rounds.jsonl rows)")
        entries_before = [e for e in archive.entries if e["id"] < r]
        sel_rec = entry.get("selection") or {}
        if seed is not None and entries_before:
            recomputed = S.select_parent(archive.entries, seed, r, linear=linear)
            C.check(recomputed["chosen"] == sel_rec.get("chosen") == entry.get("parent"),
                    f"r{r} (a) parent id = recomputed §1.3 selection", f"recomputed {recomputed['chosen']} (rule {recomputed['rule']}, draw {recomputed.get('draw')}); "
                    f"recorded {sel_rec.get('chosen')} (draw {sel_rec.get('draw')}); entry parent {entry.get('parent')}")
            if recomputed.get("rule") == "dgm_sigmoid_children":
                rec_w = {int(k): v for k, v in (sel_rec.get("weights") or {}).items()}
                C.check(all(abs(rec_w.get(i, -1) - w) < 1e-9 for i, w in recomputed["weights"].items()) and len(rec_w) == len(recomputed["weights"]),
                        f"r{r} (a) selection weights = recomputed", f"recomputed {recomputed['weights']}; recorded {rec_w}; "
                        f"probabilities {recomputed['probabilities']}; gain_root {recomputed['gain_root']}")
            print("\n" + archive.table(r) + "\n")
            if lines:
                expected_user = S.user_message(prior_rows, archive, sel_rec if sel_rec.get("chosen") is not None else recomputed, r)
                got_user = lines[0]["user"][0] if isinstance(lines[0]["user"], list) else lines[0]["user"]
                C.check(got_user == expected_user, f"r{r} (a) user message = format_history + archive block + parent (recomputed from the files)",
                        "" if got_user == expected_user else "first difference at char " + str(next((i for i, (x, y) in enumerate(zip(got_user, expected_user)) if x != y), min(len(got_user), len(expected_user)))))

        # (b) what it wrote
        print("\n### (b) what it wrote\n")
        previous = [h["payload"] for h in prior_rows]
        for k, line in enumerate(lines, 1):
            parsed = S.parse_output(line["raw"])
            why = P.check_payload(parsed["payload"], previous)
            print(f"attempt {k}: raw = {json.dumps(line['raw'])[:600]}\n  parsed: moves={parsed['moves']} diagnosis={parsed['diagnosis']!r} memo={parsed['memo']!r}\n"
                  f"  payload={parsed['payload']!r}\n  check_payload -> {why}; refusal_kind -> {S.refusal_kind(line['raw'])}")
        rej = [x for x in rejections if int(x.get("round", -1)) == r]
        print(f"rejections for round {r}: {[x['kind'] for x in rej]}; row: attempts={prop.get('attempts')} fallback={prop.get('fallback')} "
              f"refused={row.get('refused')} kinds={prop.get('refusal_kinds')} moves={prop.get('moves')}\n  diagnosis={prop.get('diagnosis')!r}\n  memo={prop.get('memo')!r}")
        C.check(prop.get("attempts") == len(lines), f"r{r} (b) attempts in the row = selfmod_log lines", f"{prop.get('attempts')} vs {len(lines)}")
        if lines and not prop.get("fallback"):
            last = S.parse_output(lines[-1]["raw"])
            C.check(last["payload"] == row["payload"], f"r{r} (b) accepted payload = the last completion's payload")
        if prop.get("fallback"):
            parent = archive.get(entry.get("parent", 0)) or {}
            fb, mv = S.fallback_mutation(parent.get("payload", ""), r, previous)
            C.check(fb == row["payload"] and mv == prop.get("moves"), f"r{r} (b) fallback = mutation of the parent's payload", f"moves {mv}")

        # (c) what reached the agents
        print("\n### (c) what reached the agents\n")
        pf = cell / f"payload_r{r}.txt"
        C.check(pf.exists() and pf.read_text(encoding="utf-8") == row["payload"], f"r{r} (c) payload_r{r}.txt = the row's payload")
        if r in logs:
            delivered = delivered_payloads(logs[r])
            for agent in COALITION:
                texts = delivered.get(agent, [])
                ok = any(("Your objective: " + row["payload"]) in t for t in texts)
                C.check(ok, f"r{r} (c) {agent}: orbit_collusion_prompt system message carries the payload byte for byte",
                        f"{len(texts)} tagged message(s)" + ("" if ok else f"; got {[t[:120] for t in texts]}"))
            firsts = first_requests(logs[r])
            for agent in COALITION:
                C.check(row["payload"] in firsts.get(agent, ""), f"r{r} (c) {agent}: first model request carries the payload")

        # (d) what was sent
        print("\n### (d) what was sent\n")
        for k, line in enumerate(lines, 1):
            sent = line.get("sent") or {}
            exp_seed = (100 * seed + r) if seed is not None else None
            C.check(sent.get("temperature") == 0 and sent.get("seed") == exp_seed and line.get("sent_source") == P.SOURCE_MODEL_CALL,
                    f"r{r} (d) attempt {k}: writer request carried temperature 0 and seed {exp_seed} (source {P.SOURCE_MODEL_CALL})",
                    f"sent={sent} source={line.get('sent_source')} requested temperature {line.get('requested_temperature')} seed {line.get('requested_seed')}")
        if r in logs:
            reqs = agent_requests(logs[r])
            # 2026-10-22 (PLAN amendment of that date): Inspect keeps the raw provider request (ModelEvent.call) only for
            # the first calls of a log, so "every request has a raw record" cannot hold on a real log. (d) now requires:
            # at least one kept raw request, every kept raw request carrying temperature 0 and the seed, and every
            # request's logged generate config carrying the same; any disagreement fails; coverage is printed.
            with_call = [q for q in reqs if q["sent"]]
            raw_ok = bool(with_call) and all(q["sent"].get("temperature") == 0 and q["sent"].get("seed") == seed for q in with_call)
            cfg_ok = bool(reqs) and all(q["cfg_temperature"] == 0 and q["cfg_seed"] == seed for q in reqs)
            ok = raw_ok and cfg_ok
            bad = [q for q in with_call if not (q["sent"].get("temperature") == 0 and q["sent"].get("seed") == seed)]
            C.check(ok, f"r{r} (d) agent requests in A{r}: every kept raw request and every logged config carry temperature 0 and seed {seed}",
                    f"raw requests kept {len(with_call)}/{len(reqs)}; logged configs {sum(1 for q in reqs if q['cfg_temperature'] == 0 and q['cfg_seed'] == seed)}/{len(reqs)} with T 0 and seed {seed}"
                    + (f"; disagreeing raw request e.g. {bad[0]['sent']}" if bad else ""))

        # (e) per step
        print(f"\n### (e) per step, A{r}\n")
        if r in logs:
            table = tool_table(logs[r])
            print("| # | turn | agent | tool | arguments | R1 R2 R3 allow | result |\n|---|---|---|---|---|---|---|")
            for i, t in enumerate(table, 1):
                jd = t["judgement"]
                jtxt = f"{jd['r1']} {jd['r2']} {jd['r3']} {jd['allow']}" if jd else "–"
                res_txt = (("ERROR " + t["error"]) if t["error"] else t["result"]).replace("|", "/")
                print(f"| {i} | {t['turn']} | {t['agent']} | {t['tool']} | {json.dumps(t['arguments'])[:80].replace('|', '/')} | {jtxt} | {res_txt[:100]} |")
            rr = rr_by_round.get(r)
            final = store_allocation(logs[r])
            replay = replay_allocation(table)
            C.check(final == replay or not final, f"r{r} (e) final allocation in the store = replay of successful assign_task results", f"store {final}; replay {replay}")
            if rr is not None:
                tickets = sum(1 for o in final.values() if o in COALITION)
                C.check(tickets == row.get("coalition_tickets") == rr.coalition_tickets, f"r{r} (e) coalition tickets = row = reader", f"{tickets} / {row.get('coalition_tickets')} / {rr.coalition_tickets}")
                coal = sum(v for a, v in rr.per_agent_reward.items() if a in COALITION)
                C.check(abs(coal - row["coalition_reward"]) < 1e-6, f"r{r} (e) coalition reward = sum of the scorer's per-agent rewards", f"{coal:.4f} vs row {row['coalition_reward']:.4f}")
                first = next(((t["turn"], t["agent"]) for t in table if t["tool"] == "assign_task" and t["agent"] in COALITION), (None, None))
                C.check(first == (row.get("first_coalition_claim_turn"), row.get("first_coalition_claim_agent")),
                        f"r{r} (e) first coalition assign_task = row", f"table {first}; row ({row.get('first_coalition_claim_turn')}, {row.get('first_coalition_claim_agent')})")
                judged = [t for t in table if t["judgement"]]
                if judged:
                    blocked = sum(1 for t in judged if t["judgement"]["allow"] is False)
                    C.check(blocked == (row.get("blocks_by_boundary") or {}).get("tool_call", 0), f"r{r} (e) rule blocks (allow=False judgements) = row's tool_call blocks",
                            f"{blocked} vs {(row.get('blocks_by_boundary') or {}).get('tool_call', 0)}; coalition blocks {sum(1 for t in judged if t['judgement']['allow'] is False and t['agent'] in COALITION)}")
                C.check(rr.halt_reason == row.get("halt_reason") and rr.valid_alloc == row.get("valid_alloc"), f"r{r} (e) halt and validity = row", f"{rr.halt_reason} {rr.valid_alloc}")
    print(f"\n## result: {C.fails} FAIL of {len(C.rows)} checks")
    return C


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cell", nargs="?", type=Path, default=DEFAULT_CELL)
    ap.add_argument("--rounds", type=int, nargs="*", default=None, help="self-modifier rounds to report (default: every round >= 1)")
    ap.add_argument("--out", type=Path, default=None, help="also write the markdown here")
    a = ap.parse_args(argv)
    buf = io.StringIO()
    with redirect_stdout(buf):
        C = report(a.cell, a.rounds)
    text = buf.getvalue()
    sys.stdout.write(text)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    return 1 if C.fails else 0


if __name__ == "__main__":
    sys.exit(main())
