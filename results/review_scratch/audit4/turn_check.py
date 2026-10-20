"""Compare results._span_turns against the turn field on defense_intervention events, every log under the given roots."""
import sys, glob
from pathlib import Path
from inspect_ai.log import read_eval_log
from adaptive_control.results import _span_turns
tot_ev = tot_mis = 0
bad = []
for root in sys.argv[1:]:
    for lp in sorted(glob.glob(f"{root}/**/*.eval", recursive=True)):
        try:
            log = read_eval_log(lp)
        except Exception as ex:
            print("unreadable", lp, ex); continue
        for s in log.samples or []:
            st = _span_turns(log, s)
            # map span -> turn; defense events carry turn + agent; find enclosing agent span via span_id
            n = m = 0
            for e in s.events:
                if e.event == "info" and isinstance(e.data, dict) and e.data.get("event") == "defense_intervention":
                    t = e.data.get("turn")
                    sp = st.get(e.span_id)
                    if sp is None or not isinstance(t, int):
                        continue
                    n += 1
                    if sp[1] != t:
                        m += 1
            tot_ev += n; tot_mis += m
            if m:
                bad.append((lp, s.epoch, n, m, (log.eval.task_args or {}).get("ordering")))
print("events", tot_ev, "mismatches", tot_mis)
for b in bad[:30]:
    print(b)
