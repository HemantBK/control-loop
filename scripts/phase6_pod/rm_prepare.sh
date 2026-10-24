#!/bin/bash
# Re-measure step 1 (owner, 2026-10-24): a fresh copy of the composed task_context, the monitor started, the three kernel
# sets the remaining steps need (initial, agent; Amendment (21)) built once in parallel, then untimed warm-up passes.
set -u; . "$(dirname "$0")/rm_common.sh"
rm -rf $TC; cp -r $TCA $TC; rm -rf $TC/workspace; cp $K/c_interleave.py $K/c_minimal_kernels.py $K/c_kl_check.py $K/c_kernel_tests.py $TC/
[ -d $P6_RM/submission/task_snapshot/kernels ] || { echo "NO_SUBMISSION"; exit 2; }
( cd $P6_RM/submission/task_snapshot && sha256sum kernels/* bindings.cpp ) > $P6_RM/agent_kernels_sha256.txt
setsid nohup bash $K/monitor.sh > $P6_RM/monitor.out 2>&1 < /dev/null & echo "monitor started pid $!"
echo "=== builds $(date -u +%T)"; rc=0
# 2026-10-24: wait on the build pids only; a bare `wait` also waited on the monitor started above, which never exits
pids=""; for s in initial agent; do ( cd $TC && python3 c_interleave.py build $s ) > $P6_RM/build_$s.log 2>&1 & pids="$pids $!"; done; wait $pids
for s in initial agent; do grep -h "BUILD_OK" $P6_RM/build_$s.log || { echo "BUILD_FAILED $s"; tail -5 $P6_RM/build_$s.log; rc=1; }; done
echo "=== warm-up $(date -u +%T)"
for s in initial agent; do ( cd $TC && timeout 600 python3 c_interleave.py pass $s --warmup ) > $P6_RM/warmup_$s.log 2>&1; grep -h "WARMUP_DONE" $P6_RM/warmup_$s.log || { echo "WARMUP_FAILED $s"; rc=1; }; done
[ $rc = 0 ] && echo "PREPARE_OK $(date -u +%T)"; exit $rc
