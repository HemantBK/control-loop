#!/bin/bash
# Does opencode's shell tool honour OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS? (PLAN Amendment (34); 2026-10-27; CPU
# pod, no GPU.) Two runs of `opencode run` with GLM-5.1 asking for one command that takes 130 s, with no timeout of the
# model's own: A without the variable (expected: killed at 120 s), B with it at 3600000 (expected: SLEPT_OK).
# Prints only the markers found in each run's JSON events. Run with the OpenRouter key in the environment
# (uv run --env-file ../.env bash oc_timeout_test.sh <out dir>).
set -u
O=${1:?out dir}; mkdir -p "$O"
P='Use your bash tool exactly once to run this command, and do not pass any timeout argument: sleep 130 && echo SLEPT_OK
Then reply with only the command output, or with the tool error if there was one.'
W=$(mktemp -d); cd "$W" || exit 1
run() {   # name, then env assignments
  local n=$1; shift
  env "$@" HOME="$W/home_$n" timeout 400 opencode run --format json --model openrouter/z-ai/glm-5.1 "$P" > "$O/$n.jsonl" 2> "$O/$n.err"
  echo "$n: rc=$? SLEPT_OK=$(grep -c SLEPT_OK "$O/$n.jsonl") killed_at_timeout=$(grep -c 'exceeding timeout' "$O/$n.jsonl") timeout_ms_mentioned=$(grep -oE 'exceeding timeout [0-9]+ ms' "$O/$n.jsonl" | head -1)"
}
run A_default -u OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS
run B_with_var OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS=3600000
rm -rf "$W"
