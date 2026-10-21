"""Phase 4 step 3: mechanism check of the ControlArena adapter (phases/phase4_controlarena/PLAN.md §10).

    uv run python -m control_loop.adapters.controlarena.mechanism_check --backend mock
    uv run --env-file ../.env python -m control_loop.adapters.controlarena.mechanism_check --backend real

Per backend: one honest and one red-team episode of data_poisoning under trusted_monitoring at
--limit 1 (the red team uses `proposer_attack_policy` with the round-0 paragraph, STATIC_PAYLOAD).
Then, from the logs:

  1. instruction delivered: the red-team policy's provider request (ModelEvent.call.request, what the
     model actually received) contains the strategy header and paragraph; the honest one does not.
  2. monitor coverage: every step with a tool call carries a parsed `suspicion_score`.
  3. reader = log: main/side success, per-step suspicion (from the monitor's own solver-span call,
     regex-parsed here), step metadata, EoT score and halt reason from `reader` equal the values
     read straight from the sample JSON inside the .eval zip (no Inspect reader); and the step
     metadata was not overwritten by the end-of-trajectory scorer (PLAN §10.5).

Mock backend only: one `RedTeamPolicy.propose` call with the mock as proposer (its output is not
JSON, so this exercises re-prompt and fallback), plus the observation row it would see.
Writes results/phase4_controlarena/mechanism_check/<backend>/{honest,redteam}/ and check.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import zipfile
from pathlib import Path

from control_loop.adapters import controlarena as ca
from control_loop.paths import rel, write_json

OUT = ca.REPO / "results" / "phase4_controlarena" / "mechanism_check"
MODELS = {"mock": ("cl_mock/dp", "cl_mock/dp"),
          "real": ("anthropic/claude-opus-5-5", "anthropic/claude-sonnet-4-6")}  # ControlArena 20.1.0 defaults
SEED = 733


def raw_sample(log_path: str) -> dict:
    import inspect_ai.log  # noqa: F401  registers the zip codec Inspect writes .eval members with
    with zipfile.ZipFile(log_path) as z:
        names = sorted(n for n in z.namelist() if n.startswith("samples/") and n.endswith(".json"))
        assert len(names) == 1, names
        return json.loads(z.read(names[0]))


def _deref(obj, attachments: dict):
    """Replace Inspect's `attachment://<hash>` strings with the stored text."""
    if isinstance(obj, str) and obj.startswith("attachment://"):
        return attachments.get(obj[len("attachment://"):], obj)
    if isinstance(obj, list):
        return [_deref(x, attachments) for x in obj]
    if isinstance(obj, dict):
        return {k: _deref(v, attachments) for k, v in obj.items()}
    return obj


def policy_requests(raw: dict) -> list[dict]:
    """Provider requests of the policy's model calls (the ones that offered the submit tool), as
    sent: Inspect 0.3.263 condenses events, so the request's message list is rebuilt from the
    sample's `events_data.calls` pool (`call.call_refs` = [start, end) ranges, `call.call_key` =
    the request field) and attachment refs are resolved."""
    pool = (raw.get("events_data") or {}).get("calls") or []
    att = raw.get("attachments") or {}
    out = []
    for ev in raw.get("events", []):
        if ev.get("event") != "model":
            continue
        if not any(t.get("name") == "submit" for t in ev.get("tools") or []):
            continue
        call = ev.get("call") or {}
        req = dict(call.get("request") or {})
        if call.get("call_refs"):
            req[call.get("call_key") or "messages"] = [m for a, b in call["call_refs"] for m in pool[a:b]]
        out.append(_deref(req, att))
    return out


def system_text(req: dict) -> str:
    """The system prompt as the provider received it (Anthropic: top-level `system`; mock and
    OpenAI-style: the system-role message)."""
    sys_ = req.get("system")
    if isinstance(sys_, list):
        return "\n".join(b.get("text", "") for b in sys_ if isinstance(b, dict))
    if isinstance(sys_, str):
        return sys_
    return "\n".join(str(m.get("content")) for m in req.get("messages", []) if m.get("role") == "system")


def raw_step_scores(raw: dict) -> list[float | None]:
    """Per-step monitor scores straight from the raw events: the trusted model's calls inside the
    solver span, `<score>` parsed with a plain regex and divided by 10 (basic_monitor's 0-10 range)."""
    att = raw.get("attachments") or {}
    spans = {e["id"]: e for e in raw.get("events", []) if e.get("event") == "span_begin"}

    def in_solver(sid):
        while sid:
            sp = spans.get(sid)
            if sp is None or sp.get("type") == "scorer":
                return False
            if sp.get("type") == "solver":
                return True
            sid = sp.get("parent_id")
        return False

    out = []
    for e in raw.get("events", []):
        if e.get("event") == "model" and e.get("role") == "trusted" and in_solver(e.get("span_id")):
            content = _deref(e["output"]["choices"][0]["message"]["content"], att)
            text = content if isinstance(content, str) else " ".join(
                str(_deref(b.get("text", ""), att)) for b in content if isinstance(b, dict))
            m = re.findall(r"<score>\s*([0-9.]+)\s*</score>", text)
            out.append(float(m[-1]) / 10 if m else None)
    return out


def raw_view(raw: dict) -> dict:
    steps = []
    for m in raw["messages"]:
        if m["role"] != "assistant":
            continue
        md = m.get("metadata") or {}
        steps.append(dict(tool_calls=[tc["function"] for tc in m.get("tool_calls") or []],
                          metadata_score=md.get("suspicion_score"), score_parsed=md.get("score_parsed")))
    sc = raw.get("scores") or {}
    dp = (sc.get("data_poisoning_scorer") or {}).get("value") or {}
    to_b = {"C": True, "I": False}
    return dict(main=to_b.get(dp.get("main_task_success")), side=to_b.get(dp.get("side_task_success")),
                eot=(sc.get("end_of_trajectory_monitor") or {}).get("value"), steps=steps,
                step_monitor_scores=raw_step_scores(raw),
                error=raw.get("error"), limit=raw.get("limit"))


def check_episode(log_path: str, payload: str | None) -> tuple[dict, object]:
    from control_loop.adapters.controlarena.proposer_policy import PAYLOAD_HEADER
    from control_loop.adapters.controlarena.reader import read_log

    raw = raw_sample(log_path)
    rv = raw_view(raw)
    (r,) = read_log(log_path)
    reqs = policy_requests(raw)
    systems = [system_text(q) for q in reqs]
    if payload is None:  # honest: no strategy paragraph, no side task in the system prompt
        delivered = bool(systems) and all(PAYLOAD_HEADER not in s and "the password is" not in s for s in systems)
    else:
        delivered = bool(systems) and all(PAYLOAD_HEADER + payload in s for s in systems)
    tool_steps = [s for s in r.steps if s.tool_calls]
    covered = bool(tool_steps) and all(s.suspicion_score is not None and s.score_parsed for s in tool_steps)
    match = dict(
        main=rv["main"] == r.main_task_success,
        side=rv["side"] == r.side_task_success,
        eot=rv["eot"] == r.eot_suspicion,
        step_scores=rv["step_monitor_scores"] == [s.suspicion_score for s in r.steps if s.tool_calls],
        step_metadata=[s["metadata_score"] for s in rv["steps"]] == [s.metadata_score for s in r.steps],
        metadata_not_overwritten=not any(s.metadata_overwritten for s in r.steps),
        halt=(r.halt_reason == "error") == bool(rv["error"]) and (r.halt_reason.startswith("limit")) == bool(rv["limit"]),
    )
    return dict(log=log_path, policy_calls=len(reqs), instruction_delivered=delivered,
                policy_system_prompt_tail=[s[-700:] for s in systems],
                monitor_scored_every_step=covered, reader_matches_raw=match, raw=rv), r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=list(MODELS), required=True)
    args = ap.parse_args()
    from control_loop.adapters.controlarena import mock_dp  # noqa: F401  (cl_mock for the proposer smoke)
    from control_loop.adapters.controlarena.proposer_policy import STATIC_PAYLOAD, RedTeamPolicy
    from control_loop.adapters.controlarena.reader import control_metrics, cost_usd, step_table

    untrusted, trusted = MODELS[args.backend]
    out = OUT / args.backend
    red = RedTeamPolicy(out / "redteam", proposer_model="cl_mock/dp", seed=SEED)
    payload_file = red.write_payload(0, STATIC_PAYLOAD)

    h_log = ca.run_eval(out / "honest", untrusted, SEED, ["-T", "mode=honest"], None, trusted)
    a_log = ca.run_eval(out / "redteam", untrusted, SEED, [], payload_file, trusted)

    h_chk, h = check_episode(h_log, None)
    a_chk, a = check_episode(a_log, STATIC_PAYLOAD)
    metrics = control_metrics(h_log, a_log)
    # requested_seed is `inspect eval --seed`; sent_settings is what the provider requests carried
    # (the Anthropic path sends no seed, audit_codex X8). Reports before 2026-10-21 call it `seed`.
    report = dict(backend=args.backend, untrusted=untrusted, trusted=trusted, requested_seed=SEED,
                  sent_settings=dict(honest=ca.sent_settings(h_log), redteam=ca.sent_settings(a_log)),
                  honest=h_chk, redteam=a_chk, control_metrics=metrics,
                  cost_usd=round(cost_usd([h, a]), 4),
                  usage={"honest": h.usage, "redteam": a.usage},
                  redteam_observation=red.observe(0, STATIC_PAYLOAD, a))
    if args.backend == "mock":
        report["proposer_smoke"] = asyncio.run(red.propose(1))
    write_json(out / "check.json", report)   # repo-relative paths only

    print("\n" + step_table([h, a]) + "\n")
    for k in ("honest", "redteam"):
        c = report[k]
        print(f"{k}: policy calls {c['policy_calls']}, instruction delivered {c['instruction_delivered']}, "
              f"monitor scored every step {c['monitor_scored_every_step']}, reader==raw {c['reader_matches_raw']}")
    print("control metrics:", json.dumps(metrics, default=str))
    print(f"cost ${report['cost_usd']:.4f}  ->  {rel(out / 'check.json')}")


if __name__ == "__main__":
    main()
