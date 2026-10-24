#!/bin/bash
# Stub of scripts/phase6_pod/rm_interleave.sh for the CPU rehearsal of the re-measure session (no GPU): prints the step's
# success markers, or fails when $P6_FAIL_STEP names this step. Paths are relative to the script (the fake ssh maps
# /workspace only in the command line).
W=$(cd "$(dirname "$0")/.." && pwd)
[ "${P6_FAIL_STEP:-}" = "interleave" ] && { echo "stub: forced failure of interleave"; exit 1; }
mkdir -p $W/remeasure/interleave; echo "stub output of interleave $(date -u +%T)" > $W/remeasure/interleave/stub.txt
echo "MEDIAN_RATIO interleave agent/initial = 1.0 (stub)"
