#!/usr/bin/env bash
# R9: runs gate.py on every fixture in raw/gate_selftest (manifest.txt: <fixture> <arm> <expected verdict>) and asserts the verdict.
# decision fixtures: the expected token is the rule_A verdict. Writes the full output to expected_output.txt.
set -u; HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; G="$HERE/gpu_run/gate.py"; F="$HERE/raw/gate_selftest"
fail=0; n=0; : > "$F/expected_output.txt"
while read -r fx arm want; do
  [ -n "$fx" ] || continue; n=$((n+1))
  out=$(python3 "$G" "$arm" "$F/$fx" 2>&1); echo "## $fx ($arm) expect $want" >> "$F/expected_output.txt"; echo "$out" >> "$F/expected_output.txt"
  if [ "$arm" = decision ]; then got=$(echo "$out" | sed -n 's/^DECISION rule_A: \([A-Z_]*\).*/\1/p'); else got=$(echo "$out" | sed -n "s/^GATE $arm \([A-Z_]*\):.*/\1/p"); fi
  [ "$got" = "$want" ] && echo "ok   $fx ($arm) -> $got" || { echo "FAIL $fx ($arm) -> '$got', expected $want"; echo "$out"; fail=1; }
done < "$F/manifest.txt"
echo "gate_selftest: $n fixtures, $([ $fail = 0 ] && echo ALL_PASS || echo FAILURES)"; exit $fail
