#!/bin/bash
# Restart loop for the cell 733 batch runner (PLAN Amendments (23) item 2, (29)). Run inside tmux session `batch`:
#     tmux new-session -d -s batch -c /root/control-loop "bash scripts/phase6/cell_loop.sh results/phase6_researcharena/batch_733/cell"
# If the runner exits or crashes before the batch is done, it starts again after 5 s and resumes from the batch's state
# files. When <batch dir>/DONE exists the loop ends. Every start and exit goes to <batch dir>/loop.log.
B=${1:?usage: batch_loop.sh <batch dir>}
cd "$(dirname "$0")/../.." || exit 1
mkdir -p "$B"
while [ ! -f "$B/DONE" ]; do
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) loop: start batch.py run $B" >> "$B/loop.log"
  uv run --frozen --env-file ../.env python scripts/phase6/cell_batch.py run >> "$B/runner.out" 2>&1
  rc=$?
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) loop: batch.py exited rc=$rc" >> "$B/loop.log"
  [ -f "$B/DONE" ] || sleep 5
done
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) loop: batch done; loop ends" >> "$B/loop.log"
