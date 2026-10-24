#!/bin/bash
# Stub of scripts/phase6_pod/rm_kl.sh for the CPU rehearsal of the re-measure session (no GPU): prints the step's
# success markers, or fails when $P6_FAIL_STEP names this step. Paths are relative to the script (the fake ssh maps
# /workspace only in the command line).
W=$(cd "$(dirname "$0")/.." && pwd)
[ "${P6_FAIL_STEP:-}" = "kl" ] && { echo "stub: forced failure of kl"; exit 1; }
mkdir -p $W/remeasure/kl; echo "stub output of kl $(date -u +%T)" > $W/remeasure/kl/stub.txt
echo "KL_DONE"
