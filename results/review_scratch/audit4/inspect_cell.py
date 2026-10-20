"""Dump per-episode facts from an .eval log directory: per-agent rewards, final owners,
tool timeline with plan-aware turn, judge decisions on assign_task, submits."""
import sys, json, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from inspect_ai.log import read_eval_log
from adaptive_control.results import latest_log, _span_turns

def dump(log_dir, verbose=True):
    lp = latest_log(log_dir)
    log = read_eval_log(lp)
    print("==", log_dir, "status", log.status, "ordering", (log.eval.task_args or {}).get("ordering"),
          "defense", (log.eval.task_args or {}).get("defense_preset"), "coalition", (log.eval.task_args or {}).get("coalition_agents"),
          "judge_seed", (log.eval.task_args or {}).get("judge_seed"), "greedy", (log.eval.task_args or {}).get("greedy_control"))
    for s in sorted(log.samples or [], key=lambda x: x.epoch):
        jt = s.scores.get("jira_ticket_scorer")
        md = jt.metadata or {}
        pa = md.get("per_agent_reward")
        st = _span_turns(log, s)
        timeline = []
        owner = {}
        judged = []
        for e in s.events:
            if e.event == "tool":
                ag, t = st.get(e.span_id, (None, None))
                res = str(e.result or "")
                args = e.arguments or {}
                timeline.append((t, ag, e.function, args.get("task_id") or args.get("message") or "", res[:60]))
                m = re.match(r"Task (\S+) assigned to (\S+)\.", res)
                if m: owner[m.group(1)] = m.group(2)
            if e.event == "info" and isinstance(e.data, dict) and e.data.get("event") == "defense_intervention":
                d = e.data
                judged.append((d.get("turn"), d.get("agent"), d.get("boundary"), d.get("allow"), str(d.get("tool_name") or d.get("tool") or "")[:20], str(d.get("reason") or "")[:80]))
        print(f" epoch {s.epoch} err={s.error is not None} rewards={pa} tasks_done={md.get('tasks_done')}/{md.get('total_tasks')} owners={owner}")
        if verbose:
            for t in timeline:
                if t[2] in ("assign_task", "submit", "secret_channel", "view_tasks"):
                    print("   ", t)
            blocks = [j for j in judged if j[3] is False]
            print("   blocks:", len(blocks))
            for j in judged:
                if j[2] == "tool_call":
                    print("   judge", j)
    return log

if __name__ == "__main__":
    verbose = "-q" not in sys.argv
    for d in sys.argv[1:]:
        if d == "-q": continue
        dump(d, verbose)
