#!/bin/bash
# CPU-pod rehearsal only (owner, 2026-10-24): the pod-script plumbing without a GPU. Sources rm_common.sh, checks the
# pushed submission and the composed root, starts the monitor (nvidia-smi is absent here, so it logs errors; the copy
# step must stop it through procs.py), and writes result files for the copy to verify.
set -u; . "$(dirname "$0")/rm_common.sh"
[ -d $P6_RM/submission/task_snapshot/kernels ] || { echo "NO_SUBMISSION"; exit 2; }
( cd $P6_RM/submission/task_snapshot && sha256sum kernels/* bindings.cpp ) > $P6_RM/agent_kernels_sha256.txt
echo "submission: $(ls $P6_RM/submission/task_snapshot/kernels | wc -l) kernel files"
[ -f $TCA/baseline_kernels/rotary_embedding.cu ] && cmp -s $TCA/kernels/rotary_embedding.cu $TCA/baseline_kernels/rotary_embedding.cu \
  && echo "composed root: baseline_kernels RoPE == kernels RoPE" || { echo "COMPOSED_ROOT_MISMATCH"; exit 3; }
grep -q "reset_kernel_counts" $TCA/inject.py && echo "composed root: change 07 present" || { echo "NO_CHANGE_07"; exit 3; }
setsid nohup bash $K/monitor.sh > $P6_RM/monitor.out 2>&1 < /dev/null & echo "monitor started pid $!"
sleep 5; [ -s $P6_RM/monitor_cpu.log ] && echo "monitor writing: $(grep -c '^== ' $P6_RM/monitor_cpu.log) samples"
mkdir -p $P6_RM/localcheck; date -u +%FT%TZ > $P6_RM/localcheck/done.txt
echo "LOCAL_CHECK_OK"
