#!/bin/bash
# Interleaved pairs (owner, 2026-10-24): A, B, A, B, A, B, each pass in its own process (fresh model load, the set
# injected, bench.py's benchmark_generation), then rm_summary.py: each pair's tok/s and ratio B/A, the median ratio,
# and the monitor's readings in each pass's window. Usage: rm_pairs.sh <set A> <set B> <label> [pairs, default 3]
set -u; . "$(dirname "$0")/rm_common.sh"
A=$1; B=$2; LBL=$3; N=${4:-3}; O=$P6_RM/$LBL; mkdir -p $O; : > $O/passes.jsonl; rc=0
for i in $(seq 1 $N); do for s in $A $B; do
  ( cd $TC && timeout 600 python3 c_interleave.py pass $s ) > $O/pass_${i}_$s.log 2>&1
  if grep -q "^PASS_RESULT " $O/pass_${i}_$s.log; then grep -h "^PASS_RESULT " $O/pass_${i}_$s.log | sed "s/^PASS_RESULT //" >> $O/passes.jsonl
  else echo "PASS_FAILED $i $s"; tail -3 $O/pass_${i}_$s.log; rc=1; fi
done; done
python3 $K/rm_summary.py $O/passes.jsonl $LBL $A $B
exit $rc
