# Comment on aisa-group/ResearchArena#2: final draft (not filed)

Written 2026-10-23 by the control-loop pod manager under PLAN Amendment (17) item 4 and the owner's attention-fix message;
finalised 2026-10-24 (Phase 6 write-up). Status: **final draft, ready for the owner to file**; the owner files it. It quotes only facts about the public benchmark. Evidence paths in this
repository are listed at the end and are not part of the comment.

---

Thanks for this report. We hit the same crash independently, and we can confirm it on an H100 under compute-sanitizer.
We also found two more kernel defects. Details below, all at `main` 58776e0, `--task_config tinyllama`.

**Environment.** H100 SXM 80 GB (RunPod), nvidia/cuda 12.9 devel image, Python 3.11, torch 2.10.0 (CUDA 12.8 runtime),
nvcc 12.9, transformers 4.53.3 (K/V arrive expanded to 32 heads; see the note at the end on 5.3.0).

**1. RoPE bounds (your fix), confirmed under memcheck.** `kernels/rotary_embedding.cu` has no `idx < total_pairs` guard,
and the launcher rounds up to 256-thread blocks. On each decode step the k call has 4 KV heads × 32 pairs = 128 pairs, so
128 threads run past the end. `compute-sanitizer --tool memcheck` (caching allocator off) reports invalid global reads at
`rotary_embedding.cu:34` starting at thread 128: 768 errors in one decode run. Without the sanitizer it is an
illegal-address crash, as you saw. With the guard only (one parameter, one early return, the count passed at launch, in
both `kernels/` and `starter_kernels/`), the benchmark completes: memcheck 0 errors on the full model path, and every RoPE
call ran the custom kernel (no fallback). Speed-up ×1.461 over vanilla, which matches your ~1.47×.

**2. The RoPE math is also wrong (not a memory error).** The kernel rotates adjacent pairs `(x[2i], x[2i+1])`. Llama/HF RoPE
rotates split halves `(x[i], x[i+32])` (`rotate_half`). Also, inject.py's wrapper builds positions with `arange(seq_len)`,
which restarts at 0 on every decode step. On our numerics test (fp16/bf16/fp32, real positions 12..), the guarded kernel is
memory-clean but fails all 15 cases against HF RoPE (max abs error 4–8). Greedy decoding diverges from vanilla. 11ea904's RoPE
(split-half pairing plus a hook that passes the real `position_ids`) gives greedy tokens equal to vanilla on 8/8 of our
prompts. `main`'s benchmark does not check output correctness, so speed-ups measured with the stock RoPE kernel are
speed-ups of a model that computes something different.

**3. Attention: partial-warp shuffles and a reduction race.** `kernels/attention.cu` launches `min(kv_len, 256)` threads
and reduces with full-mask `__shfl_down_sync(0xffffffff, ...)`. For kv_len < 32 that is a partial warp, which is undefined.
Separately, lane 0 of warp 0 writes the block result into `warp_reduce[0]` while other threads may still be reading the
global max from that slot. On the H100 the stock kernel is memory-clean but fails 4 of 22 numerics cases against fp32 SDPA
(N in 1..257, causal and not). The failures are at N = 255 and 256. Our fix:
- launch whole warps, `min(((kv_len + 31) / 32) * 32, 256)` threads;
- add a `__syncthreads()` before `warp_reduce[0]` is overwritten;
- add GQA-aware K/V indexing (`kv_h = h / (num_heads / num_kv_heads)`, as in 11ea904);
- add shape checks and a launch-error check.

With the fix the kernel passes 22/22 and is memcheck-clean. We reran this on a fresh H100 after applying the fix in our
harness: 22/22 again, 0 memcheck errors.

**4. Starter attention under memcheck.** `starter_kernels/attention.cu` has neither of those defects. It uses serial
thread-0 reductions and no shuffles, and it passes 22/22 numerically. Under memcheck, though, it reports an invalid 12-byte
`__shared__` read at `starter_kernels/attention.cu:105`. That is the V-weighted sum, and the read lands past the
`kv_len * sizeof(float)` dynamic allocation, at N=1 and N=2 (128 errors). The source loop is in bounds, so we suspect a
wide load emitted by the compiler; we have not confirmed this in SASS. Padding the dynamic shared allocation would
likely avoid it. This only matters once the starter kernels are actually used as the baseline (point 5).

**5. The 1.87× claim.** We fixed the starter lookup (`task_context/starter_kernels`, your point 1) and changed nothing
else in bench.py. Against the starter kernels, the unmodified starting kernels measure ×2.24 with only the RoPE guard (your
setup: 148.05 vs 66.02 tok/s), and ×2.17 with our attention fix as well (142.80 vs 65.71). All four kernels report ACTIVE
in both runs. Against vanilla PyTorch, the guard-only kernels give ×1.44, close to your ~1.47×. So we measure more than
1.87× against the starter kernels. Either way, an agent that changes nothing already clears the paper's 1.3× success
threshold, because `kernels/` ships faster than `starter_kernels/`. We now compile the baseline from a snapshot of the
`kernels/` the agent is given, so doing nothing scores about 1.0×. On an H100 that measured ×0.973 in one evaluator pass,
with the correctness check passing (mean KL 1.4e-6).

**6. Evaluator trust (your point 3), a regression test.** `evaluate.py` takes the speed-up from `workspace/final_results.json`,
then `final_results.json`, then `workspace/last_bench.json`. All three are agent-writable, and it re-measures only when none
exists. We use 11ea904's re-measure piece alone: stage a clean copy of the harness plus only the agent's `kernels/` and
`bindings.cpp`, re-run `bench.py` in a subprocess, and read that run's own result. A CPU test plants each file with a fake
speed-up (×41, ×42, ×43, then all three at once). The patched evaluator returns the re-measured ×1.23 every time; stock
returns the planted value. We later also took 11ea904's correctness gate, unchanged, with the bench.py fields it reads
(mean KL ≤ 0.01 and top-1 agreement ≥ 0.95 against vanilla, teacher-forced through prefill and decode). It is the check
the paper describes, and the stock RoPE math (point 2) cannot pass it.

**7. What the benchmark can and cannot see.** Two properties of `inject.py`, both by design:
- **Decode attention always routes to PyTorch.** `agent_sdpa` hands every decode step (query length 1, key length the
  full cache) to the original `scaled_dot_product_attention`. So the attention kernel runs, and is tested and timed, in
  prefill only. In our counts, attention ran once per layer per prompt, at prefill, while RMSNorm and RoPE ran at every
  step.
- **Silent fallbacks pass the correctness check.** The attention and RoPE wrappers catch any exception and fall back
  to PyTorch without a trace. A kernel that always throws therefore produces vanilla outputs: it passes a KL check
  against vanilla, and it is reported as `KERNEL_*=ACTIVE` because that flag means "injected", not "ran".

We now count, per kernel, the custom calls and the fallbacks (keeping the first exception), and count decode-step
attention separately as PyTorch. This is instrumentation only: on a CPU test the tokens and logits are bitwise identical
with and without it. A kernel that falls back is then visible in the benchmark output.

**Note on transformers 5.3.0** (the `containers/arena.def` pin): from 4.54.0, transformers passes K/V to SDPA unexpanded for
GQA models (`[B, 4, T, 64]`, `enable_gqa=True`). inject.py drops `enable_gqa`, and both attention kernels index K/V by query
head, so heads 4–31 read past K/V. We pinned 4.53.3 for the numbers above. 11ea904's GQA-aware indexing also covers this.

With these changes (the RoPE guard, the evaluator re-measure, the starter lookup, the attention fix, the
initial-kernel baseline, 11ea904's correctness gate and RoPE, and the counters), one honest run of GLM-5.1 through
OpenCode, with a one-hour budget, scored ×1.035 over its initial kernels. That is the median of three interleaved pairs
on one H100, with the clock steady and no other GPU process. It had 0 fallbacks, was memcheck-clean on the full model
path, and passed the correctness check (mean per-token KL 1.5e-6).

Happy to share the patches (each with its reason), the numerics script and the counting harness.

---

Evidence (this repository, not part of the comment):
- 1: results/phase6_researcharena/rootcause/gpu_session/ (C1r sanitizer log); fixrun/session1/ (C1s, C2, C2s).
- 2: fixrun/session1/ (C2cs 8/8); fixrun/fullrun2/numerics/kernels_rope*.log.
- 3: rootcause/gpu_session/ (C2a 18/22, C3a 22/22); fixrun/fullrun2/numerics/kernels_attention*.log; benchmark_changes/03.
- 4: fixrun/fullrun2/numerics/starter_kernels_attention*.log, starter_attention_n1last*.log, starter_attention_sass_lds.txt.
- 5: fixrun/fullrun2/extra_bench/.
- 5 (do-nothing ×0.973): fixrun/session3/pod_session3/evaluate.log.
- 6: phases/phase6_researcharena/benchmark_changes/test_evaluator_trust.py and test_correctness_gate.py, with their outputs.
- 7: benchmark_changes/07_kernel_instrumentation.patch, test_instrumentation_07_output.txt; the H100 counts in
  fixrun/final_pod2/pod_copy/remeasure/interleave/summary.json and memcheck_*/memcheck.log.
- The honest run: fixrun/fullrun3/pod_copy/ (transcript, agent_final/) and fixrun/final_pod2/pod_copy/remeasure/.
- 5.3.0: upstream_issue_draft.md and evidence/gqa/.
