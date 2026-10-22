#!/bin/bash
# p6state.sh <name>: one line, always exit 0. STATE=RUNNING|EXITED rc=N|UNKNOWN; ERR=1 if the log shows a failure marker;
# AGE=seconds since the log last grew; P6PODS=live RunPod pods named p6-* (needs runpodctl); LAST=<last log line>.
# Tracked copy (2026-10-22, audits/RESPONSE.md A8) of the state check the Phase 6 runs used from the session scratch
# directory; unchanged except that the job directory is $JOBS_DIR (default $HOME/jobs, as for p6run.sh) and `stat`
# falls back to the BSD form.
name="${1:?usage: p6state.sh <name>}"; d="${JOBS_DIR:-$HOME/jobs}"; log="$d/$name.log"
if [ -f "$d/$name.pid" ] && kill -0 "$(cat "$d/$name.pid")" 2>/dev/null; then st=RUNNING
elif [ -f "$d/$name.rc" ]; then st="EXITED rc=$(cat "$d/$name.rc")"
else st=UNKNOWN; fi
err=0; grep -qE 'Traceback|LaunchError|RuntimeError|stopped:|CANARY FAIL|no pod could be created|FAIL ' "$log" 2>/dev/null && err=1
mtime=$(stat -c %Y "$log" 2>/dev/null || stat -f %m "$log" 2>/dev/null || date +%s)
age=$(( $(date +%s) - mtime ))
pods=$(runpodctl pod list -o json 2>/dev/null | python3 -c 'import json,sys
try: d=json.load(sys.stdin)
except Exception: d=[]
d=d if isinstance(d,list) else d.get("pods",d.get("data",[]))
print(",".join(p.get("name","?") for p in d if (p.get("name") or "").startswith("p6-")) or "none")')
echo "STATE=$st ERR=$err AGE=${age}s P6PODS=$pods LAST=$(tail -1 "$log" 2>/dev/null | cut -c1-160)"
exit 0
