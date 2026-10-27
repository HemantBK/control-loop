#!/bin/bash
# One lane of the cell 733 batch (PLAN Amendment (29)): the supervised session's order, for the episodes in the lane's
# plan.json. Detached on the CPU pod, started by scripts/phase6/cell_batch.py. Markers in the lane dir: SETUP_FAILED,
# DONE_<cid> / FAIL_<cid> (first line: the failure's signature), CAP_REACHED, LANE_END. Step outputs in steps_out/.
#     bash scripts/phase6/cell_lane.sh <lane>
LANE=${1:?lane}
cd "$(dirname "$0")/../.." || exit 1
D=results/phase6_researcharena/batch_733/lanes/$LANE; O=$D/steps_out; mkdir -p $O
LOG=$D/lane.log
run() { local n; n=$(echo "$*" | tr ' ' _); echo "$(date -u +%FT%TZ) step $*" >> $LOG
  P6_LANE=$LANE uv run --frozen --env-file ../.env python scripts/phase6/cell_step.py "$@" > $O/$n.out 2>&1; local rc=$?
  echo "$(date -u +%FT%TZ) step $* rc=$rc" >> $LOG; return $rc; }
sig() {   # the failure signature: the step and the last meaningful line of its output
  local n; n=$(echo "$*" | tr ' ' _)
  echo "$1: $(grep -vE '^\s*$|^---|full output' $O/$n.out | tail -1 | cut -c1-160)"; }
mapfile -t EPS < <(python3 -c "import json;[print(e['cid']) for e in json.load(open('$D/plan.json'))['episodes']]")
end() { wait; echo "$(date -u +%FT%TZ) LANE_END" >> $LOG; touch $D/LANE_END; exit 0; }
# a create can fail on H100 stock ("no longer any instances available"): up to 6 attempts, 2 minutes apart
for try in 1 2 3 4 5 6; do run create && break; [ $try = 6 ] || sleep 120; done
if ! grep -q "rc=0" <(tail -1 $LOG); then sig create > $D/SETUP_FAILED; for c in "${EPS[@]}"; do cp $D/SETUP_FAILED $D/FAIL_$c; done; end; fi
for s in ready driver setup kit harness; do
  if ! run $s; then sig $s > $D/SETUP_FAILED; for c in "${EPS[@]}"; do cp $D/SETUP_FAILED $D/FAIL_$c; done
    run delete; end; fi
done
for i in "${!EPS[@]}"; do
  c=${EPS[$i]}; nxt=${EPS[$((i + 1))]:-"lane ends"}
  ok=1
  for s in iso "dryrun $c" "episode $c" "pull $c"; do
    if ! run $s; then
      if grep -q CAP_REACHED $O/$(echo "$s" | tr ' ' _).out; then grep CAP_REACHED $O/$(echo "$s" | tr ' ' _).out | head -1 > $D/CAP_REACHED; fi
      sig $s > $D/FAIL_$c; ok=0; break
    fi
  done
  if [ $ok = 1 ]; then
    ( run monitor $c && run status $c "$nxt" && touch $D/DONE_$c || { sig monitor $c > $D/FAIL_$c; } ) &
  else
    run status $c "$nxt"
    [ -f $D/CAP_REACHED ] && break
  fi
done
wait
run delete
end
