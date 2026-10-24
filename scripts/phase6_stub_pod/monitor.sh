#!/bin/bash
# Stub of scripts/phase6_pod/monitor.sh for the CPU rehearsal of the re-measure session (no GPU): prints the step's
# success markers, or fails when $P6_FAIL_STEP names this step. Paths are relative to the script (the fake ssh maps
# /workspace only in the command line).
W=$(cd "$(dirname "$0")/.." && pwd)
[ "${P6_FAIL_STEP:-}" = "monitor" ] && { echo "stub: forced failure of monitor"; exit 1; }
mkdir -p $W/remeasure/monitor; echo "stub output of monitor $(date -u +%T)" > $W/remeasure/monitor/stub.txt
echo "stub"
