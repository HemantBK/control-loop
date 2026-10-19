"""Tables for paired Jira contrasts, with a valid/total column and one line per
excluded episode.

Two inputs:

  python -m adaptive_control.replication_tables report results/g0_gpt4o/replication.json
      Re-renders the contrasts in a scripts/replicate_jira.py report. Each excluded
      pair gets one line saying which arm failed and why (which agents never
      called submit, how many tickets were allocated).

  python -m adaptive_control.replication_tables pair LEFT_LOG_DIR RIGHT_LOG_DIR [label]
      Pairs two Inspect logs epoch by epoch (right minus left) using the same
      definitions as ORBIT's paired scorer: coalition = dev_0 + dev_1 reward, an
      episode is valid only if every agent called submit. Used for the clean-vs-
      clean noise checks that the replication script cannot run (other num_tasks).

Definitions match scripts/replicate_jira.py: coalition delta is the right arm's
(dev_0 + dev_1) minus the left arm's, paired by epoch; a pair is excluded when
either episode did not finish all agents ("runtime_did_not_finish_all_agents").
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

COALITION = ("dev_0", "dev_1")


def _plain(path: str) -> str:
    for prefix in ("file://", "file:"):
        if path.startswith(prefix):
            return path[len(prefix):]
    return path


def episode_rows(log_path: str) -> dict[int, dict]:
    """Per-epoch facts from one Inspect log: rewards, completion, who never submitted."""
    log = read_eval_log(_plain(log_path))
    rows: dict[int, dict] = {}
    for s in log.samples or []:
        jt = s.scores.get("jira_ticket_scorer") if s.scores else None
        md = (jt.metadata or {}) if jt else {}
        rewards = md.get("per_agent_reward") or {}
        agents = sorted(rewards)
        slot: dict[str, str] = {}
        for e in s.events:
            if e.event == "span_begin" and e.type == "agent":
                slot[e.id] = e.name
        submitted = {slot.get(e.span_id) for e in s.events
                     if e.event == "tool" and e.function == "submit"}
        unsubmitted = [a for a in agents if a not in submitted]
        coalition = sum(rewards.get(a, 0.0) for a in COALITION)
        rows[s.epoch] = dict(
            epoch=s.epoch,
            coalition=round(coalition, 2),
            outsiders=round(sum(v for a, v in rewards.items() if a not in COALITION), 2),
            team=round(sum(rewards.values()), 2),
            tasks_done=md.get("tasks_done"),
            total_tasks=md.get("total_tasks"),
            unsubmitted=unsubmitted,
            finished_all_agents=not unsubmitted and bool(agents),
            error=str(s.error.message)[:80] if s.error else None,
        )
    return rows


def _why(arm: str, row: dict | None) -> str:
    if row is None:
        return f"{arm}: no sample for this epoch"
    if row["error"]:
        return f"{arm}: sample error ({row['error']})"
    if not row["finished_all_agents"]:
        who = ", ".join(row["unsubmitted"]) or "unknown agents"
        return (f"{arm} did not finish all agents ({who} never called submit; "
                f"{row['tasks_done']}/{row['total_tasks']} tickets allocated)")
    return f"{arm}: excluded by the script for an unrecorded reason"


def pair_logs(left_dir: str, right_dir: str, label: str,
              left_name: str = "left", right_name: str = "right") -> dict:
    left = episode_rows(list_eval_logs(left_dir)[0].name)
    right = episode_rows(list_eval_logs(right_dir)[0].name)
    pairs = []
    for epoch in sorted(set(left) | set(right)):
        l, r = left.get(epoch), right.get(epoch)
        reasons = []
        if l is None or not l["finished_all_agents"] or l["error"]:
            reasons.append(_why(left_name, l))
        if r is None or not r["finished_all_agents"] or r["error"]:
            reasons.append(_why(right_name, r))
        pairs.append(dict(epoch=epoch, valid=not reasons, reasons=reasons,
                          delta=(r["coalition"] - l["coalition"]) if (l and r) else None,
                          left=l, right=r))
    return dict(label=label, pairs=pairs)


def contrast_from_report(report: dict, name: str) -> dict:
    """One contrast from a replicate_jira.py report, with excluded episodes diagnosed."""
    analysis = report["analysis"][name]
    arms = report["blocks"][0]["arms"]
    cache: dict[str, dict[int, dict]] = {}
    pairs = []
    for p in analysis["pairs"]:
        reasons = []
        for reason in p.get("reasons") or []:
            arm = reason.split(":", 1)[0]
            if arm not in cache:
                cache[arm] = episode_rows(arms[arm]["log"])
            reasons.append(_why(arm, cache[arm].get(p["epoch"])))
        pairs.append(dict(epoch=p["epoch"], valid=p["valid"], reasons=reasons,
                          delta=p["deltas"]["coalition"] if p["valid"] else None))
    return dict(label=name, pairs=pairs)


def render(contrasts: list[dict], title: str) -> str:
    out = [f"### {title}", "",
           "| contrast | valid/total | mean | min | max | sd | deltas |",
           "|---|---|---|---|---|---|---|"]
    excluded = []
    for c in contrasts:
        d = [p["delta"] for p in c["pairs"] if p["valid"]]
        n = len(c["pairs"])
        if d:
            out.append(f"| {c['label']} | {len(d)}/{n} | {st.mean(d):+.2f} | {min(d):+.2f} | "
                       f"{max(d):+.2f} | {st.pstdev(d):.2f} | {', '.join(f'{x:+.1f}' for x in d)} |")
        else:
            out.append(f"| {c['label']} | 0/{n} | – | – | – | – | – |")
        for p in c["pairs"]:
            if not p["valid"]:
                excluded.append(f"- {c['label']}, epoch {p['epoch']}: " + "; ".join(p["reasons"]))
    out.append("")
    out.append("Excluded episodes:" if excluded else "Excluded episodes: none")
    out.extend(excluded)
    return "\n".join(out)


def main(argv: list[str]) -> None:
    if not argv or argv[0] not in ("report", "pair"):
        sys.exit(__doc__)
    if argv[0] == "report":
        report = json.loads(Path(argv[1]).read_text())
        names = argv[2:] or ["clean_clean_undefended", "attack_undefended",
                             "clean_clean_defended", "attack_defended", "defense_gain_reduction"]
        contrasts = [contrast_from_report(report, n) for n in names if n in report["analysis"]]
        print(render(contrasts, f"{report['model']} — {Path(argv[1]).parent.name} ({report['status']})"))
    else:
        left, right = argv[1], argv[2]
        label = argv[3] if len(argv) > 3 else f"{Path(right).name} minus {Path(left).name}"
        c = pair_logs(left, right, label, Path(left).name, Path(right).name)
        print(render([c], label))
        for p in c["pairs"]:
            l, r = p["left"], p["right"]
            print(f"  epoch {p['epoch']}: {Path(left).name} coalition={l['coalition'] if l else None} "
                  f"{Path(right).name} coalition={r['coalition'] if r else None} valid={p['valid']}")


if __name__ == "__main__":
    main(sys.argv[1:])
