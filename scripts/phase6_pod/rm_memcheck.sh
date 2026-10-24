#!/bin/bash
# Re-measure steps 3 and 3b (done criteria 2 and 3): a kernel set (agent by default; initial for rm_memcheck_initial.sh) on
# the full model path under compute-sanitizer memcheck, every op call and exception counted (c_minimal_kernels.py), fixrun
# session 1's C2s prompt and length; the set built once in rm_prepare.sh.
set -u; . "$(dirname "$0")/rm_common.sh"
SETN=${1:-agent}; O=$P6_RM/memcheck_$SETN; mkdir -p $O; S=$(command -v compute-sanitizer || ls /usr/local/cuda/bin/compute-sanitizer 2>/dev/null | head -1)
( cd $TC && C_PREBUILT_SET=$SETN PYTORCH_NO_CUDA_MEMORY_CACHING=1 C_PROMPT="Explain the theory of relativity in simple terms." C_MAX_NEW=8 C_OPS=all \
  timeout 1200 $S --tool memcheck --target-processes application-only --print-limit 200 --report-api-errors no --log-file $O/sanitizer.log python3 c_minimal_kernels.py ) > $O/memcheck.log 2>&1
echo "rc=$?"; grep -hE "^MIN_" $O/memcheck.log | head -12; grep -h "ERROR SUMMARY" $O/sanitizer.log | tail -1
echo "MEMCHECK_DONE"
