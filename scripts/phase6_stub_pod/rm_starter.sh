#!/bin/bash
# Stub of scripts/phase6_pod/rm_starter.sh for the CPU rehearsal of the re-measure session (no GPU): prints the step's
# success markers, or fails when $P6_FAIL_STEP names this step. Paths are relative to the script (the fake ssh maps
# /workspace only in the command line).
W=$(cd "$(dirname "$0")/.." && pwd)
[ "${P6_FAIL_STEP:-}" = "starter" ] && { echo "stub: forced failure of starter"; exit 1; }
mkdir -p $W/remeasure/starter; echo "stub output of starter $(date -u +%T)" > $W/remeasure/starter/stub.txt
echo "MEDIAN_RATIO starter (stub)"
