#!/bin/bash
# Stub of scripts/phase6_pod/rm_vanilla.sh for the CPU rehearsal of the re-measure session (no GPU): prints the step's
# success markers, or fails when $P6_FAIL_STEP names this step. Paths are relative to the script (the fake ssh maps
# /workspace only in the command line).
W=$(cd "$(dirname "$0")/.." && pwd)
[ "${P6_FAIL_STEP:-}" = "vanilla" ] && { echo "stub: forced failure of vanilla"; exit 1; }
mkdir -p $W/remeasure/vanilla; echo "stub output of vanilla $(date -u +%T)" > $W/remeasure/vanilla/stub.txt
echo "MEDIAN_RATIO vanilla (stub)"
