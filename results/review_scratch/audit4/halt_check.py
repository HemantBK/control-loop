"""ORBIT's own completion criterion (halt_reason=all_agents_submitted in the 'Experiment complete' info event)
versus results.py's valid_submit, for every episode of the given log dirs."""
import sys
from inspect_ai.log import read_eval_log
from adaptive_control.results import latest_log, read_run
rows = []
for d in sys.argv[1:]:
    lp = latest_log(d); log = read_eval_log(lp)
    for s in sorted(log.samples or [], key=lambda x: x.epoch):
        halt = None
        for e in s.events:
            if e.event == "info" and isinstance(e.data, str) and e.data.startswith("Experiment complete"):
                halt = e.data.split("halt_reason=")[-1].strip()
        r = read_run(lp, epoch=s.epoch)
        orbit_finished = (halt == "all_agents_submitted")
        flag = ""
        if r.valid_submit and not orbit_finished: flag = "OVERCOUNT"
        if (not r.valid_submit) and orbit_finished and r.valid_alloc: flag = "UNDERCOUNT"
        print(f"{d} ep{s.epoch} coal={r.coalition_reward:.2f} tk={r.coalition_tickets} valid_alloc={r.valid_alloc} valid_submit={r.valid_submit} halt={halt} {flag}")
