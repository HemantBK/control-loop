#!/bin/bash
# Stub of scripts/phase6_pod/rm_embedded.sh for the CPU rehearsal of the re-measure session (no GPU): prints the step's
# success markers, or fails when $P6_FAIL_STEP names this step. Paths are relative to the script (the fake ssh maps
# /workspace only in the command line).
W=$(cd "$(dirname "$0")/.." && pwd)
[ "${P6_FAIL_STEP:-}" = "embedded" ] && { echo "stub: forced failure of embedded"; exit 1; }
mkdir -p $W/remeasure/embedded; echo "stub output of embedded $(date -u +%T)" > $W/remeasure/embedded/stub.txt
echo "EMBEDDED_DONE"
