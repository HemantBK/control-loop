#!/bin/bash
# Re-measure step 5b: the RoPE numerics after change 06 (c_kernel_tests.py --task rope: 15 cases against HF rotate_half
# with real positions, fp16/bf16/fp32) on the initial kernels' RoPE, under memcheck; the set built once in rm_prepare.sh.
set -u; . "$(dirname "$0")/rm_common.sh"
O=$P6_RM/rope; mkdir -p $O; S=$(command -v compute-sanitizer || ls /usr/local/cuda/bin/compute-sanitizer 2>/dev/null | head -1)
( cd $TC && C_PREBUILT_SET=initial PYTORCH_NO_CUDA_MEMORY_CACHING=1 timeout 600 $S --tool memcheck --target-processes application-only \
  --print-limit 50 --report-api-errors no --log-file $O/sanitizer.log python3 c_kernel_tests.py --task rope ) > $O/rope.log 2>&1
echo "rc=$?"; grep -hE "ROPE_|KT_COMPILE" $O/rope.log | head -20; grep -h "ERROR SUMMARY" $O/sanitizer.log | tail -1
echo "ROPE_DONE"
