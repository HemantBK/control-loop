#!/bin/bash
# Re-measure step 4: per-token KL of the agent's kernels against vanilla (change 05's functions): the 0.01 gate, and the
# paper's 0.1 on the mean and on the max; prebuilt set.
set -u; . "$(dirname "$0")/rm_common.sh"
O=$P6_RM/kl; mkdir -p $O
( cd $TC && C_PREBUILT_SET=agent timeout 900 python3 c_kl_check.py ) > $O/kl_check.log 2>&1; echo "rc=$?"
grep -hE "^KL_|^GATE_|^PAPER_" $O/kl_check.log | head -10
echo "KL_DONE"
