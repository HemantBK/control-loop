#!/usr/bin/env bash
# R7: session driver, run on the CPU machine (the GPU pod cannot push to it). One arm per ssh call, the arm's output
# rsynced back after every arm, one global deadline: an arm is skipped as NOT_RUN when fewer than its timeout's worth of
# seconds remain before minute DEADLINE_MIN (80, Amendment (15)) counted from the pod allocation epoch.
#
# Usage: bash drive_session.sh <ssh_addr> <alloc_epoch> <arm> [arm...]
#   ssh_addr     e.g. root@1.2.3.4   (extra ssh flags such as "-p 12345 -i ~/.ssh/id_ed25519" go in SSH_OPTS)
#   alloc_epoch  `date +%s` taken when the pod was allocated (the $6 watchdog counts from there)
# Env: SSH_OPTS, REMOTE_RUN=/workspace/gpu_run (run_arms.sh, gate.py, drivers and patches must already be there: pod_setup
#      copies ~/out/gpu_run), REMOTE_OUT=/workspace/rootcause, LOCAL_OUT=~/out/gpu_session, DEADLINE_MIN=80, SSH_GRACE=180
# Per-arm timeouts (mirrored into the pod's env so run_arms.sh uses the same numbers): T_C0=600 T_C2=900 T_CS=300 T_C1B=1500
set -uo pipefail
ADDR="${1:?ssh addr}"; EPOCH="${2:?allocation epoch}"; shift 2; ARMS=("$@"); [ ${#ARMS[@]} -gt 0 ] || { echo "no arms"; exit 2; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${SSH_OPTS:=}"; : "${REMOTE_RUN:=/workspace/gpu_run}"; : "${REMOTE_OUT:=/workspace/rootcause}"
# Amendment (13), manager: a fresh output folder per invocation (it also holds this session's known_hosts)
: "${LOCAL_OUT:=$HOME/out/gpu_session_$(date -u +%Y%m%dT%H%M%SZ)}"
if [ -e "$LOCAL_OUT/known_hosts" ] || [ -e "$LOCAL_OUT/session.log" ]; then echo "LOCAL_OUT $LOCAL_OUT is not fresh: refusing"; exit 2; fi
: "${OUTER_MARGIN:=60}"   # the pod-side outer limit is the arm's timeout + OUTER_MARGIN (run_arms.sh)
: "${DEADLINE_MIN:=80}"; : "${SSH_GRACE:=180}"   # Amendment (15): deadline 80 minutes from allocation (was 55)
: "${T_C0:=600}"; : "${T_C2:=900}"; : "${T_CS:=300}"; : "${T_C1B:=1500}"; : "${T_PRE:=600}"
: "${T_C2S:=900}"   # Amendment (13), manager: C2s is a rule-A arm and keeps 900 s; the information arms keep T_CS
mkdir -p "$LOCAL_OUT"; LOG="$LOCAL_OUT/session.log"; SUMMARY="$LOCAL_OUT/SUMMARY.txt"; touch "$SUMMARY"
# Amendment (13), manager: a new pod's host key is unknown; accept it on first contact into a per-session known_hosts file
# (BatchMode stays on, so nothing ever waits for a prompt)
SSH="ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$LOCAL_OUT/known_hosts -o ServerAliveInterval=20 -o ServerAliveCountMax=6 -o ConnectTimeout=30 $SSH_OPTS"
DEADLINE=$(( EPOCH + DEADLINE_MIN * 60 ))
say() { echo "[$(date -u +%FT%TZ) +$(( ($(date +%s) - EPOCH) / 60 ))m$(( ($(date +%s) - EPOCH) % 60 ))s since alloc] $*" | tee -a "$LOG"; }
arm_timeout() {  # the `timeout` run_arms.sh applies to this arm (same table as run_arms.sh)
  case "$1" in
    preflight) echo "$T_PRE" ;; C0) echo "$T_C0" ;; C1b) echo "$T_C1B" ;; C2s|C2cm) echo "$T_C2S" ;;
    C1s|C1c|C2|C2c|C3|C2ce) echo "$T_C2" ;;
    C2cs) echo $(( 2 * T_CS )) ;;                      # two runs (RoPE-only, all kernels)
    C1a|C1r|C2r|C2a|C2cr|C3a|C3s) echo "$T_CS" ;;
    *) echo "$T_C2" ;;
  esac
}
pull() {  # pull <arm>: copy the arm's folder (without build products) and the pod's SUMMARY/run.log back
  rsync -az --timeout=120 -e "$SSH" --exclude='*.so' --exclude='__pycache__' --exclude='_build' --exclude='arena_build*' \
    "$ADDR:$REMOTE_OUT/$1/" "$LOCAL_OUT/$1/" 2>>"$LOG" || say "WARNING: rsync of $1 failed"
  mkdir -p "$LOCAL_OUT/pod"   # the pod-side SUMMARY.txt and run.log (the local SUMMARY.txt is rebuilt from the GATE lines below)
  rsync -az --timeout=60 -e "$SSH" "$ADDR:$REMOTE_OUT/run.log" "$ADDR:$REMOTE_OUT/SUMMARY.txt" "$LOCAL_OUT/pod/" 2>>"$LOG" || say "WARNING: rsync of SUMMARY/run.log failed"
}
say "drive_session start: addr=$ADDR epoch=$EPOCH deadline=minute $DEADLINE_MIN arms=${ARMS[*]} LOCAL_OUT=$LOCAL_OUT"
ABORT=""
for a in "${ARMS[@]}"; do
  if [ -n "$ABORT" ]; then   # Amendment (15): after a failed preflight or C0 nothing else runs; the caller deletes the pod
    mkdir -p "$LOCAL_OUT/$a"; echo "{\"arm\":\"$a\",\"rc\":-1,\"seconds\":0,\"skipped\":\"abort\"}" > "$LOCAL_OUT/$a/meta.json"
    echo "GATE $a NOT_RUN: session aborted ($ABORT)" | tee -a "$SUMMARY" | tee -a "$LOG"; continue
  fi
  T=$(( $(arm_timeout "$a") + OUTER_MARGIN )); NOW=$(date +%s); LEFT=$(( DEADLINE - NOW ))   # the arm's real maximum on the pod
  if [ "$LEFT" -lt "$T" ]; then
    say "SKIP $a: ${LEFT}s left before the deadline < timeout ${T}s"
    mkdir -p "$LOCAL_OUT/$a"; echo "{\"arm\":\"$a\",\"rc\":-1,\"seconds\":0,\"skipped\":\"deadline\"}" > "$LOCAL_OUT/$a/meta.json"
    echo "GATE $a NOT_RUN: skipped by the session deadline (${LEFT}s left < timeout ${T}s)" | tee -a "$SUMMARY" | tee -a "$LOG"
    continue
  fi
  say "=== arm $a start (timeout ${T}s, ${LEFT}s left)"
  t0=$(date +%s)
  timeout --signal=TERM --kill-after=30s $(( T + SSH_GRACE )) $SSH "$ADDR" \
    "T_C0=$T_C0 T_C2=$T_C2 T_CS=$T_CS T_C2S=$T_C2S T_PRE=$T_PRE T_C1B=$T_C1B OUTER_MARGIN=$OUTER_MARGIN OUT_DIR=$REMOTE_OUT bash $REMOTE_RUN/run_arms.sh $a" >> "$LOG" 2>&1; rc=$?
  # (run_arms.sh kills the arm's whole session on the pod when the arm's limit passes; this local timeout, SSH_GRACE later,
  # only bounds a dead connection)
  say "=== arm $a ssh rc=$rc in $(( $(date +%s) - t0 ))s; pulling"
  pull "$a"
  line=$(grep -h "^GATE $a " "$LOCAL_OUT/pod/SUMMARY.txt" 2>/dev/null | tail -1)
  [ -n "$line" ] || line="GATE $a NOT_RUN: no gate line came back (ssh rc=$rc)"
  echo "$line" | tee -a "$SUMMARY"
  case "$a" in preflight|C0) case "$line" in "GATE $a PASS"*) ;; *) ABORT="$a did not pass"; say "ABORT: $ABORT; remaining arms not run; delete the pod";; esac;; esac
done
python3 "$HERE/gate.py" decision "$LOCAL_OUT" | tee -a "$SUMMARY" | tee -a "$LOG"
say "SESSION_DONE; results in $LOCAL_OUT (delete the pod now)"
