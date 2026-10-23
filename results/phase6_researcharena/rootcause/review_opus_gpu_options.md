# Review of the rule-A GPU session and the Amendment (14) options: Opus (Claude Opus 5.5), 2026-10-23

Read-only, through the restricted reviewer key, on ~/review/{gpu_results, gpu_kit, options}. Findings as reported by the
reviewer, recorded faithfully (condensed into list form):

- **R1 HIGH:** the manager's diagnosis holds on every link.
  - pod_setup.sh:388-394 calls snapshot_download with no cache_dir; setup.log:27 shows /workspace/hf/hub/models--TinyLlama.
  - bench.py:44-48 and :54-60 pass cache_dir=config.hf_cache_dir (HF_HOME, config.py:51-52), so the lookup goes to
    $HF_HOME/models--*.
  - run_arms.sh:39 sets HF_HUB_OFFLINE=1; run_arms.sh:31, :95 and gate.py:51 test only the hub/ path.
  - All 10 model logs fail at bench.py:44 AutoTokenizer with LocalEntryNotFoundError. None prints "Tokenizer loaded".
  - debug8, without the offline flag, did load the model.
  - Remedy: cache with cache_dir=$HF_HOME, or symlink. Keep the offline flag.
- **R2 HIGH:** the gate turns a harness failure into a kernel verdict.
  - Rule A = FAIL follows literally from Am.12, but no rule-A arm ever ran a kernel. The reviewer recommends recording
    the session as void; the owner must rule.
  - C1a's reason, "fault did not reproduce under the tool", is false: its sanitizer.log shows the target exited with an
    error and nothing was launched.
  - "stock_crashes_under_C2_conditions: NO" should read UNDECIDED.
  - Remedy: an INVALID verdict for arms that never load the model, and rule_A=VOID when any rule-A arm is INVALID.
- **R3 MEDIUM:** preflight checked a file listing, not the real load path.
  - drive_session.sh never stops on a failed preflight or C0: 14 more arms ran for about 26 min (about $1.75) after C0
    failed at 11:06:51.
  - Remedy: preflight runs load_model_and_tokenizer(ArenaConfig()) from a fresh copy; the session aborts and the pod is
    deleted if preflight or C0 fails.
- **R4 LOW:** gate.py:41 takes the last "ERROR SUMMARY" line, so C1r reports 568; the real count is 768.
- **R5 INFO:** the arms that never load the model are valid.
  - C1r: the stock kernel at (1,1,4,64) first fails at rotary_embedding.cu:34 (the positions read) by thread 128 of
    block 0, the predicted tail. RoPE is the only kernel named.
  - C2r (guard only): memcheck clean; numerics 0/15 with the same error as stock, so the guard changes no in-bounds math.
  - C2cr (11ea904): clean, 15/15.
  - C3a: 22/22, clean.
  - C2a (stock attention): clean but 18/22. It fails at N=255 and 256 (up to 0.61), not at N<32 as predicted, which fits
    the warp_reduce[0] race at attention.cu:91 and :105.
- **R6 INFO:** the deadline, skip, kill and copy-back machinery was correct.
  - C3 was skipped with 883 s left against 960 s; C3s ran.
  - No outer-limit kill fired; every arm was pulled.
  - Nit: the skip test leaves no room for SSH_GRACE, the pull or the delete.
- **R7 INFO:** cost and rules fine.
  - 2,582 s × $3.99/h = $2.86, within $5; the watchdog agrees.
  - The delete came 48 s after SESSION_DONE; 43 min against the 55-minute deadline.
  - Not checked against RunPod billing.
- **R8 MEDIUM:** option 2's patch content is right (exactly the 4 files; the inject RoPE hunks equal upstream's; no
  attn_mask hunk; kernel and starter byte-identical), but it will not apply in the kit.
  - Its paths are rooted at settings/cuda_kernel/ with mixed headers, while run_arms.sh runs patch -p1 inside
    task_context.
  - The kit's C2c/C2cs use a different patch (with the attn_mask hunk, without the starter), so they do not test
    option 2.
- **R9 MEDIUM:** the claim that the `embedded` KL evaluator stays consistent is unverified.
  - From inject.py: the module-global apply_rotary_pos_emb is replaced by the latest injection, while current_positions
    belongs to each injection. After a second injection, both models use the second wrapper's ops and its positions.
  - If the lengths differ, `.expand` raises inside `except Exception` and RoPE silently falls back.
  - Needed: the evaluator source, and a GPU run with agent = starter = 11ea904 that counts calls and fallbacks and
    expects KL ≈ 0.
- **R10 LOW:** option 2's CPU checks are sound.
  - 11,264 RoPE calls (8 × 22 × 2 × 32); 8/8 match against 0/8 for stock; ASan as claimed.
  - Gaps: exceptions are not counted (a swallowed fallback would also match); decode positions were not logged; the
    cross case "stock evaluator × 11ea904 kernel" was not run.
- **R11 LOW:** the heap-crash explanation is plausible but not shown: the attempt-1 log printed nothing before the crash.
  The padding is correct (slack of 576 elements against an overrun of at most about 511).
- **R12 INFO:** option 3's checks are verified: config, hooks [1,16,T,128], launch shapes (T=1 × 5,760 calls, T=8 and
  10-14), all tails 0 and ASan clean. Ungated and .bin-only could not be checked from the copy (o3_config output not
  saved).
- **R13 HIGH:** the list of TinyLlama ties is incomplete.
  - bench.py loads with no revision (main); caching by SHA writes no refs/main, so the same offline failure would recur.
  - ARENA_MODEL_ID is set nowhere.
  - The harness's TinyLlama paths: run_arms.sh:28-33 and :95, gate.py:51, pod_setup.sh:308, :338, :365, and step 7
    (--task_config tinyllama).
  - c_kernel_tests.py:25 and :43-45 hard-code TinyLlama shapes; c_minimal_kernels.py:69 prints TinyLlama arithmetic.
  - gate.py:66, C0's ≥20 tok/s threshold and the 55.13 fallback are TinyLlama numbers.
  - Base versus chat model (different outputs).
  - The .bin pickle load and 24 layers under memcheck cost time.
  - The embedded and embedded2 probe shapes were not checked for tails.
- **R14 HIGH:** what the combined session must include.
  - The R1 fix and R3's real-load preflight for each model.
  - INVALID and VOID verdicts, and an abort on preflight or C0 failure.
  - C0 first for each model, then the rule-A arms C1s, C2, C2s.
  - Option 2: the re-rooted minimal patch through bench.sh (8 prompts), greedy match for RoPE-only and all ops with a
    fallback count, a memcheck model-path arm, and the embedded3 and embedded probes.
  - Option 3: ARENA_MODEL_ID set, C0 on Sheared, stock bench.sh completing, memcheck on the model path with
    RoPE calls = 2 × 24 × MAX_NEW × prompts, and kernel tests at (16,128).
  - Budget: this session spent about 15 min on setup and about 100 s compiling per arm, with no model work. With model
    runs and memcheck the session will not fit in 55 min: bake an image, reuse builds per variant, or get the owner's
    approval for more time.

**(A) conclusions:**
- No arm that loads the model reached a kernel; rule A's FAIL is a harness artifact.
- The stock crash under C2's conditions and the guard-only patch's end-to-end behaviour remain untested.
- What the session does show:
  - the decode-K tail fault is real on H100 (C1r);
  - the guard alone is memory-clean but keeps the stock math (C2r);
  - the 11ea904 kernel is clean and correct in isolation (C2cr);
  - stock attention has memory-clean numeric errors (C2a), which the hardening removes (C3a).
- Cost, deadline, skip and delete all worked. Whether the FAIL closes Phase 6 is the owner's call.

**(B) readiness:**
- **Option 2: NOT READY.** R8 (the patch does not apply as written; the kit's arms test a different patch), no memcheck
  arm on the model path, R9 (embedded consistency unverified) and R1.
- **Option 3: NOT READY.** R13: nothing caches Sheared or sets ARENA_MODEL_ID, the revision/refs issue, the TinyLlama
  hard-wiring, no Sheared-shape kernel tests, and the KL thresholds.
