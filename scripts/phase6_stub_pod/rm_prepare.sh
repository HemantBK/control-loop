#!/bin/bash
# Stub of scripts/phase6_pod/rm_prepare.sh for the CPU rehearsal of the re-measure session (no GPU): prints the step's
# success markers, or fails when $P6_FAIL_STEP names this step. Paths are relative to the script (the fake ssh maps
# /workspace only in the command line).
W=$(cd "$(dirname "$0")/.." && pwd)
[ "${P6_FAIL_STEP:-}" = "prepare" ] && { echo "stub: forced failure of prepare"; exit 1; }
mkdir -p $W/remeasure/prepare; echo "stub output of prepare $(date -u +%T)" > $W/remeasure/prepare/stub.txt
echo "PREPARE_OK"
