#!/bin/bash
# Stub of scripts/phase6_pod/harness.sh for the CPU rehearsal of the re-measure session (no GPU): prints the step's
# success markers, or fails when $P6_FAIL_STEP names this step. Paths are relative to the script (the fake ssh maps
# /workspace only in the command line).
W=$(cd "$(dirname "$0")/.." && pwd)
[ "${P6_FAIL_STEP:-}" = "harness" ] && { echo "stub: forced failure of harness"; exit 1; }
mkdir -p $W/remeasure/harness; echo "stub output of harness $(date -u +%T)" > $W/remeasure/harness/stub.txt
echo "PATCHED_FILES_MATCH_EXPECTED CHECKOUT_UNCHANGED PROCS_OK MODEL_LOAD_OK"
