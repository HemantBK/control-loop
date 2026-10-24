#!/bin/bash
# Stub of scripts/phase6_pod/rm_rope.sh for the CPU rehearsal (no GPU).
W=$(cd "$(dirname "$0")/.." && pwd)
[ "${P6_FAIL_STEP:-}" = "rope" ] && { echo "stub: forced failure of rope"; exit 1; }
mkdir -p $W/remeasure/rope; echo "stub output of rope" > $W/remeasure/rope/stub.txt
echo "ROPE_DONE"
