#!/bin/bash
# Phase 6 re-measure with one automatic retry (owner, 2026-10-24): attempt A in data centres other than US-MO-1; if its
# pod fails to come up (the create or ready step fails, 10-minute rule), one more pod right away (attempt B, US-MO-1
# allowed), each with its own watchdog. Any other failure, or two failed pods: stop and report. Watchdog limits: A $3.16
# (what is left of the $4.50 session cap), B $3.20 (Phase 6 GPU raised to $24).
set -u; cd ${P6_REPO:-/root/control-loop}
BASE=${P6_RM_BASE:-results/phase6_researcharena/fixrun}
start_watchdog() {   # <name> <minutes> <usd> <out dir>
  [ -n "${P6_STUB_RUN:-}" ] && return 0
  local pre="cd $(pwd) && P6_RM_OUT=$4 P6_RM_NAME=$1 P6_RM_RUN_ID=$1 uv run --frozen --env-file ../.env python scripts/phase6/remeasure.py copy >> $4/watchdog_precopy.out 2>&1"
  ( setsid nohup uv run --frozen --env-file ../.env python -m control_loop.adapters.researcharena.session_watchdog $1 $2 $3 $4/watchdog.log \
      --pre-delete-cmd "$pre" --lead-s 420 > $4/watchdog.out 2>&1 < /dev/null & )
}
attempt() {   # <tag> <pod name> <dcs> <minutes> <usd> -> rc 0 done, 10 pod did not come up, 1 other failure
  local tag=$1 name=$2 dcs=$3 min=$4 usd=$5; local out=$BASE/remeasure_$tag; mkdir -p $out
  echo "##### attempt $tag: pod $name, data centres $dcs, watchdog $min min / \$$usd $(date -u +%T)"
  start_watchdog $name $min $usd $out
  local fail_var="P6_FAIL_STEP_$tag"
  P6_RM_OUT=$out P6_OUT_DIR=${P6_STUB_RUN:+$out} P6_RM_NAME=$name P6_RM_RUN_ID=$name P6_DCS_LIST=$dcs \
    P6_FAIL_STEP=${!fail_var:-} bash scripts/phase6/remeasure.sh > $out/session.log 2>&1
  cat $out/session.log
  if grep -qE "^STEP_FAILED (create|ready) " $out/session.log; then return 10; fi
  if grep -q "^STEP_FAILED " $out/session.log; then return 1; fi
  return 0
}
attempt A p6-fixrmA EU-FR-1,US-NE-1,EU-NL-1,US-GA-2,US-CA-2 47 3.16; rc=$?
if [ $rc = 10 ]; then
  echo "RETRY: attempt A's pod did not come up; one more pod (owner's rule)"
  attempt B p6-fixrmB EU-FR-1,US-NE-1,EU-NL-1,US-GA-2,US-CA-2,US-MO-1 48 3.20; rc=$?
  [ $rc = 10 ] && { echo "STOP: two failed pods (owner's rule)"; echo "RETRY_SESSION_END two_pods_failed"; exit 2; }
fi
[ $rc = 0 ] && echo "RETRY_SESSION_END measured" || echo "RETRY_SESSION_END stopped_on_failure (rc=$rc)"
