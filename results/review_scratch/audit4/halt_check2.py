"""ORBIT's own completion criterion (halt_reason=all_agents_submitted) versus results.py's valid_submit,
for every episode of every monitor-arm log dir given; robust to unreadable dirs."""
import sys, glob
from inspect_ai.log import read_eval_log
from adaptive_control.results import read_run
over = under = total = 0
for d in sys.argv[1:]:
    files = sorted(glob.glob(d + "/*.eval"))
    if not files:
        print("SKIP no logs", d); continue
    lp = files[-1]
    try:
        log = read_eval_log(lp)
    except Exception as ex:
        print("SKIP unreadable", d, ex); continue
    for s in sorted(log.samples or [], key=lambda x: x.epoch):
        halt = None
        for e in s.events:
            if e.event == "info" and isinstance(e.data, str) and e.data.startswith("Experiment complete"):
                halt = e.data.split("halt_reason=")[-1].strip()
        r = read_run(lp, epoch=s.epoch)
        fin = (halt == "all_agents_submitted")
        total += 1
        flag = ""
        if r.valid_submit and not fin: flag = "OVERCOUNT"; over += 1
        if (not r.valid_submit) and fin and r.valid_alloc: flag = "UNDERCOUNT"; under += 1
        print(f"{d} ep{s.epoch} coal={r.coalition_reward:.2f} tk={r.coalition_tickets} valid_alloc={r.valid_alloc} valid_submit={r.valid_submit} halt={halt} {flag}")
print(f"TOTAL episodes {total} overcount {over} undercount {under}")
