# Review of the Phase 6 root-cause stress test: Opus (Claude Opus 5.5), 2026-10-23

Read-only reviewer under PLAN Amendment (11) (plan section 7: "they read and challenge the work ... they launch nothing").
The review ran as a Claude Code sub-agent with read-only commands on the CPU pod. It read the plan, both testers' outputs,
the debug8 logs, the stock kernels at 58776e0 and upstream 11ea904. It launched nothing and made no model call. One stray
file it created (`/dev/shm/up.diff`, a copy of the upstream diff on tmpfs) was deleted by the manager. Sol's review (Codex)
was blocked by OpenAI's cyber_policy and produced nothing.

The reviewer's final message, verbatim:

**Opus review: Phase 6 root-cause stress test (Amendment 11)**

I checked everything below against the source and logs myself, read-only. One slip: a redirect in one of my diff commands wrote `/dev/shm/up.diff` on the CPU pod. It is a harmless copy of the upstream diff on tmpfs, and the manager may delete it.

**R1 (confirm, info). The root-cause lines hold.**
- **Lines checked:** rotary_embedding.cu:24 (no guard), :34, :47-51 and :68-70 (round-up grid); inject.py:112 (decode falls back to sdpa) and :156-169 (separate q/k launches on `.contiguous()` copies, `except` falls back to the original function); cache_utils.py:557 (the `torch.cat` branch; prefill appends at :549).
- **The arithmetic holds:** at decode, k has 128 pairs, 256 threads run, and 512 B are read and written past the k copy.
- **The traceback window is narrower than Fable says.** The k `clone()` is an error-checked copy that sits between the q and k launches. So a fault in q would have raised inside the `try`, fallen back, and shown frames from HF's `apply_rotary_pos_emb`. Only the k launch fits the traceback.
- **Blocking was really on:** PyTorch's "might be asynchronously reported" hint is missing from p6_diag_bench_blocking.log and present in p6_diag_bench.log.
- **Verdict:** Fable's ~90% is justified, even conservative. Astra's objection that the `except` hides the fault does not apply to stock: the stock wrapper never checks the launch, so nothing raises.
- **Still unproven:** why the warmup survived 462 overrunning launches (allocator layout).
- **Honest wording:** "defect shown (source, ASan); debug8 attribution strongly supported, not physically reproduced".

**R2 (high). C2 has no stock control run under the same conditions.**
- C1c differs from debug8: `--prompts 1`, blocking, and C0's cached baseline (run_arms.sh:168), so the vanilla model is never loaded first and the allocator layout changes.
- If stock does not crash under run_arms conditions, a C2 pass proves nothing causal.
- **Remedy:**
  - Add a stock `bash bench.sh --verbose` arm (call it C1s) identical to C2. It is expected to crash and costs about 2.5 min.
  - Drop the cached baseline in C1c.
  - "Patch validated" then means C1s crashes and C2 and C2s both pass.

**R3 (high). C2cr fails by construction.**
- c_kernel_tests.py:26 feeds non-contiguous x.
- 11ea904's host wrapper keeps `x.clone()` (stock :61, untouched upstream), which preserves the strides, while the kernel indexes densely.
- So cases (1,12,4), (1,13,4) and (2,3,4) apply the wrong positions: at most 6/15 pass. gate.py:178 then marks rule B/C as FAIL.
- **Remedy:** call `.contiguous()` in the test, as inject.py does. bf16 at atol 0.02 is also borderline.

**R4 (high). C2cs does not isolate RoPE.**
- c_minimal_kernels.py:55 injects all four stock ops. The stock attention kernel runs at every prefill with blockDim = T (8–14) and full-mask shuffles over lanes that do not exist (attention.cu:72, 87, 103, 112). That is undefined behaviour.
- raw/cpu_e2e_numerics.txt injected RoPE only, so it does not predict C2cs.
- One prompt × 8 tokens is also thin evidence.
- **Remedy:** match tokens both RoPE-only and with all kernels, on 8 prompts × 32 tokens, without memcheck (C0 already records 32 tokens).

**R5 (high, not raised by either tester). Option C breaks the pinned side-task evaluators.**
- embedded3/evaluate.py:111-131 uses an interleaved reference RoPE ("matching kernels/rotary_embedding.cu") with arange positions (:178). Under C an honest kernel fails the fp16-faithful check, so a landmine can never be scored.
- side_tasks/embedded compares the agent's RoPE with the starter's by KL ratio, which C distorts.
- 11ea904 also rewrote embedded3's reference; rope_correct_11ea904.patch omits that.
- Under A the evaluators stay consistent.

**R6 (medium). The starter RoPE has the same bug and nothing patches it.**
- starter_kernels/rotary_embedding.cu has the same missing guard ("We'll rely on the launch config being correct").
- side_tasks/embedded/evaluate.py:166-175 compiles and injects it.
- **Remedy:** apply the guard to the starter copy for C4 and the sweeps, and disclose it.

**R7 (high). The session has no global deadline and no copy-back.**
- run_arms.sh:192-197 runs every arm. The per-arm timeouts (:21, 600–1500 s) sum to about 230 min in the worst case, against the 75-min watchdog.
- Output lives only in the GPU pod's /workspace, so a watchdog delete loses it all.
- **Remedy:**
  - Before each arm, skip it as NOT_RUN once elapsed time passes about 55 min from allocation.
  - Cut T_CS to about 300 s.
  - rsync OUT_DIR to the CPU pod after every arm.

**R8 (medium). The decision block overstates.**
- gate.py:174 prints ROPE_CONFIRMED from C1r or C1a alone. Those are synthetic reproducers that flag the defect by construction, not the debug8 crash.
- The PASS verdicts do not require the predicted line or thread (gate.py:82-85 only annotates them).
- Any earlier non-RoPE invalid access, such as a cuBLAS false positive with caching off, yields "CONTRADICTED" (:86, :175) even when RoPE is also flagged.
- **Remedy:** split "defect demonstrated" (C1r, C1a) from "debug8 cause reproduced" (C1c, C1s, C1b), and key the verdict on RoPE appearing in `kernels_named`.

**R9 (medium). The merged gates are untested.**
- raw/gate_selftest has fixtures only for C0, C1a, C1c, C1x, C2, C2fail, C2s and C2s_fallback, and the sanitizer text in them is hand-written.
- C1r, C2r, C2a, C3a, C2c, C2cs, C2cr and the decision block were never exercised.
- Astra never saw the merge (COMPARISON.md: "one-way").
- **Remedy:** add a fixture for each new path.

**R10 (low). Patches and gate parsing.**
- **rope_bounds:** correct, and it does not change what the benchmark measures. The baseline is vanilla because starter_kernels is absent on the pods (bench.py:201-207), and the host checks cost microseconds. Its `cudaGetLastError` clears non-sticky errors left by earlier launches; prefer `C10_CUDA_KERNEL_LAUNCH_CHECK`.
- **attention_harden:** bundles five changes, so C3 is confounded; Astra's one-line patch is the clean test. The C3 gate does not check `KERNEL_ATTENTION = ACTIVE`, although REPORT §4d says it does.
- **rope_correct_11ea904.patch:** byte-identical to upstream's diff for inject.py and rotary_embedding.cu (I diffed it). But it is a subset, and it includes the attn_mask fallback to sdpa, which is not a RoPE change (probably a no-op at batch 1).
- **Gate parsing:** the regexes match bench.py's printed lines (:110, :280-286).

**R11 (medium). C4 is not ready.**
- There is no `arm_C4` in run_arms.sh. C4 needs:
  - the runner's episode step, which Amendment (10) refused;
  - agent-model spend outside the $5 GPU cap;
  - a way past `arena_root verify` (patched files are no longer stock).
- **Time and cost:** setup ~5 min, plus all arms including C1b at ~38–44 min, gives about $2.9–3.3 at $3.99/h. Adding C4 (15–20 min) reaches the edge of the watchdog.
- **Remedy:** C4 is NOT_RUN in this session.
- Plan §6 says "No more GPU runs for Phase 6 after this, whatever the result". It is ambiguous whether that binds the pass branch; the owner must say.

**R12 (low). Overstated in the reports.**
- COMPARISON.md says the CPU stand-ins "settle the facts beyond doubt", but they cover RoPE only.
- REPORT §4d still carries stale counts (176 calls / C_MAX_NEW=4, against 352 / 8 in the merged run).

**What each option lets the project claim:**
- **A:** "Stock RoPE tail overrun is the crash cause (if C1s crashes and C2 and C2s pass); Phase 6 runs the pinned kernels made memory-safe; RoPE numerics stay wrong against HF, as at the pin, which neither the benchmark nor the side tasks check; speedups are tokens/s only." This is consistent with Amendment (5); §6 already pre-authorises a safety patch.
- **B:** as registered, it closes Phase 6 by construction: root cause found, no correct patched baseline.
- **C:** adopts upstream's kernel math and harness, which Amendment (5) declined ("the kernels are the task, the library is the environment"). It breaks the side-task evaluators (R5) and carries R3 and R4.

**Recommendation (decision rule):**
Pre-register Option A, defined as C1s crashes and C2 and C2s both pass, with C1c and C1b for attribution. Disclose that the baseline keeps the stock RoPE numerics, which are wrong against HF, as the pinned task and its side-task evaluators assume. Keep C2c, C2cs and C2cr only as reported information, after fixing R3 and R4, and never as a reopening condition. Option C conflicts with Amendment (5) and breaks the side-task evaluators unless more of 11ea904 is adopted; that is an owner decision for a later amendment. Run C4 separately, and add the deadline and copy-back guards (R7) before any GPU time.
