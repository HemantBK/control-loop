# FIXES.md — fix round after the Opus review (`~/review_opus.md`), PLAN Amendment (12) applied

No GPU was used. Everything below was exercised on the CPU machine: nvcc 12.9.86 compile checks (sm_90, the toolkit under
`~/work/cuda_debs/root/usr/local/cuda-12.9`, same flags as `bench.py`), the gate self-test (34 fixtures), a shimmed dry run of
`drive_session.sh`, and `bash -n` / `py_compile` on every script. Nothing outside the listed findings was changed (REPORT.md and
COMPARISON.md are untouched; this file supersedes their arm list, decision rule and budget).

## Rulings applied (Amendment 12)

- **Rule A, fixed before the run:** PASS iff `C1s` ends in a CUDA error AND `C2` passes AND `C2s` passes. Nothing else enters the
  verdict (`gate.py decision`, line `DECISION rule_A:` is computed only from those three GATE lines).
- **Only the bounds guard.** `patches/rope_guard_only.patch` (copy in `gpu_run/`) adds one kernel parameter and one early return
  and passes `total_pairs` at the launch; no launch check, no shape checks, no `.contiguous()`. Launch checks stay only in the
  diagnostic `stock_launchcheck.patch` (C1c). `rope_bounds.patch` is no longer used by C2/C2s (it remains the base of C3/C3s/C3a,
  information only).
  ```
  -    float base
  +    float base,
  +    int total_pairs             // PATCH(guard_only): number of valid (batch, seq, head, pair) work items
   ) {
       int idx = blockIdx.x * blockDim.x + threadIdx.x;
  +    if (idx >= total_pairs) return;   // PATCH(guard_only): the last block is partial whenever total_pairs % 256 != 0
  ...
  -                static_cast<float>(base)
  +                static_cast<float>(base),
  +                total_pairs
  ```
- **Starter kernels:** `patches/starter_rope_guard_only.patch` = the same three hunks against `starter_kernels/rotary_embedding.cu`
  (7 changed lines). `run_arms.sh apply_variant rope_guard` applies both patches, so the C2/C2s copies are exactly the reopened baseline.
- **Compile check** (`raw/compile_guard_only_sm90.txt`): `kernels/` with the guard: `rotary_embedding.cu (0 warnings)`, link OK,
  `RESULT: COMPILE_OK`; `starter_kernels/rotary_embedding.cu` with the guard: OK, 3 warnings = the starter's pre-existing unused
  variables `total` / `num_elements` (present before the patch), `RESULT: COMPILE_OK`. Both patches apply cleanly with `patch -p1`.
- **C4 is out**: not in the arm list; the `C4` gate branch is dead code.

## R2 — stock control under C2's exact conditions; no cached baseline in C1c

`gpu_run/run_arms.sh`:
```
+arm_C1s() { bench_arm C1s stock; }        # R2: stock kernels, `bash bench.sh --verbose`, identical conditions to C2
 arm_C2() { bench_arm C2 rope_guard; }     # rule A: ONLY the `idx < total_pairs` guard (kernels/ and starter_kernels/)
...
-  local d="$OUT_DIR/C1c"; fresh_copy "$d"; apply_patch ... ; mkdir -p "$d/workspace"
-  cp "$OUT_DIR/C0/workspace/baseline_tps.txt" "$d/workspace/" 2>/dev/null || true
+  local d="$OUT_DIR/C1c"; fresh_copy "$d"; apply_patch "$d" "$PATCH_DIR/stock_launchcheck.patch"   # R2: no cached baseline
```
`bench_arm` is the same function for C1s and C2 (same `fresh_copy`, same `timeout $T_C2 bash bench.sh --verbose`, same env); the
only difference is `apply_variant stock` vs `rope_guard`. `gate.py` has a new `C1s` branch: PASS iff `bench.log` contains a CUDA
error (fields: `err=`, `last_prompt_completed=`); FAIL if the 8 prompts completed, or on timeout/compile failure (rule A then
cannot pass). Evidence: fixtures `C1s_crash` → PASS, `C1s_nocrash` → FAIL, `C1s_timeout` → FAIL, `missing_dir` → NOT_RUN.

## R3 — C2cr input contiguity and bf16 tolerance

`gpu_run/c_kernel_tests.py`:
```
-            x = torch.randn(b, h, s, 64, device="cuda", dtype=dtype).transpose(1, 2)          # non-contiguous
+            x = torch.randn(b, h, s, 64, device="cuda", dtype=dtype).transpose(1, 2).contiguous()   # as inject.py:162-163 (R3)
...
-            c = f.cos().to(dtype)[:, :, None]; sn = f.sin().to(dtype)[:, :, None]
-            hf = torch.cat([x[..., :32] * c - ..., ], -1); ok = ... torch.allclose(y, hf, atol=.02, rtol=.02)
+            xf = x.float(); ...reference computed in fp32...
+            atol = {torch.float32: 1e-4, torch.float16: 1e-2, torch.bfloat16: 6e-2}[dtype]
+            ok = ... torch.allclose(y.float(), hf, atol=atol, rtol=atol)
```
Tolerance rationale, checked on CPU (`raw/` not needed, printed in the session log): a correct kernel computes in fp32 and rounds
once to the dtype; on 4096×64 randn inputs at position 12 that rounding gives maxabs 0.0019 (fp16) and 0.0144 (bf16) against the
fp32 reference, so fp16 1e-2 and bf16 6e-2 (= 2 bf16 ulps at |x|≈4) leave ~4× headroom while an interleaved-pair kernel (stock
math) still fails by O(1). The C2a/C3a attention tolerance was not touched (R3 is about RoPE).

## R4 — C2cs isolates RoPE, 8 prompts × 32 tokens, no memcheck

`gpu_run/c_minimal_kernels.py`: new env `C_OPS=rope|all` (in `rope` mode `Counted.__getattr__` raises `AttributeError` for
`rmsnorm/fused_mlp/attention`, so `inject.py:18 hasattr()` leaves them on PyTorch), `C_PROMPT=all` = `cfg.eval_prompts`, a per-prompt
`MIN_PROMPT_MATCH i yes|no` and the summary `MIN_TEXT_MATCH_C0=yes|no matched=k/8 tokens_each=32`; `MIN_ROPE_CALLS expected=` now
multiplies by the number of prompts. `run_arms.sh arm_C2cs` runs the script twice without the sanitizer:
```
+  ( cd "$d" && C_OPS=rope C_PROMPT=all C_MAX_NEW=32 C_REF=.../c0_outputs.json timeout "$T_CS" python3 c_minimal_kernels.py ) > "$d/bench_rope.log"
+  ( cd "$d" && C_OPS=all  C_PROMPT=all C_MAX_NEW=32 C_REF=.../c0_outputs.json timeout "$T_CS" python3 c_minimal_kernels.py ) > "$d/bench.log"
```
`gate.py` C2cs: PASS iff both runs ran RoPE on every launch, no CUDA error, and `MIN_TEXT_MATCH_C0=yes matched=8/8 tokens_each=32`
in both; a RoPE-only match with an all-ops mismatch is reported as "divergence in another stock op". C0 already records 32 greedy
tokens per prompt (`c0_vanilla.py:26`). Evidence: fixtures `C2cs` → PASS, `C2cs_allfail`, `C2cs_ropefail`, `C2cs_fallback` → FAIL.

## R7 — one global deadline, copy-back after every arm, single-arm mode

- `run_arms.sh`: `bash run_arms.sh <ARM>` runs one arm and appends its GATE line to `$OUT_DIR/SUMMARY.txt` (no longer truncated);
  `bash run_arms.sh decision` prints the decision; unknown arms are logged, not fatal. `T_CS` default 900 → **300 s**.
- New `gpu_run/drive_session.sh <ssh_addr> <alloc_epoch> <arm...>` (CPU machine): per arm, computes `left = epoch + 55 min − now`;
  if `left < timeout(arm)` it writes `GATE <arm> NOT_RUN: skipped by the session deadline (...)` and a `meta.json`, else runs one
  `ssh ... "T_C0=.. T_C2=.. T_CS=.. T_C1B=.. OUT_DIR=/workspace/rootcause bash /workspace/gpu_run/run_arms.sh <arm>"` under
  `timeout (T+180 s)`, then `rsync`s `/workspace/rootcause/<arm>/` (minus `.so`/build dirs) and the pod's `SUMMARY.txt`/`run.log`
  back, and appends the arm's GATE line to the local `SUMMARY.txt`. After the list it runs `gate.py decision` locally.
  The per-arm timeout table is in the driver (`arm_timeout`) and mirrored to the pod through the ssh environment.
- Evidence: `raw/drive_session_dryrun_cpu.txt` (fake `ssh`/`rsync` shims, timeouts 10/5 s, 20 s left before the deadline): C1s, C2,
  C2s, C2cs ran and were pulled one by one, `SKIP C1b: 12s left before the deadline < timeout 1500s`, decision `rule_A: PASS`.
  A bug found by this dry run (multi-source rsync destination turned into a directory) was fixed before the file was recorded.

## R8 — decision block split, verdict keyed on RoPE in `kernels_named`

`gate.py` C1a/C1b/C1r: PASS iff `rotary_embedding_kernel` ∈ `kernels_named` (any invalid-access block attributed to the RoPE kernel);
FAIL only when invalid accesses exist and none is in RoPE. New fields `rope_first=` and `predicted_line_thread=` annotate whether
RoPE is the first block and whether line ∈ {34,47,48,50,51} and thread ≥ 128. Decision block:
```
DECISION defect_demonstrated: YES|NO|UNDECIDED (synthetic reproducers; RoPE in kernels_named: C1r=.. C1a=..)
DECISION debug8_cause_reproduced: YES|NO|UNDECIDED (real benchmark path: C1c=.. C1s=.. C1b=..; C1b_rope_first=.. C1b_kernels=..)
DECISION rule_A: PASS|FAIL (C1s=.. C2=.. C2s=..) -> reopen Phase 6 on the guard-only baseline | do not reopen on this evidence [..]
DECISION info_only (not in the verdict): C2c C2cs C2cr C2r C2a C3a C3 C3s
```
The last GATE line per arm wins (a rerun overrides). Evidence: fixtures `C1r_rope_second` (RoPE flagged after an rmsnorm block) →
PASS, `C1r_fail` (attention only) → FAIL, `decision_pass`, `decision_fail_c1s`, `decision_fail_skipped` (C2s NOT_RUN), `decision_fail_c2`.

## R9 — fixtures and self-test for every gate path

`scripts/gate_selftest.sh` runs `gate.py` on every entry of `raw/gate_selftest/manifest.txt` (fixture, arm, expected verdict) and
asserts the verdict (rule-A token for decision fixtures); full output in `raw/gate_selftest/expected_output.txt`. 34 fixtures:
C0, C1a (+C1x FAIL), C1c, C1s ×3, C1r ×3, C2 (+C2fail, +C2_wrongpatch = old rope_bounds apply.log must FAIL), C2s (+fallback),
C2r ×2, C2cr ×2, C2a ×2 (incl. UNDECIDED), C3a ×2, C2c ×2, C2cs ×4, missing dir → NOT_RUN, decision ×4 (PASS and three FAILs).
Result: `gate_selftest: 34 fixtures, ALL_PASS`. The sanitizer text in the fixtures is still hand-written in compute-sanitizer's
format; to close that gap on the pod, preflight now runs `gate.py parse canary_bad.log` on the real memcheck output of the known-bad
canary and prints `PARSER_OK`, which the preflight gate reports as `parser=ok-on-real-canary-output`.

## Final arm list and order (rule-A arms right after C0), per-arm timeouts, estimates

| # | arm | what | timeout | est. wall |
|---|-----|------|---------|-----------|
| 1 | preflight | env, model cache, sanitizer smoke + canary + parser | 420 s | 2 min |
| 2 | C0 | vanilla model, records 8×32 reference tokens + baseline tps | 600 s | 2.5 min |
| 3 | **C1s** | stock `bash bench.sh --verbose` (rule A: must end in a CUDA error) | 900 s | 2.5 min |
| 4 | **C2** | guard-only kernels + starter, `bash bench.sh --verbose` | 900 s | 3.5 min |
| 5 | **C2s** | guard-only, 1 prompt × 8 tokens under memcheck, launch count | 300 s | 3 min |
| 6 | C1r | stock kernel tests under memcheck (defect demonstrated) | 300 s | 2 min |
| 7 | C1a | stock minimal run under memcheck, strict | 300 s | 2.5 min |
| 8 | C1c | stock + launch checks, blocking, `--prompts 1`, no cached baseline | 900 s | 3 min |
| 9 | C2cs | 11ea904 RoPE, 8×32 tokens, RoPE-only then all ops, no memcheck | 600 s | 4.5 min |
| 10 | C2c | 11ea904 RoPE, full bench.sh | 900 s | 3.5 min |
| 11 | C2cr | 11ea904 kernel tests under memcheck (contiguous input) | 300 s | 2 min |
| 12 | C2r | guard-only kernel tests under memcheck | 300 s | 2 min |
| 13 | C2a | stock attention kernel tests under memcheck | 300 s | 2 min |
| 14 | C3a | hardened attention kernel tests | 300 s | 2 min |
| 15 | C3 | rope_bounds + attention_harden, full bench.sh | 900 s | 3.5 min |
| 16 | C3s | same under memcheck, 8 tokens | 300 s | 3 min |
| 17 | ~~C1b~~ | dropped (Amendment (13)): could never start before its deadline | — | — |

Expected wall ≈ 49 min of arms + ~1 min of ssh/rsync overhead + 5 min pod setup ≈ 55 min; the deadline rule guarantees no arm
*starts* after minute 55 − its timeout, so C1b (1500 s) is skipped unless it can start by minute 30, and the last possible
arm end is minute 55 + 30 s kill grace + rsync, well inside the 75-min watchdog. Worst case all timeouts: the driver skips the
tail of the list; the rule-A arms (3–5) need at most 35 min and always run.
Cost at $3.99/h: expected 55–60 min ≈ **$3.65–3.99**; hard ceiling 75 min = $4.99 < $5 cap.

## Exact invocation (CPU machine, after pod_setup has copied `~/out/gpu_run` to `/workspace/gpu_run` on the pod)

```
EPOCH=$(date +%s)   # taken when the pod is allocated, before pod_setup
SSH_OPTS="-p <port> -i ~/.ssh/id_ed25519" LOCAL_OUT=<a fresh, empty folder> bash ~/out/gpu_run/drive_session.sh root@<pod-ip> $EPOCH \
  preflight C0 C1s C2 C2s C1r C1a C1c C2cs C2c C2cr C2r C2a C3a C3 C3s
# Amendment (13), manager: C1b dropped; LOCAL_OUT must be fresh (the driver refuses a used one; default is timestamped)
# results: $LOCAL_OUT/<arm>/, $LOCAL_OUT/SUMMARY.txt (ends with the DECISION block); then delete the pod
```
