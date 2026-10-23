#!/usr/bin/env bash
# Amendment (15): drive_session.sh must stop after a failed preflight or C0 (the void run kept going for ~26 min after C0
# failed). Fake ssh/rsync on PATH stand in for the pod: the fake ssh records each requested arm and appends a canned GATE
# line (PASS, except FAIL for the arm named in FAKE_FAIL) to a fake remote SUMMARY.txt; the fake rsync copies it back.
# Output: raw/abort_selftest_output.txt.
set -u; HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; REC="$HERE/raw/abort_selftest_output.txt"
main() {
  local T; T=$(mktemp -d); mkdir -p "$T/bin" "$T/remote"; fail=0
  cat > "$T/bin/ssh" <<'SH'
#!/bin/bash
cmd="${@: -1}"; arm="${cmd##* }"; echo "$arm" >> "$FAKE_REMOTE/requested"
v=PASS; [ "$arm" = "$FAKE_FAIL" ] && v=FAIL; echo "GATE $arm $v: fake" >> "$FAKE_REMOTE/SUMMARY.txt"; touch "$FAKE_REMOTE/run.log"; mkdir -p "$FAKE_REMOTE/$arm"
SH
  cat > "$T/bin/rsync" <<'SH'
#!/bin/bash
dst="${@: -1}"; for a in "$@"; do case "$a" in *:*/SUMMARY.txt) cp "$FAKE_REMOTE/SUMMARY.txt" "$dst/";; *:*/run.log) cp "$FAKE_REMOTE/run.log" "$dst/";; esac; done; exit 0
SH
  chmod +x "$T/bin/ssh" "$T/bin/rsync"
  for failarm in C0 preflight; do
    rm -rf "$T/remote"/*; : > "$T/remote/requested"
    PATH="$T/bin:$PATH" FAKE_REMOTE="$T/remote" FAKE_FAIL=$failarm LOCAL_OUT="$T/out_$failarm" \
      bash "$HERE/gpu_run/drive_session.sh" root@fake $(date +%s) preflight C0 C1s C2 C2s C2c C2cm C2cs C2ce C2cr > "$T/drive_$failarm.log" 2>&1
    req=$(tr '\n' ' ' < "$T/remote/requested"); notrun=$(grep -c "NOT_RUN: session aborted" "$T/out_$failarm/SUMMARY.txt")
    echo "FAKE_FAIL=$failarm: arms requested on the pod: $req| NOT_RUN aborted lines: $notrun"
    grep -h "^DECISION rule_A\|^DECISION option_2" "$T/out_$failarm/SUMMARY.txt" | sed 's/^/  /'
    want_req=$([ $failarm = C0 ] && echo "preflight C0 " || echo "preflight ")
    want_nr=$([ $failarm = C0 ] && echo 8 || echo 9)
    if [ "$req" = "$want_req" ] && [ "$notrun" = "$want_nr" ] && grep -q "^DECISION rule_A: VOID" "$T/out_$failarm/SUMMARY.txt"; then echo "ok   abort after $failarm: no later arm ran; rule_A VOID"; else echo "FAIL abort after $failarm"; fail=1; fi
  done
  rm -rf "$T"; echo "abort_selftest: $([ $fail = 0 ] && echo ALL_PASS || echo FAILURES)"; return $fail
}
main 2>&1 | tee "$REC"; exit "${PIPESTATUS[0]}"
