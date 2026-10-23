# Review of the Amendment (15) fix round: Opus (Claude Opus 5.5), 2026-10-23 (the one review the owner asked for)

Read-only, through the restricted reviewer key. Findings as reported (condensed into list form). Verdict: OPEN ITEMS REMAIN.

1. **Cache fix: SOUND.**
   - HF_HOME is resolved first; mirror_hf_cache runs at top level, so it covers the outer call, every `__inner` arm and
     preflight.
   - The symlinks resolve refs/main and the blobs.
   - cache_test.sh matches pod_setup.sh:389-392; its result was claimed but not recorded in raw/.
2. **Preflight: SOUND.** bench's own loader runs on a fresh copy, offline, with the arms' env; the gate requires
   MODEL_LOAD_OK. T_PRE=600 is fine.
3. **Abort: SOUND.** drive_session stops after any preflight or C0 result that is not PASS, and abort_selftest is sound.
   The kit itself does not delete the pod: deletion is the manager's watcher and the $6 watchdog.
4. **INVALID/VOID: SOUND,** with one OPEN minor item.
   - The markers match the real prints, and the new gate gives INVALID on the real void logs.
   - void_C2cs's apply.log was edited to the new patch name.
   - VOID logic OK.
   - OPEN (minor): a real kernel crash in C2ce would be labelled INVALID, because the evaluator catches it and never
     prints its marker.
   - Carried-over risk: a patch that fails to apply, or a memcheck overrun in C2s/C2cm, reads as FAIL, not INVALID.
5. **Option 2: SOUND,** with notes.
   - The patch is exactly the minimal set, and every option 2 arm is wired to it.
   - C2cs's changed gate is a reasonable pre-registration.
   - C2ce's wrapper is picked up.
   - task_dir/starter_kernels exists in the copy and carries the same option 2 RoPE, so embedded's KL is ~0 by
     construction. The gate is meaningful only for no crash, no fallback and no landmine.
   - The gate does not require the starter module.
   - C2cm's expected count (352) is right.
6. **Overstated lines and the error count: FIXED** in gate.py. OPEN (minor): CORRECTIONS.md item 5 leaves out C1c.
7. **Session timing: OPEN.**
   - drive_session.sh still defaults DEADLINE_MIN to 55 and nothing sets 80. As launched, C2cm, C2cs and C2ce would be
     skipped and option 2 would be VOID.
   - With 80, C2ce and C2cr have small margins (both information only).
   - C2cs would be skipped if C2s and C2cm both ran to their limits.
   - Suggested order: C2c C2cs C2cm C2cr C2ce.
8. **New defects:** none in quoting, `set -u` or variable names; the arm tables match. Stale comments. Preflight did not
   check the evaluator helper files.

Fixes listed as needed before the session:
- (a) DEADLINE_MIN=80;
- (b) suggested: order C2c C2cs C2cm C2cr C2ce;
- (c) gate C2ce's CUDA error / "KL computation failed" before INVALID;
- (d) add C1c to CORRECTIONS.md.
