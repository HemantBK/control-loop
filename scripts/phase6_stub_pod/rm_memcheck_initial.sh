#!/bin/bash
# Stub of scripts/phase6_pod/rm_memcheck_initial.sh for the CPU rehearsal (no GPU).
W=$(cd "$(dirname "$0")/.." && pwd)
[ "${P6_FAIL_STEP:-}" = "memcheck_initial" ] && { echo "stub: forced failure of memcheck_initial"; exit 1; }
mkdir -p $W/remeasure/memcheck_initial; echo "stub output of memcheck_initial" > $W/remeasure/memcheck_initial/stub.txt
echo "MEMCHECK_DONE"
