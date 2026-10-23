# Re-check of the fix round (R2, R3, R4, R7, R8, R9): Opus (Claude Opus 5.5), 2026-10-23

Read-only reviewer under PLAN Amendment (12), item 2. It ran through the restricted reviewer key: every command ran as the
unprivileged user `reviewer` and was logged to /root/scratch/reviewer_audit.log. That log shows no write attempt by the
reviewer; the only two write-like commands in it are the manager's own isolation tests. Material: a root-owned, read-only
copy under /home/reviewer/review/. The reviewer's final message, verbatim:

**R2: FIXED.** C1s and C2 go through the same `bench_arm` (run_arms.sh:186-195): same fresh copy, same `timeout $T_C2 bash bench.sh --verbose`, same environment. The only difference is `apply_variant stock` vs `rope_guard`. C1c no longer gets a cached baseline (run_arms.sh:180). `rope_guard_only.patch` really is guard-only: one parameter, `if (idx >= total_pairs) return;`, and `total_pairs` passed at the launch. The starter patch is the same three hunks, and the gpu_run/ and patches/ copies are byte-identical.
- Note: on the bench path the starter patch never runs. bench.py:197-201 reads `$ARENA_ROOT/starter_kernels`, which is absent on the pods (debug8 p6_diag_bench.log:32,36). So the baseline is vanilla in both C1s and C2, which keeps them equal, but the starter guard is only compile-checked.
- New defect, minor, annotation only: `last_prompt_completed` (gate.py:106) also counts the baseline-phase "prompt N/8" lines, so a crash in agent prompt 1 reports 8.

**R3: FIXED.** c_kernel_tests.py:26 now calls `.contiguous()`. The fp32 rotate_half reference (:35-38) is correct. The tolerances (:39) leave real headroom, and the interleaved stock math still fails by O(1). The 11ea904 kernel computes sin/cos in double, so fp32 at 1e-4 is plausible. No new defect.

**R4: FIXED.** In rope mode, `Counted.__getattr__` raises AttributeError (c_minimal_kernels.py:38-39), so inject.py:17-18 `hasattr` is False for the other ops. There are two runs without memcheck on 8 prompts × 32 tokens (run_arms.sh:140-141), and the expected call count is correct (:87, 32 forward passes per prompt). The gate logic at gate.py:151-167 is sound.
- Caveat, info only: an exact 256-token greedy match in fp16 is strict, so a correct kernel could miss on a near-tie.

**R7: PARTLY FIXED.**
- Deadline: enforced per arm. An arm is skipped if the time left is less than its timeout (drive_session.sh:39-45).
- Copy-back: results are copied back after every arm that runs (:51).
- Watchdog: the last possible end is about minute 55 + 3.5 (ssh grace 180 s + 30 s kill) + rsync, so about 59-62 min, under 75.
- Cost: right. 55-60 min at $3.99/h is $3.66-3.99, and 75 min is $4.99.
  - The 49-min estimate includes C1b, but in this order C1b can never start by minute 30 (that point is reached around minute 43), so it is always skipped. The realistic run is about 50 min, about $3.3.
- **New defect, should fix:** the cut of the sanitizer/kernel-test timeout (`T_CS`, 900 → 300 s) also applies to C2s (run_arms.sh:24,134; drive_session.sh:27). C2s is a rule-A arm that compiles, loads the model and generates 8 tokens under memcheck, and its run time has never been measured on a GPU. REPORT.md:657 gave about 85% that memcheck fits, and that was at 900 s. A C2s timeout falls to gate.py:182 FAIL, so rule A FAILs and Phase 6 closes for good. My original remedy was meant for the information arms. Fix: give C2s its own 900 s in both files.
- Minor:
  - preflight has no overall timeout in run_arms.sh (sub-timeouts of 300+120+120 s plus nvcc and curl with no timeout), against the driver's 420 s budget.
  - `gpu_ok` (run_arms.sh:58-60) has no timeout.
  - Killing the local ssh does not kill the remote command, because there is no pty. An overrunning arm could therefore overlap the next one on the GPU.

**R8: PARTLY FIXED. The rule-A computation itself is correct.**
- gate.py:227 uses only C1s, C2 and C2s, and the last GATE line per arm wins (:216). `^GATE C2 ` does not match the C2s lines. The verdict is now keyed on RoPE appearing in `kernels_named` (:89-98).
- Still overstated: `debug8_cause_reproduced` is YES from C1s alone (:223-224), and C1s only shows that stock crashes, with no kernel named. It stays YES even when C1c FAILs (another kernel fails first). The fixture decision_fail_c2 prints YES with only C1s=PASS. This line is not part of the verdict.
- C2s gate: with the tool present but sanitizer.log empty, `parse_sanitizer` returns None, and :179 reports PASS "no sanitizer available". A tool failure gets labelled as a pass; the call counts must still match.

**R9: PARTLY FIXED.** All 34 recorded outputs in expected_output.txt match manifest.txt, but the "ALL_PASS" summary line itself is not recorded in raw/.
- Untested paths:
  - C2s: memcheck still finds an invalid access, FAIL (gate.py:181). This is the case C2s exists to catch.
  - C2s: the no-sanitizer PASS (:179) and the CUDA-error FAIL (:175).
  - C2: timeout, compile failure, and RoPE not ACTIVE (:134-135, :145).
  - C1s: compile failure (:102).
  - C1c: FAIL and UNDECIDED (:118-125).
  - C1a, C1b, C1r: all UNDECIDED paths (:71-81).
  - preflight, C3, C3s.
- A fixture that cannot catch a fault: decision_fail_c2 has C2=FAIL and C2s=FAIL together, so a rule that ignored C2 would still pass every fixture. No fixture has C2 or C2s failing alone.
- gate_selftest.sh:9 asserts only the rule_A token, so the new R8 lines are never checked.
- The sanitizer text in the fixtures is still hand-written. The preflight canary check validates only the "what" field, not kernel naming.

**Possible blocker, needs checking:** drive_session.sh:18 uses `BatchMode=yes` and no `StrictHostKeyChecking=accept-new`. The dry run used a fake ssh, so this was never exercised. If pod_setup does not record the new pod's host key first, every ssh and rsync fails, every arm comes back NOT_RUN, and rule A reports FAIL. Confirm pod_setup records the key, or add the option.

**Overall: not ready for the owner's GPU decision yet.** R2, R3, R4 and the rule-A logic are sound. What is left before GPU time is small:
1. Give C2s a 900 s timeout, so a slow memcheck run cannot fail rule A by itself.
2. Settle the host-key option.
3. Add fixtures for C2-only FAIL, C2s-only FAIL and the C2s memcheck-invalid case.
