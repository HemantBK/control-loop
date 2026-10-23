# Re-check of the manager's Amendment (13) edits: Opus (Claude Opus 5.5), 2026-10-23

Read-only, through the restricted reviewer key, on ~/review/gpu_kit/. The reviewer's final message, verbatim:

Opus re-check of the Amendment (13) items. Everything ran read-only through the reviewer key on ~/review/. I re-ran gate.py by hand on all 41 fixtures and all 15 checks.txt patterns: 0 mismatches. I also tested setsid, pkill -s and the `local` shadowing on the CPU pod.

1. **FIXED.** T_C2S=900 is set in run_arms.sh:25 and drive_session.sh:18. The driver's table is at :27 and the pod env at :52. sanitizer_min's `local T_CS="${SAN_TIMEOUT:-$T_CS}"` (:131) works: tested, SAN_TIMEOUT=900 gives 900, unset gives 300, and the global is unchanged. The information arms keep T_CS=300. The tables in arm_limit and arm_timeout are identical. (See new defect A: the arm actually gets slightly less than 900 s.)
2. **FIXED.** drive_session.sh:22 has `BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$LOCAL_OUT/known_hosts`. SSH_OPTS comes later, so it cannot override them. Both rsync calls (:35, :38) use `-e "$SSH"`.
   - Caveat: the file is only per-session if LOCAL_OUT is fresh. The default `~/out/gpu_session` is fixed and the FIXES.md invocation does not override it. A stale key for a reused IP:port would fail every arm.
3. **FIXED.** gate.py:182-186, with the tool present:
   - an empty or missing log is FAIL;
   - a tool error is FAIL;
   - a log with no ERROR SUMMARY is FAIL;
   - PASS needs `n_errors == 0` and no invalid block.
   Keeping the NO_SANITIZER launch-count PASS is acceptable. Amendment 12 defines C2s as the "launch-count companion", and run_arms.sh:133-137 writes NO_SANITIZER only when sanitizer_bin finds no tool. fresh_copy removes the folder first, so a stale log cannot carry over. C2cs writes it too, but its own branch returns earlier. The extra tightening (n_errors>0 with no parsed block is now FAIL) is conservative.
4. **FIXED.** Each new fixture is written so it can fail:
   - each C2s fixture asserts its own reason string;
   - c2only and c2sonly assert the exact `(C1s=.. C2=.. C2s=..)` triple, so a rule that ignored C2 or C2s would fail them.
   ALL_PASS is recorded in raw/gate_selftest_output.txt (41 fixtures, 15 checks), and my re-run agrees. Untested path: `debug8_cause_attributed_to_RoPE: NO`.
5a. **FIXED.** gpu_ok has `timeout 60` and `timeout 120`. Preflight runs under arm_limit with T_PRE=420, plus curl `--max-time 90` and nvcc `timeout 120`.
5b. **FIXED as logic.**
   - Session id: verified on the CPU pod with no pty. The background child is not a group leader, so setsid does not fork, and sid == $!. Nested `timeout`s get their own process groups but keep that sid.
   - Kill: `pkill -TERM -s` cleared all of them, `kill -0` then fails, and no sleep was left.
   - __inner mode, leftover cleanup through .arm_sid, and rc-124 gating of a killed arm are correct.
   - SSH_GRACE: outer startup plus the 2 s poll, 5 s TERM-to-KILL grace and finish is about lim+30 s, well inside lim+180.
   - Race (tiny): an arm that finishes right at the limit can be killed during its own `finish` and re-gated as 124.
   - The raw killtest file used an arm ZZ that is not in the kit, and it shows no leftover-process check; my test covers that.
6. **NOT FIXED on the path that actually runs.** Only run_arms.sh's default order changed (:245), and its own header says that order is "not for the pod". The pod is driven by drive_session.sh with an explicit arm list. The kit's only exact invocation, FIXES.md:153-154, still ends in `C3s C1b`. The run_arms.sh:10 comment still lists C1b too.
7. **FIXED, with one logic slip.** stock_crashes_under_C2_conditions uses C1s only and names no kernel. YES needs C1c PASS (first failing launch is RoPE) or C1b PASS with RoPE named. Rule A at :239 still uses only C1s, C2 and C2s.
   - Slip: `named_other = C1c FAIL or C1b FAIL` (:235) also prints NO when C1c FAILs because the launch-check patch did not apply (gate.py C1c PATCH_FAILED). No kernel is named in that case, so it should be UNDECIDED. MANAGER_EDITS says "NO when C1c or C1b names another kernel".

New defects:
- **A (from 5b): every arm, C2s included, gets less than its stated limit.** run_one's limit equals the arm's inner `timeout`, but the clock (t0, :229) starts before the inner script's startup, gpu_ok, fresh_copy and patching. So the outer session kill always fires first. That startup is about 10-30 s, or up to about 200 s if the GPU probes hang. The inner `timeout ... --kill-after=30s` never takes effect. C2s gets about 870-890 s, not 900. Fix: set the outer limit to arm_limit + 60 s, which still fits SSH_GRACE=180.
- **B:** the item 7 slip above.
- No `set -u` or quoting bugs found. `bash -n` passes on all three scripts and gate.py parses.

VERDICT: OPEN ITEMS REMAIN
