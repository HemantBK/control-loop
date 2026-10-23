#!/usr/bin/env bash
# Amendment (13), manager: proves C2s gets its full inner timeout inside the pod-side outer limit. (1) With the real
# defaults, run_arms.sh reports C2s inner=900 outer=960. (2) Live, time-scaled: a stand-in C2s arm that spends 3 s on
# startup and then runs under its inner `timeout $T_C2S` (8 s) must be ended by that inner timeout (rc 124 in meta.json),
# not by the outer limit (8 + 6 = 14 s), i.e. no "exceeded its overall limit" line. Output: raw/limits_selftest_output.txt.
set -u; HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; REC="$HERE/raw/limits_selftest_output.txt"
main() {
  local T; T=$(mktemp -d); fail=0
  l=$(OUT_DIR=$T/o0 WORKSPACE=$T bash "$HERE/gpu_run/run_arms.sh" limits C2s); echo "$l"
  [ "$l" = "ARM_LIMITS C2s inner=900 outer=960" ] && echo "ok   defaults: C2s inner 900 s inside outer 960 s" || { echo "FAIL defaults: $l"; fail=1; }
  mkdir -p "$T/kit"; cp "$HERE"/gpu_run/* "$T/kit/" 2>/dev/null
  sed -i 's|^arm_C2s() {.*|arm_C2s() { sleep 3; local t0=$(date +%s); ( timeout --kill-after=30s "$T_C2S" sleep 1000 ); finish C2s $? $(( $(date +%s) - t0 )); }|' "$T/kit/run_arms.sh"
  s=$(date +%s); OUT_DIR=$T/o1 WORKSPACE=$T T_C2S=8 OUTER_MARGIN=6 bash "$T/kit/run_arms.sh" C2s > "$T/run.out" 2>&1; el=$(( $(date +%s) - s ))
  rc=$(python3 -c "import json; print(json.load(open('$T/o1/C2s/meta.json'))['rc'])" 2>/dev/null || echo none)
  echo "live: elapsed ${el}s, C2s meta rc=$rc"; grep -h "arm C2s\|exceeded" "$T/o1/run.log" | sed 's/^/  /'
  if [ "$rc" = 124 ] && ! grep -q "exceeded its overall limit" "$T/o1/run.log"; then echo "ok   live: the inner timeout ended C2s; the outer limit did not fire"; else echo "FAIL live: inner timeout did not govern"; fail=1; fi
  rm -rf "$T"; echo "limits_selftest: $([ $fail = 0 ] && echo ALL_PASS || echo FAILURES)"; return $fail
}
main 2>&1 | tee "$REC"; exit "${PIPESTATUS[0]}"
