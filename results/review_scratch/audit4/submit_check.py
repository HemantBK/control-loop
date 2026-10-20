"""For every episode in the given log dirs: agents with submit tool events, agents whose
submit actually succeeded (no ToolCallError), and how results.py classified them."""
import sys, glob
from pathlib import Path
from inspect_ai.log import read_eval_log
from adaptive_control.results import latest_log, read_run, _span_turns

def check(d):
    lp = latest_log(d); log = read_eval_log(lp)
    out = []
    for s in sorted(log.samples or [], key=lambda x: x.epoch):
        st = _span_turns(log, s)
        called, ok = set(), set()
        last_turn = max((t for (_, t) in st.values()), default=None)
        nspans = len(st)
        for e in s.events:
            if e.event == "tool" and e.function == "submit":
                ag = st.get(e.span_id, (None, None))[0]
                called.add(ag)
                if e.error is None:
                    ok.add(ag)
        r = read_run(lp, epoch=s.epoch)
        blocked_only = sorted(called - ok)
        out.append((s.epoch, r.coalition_reward, r.coalition_tickets, r.valid_alloc, r.valid_submit, r.unsubmitted, blocked_only, nspans, last_turn))
    return out

if __name__ == "__main__":
    for d in sys.argv[1:]:
        for row in check(d):
            ep, coal, tk, va, vs, unsub, blocked_only, nspans, last = row
            flag = " <-- submit-rule validity relies on a BLOCKED submit" if (vs and blocked_only) else ""
            print(f"{d} ep{ep} coal={coal:.2f} tk={tk} valid_alloc={va} valid_submit={vs} unsubmitted={unsub} blocked_only_submitters={blocked_only} spans={nspans} last_turn={last}{flag}")
