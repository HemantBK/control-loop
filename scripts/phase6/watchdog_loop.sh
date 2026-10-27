#!/bin/bash
# Restart loop for the fleet watchdog (PLAN Amendment (22), Part A item 2). Run inside tmux session `watchdog`:
#     tmux new-session -d -s watchdog "bash scripts/phase6/watchdog_loop.sh <state dir> [fleet_watchdog options]"
# If the watchdog exits or crashes it starts again after 5 s; every start and exit goes to <state dir>/loop.log.
# It needs no API key: runpodctl reads its own config on the CPU pod.
STATE=${1:?usage: watchdog_loop.sh <state dir> [options]}
shift
cd "$(dirname "$0")/../.." || exit 1
mkdir -p "$STATE"
while true; do
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) loop: start fleet_watchdog $STATE $*" >> "$STATE/loop.log"
  .venv/bin/python -m control_loop.adapters.researcharena.fleet_watchdog "$STATE" "$@"
  rc=$?
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) loop: fleet_watchdog exited rc=$rc; restart in 5 s" >> "$STATE/loop.log"
  sleep 5
done
