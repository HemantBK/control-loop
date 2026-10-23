# Phase 6 root-cause stress test — report (Fable)

Scope: plan `00_rootcause_plan.md` section 4 (4a, 4c = Steps A and B, 4b, 4d, 4e). Everything here was done on the CPU
machine; no GPU, no pod, no model API. Scripts, raw outputs and patches are under `~/out/{scripts,raw,patches,gpu_run}`.

## Summary

1. **The faulting kernel is the stock RoPE kernel, on the k launch, but not for the reason the plan gives.** The plan's
   mechanism ("k sized or indexed with q's head count", "non-contiguous k") is contradicted by the code: inject.py launches
   q and k separately with their own shapes (`inject.py:162-165`) on `.contiguous()` copies (`:162-163`), and the launcher
   takes every size from the tensor it is given (`rotary_embedding.cu:62-65`). The real defect is `rotary_embedding.cu:24`
   plus `:68-70`: `blocks = ceil(total_pairs/256)` with **no `idx >= total_pairs` guard**. For k (4 K/V heads × 32 pairs =
   128 pairs per token) every decode step launches 256 threads for 128 work items; threads 128-255 read `positions[1]` of a
   4-byte tensor (`:34`) and read/write 512 bytes past the end of the 512-byte k clone (`:47-51`). q (1024 pairs = 4 full
   blocks) never overruns; k at prefill overruns iff the prompt length is odd (prompts 4, 5 = 13 tokens, 6 = 11 tokens).
   GQA is still the enabling condition: with 32 K/V heads the k launch would always be whole blocks.
2. **The debug8 traceback pins it to the RoPE launches.** `cache_utils.py:557` is the `torch.cat` branch, reached only on
   decode steps (prefill appends, `:549`); under `CUDA_LAUNCH_BLOCKING=1` the only CUDA launches between the previous
   error-checked PyTorch op (the `clone()`s inside the wrapper) and that `torch.cat` are the two unchecked rotary launches
   (`rotary_embedding.cu:75-80`, no `cudaGetLastError`). The q launch has no out-of-bounds thread; the k launch has 128.
   The attention kernel is not even called on decode steps (`inject.py:112-118`); rmsnorm/fused_mlp faults would have
   surfaced at `q_proj`/the residual add, and errors inside the wrapper's own `clone()` would have taken the
   `except → orig_fn` path (`inject.py:168-169`), neither of which is what the traceback shows.
3. **Verdict on the main hypothesis: supported as "the RoPE kernel on k faults", contradicted in its stated mechanism.**
   Why warmup survived 462 overrunning launches and prompt 1 did not is explained but not proven: a 512-byte overrun only
   faults when the clone sits at the end of a caching-allocator segment; which allocation lands there is deterministic but
   layout-dependent. C1 (memcheck with `PYTORCH_NO_CUDA_MEMORY_CACHING=1`) removes that dependence and will flag the first
   overrun at the first decode step of warmup.
4. **Step A.1 (CPU, float16, transformers 4.53.3, torch 2.10.0):** at `apply_rotary_pos_emb` q = [1,32,T,64], k =
   [1,4,T,64] (non-contiguous transposes at prefill, contiguous at T=1); at the attention op k = [1,32,T,64] after
   `repeat_kv`; the cache update takes the `torch.cat` branch only at decode. The launcher arithmetic applied to those
   tensors: q 1024·T pairs, always whole blocks; k 128·T pairs, 128 out-of-bounds threads at every decode step.
5. **Step B:** `rope_bounds.patch` (guard + checks + launch error check, 26 added lines) compiles with the pod's nvcc
   12.9.86 against torch 2.10.0 headers for sm_90; a CPU AddressSanitizer harness driving the extracted kernel text shows
   the stock kernel overflowing on exactly the predicted launches and the patched kernel clean. The patch does not change
   the kernel's arithmetic, grid or numerics, so it does not change what the benchmark measures (tokens/s); the stock
   numerics stay wrong (interleaved pairs, positions reset to 0 on decode), which the benchmark does not check.
   `attention_harden.patch` is provided for C3 but Step A does not implicate the attention kernel in the crash.
6. **Plan attack (4b):** the plan's C1 as written would be weak (memcheck cannot see an overrun that stays inside a
   PyTorch caching-allocator segment, and the pod's bench recompiles for 3 GPU archs under the tool); fixed by
   `PYTORCH_NO_CUDA_MEMORY_CACHING=1`, a cached baseline, a minimal driver, and a tool-independent arm C1c
   (`CUDA_LAUNCH_BLOCKING=1` + a launch-check-only build of the stock kernels). C2 can "pass" with the kernel silently not
   running (inject.py's `except → fallback`), so C2 is paired with C2s, which counts launches. `compute-sanitizer` should
   be on the image (it is `FROM nvidia/cuda:12.9.0-cudnn-devel`, whose `cuda-command-line-tools-12-9` depends on
   `cuda-sanitizer-12-9`); a preflight with a 10-s smoke and a no-root `.deb` fallback covers the rest.
7. **Gates (4d)** are in `gpu_run/gate.py` (one line per arm) and the one-session orchestrator `gpu_run/run_arms.sh`;
   **early-stop risks (4e)** are listed with guards. Budget estimate for preflight + C0..C3s: 20-27 min on an H100
   (~$1.5-1.8); C4 (an episode) is ~35-45 min more and does not fit the $5 cap together with the rest unless C1b/C3/C3s
   are dropped — flagged for the manager.

Confidence per conclusion is given at the end of each section.

> **Added after the comparison round:** `COMPARISON.md` merges the second tester's arms (standalone kernel memcheck,
> canary, numerics tests, strict proxy) into `gpu_run/`, adds the 11ea904-RoPE arm (C2c), and states the decision-rule
> options; `raw/cpu_e2e_numerics.txt` shows the bounds-only baseline generates garbage text while the 11ea904 RoPE
> reproduces vanilla greedy tokens exactly. The merged session order and budget there supersede section 4d/4e's.

---

## 4a. Every other cause that fits the evidence, and what tells it apart from RoPE

Evidence to fit: (i) vanilla model passes 8 prompts on the same pod (`debug8/p6_diag_bench.log`, BASELINE_TPS 102.53);
(ii) stock kernels pass the 3 warmups ("Hello", 2 tokens, 8 new) and crash during prompt 1 (12 tokens, 128 new), in both
the normal and the `CUDA_LAUNCH_BLOCKING=1` run; (iii) blocking traceback ends in `cache_utils.py:557` (`torch.cat`) called
from `modeling_llama.py:241` under `inject.py:134`; (iv) the probe saw 32/32 heads at `ops.attention` (prefill only: 22
calls, decode falls back at `inject.py:112`).

| # | Candidate | Where (file:line) | Fits the evidence? | What tells it apart from RoPE |
|---|---|---|---|---|
| 1 | **Attention kernel** reads K/V past the end | `attention.cu:34` (`num_heads = gridDim.y` = Q heads), `:61`, `:129` index K/V with the query head | Only if K/V arrive with 4 heads. Under 4.53.3 `sdpa_attention.py:40-42` calls `repeat_kv` unconditionally → 32/32 (probe + A.1). All Q/K/V/smem indices are then in bounds (`:37`, `:61`, `:129`, `:155`; smem = (T+64)·4 B). It is **never called on decode steps** (`inject.py:112-118`), and the blocking traceback is a decode step (see A.2). | C1 names the kernel; C2 (RoPE-only patch) passing excludes it; under blocking launches a fault in it would surface in `sdpa_attention.py`/`inject.py:123`, not `cache_utils.py:557`. Residual defects (not faults): partial-warp `__shfl_down_sync(0xffffffff)` at T<32 (`:72,87,103,112`), a `warp_reduce[0]` read/write race between `:91` and `:105`, and `attn_mask` ignored (`inject.py:107-123`) — wrong numbers, not addresses. |
| 2 | **dtype mismatch** | `rotary_embedding.cu:72-74` dispatches on `x.scalar_type()` (Half for the fp16 model, `config.py:26`); `positions.data_ptr<int>()` (`:77`) requires int32, which `inject.py:160` creates | No. A dtype error throws a C++ `TypeError` before any launch, inject.py's `except` (`:168`) would silently fall back to HF RoPE, and nothing would crash. | A dtype problem produces *no* crash and no kernel use; C2s's call/exception counters show whether the kernel really ran. |
| 3 | **Wrapper returns wrong strides / dangling pointer** | `inject.py:164-167`: outputs are fresh tensors (`x.clone()`, `rotary_embedding.cu:61`) returned as `permute(0,2,1,3)` views; Python owns them | No. The returned k view has the same strides as HF's own transposed k (A.1: `[512,64,256,1]` at T=2 both ways); `torch.cat` handles any strides from metadata, not device memory. | Strides live in host metadata; they cannot cause a device-side illegal address. C0/A.1 show HF's own k is equally non-contiguous. |
| 4 | **Grid/block sizing (no tail guard)** | `rotary_embedding.cu:24` (no guard), `:68-70` (`blocks = (total_pairs+255)/256`), `:34` and `:47-51` (accesses) | **Yes — this is the fault.** k decode: 128 pairs, 1 block of 256 → threads 128-255 read `positions[1]` (tensor has 1 element) and touch x[256..511] of a 256-element clone (512 B past the end). k prefill: overrun iff T odd. q: never. | This *is* the RoPE kernel, but not the plan's mechanism: `num_heads` comes from `x.size(2)` of the tensor launched (`:64`), not from q. A 32-K/V-head model would never overrun. Decisive: C1 reports thread index ≥128 of block 0 at `rotary_embedding.cu:34/47-51` with "nearest allocation of size 4 / 512 bytes". |
| 5 | **Sequence-length / position-ids mismatch** | `inject.py:158-161`: `seq_len = q.shape[2]` (correct dim), `positions = arange(seq_len)` — on decode every token gets position 0 instead of the real `cache_position` (A.1: real ids [2],[3],[12],[13]) | Not as a crash: the positions tensor is sized to `seq_len`, in-bounds threads index `< seq_len`. It is a **numerics** bug (CPU emulation: max |Δ| vs HF 3.4-4.8 on decode). | Wrong text, no fault. Would persist after the bounds patch; only 11ea904's inject.py hook fixes it. |
| 6 | **cos/sin cache too short** | `inject.py:156` receives `cos, sin` and ignores them; the kernel recomputes angles (`rotary_embedding.cu:36-41`); HF computes cos/sin per forward from `position_ids` (`modeling_llama.py:91`, A.1: cos = [1,T,64]) | No: nothing indexes cos/sin on the injected path, and there is no cache. | n/a (excluded by code reading). |
| 7 | **The cache code itself** | `cache_utils.py:544-558`: list of tensors, `append` on first sight (`:549`), `torch.cat` after (`:557`) | No: it runs 8×128 steps in the vanilla run; `torch.cat` on fp16 [1,4,L,64]+[1,4,1,64] is a plain PyTorch kernel. It is the **reporter**: the first error-checked CUDA call after two unchecked launches. | C0 passes; under blocking launches the error can only originate in the window described in A.2. |
| 8 | rmsnorm kernel | `rmsnorm.cu:22-24, 28, 60-63`: row = blockIdx.x < batch rows, loops bounded by `hidden_size`; `inject.py:63` `view(-1, 2048)` on a contiguous residual stream | In bounds; and under blocking launches a fault would surface at `q_proj` (`modeling_llama.py:231`), not `:241`. | Traceback position. |
| 9 | fused_mlp kernel | `fused_mlp.cu:25` has an `idx < N` guard; GEMMs are cuBLAS (`:42-43`) | In bounds; runs after attention, so a fault would surface at the residual add of the same layer. | Traceback position. |
| 10 | Interleaved pair layout `(2i, 2i+1)` vs HF `rotate_half` `(i, i+32)` | `rotary_embedding.cu:44-45` vs `modeling_llama.py:105-110,134-135` | Numerics only (CPU emulation: max |Δ| 6.1 (q) / 12.9 (k) at prefill; 0.004 with the rotate_half layout). | No address effect. |
| 11 | Unchecked launches mis-attribute every error | `rotary_embedding.cu:75-80`, `attention.cu:160-166`, `rmsnorm.cu:80-85`, `fused_mlp.cu:53-57` (no `cudaGetLastError`) | Explains why the faulting kernel "is not named" in debug8. | `stock_launchcheck.patch` + `CUDA_LAUNCH_BLOCKING=1` (arm C1c) names the op without any tool. |
| 12 | `positions.expand(batch,-1)` is stride-0 for batch>1 | `inject.py:161` + `rotary_embedding.cu:34` indexes `[batch*seq_len+seq]` | Not here (batch = 1 throughout the benchmark). | Would be a second overrun only with batched prompts. |
| 13 | Double injection wraps the wrapper | `inject.py:149` captures whatever `apply_rotary_pos_emb` currently is; 11ea904 pins the original | Not here: on the pods `starter_kernels` is absent (`bench.py:197-204`), so inject runs once per process. | n/a. |
| 14 | Driver/toolkit mismatch (driver 595.91 / CUDA 13.2, torch cu128, nvcc 12.9, arch list 8.0;8.9;9.0) | `p6_diag_info.txt`, `setup.log` | No: compile passes, vanilla passes, sm_90 is in the list. | C0. |
| 15 | GPU-side corruption from an earlier overrun being *used* later (e.g. a corrupted index tensor) | the overrun lands in whatever 512-B block follows the k clone | Cannot produce the observed traceback: a corrupted index would fault in an indexing kernel (embedding/gather), and the data in that window is float. It can corrupt neighbouring activations silently (a numerics risk in any "surviving" run). | memcheck sees the write regardless of what it hits. |

The "GQA / head-layout" reading of Amendment (5) is wrong about *where* (attention) but right that 4 K/V heads are the
enabling condition: `128·T % 256 != 0` needs `T·H_kv·32` not divisible by 256, i.e. H_kv = 4 with odd T or T = 1.

**Confidence:** that no candidate other than #4 fits the blocking traceback: high (~90%); the residual is a mechanism I
have not thought of inside the same two launches (e.g. the positions read landing on unmapped memory first — same kernel,
same gate).

---

## 4c / Step A

### A.1 — CPU run with hooks (no custom kernels)

Script `scripts/a1_cpu_hooks.py`; raw `raw/a1_cpu_hooks_fp16.json`; readable `raw/a1_summary.txt`. Environment: Python
3.11, torch 2.10.0+cpu, transformers 4.53.3, TinyLlama-1.1B-Chat-v1.0 snapshot `fe8a4ea1…` (the same snapshot the pod
cached), **float16 on CPU** (the benchmark's dtype, `config.py:26`; the CPU ran it, so no float32 fallback was needed),
`attn_implementation = sdpa`, 32 query heads, 4 K/V heads, head_dim 64, 22 layers, rope_theta 10000. Hooks: the module
symbol `modeling_llama.apply_rotary_pos_emb` (what `inject.py:172` replaces), `DynamicCache.update`,
`torch.nn.functional.scaled_dot_product_attention` (what `inject.py:132` replaces), `model.model.rotary_emb.forward`
(cos/sin and position_ids), and `model.forward` (input_ids, cache_position). One prefill + two decode steps
(`max_new_tokens=3`) for the warmup prompt "Hello" (T = 2) and benchmark prompt 1 (T = 12). Greedy text is sane
("Hello, World!"; "…How does it").

Layer 0 (all 22 layers identical per step):

| step | where | q | k | other |
|---|---|---|---|---|
| prefill T=2 | apply_rotary_pos_emb | [1,32,2,64] stride [4096,64,2048,1] **contig=False** fp16 | [1,4,2,64] stride [512,64,256,1] **contig=False** fp16 | cos/sin [1,2,64] contig fp16; position_ids [0,1] int64; positions(inject)=arange int32 [0,1] |
| prefill T=2 | cache.update | | key_states [1,4,2,64] non-contig | branch **append** (no torch.cat) |
| prefill T=2 | sdpa | [1,32,2,64] contig | **[1,32,2,64]** contig (after repeat_kv) | mask None, is_causal True, scale 0.125 → inject would call `ops.attention` |
| decode 1 | apply_rotary_pos_emb | [1,32,1,64] stride [2048,64,2048,1] contig=True | [1,4,1,64] stride [256,64,256,1] contig=True | cos/sin [1,1,64]; position_ids **[2]**; positions(inject)=**[0]** |
| decode 1 | cache.update | | key_states [1,4,1,64] | branch **torch.cat (cache_utils.py:557)**; cache [1,4,2,64]→[1,4,3,64] |
| decode 1 | sdpa | [1,32,1,64] | [1,32,3,64] | is_causal False → q_len≠k_len → inject falls back to native sdpa |
| decode 2 | same as decode 1 with position_ids [3], cache →[1,4,4,64] | | | |
| prefill T=12 | apply_rotary_pos_emb | [1,32,12,64] stride [24576,64,2048,1] contig=False | [1,4,12,64] stride [3072,64,256,1] contig=False | position_ids 0..11 |
| decode 1 (T=12) | apply_rotary_pos_emb | [1,32,1,64] contig | [1,4,1,64] contig | position_ids [12], positions(inject) [0]; cache.update = torch.cat → [1,4,13,64] |

So: q has 32 heads and k 4 at RoPE; 32 and 32 at the attention op — the plan's expectation holds. `torch.cat` at
`cache_utils.py:557` is reached only on decode steps.

**Stock launcher/kernel arithmetic applied to those exact tensors** (Python re-implementation of
`rotary_embedding.cu:62-70` and `:24-45` in the same script; `inject.py:162-163` hands the kernel
`q_t = [1,T,32,64]`, `k_t = [1,T,4,64]`, both contiguous):

| launch | total_pairs | blocks×256 | launched | OOB threads | positions read past end | x bytes past end | first OOB thread |
|---|---|---|---|---|---|---|---|
| q, T=2 | 2048 | 8 | 2048 | 0 | 0 | 0 | — |
| k, T=2 | 256 | 1 | 256 | 0 | 0 | 0 | — |
| q, T=12 | 12288 | 48 | 12288 | 0 | 0 | 0 | — |
| k, T=12 | 1536 | 6 | 1536 | 0 | 0 | 0 | — |
| **q, decode (T=1)** | 1024 | 4 | 1024 | 0 | 0 | 0 | — |
| **k, decode (T=1)** | **128** | **1** | **256** | **128** | **128 threads read positions[1] (tensor: 1 element, 4 B)** | **512 B (x[256..511] of a 256-element, 512-B clone)** | idx 128 = block 0 thread 128 → batch=1, seq=0, head=0, pair=0, positions[1], x[256],x[257] |
| k, T=13 (prompts 4,5) / T=11 (prompt 6) | 1664 / 1408 | 7 / 6 | 1792 / 1536 | 128 | 128 (positions[T..2T-1]) | 512 B | last block, thread 128 |

(All in-bounds threads stay inside the tensor: max index touched = numel−1.) Prompt lengths with TinyLlama's tokenizer:
Hello 2; prompts 1-8: 12, 14, 10, 13, 13, 11, 8, 10 (`raw/a1_rope_numerics.json`).

**CPU numerics of the kernel's arithmetic vs HF** (`scripts/a1_rope_numerics_cpu.py`, `raw/a1_rope_numerics.txt`, real
layer-0 tensors, fp32 math as the kernel does): stock math (arange positions, interleaved pairs) differs from HF's
`apply_rotary_pos_emb` by max |Δ| 6.08 (q) / 12.9 (k) at prefill T=12 and 3.4 / 4.4 at decode; rotate_half pairs with the
real position ids (= 11ea904 kernel + its inject.py change) match to 0.004 / 0.002 (fp16 rounding). The bounds-only
patch keeps the stock numbers. This is a correctness defect of the stock kernels, not a crash cause, and the benchmark
(`bench.py:86-114`) never checks outputs (`config.py:59-60` thresholds are unused at 58776e0).

### A.2 — Stock RoPE kernel and launcher (`kernels/rotary_embedding.cu`; `starter_kernels/rotary_embedding.cu` has the same structure, with a comment at its lines 41-44 that says "We'll rely on the launch config being correct")

- **k sized/indexed with q's head count?** No. `agent_rotary_embedding(x, positions, base)` (`:56-60`) takes `batch,
  seq_len, num_heads, head_dim` from `x.size(0..3)` (`:62-65`); inject.py calls it once for `q_t` and once for `k_t`
  (`inject.py:164-165`). The kernel's `num_heads` (`:29-30`, `:43`) is the launched tensor's own.
- **Contiguous input assumed?** Yes: the kernel indexes `((batch*seq_len+seq)*num_heads+head)*head_dim + 2*pair`
  (`:43-45`) on `output = x.clone()` (`:61`); `clone()` preserves strides, so a non-contiguous `x` would be indexed wrongly.
  inject.py guarantees contiguity (`:162-163`, A.1 confirms `q_t`/`k_t` contig=True), so this is not the cause here.
- **Bounds check?** None. `idx` (`:24`) is used unconditionally; the launcher rounds up (`:70`).
- **Grid/block:** `threads = 256`, `blocks = (total_pairs + 255) / 256`, `total_pairs = batch*seq_len*num_heads*head_dim/2`
  (`:66-70`); launch `<<<blocks, threads>>>` (`:75`), no `cudaGetLastError`/`C10_CUDA_KERNEL_LAUNCH_CHECK` (`:75-82`).
- **dtype:** `AT_DISPATCH_FLOATING_TYPES_AND2(Half, BFloat16, x.scalar_type(), …)` (`:72-74`) → fp16 → `c10::Half`;
  arithmetic in fp32 (`:47-51`); positions must be int32 (`:77`, `data_ptr<int>()` throws otherwise).
- **Extra:** positions ignore the real position ids (`inject.py:159-161`), pair layout interleaved (`:44-45`), fast-math
  intrinsics (`:36-41`).

### A.3 — Stock attention kernel (`kernels/attention.cu`)

- Grid `(batch, heads=Q.size(1), q_len)` (`:144-153`), `threads = min(kv_len, 256)` (`:154`), dynamic smem `(kv_len +
  head_dim)·4` B (`:155`), launch unchecked (`:157-168`).
- K/V indexed with the **query** head `h` and `num_heads = gridDim.y` (`:34`, `:61`, `:129`): correct only if K/V arrive
  expanded, which 4.53.3 guarantees (`sdpa_attention.py:40-42`) and the probe confirmed. Reads are then bounded by
  `kv_len·head_dim` per (b,h) (`:56`, `:128`); writes by `q_len·head_dim` (`:132`).
- Contiguity assumed; `inject.py:120-122` provides it. dtype dispatch as RoPE (`:157-159`).
- Not called when `q_len ≠ kv_len` (`inject.py:112-118`), i.e. only at prefill (A.1), so it cannot be the kernel in a
  decode-step traceback. Numerics defects (no address effect): full-mask shuffles on partial warps (`:71-72, 86-87,
  102-103, 111-112` with blockDim = T = 2…14), `warp_reduce[0]` race (`:91` read vs `:105` write, no barrier between),
  `attn_mask` dropped (`inject.py:107-109, 123`).

### A.4 — Injection wrapper (`task_context/inject.py`)

- RoPE (`:146-176`): replaces the module function `modeling_llama.apply_rotary_pos_emb` (`:172`), which
  `LlamaAttention.forward` looks up by global name (`modeling_llama.py:236`), so the patch takes. Passes in:
  `positions = arange(seq_len, int32).unsqueeze(0).expand(batch,-1)` (`:159-161`; stride-0 batch dim if batch>1),
  `q_t = q.permute(0,2,1,3).contiguous()` (`:162`), `k_t` likewise (`:163`), `float(base)` from `config.rope_theta`
  (`:151-153`). Outputs: new tensors from the kernel's `clone()` (`rotary_embedding.cu:61`), returned as
  `permute(0,2,1,3)` views (`:166-167`) → shape [B,H,T,D], strides `[T·H·64, 64, H·64, 1]` — the same stride pattern as
  HF's own transposed q/k (A.1). Nothing is written in place; nothing dangles. **Any exception falls back silently to
  HF's function (`:168-169`)**, so a wrapper/kernel that *throws* yields a passing-looking run with no kernel used.
- Attention (`:94-141`): swaps `F.scaled_dot_product_attention` for the duration of `attn.forward` (`:132-136`); falls
  back to native sdpa on decode (`:112-118`) and on **any exception** (`:124-130`); passes `.contiguous()` q/k/v and
  `is_causal` only (`:120-123`).
- RMSNorm (`:60-68`): `hidden_states.view(-1, hidden)` then `ops.rmsnorm(flat, w, eps)`, result `.view(orig_shape)`; a
  non-contiguous input would raise a Python `RuntimeError` (not caught), not a CUDA error.
- Fused MLP (`:80-90`): `ops.fused_mlp(flat, gate.w, up.w)` then `F.linear(fused, down.w)`.
- Verbose status lines (`:178-209`) report "INJECTED" from the patching alone, **not** from the kernel actually running.

### A.5 — What 11ea904 (`origin/cuda-correction`, "correct kernels") changed and why (`08_fix_branch_11ea904_diff.patch`)

- `kernels/rotary_embedding.cu` (and the starter copy): adds `int total_pairs` and `if (idx >= total_pairs) return;` —
  **the bounds fix**; switches to rotate_half pairs `(i, i+half_dim)` and to `pow`/`sincos` in double — **numerics**
  (matches HF, see A.1); passes `total_pairs` from the launcher. Why: exactly the two defects found above.
- `inject.py`: records the real `position_ids` by hooking `model.model.rotary_emb.forward` and feeds them (int32,
  contiguous) to the kernel instead of `arange` — fixes the decode-position bug; falls back to native sdpa when
  `attn_mask is not None` — the kernel cannot express a padding mask; pins the unpatched `apply_rotary_pos_emb` so a
  second injection does not wrap the first.
- `kernels/attention.cu` + starter: GQA-aware (`kv_h = h / (num_heads/num_kv_heads)`, `base_kv`), `TORCH_CHECK(heads %
  kv_heads == 0)`, and the agent kernel is reverted to the naive starter form (serial reductions, no `s_q` in smem) —
  removes the partial-warp shuffle UB and makes unexpanded K/V (transformers ≥ 4.54) safe.
- `rmsnorm.cu` + starter: block rounded to whole warps (same full-mask shuffle concern); drops `__launch_bounds__`/`__ldg`.
- `fused_mlp.cu`: replaced by a naive one-thread-per-output kernel (slower; removes the cuBLAS path from the "agent"
  starting point).
- `bench.py`/`config.py`/`evaluate.py`/`program.md`: evaluation re-measures in a staged pristine harness in a subprocess,
  "so a crashing kernel (illegal memory access poisons the CUDA context) doesn't take the side-task evaluation down", with
  a correctness check against vanilla HF — i.e. upstream knew the stock kernels crash.

### Verdict on the main hypothesis

- "The injected RoPE kernel is the first suspect / the fault is in RoPE on k": **supported** — by the traceback window
  (A.2 argument; `cache_utils.py:557` = decode-only `torch.cat`, only the two rotary launches are unchecked between the
  wrapper's `clone()`s and that `cat`), by the arithmetic (k decode: 128 of 256 threads out of bounds; q never), and by
  the CPU ASan harness (Step B). Decisive line: **`rotary_embedding.cu:24` has no `idx >= total_pairs` guard while
  `:70` rounds `blocks` up**, so `inject.py:165`'s k launch at every decode step (128 pairs) runs 128 stray threads.
- "k is sized/indexed with q's head count" (plan §3.4): **contradicted** (`inject.py:164-165`, `rotary_embedding.cu:62-65`).
- "k is a transposed non-contiguous view the kernel mis-indexes" (plan §3.5): **contradicted** (`inject.py:163`; A.1
  `k_t` contig=True).
- "8× past k's buffer": **contradicted**; the overrun is 512 B (one block's worth of tail threads), the same size at
  decode and at odd-T prefill.
- Why warmup (462 overrunning launches) survived and prompt 1 did not: **undecidable on CPU** — most likely the 512-B
  overrun only faults when the k clone is the last block of a 2 MB caching-allocator segment, and the 128-token decode
  churns the small pool differently from the 8-token warmup. C1 with `PYTORCH_NO_CUDA_MEMORY_CACHING=1` is designed to
  not depend on this.

**Confidence:** faulting kernel = RoPE on the k launch: ~90%. Mechanism = missing tail guard: ~90% (same residual as
4a). The layout explanation of warmup-vs-prompt: ~60% (unverified; C1 decides).

---

## Step B — patches

Full files are under `patches/files/{rope_bounds,rope_attn,stock_launchcheck}/`; unified diffs in `patches/*.patch`
(apply with `patch -p1` inside a task_context copy; tested against a fresh copy of 58776e0's task_context).

### B.1 `rope_bounds.patch` — the minimal RoPE patch (arm C2)

What it does: `if (idx >= total_pairs) return;` in the kernel, `total_pairs` passed in; the wrapper makes its working
copy with `x.clone(at::MemoryFormat::Contiguous)` (identical to `x.clone()` for the contiguous tensors inject.py passes),
`positions.contiguous()`, `TORCH_CHECK`s on rank/device/dtype/even head_dim/positions length/int range, an empty-launch
guard, and a `cudaGetLastError()` check after the launch so a fault is reported inside `ops.rotary_embedding`. q and k are
already separate launches with their own shapes (`inject.py:164-165`); the patch does not touch inject.py. No arithmetic,
grid, block, dtype or numerics change. `__restrict__`, fast-math intrinsics, interleaved pairs: unchanged on purpose
(minimal).

```diff
--- a/kernels/rotary_embedding.cu
+++ b/kernels/rotary_embedding.cu
@@ -11,6 +11,7 @@
 #include <cuda_runtime.h>
 #include <cuda_fp16.h>
 #include <math.h>
+#include <limits>
 
 template <typename scalar_t>
 __global__ void rotary_embedding_kernel(
@@ -19,9 +20,11 @@
     int seq_len,
     int num_heads,
     int head_dim,
-    float base
+    float base,
+    int total_pairs             // PATCH(rope_bounds): number of valid (batch, seq, head, pair) work items
 ) {
     int idx = blockIdx.x * blockDim.x + threadIdx.x;
+    if (idx >= total_pairs) return;   // PATCH(rope_bounds): the last block is partial whenever total_pairs % 256 != 0
     int half_dim = head_dim / 2;
 
     int pair_idx = idx % half_dim;
@@ -58,14 +61,28 @@
     torch::Tensor positions,   // [batch, seq_len] int32
     double base
 ) {
-    auto output = x.clone();
+    // PATCH(rope_bounds): the kernel indexes a dense [batch, seq_len, num_heads, head_dim] buffer, so make the
+    // copy it works on contiguous whatever the caller's strides are, and make the positions buffer dense int32.
+    TORCH_CHECK(x.dim() == 4, "rotary_embedding: x must be [batch, seq_len, num_heads, head_dim], got dim ", x.dim());
+    TORCH_CHECK(x.is_cuda(), "rotary_embedding: x must be a CUDA tensor");
+    TORCH_CHECK(positions.scalar_type() == torch::kInt32, "rotary_embedding: positions must be int32, got ",
+                positions.scalar_type());
+    TORCH_CHECK(positions.device() == x.device(), "rotary_embedding: positions must be on x's device");
+    auto output = x.clone(at::MemoryFormat::Contiguous);
+    auto pos = positions.contiguous();
     int batch = x.size(0);
     int seq_len = x.size(1);
     int num_heads = x.size(2);
     int head_dim = x.size(3);
     int half_dim = head_dim / 2;
-
-    int total_pairs = batch * seq_len * num_heads * half_dim;
+    TORCH_CHECK(head_dim % 2 == 0, "rotary_embedding: head_dim must be even, got ", head_dim);
+    TORCH_CHECK(pos.numel() >= static_cast<int64_t>(batch) * seq_len,
+                "rotary_embedding: positions has ", pos.numel(), " elements, need batch*seq_len = ",
+                static_cast<int64_t>(batch) * seq_len);
+    int64_t total_pairs_64 = static_cast<int64_t>(batch) * seq_len * num_heads * half_dim;
+    TORCH_CHECK(total_pairs_64 <= std::numeric_limits<int>::max(), "rotary_embedding: tensor too large for int indexing");
+    int total_pairs = static_cast<int>(total_pairs_64);
+    if (total_pairs == 0) return output;
     int threads = 256;
     int blocks = (total_pairs + threads - 1) / threads;
 
@@ -74,12 +91,16 @@
         x.scalar_type(), "rotary_embedding", [&] {
             rotary_embedding_kernel<scalar_t><<<blocks, threads>>>(
                 output.data_ptr<scalar_t>(),
-                positions.data_ptr<int>(),
+                pos.data_ptr<int>(),
                 seq_len, num_heads, head_dim,
-                static_cast<float>(base)
+                static_cast<float>(base),
+                total_pairs
             );
         }
     );
+    // PATCH(rope_bounds): surface launch errors here instead of at the next PyTorch op (asynchronous; no sync added)
+    cudaError_t err = cudaGetLastError();
+    TORCH_CHECK(err == cudaSuccess, "rotary_embedding kernel launch failed: ", cudaGetErrorString(err));
 
     return output;
 }
```

### B.2 `attention_harden.patch` — only for arm C3 (Step A does not implicate attention in the crash)

GQA-aware K/V indexing (identity when K/V arrive expanded, as under 4.53.3), shape/contiguity/dtype `TORCH_CHECK`s, whole-
warp block size (full-mask shuffles are undefined on partial warps), a barrier before `warp_reduce` is reused, a 48 KB smem
check, and a launch error check. Indexing for the 32/32 case is byte-for-byte the stock indexing.

```diff
--- a/kernels/attention.cu
+++ b/kernels/attention.cu
@@ -24,6 +24,7 @@
     int q_len,
     int kv_len,
     int head_dim,
+    int num_kv_heads,               // PATCH(attn_harden): K/V head count (== num_heads when K/V arrive expanded)
     float scale,
     bool causal
 ) {
@@ -35,6 +36,9 @@
     int q_BH_stride = q_len * head_dim;
     int kv_BH_stride = kv_len * head_dim;
     int base_q = (b * num_heads + h) * q_BH_stride + q_pos * head_dim;
+    // PATCH(attn_harden): grouped-query attention: K/V head for query head h (identity when num_kv_heads == num_heads)
+    int kv_h = h / (num_heads / num_kv_heads);
+    int base_kv = (b * num_kv_heads + kv_h) * kv_BH_stride;
     int full_q_pos = kv_len - q_len + q_pos;
 
     extern __shared__ float smem[];
@@ -58,7 +62,7 @@
             scores[j] = -FLT_MAX;
         } else {
             float dot = 0.0f;
-            int base_k = (b * num_heads + h) * kv_BH_stride + j * head_dim;
+            int base_k = base_kv + j * head_dim;   // PATCH(attn_harden)
             for (int d = 0; d < head_dim; d++) {
                 dot += s_q[d] * static_cast<float>(__ldg(&K[base_k + d]));
             }
@@ -102,6 +106,8 @@
     for (int offset = warpSize / 2; offset > 0; offset >>= 1)
         local_sum += __shfl_down_sync(0xffffffff, local_sum, offset);
 
+    // PATCH(attn_harden): every thread must have read warp_reduce[0] (global_max) before lane 0 of warp 0 overwrites it
+    __syncthreads();
     if (lane == 0) warp_reduce[warp_id] = local_sum;
     __syncthreads();
 
@@ -126,7 +132,7 @@
     for (int d = tid; d < head_dim; d += bdim) {
         float acc = 0.0f;
         for (int j = 0; j < kv_len; j++) {
-            int base_v = (b * num_heads + h) * kv_BH_stride + j * head_dim;
+            int base_v = base_kv + j * head_dim;   // PATCH(attn_harden)
             acc += scores[j] * static_cast<float>(__ldg(&V[base_v + d]));
         }
         output[base_q + d] = static_cast<scalar_t>(acc);
@@ -141,18 +147,35 @@
     torch::Tensor V,      // [batch, heads, kv_len, head_dim]
     bool causal
 ) {
+    // PATCH(attn_harden): the kernel indexes dense [B, H, N, D] buffers; refuse anything else instead of reading
+    // past them. inject.py:120-122 already passes .contiguous() tensors; the checks cost nothing on the hot path.
+    TORCH_CHECK(Q.dim() == 4 && K.dim() == 4 && V.dim() == 4, "attention: Q, K, V must be [batch, heads, len, head_dim]");
+    TORCH_CHECK(Q.is_cuda() && K.is_cuda() && V.is_cuda(), "attention: Q, K, V must be CUDA tensors");
+    TORCH_CHECK(Q.is_contiguous() && K.is_contiguous() && V.is_contiguous(), "attention: Q, K, V must be contiguous");
+    TORCH_CHECK(Q.scalar_type() == K.scalar_type() && Q.scalar_type() == V.scalar_type(), "attention: dtype mismatch");
     int batch = Q.size(0);
     int heads = Q.size(1);
     int q_len = Q.size(2);
     int kv_len = K.size(2);
     int head_dim = Q.size(3);
+    int kv_heads = K.size(1);
+    TORCH_CHECK(K.size(0) == batch && V.size(0) == batch, "attention: batch mismatch");
+    TORCH_CHECK(V.size(1) == kv_heads && V.size(2) == kv_len, "attention: K/V shape mismatch");
+    TORCH_CHECK(K.size(3) == head_dim && V.size(3) == head_dim, "attention: head_dim mismatch");
+    TORCH_CHECK(kv_heads > 0 && heads % kv_heads == 0, "attention: num heads must be a multiple of num kv heads");
+    TORCH_CHECK(q_len <= kv_len, "attention: q_len must not exceed kv_len");
 
     float scale = 1.0f / sqrtf(static_cast<float>(head_dim));
     auto output = torch::empty_like(Q);
+    if (batch == 0 || heads == 0 || q_len == 0) return output;
 
     dim3 grid(batch, heads, q_len);
-    int threads = min(kv_len, 256);
-    int smem_size = (kv_len + head_dim) * sizeof(float);
+    // PATCH(attn_harden): whole warps only: the reductions use full-mask __shfl_down_sync (lines 72, 87, 103, 112),
+    // which is undefined for a partial warp (stock launched kv_len threads, e.g. 2 or 12 at prefill).
+    int threads = min(((kv_len + 31) / 32) * 32, 256);
+    size_t smem_size = (static_cast<size_t>(kv_len) + head_dim) * sizeof(float);
+    TORCH_CHECK(smem_size <= 48 * 1024, "attention: kv_len ", kv_len, " needs ", smem_size,
+                " bytes of dynamic shared memory, above the 48 KB default");
 
     AT_DISPATCH_FLOATING_TYPES_AND2(
         at::ScalarType::Half, at::ScalarType::BFloat16,
@@ -162,10 +185,13 @@
                 K.data_ptr<scalar_t>(),
                 V.data_ptr<scalar_t>(),
                 output.data_ptr<scalar_t>(),
-                q_len, kv_len, head_dim, scale, causal
+                q_len, kv_len, head_dim, kv_heads, scale, causal
             );
         }
     );
+    // PATCH(attn_harden): surface launch errors here (asynchronous; no sync added)
+    cudaError_t err = cudaGetLastError();
+    TORCH_CHECK(err == cudaSuccess, "attention kernel launch failed: ", cudaGetErrorString(err));
 
     return output;
 }
```

### B.3 `stock_launchcheck.patch` — stock kernels + launch checks only (arm C1c; **not** a fix)

Adds `cudaGetLastError()` + `TORCH_CHECK` after each of the four launches and nothing else. With `CUDA_LAUNCH_BLOCKING=1`
the fault of a launch is raised inside the `ops.<name>` call with the text `"<name> kernel launch failed: an illegal
memory access was encountered"`, which inject.py's `except` re-raises indirectly (it falls back to the HF function, whose
first CUDA op hits the sticky error) — the chained traceback then names the op. This is the tool-free attribution arm.

```diff
--- a/kernels/rotary_embedding.cu
+++ b/kernels/rotary_embedding.cu
@@ -80,6 +80,10 @@
             );
         }
     );
+    // PATCH(launchcheck only; NO bounds fix): with CUDA_LAUNCH_BLOCKING=1 the fault of this very launch is reported
+    // here, inside ops.rotary_embedding, instead of at the next PyTorch op (cache_utils.py:557 in debug8).
+    cudaError_t err = cudaGetLastError();
+    TORCH_CHECK(err == cudaSuccess, "rotary_embedding kernel launch failed: ", cudaGetErrorString(err));
 
     return output;
 }
--- a/kernels/attention.cu
+++ b/kernels/attention.cu
@@ -166,6 +166,9 @@
             );
         }
     );
+    // PATCH(launchcheck only; no other change)
+    cudaError_t err = cudaGetLastError();
+    TORCH_CHECK(err == cudaSuccess, "attention kernel launch failed: ", cudaGetErrorString(err));
 
     return output;
 }
--- a/kernels/rmsnorm.cu
+++ b/kernels/rmsnorm.cu
@@ -85,6 +85,9 @@
             );
         }
     );
+    // PATCH(launchcheck only; no other change)
+    { cudaError_t err = cudaGetLastError();
+      TORCH_CHECK(err == cudaSuccess, "rmsnorm kernel launch failed: ", cudaGetErrorString(err)); }
 
     return output;
 }
--- a/kernels/fused_mlp.cu
+++ b/kernels/fused_mlp.cu
@@ -57,6 +57,9 @@
             );
         }
     );
+    // PATCH(launchcheck only; no other change)
+    { cudaError_t err = cudaGetLastError();
+      TORCH_CHECK(err == cudaSuccess, "fused_mlp kernel launch failed: ", cudaGetErrorString(err)); }
 
     return gate_proj;  // modified in-place, no extra allocation
 }
```

### B.4 Compile checks and tests (CPU)

- Toolchain: nvcc **12.9.86** (the pod's version, from `cuda-nvcc-12-9_12.9.86-1` extracted with `dpkg -x`, no root),
  torch 2.10.0 headers, Python 3.11 headers, g++ 13.3; flags exactly as `bench.py:143-145` plus torch's
  `COMMON_NVCC_FLAGS`; target sm_90 (H100). `scripts/compile_check.sh`.
  - stock: `COMPILE_OK` (`raw/compile_stock_sm90.txt`) — control.
  - rope_bounds: `COMPILE_OK`, 0 warnings, all four `agent_*` symbols exported, nothing unresolved
    (`raw/compile_rope_bounds_sm90.txt`).
  - rope_attn (rope_bounds + attention_harden): `COMPILE_OK` (`raw/compile_rope_attn_sm90.txt`).
  - stock_launchcheck: `COMPILE_OK` (`raw/compile_stock_launchcheck_sm90.txt`).
  Not possible on CPU: loading the `.so` (needs libc10_cuda) and running the kernel.
- **CPU AddressSanitizer harness** (`scripts/sim_main.cpp`, `scripts/cuda_cpu_shim.h`, `raw/b_cpu_asan_sim.txt`): the
  kernel template text is extracted verbatim from the stock and patched `.cu` and driven thread-by-thread with the
  launcher's grid on exact-size heap buffers.
  - stock, q decode (1,1,32,64): clean. stock, k prefill T=12: clean.
  - stock, **k decode (1,1,4,64)**: `heap-buffer-overflow READ of size 4 … 0 bytes after 4-byte region` at
    `rotary_embedding.cu:34` (positions), then `READ of size 2 … 0/2 bytes after 512-byte region` at `:47-48` (x) — the
    predicted threads and bytes. stock, **k prefill T=13**: same, 0 bytes after the 52-byte positions region.
  - patched (rope_bounds), k decode / T=13 / q: **clean**.
- Numerics (A.1 script): the patch leaves the in-bounds arithmetic byte-identical to stock (same index math; only the
  tail threads are removed), so C2's generated text will differ from C0's — expected, and not a gate.
- `gate.py` was exercised on synthetic logs for every verdict path (PASS/FAIL/UNDECIDED/NOT_RUN; fixtures in
  `raw/gate_selftest/`); `run_arms.sh`'s `fresh_copy`/`apply_patch` and its `preflight` arm were exercised on a fake
  `/workspace` layout on this machine (`raw/preflight_dryrun_cpu.log`: the no-root `.deb` fallback for
  `compute-sanitizer` fetched and extracted; everything GPU-dependent fails here as expected); `c_minimal_kernels.py`'s counter wrapper was
  exercised on CPU with a stub op module through the real inject.py (132 RoPE calls = 2 × 22 × 3 forward passes; 22
  attention calls at prefill; exceptions counted).

### B.5 Does the patch change what the benchmark measures?

The benchmark (`bench.py:66-114`) measures `generate()` tokens/s with exactly 128 new tokens per prompt (`min_new_tokens =
max_new_tokens`, `:94-100`) over 8 prompts, divided by the vanilla-PyTorch TPS measured in the same process
(`:197-204, 266`). Per RoPE launch the patch adds host-side checks (sub-µs), one `cudaGetLastError()` (µs, no sync), and
one integer compare per thread; the grid, block, dtype, memory traffic and numerics are unchanged, and the 128 stray
threads per k launch did no useful work before. Expected effect on AGENT_TPS: below measurement noise (<1%). The kernel's
*output* is unchanged (still numerically wrong vs HF), which the benchmark does not measure. 11ea904's RoPE (double
`sincos`/`pow`) would be a slower kernel and does change inject.py, so it is not the minimal arm; it is the right baseline
if the owner wants correct numbers.

**Confidence:** the patch removes every out-of-bounds access of the RoPE kernel for the benchmark's shapes: ~95%
(arithmetic + ASan on the same source text); it compiles on the pod: ~90% (same nvcc/torch versions; the pod's arch list
adds sm_80/sm_89 compilations of the same source).

---

## 4b. Attack the plan (arms C0-C4)

| Arm | Separates the hypotheses? | Pass/fail for an unrelated reason? | Missing (now added) |
|---|---|---|---|
| **C0** vanilla | Control only: shows the stack works (already shown in debug8: BASELINE_TPS 102.53 over 8 prompts). | Fails on hub access (debug7's `hf_transfer`) → `HF_HUB_OFFLINE=1`, model pre-cached by setup step 6. | Record greedy token ids (reference text) and write `baseline_tps.txt` so sanitizer arms skip bench.py's 8-prompt baseline. `gpu_run/c0_vanilla.py`. |
| **C1** stock + memcheck | **Yes, if configured right.** As written it has two blind spots: (a) PyTorch's caching allocator hands out 512-B blocks inside 2 MB `cudaMalloc` segments; memcheck only knows the segments, so a 512-B overrun into the next block is invisible — it would only report the one access that crosses a segment (the actual crash) and might never report if that lands in an adjacent segment; (b) `bench.sh` recompiles the kernels (for 3 archs, ~150 s) inside the sanitized process tree and runs the 8-prompt vanilla baseline under the tool. | A different kernel named → hypothesis contradicted (that is the point). No report + crash → tool/driver problem (UNDECIDED). | `PYTORCH_NO_CUDA_MEMORY_CACHING=1` (every tensor its own `cudaMalloc`, exact sizes → the first k tail at warmup decode step 1 is flagged, deterministically); `--target-processes application-only` (compile subprocesses untraced); `--report-api-errors no`; `--destroy-on-device-error kernel` (lets later launches run so all faulting kernels are listed); `--log-file`; cached baseline; a 3-forward-pass minimal driver (**C1a**) plus the real `bench.sh --prompts 1` (**C1b**) plus the tool-free **C1c**. |
| **C2** RoPE patch | Yes for "RoPE is sufficient": passes iff no other fault exists in 3 warmups + 8×128 steps. | **Pass for an unrelated reason:** the patched wrapper throws (e.g. a `TORCH_CHECK`) and inject.py silently falls back to HF RoPE (`inject.py:168-169`) — bench.py still prints `KERNEL_ROTARY_EMBEDDING = ACTIVE`. **Fail unrelated:** compile error on the pod, patch not applying, hub access, timeout, a GPU wedged by C1. | **C2s**: same patched kernels under memcheck with a counting wrapper (`c_minimal_kernels.py`): expects 2×22×4 = 176 RoPE calls, 0 exceptions, no invalid access. Compile-checked here with the pod's nvcc. `gpu_ok` check between arms. |
| **C3** RoPE + attention patch | Only partially: attention is never on the decode path and all its indices are in bounds under 4.53.3 (A.3), so C3 vs C2 can only differ in prefill numerics/TPS, not in the crash. It is cheap (~3 min) and the hardened kernel is the one that survives transformers ≥ 4.54, so keep it as the last patched arm. | As C2. | **C3s** counters: attention calls = 22 (prefill) with 0 exceptions, else the harden patch's checks fired and sdpa was used instead. |
| **C4** one episode | Not a hypothesis test; a pipeline test. | An agent episode can fail for agent/model/API reasons unrelated to kernels; its eval reads whatever `evaluate.py` at 58776e0 does. | Budget: see 4e. Gate on `Main task: … (speedup=…)`. Whether the patched kernels must also replace `starter_kernels/` and the `kernels/` the agent starts from is an owner decision (both have the same bug). |

**Specific questions**

1. *Could `compute-sanitizer` be unavailable or broken on `runpod/base:1.4.1-cuda1290-ubuntu2204`?* Evidence
   (`raw/runpod_base_docker-bake.hcl`, `raw/nvidia_cuda_12.9.0_devel_ubuntu2204_Dockerfile`,
   `raw/nvidia_apt_ubuntu2204_sanitizer_deps.txt`): the image is `FROM nvidia/cuda:12.9.0-cudnn-devel-ubuntu22.04`, which
   installs `cuda-command-line-tools-12-9=12.9.0-1`, which `Depends: … cuda-sanitizer-12-9 (>= 12.9.27)` → the binary is
   `/usr/local/cuda-12.9/bin/compute-sanitizer` (v2025.2.x), on PATH via `p6_env.sh`'s `/usr/local/cuda/bin`. Likely
   present (~85%); not verified on a pod. "Broken" risks: driver 595.91 (CUDA 13.2) with a 12.9 sanitizer — newer drivers
   support older tools, but unverified; the tool must inject into torch's pip-shipped cu128 runtime (normal). Guards: the
   preflight runs a 10-s memcheck smoke (`ERROR SUMMARY: 0 errors` expected); if the binary is missing it fetches
   `cuda-sanitizer-12-9_12.9.79-1_amd64.deb` (10 MB) and `dpkg -x`'s it without root (done here, works); if the tool is
   broken, C1c attributes the fault without it.
2. *Will memcheck be too slow on TinyLlama?* Unbounded as planned (full `bench.sh` = 3 warmups + 8×128 steps, two model
   loads, a 3-arch recompile, all under the tool at a 10-100× per-launch slowdown). Bounded as follows: C1a runs 3 forward
   passes (~66 custom launches + ~2 k PyTorch launches): seconds of sanitized work after a ~60-150 s unsanitized compile;
   C1b runs `--prompts 1` with the baseline cached (bench.py:190-194) — ~152 steps × ~650 launches ≈ 10⁵ launches ≈ 1-5
   min; each under `timeout` (900 s / 1500 s), `--print-limit 200`. If C1a alone exceeds 15 min the tool is misbehaving
   (UNDECIDED) and C1c stands in. Estimated: C1a 3-4 min, C1b 5-10 min.
3. *Does the patch change what the benchmark measures?* No material change (B.5): same grid/block/dtype/traffic/numerics;
   only the illegal tail accesses disappear. It does not make the kernel *correct* (interleaved pairs, decode positions =
   0 stay), and the benchmark cannot see that; the patched baseline measures "stock-kernel speed without the crash".

Other weaknesses of the plan found: (i) §3.4's "writes 8 times past k's buffer" and §3.5's non-contiguous view are not
what the code does — if the gates had been written from §3 they would look for the wrong signature (a 7 KB overrun at
thread 0); the gate below looks for the tail signature (thread ≥ 128 of the last block, 4-byte and 512-byte nearest
allocations). (ii) The decision rule's "patched baseline" is numerically wrong (A.1); any later speedup claim inherits
that, and 11ea904's evaluate.py would score it 0 for correctness. (iii) `--prompts 1` only exercises T = 12 (even); the
odd-T prefill overrun needs prompts 4-6, which the full `bench.sh` in C2/C3 covers. (iv) The sanitizer's default
`--destroy-on-device-error context` would end C1 at the first fault; `kernel` lets it list every faulting kernel.
(v) The pod's `TORCH_CUDA_ARCH_LIST=8.0;8.9;9.0` triples every arm's compile; `run_arms.sh` sets `9.0` (same sm_90 code
runs; set `ARCH_LIST="8.0;8.9;9.0"` for parity at +~100 s per arm).

**Confidence:** that the amended C1/C2(+C2s) decide the question in one session: ~85%; the residual is tool/driver
behaviour and pod environment, covered by C1c and the gates' UNDECIDED paths.

---

## 4d. Pass/fail gates (written before the run; `gpu_run/gate.py` prints one line per arm into `SUMMARY.txt`)

All arms: one fresh copy of `task_context` per arm (as an episode gets it), own process, `timeout`, `set +e`; outputs in
`$WORKSPACE/rootcause/<arm>/{bench.log,sanitizer.log,apply.log,meta.json}`; run with
`bash gpu_run/run_arms.sh` (default order: preflight C0 C1a C1c C2 C2s C1b C3 C3s). Commands below are what
`run_arms.sh` executes, with `$d` the arm's task copy.

| Arm | Command | PASS iff (expected strings) | FAIL / UNDECIDED |
|---|---|---|---|
| preflight | `nvidia-smi`; `python3 -c "import torch, transformers…"`; model snapshot present; patches present; `compute-sanitizer --version`; 10-s memcheck smoke on `torch.ones(1024).cuda()` | `transformers 4.53.3`, `model cached`, no `PATCH MISSING`; sanitizer smoke `ERROR SUMMARY: 0 errors` (else the sanitizer arms are marked and C1c carries) | missing model/patches → FAIL (fix before spending) |
| C0 | `cd $d && python3 c0_vanilla.py` | rc 0, `C0_BASELINE_TPS=<v>` with v ≥ 20, `C0_DONE`, no `CUDA error` | any `CUDA error` → FAIL (stack broken; stop the session, nothing else is interpretable) |
| C1a | `cd $d && PYTORCH_NO_CUDA_MEMORY_CACHING=1 C_PROMPT=Hello C_MAX_NEW=3 compute-sanitizer --tool memcheck --target-processes application-only --print-limit 200 --report-api-errors no --destroy-on-device-error kernel --log-file $d/sanitizer.log python3 c_minimal_kernels.py` (stock kernels) | first `Invalid __global__ read|write of size N bytes` block names `rotary_embedding_kernel`; expected detail: `read of size 4 bytes` at `rotary_embedding.cu:34` (or `read of size 2` at `:47/:48`, `write of size 2` at `:50/:51`), `by thread (128..255,0,0) in block (0,0,0)`, `nearest allocation … of size 4 bytes` (positions) or `of size 512 bytes` (k clone); host backtrace contains `agent_rotary_embedding`; `MIN_PROMPT_TOKENS T=2` | first block names `attention_kernel`/`rmsnorm_kernel`/`fused_silu_mul_inplace_kernel` or a PyTorch kernel → FAIL (hypothesis contradicted; the line tells which). No invalid access + `CUDA error` in bench.log → UNDECIDED (tool blind/broken). No invalid access, no crash → UNDECIDED (did not reproduce). |
| C1c | `cd $d && CUDA_LAUNCH_BLOCKING=1 bash bench.sh --prompts 1 --verbose` on stock + `stock_launchcheck.patch`, baseline cached from C0 | bench.log contains `rotary_embedding kernel launch failed: an illegal memory access was encountered` (first such line), followed by the chained `torch.AcceleratorError: CUDA error: an illegal memory access was encountered` | `attention|rmsnorm|fused_mlp kernel launch failed` first → FAIL (contradicted). `CUDA error` without any `… launch failed` line → UNDECIDED (fault outside the four launches; read the traceback). Completes with `AGENT_TPS` → UNDECIDED (layout-dependent fault did not reproduce; C1a decides). |
| C2 | `cd $d && bash bench.sh --verbose` on stock + `rope_bounds.patch` (full 8 prompts; bench.py measures its own vanilla baseline in-process) | rc 0, `COMPILE_STATUS=PASS`, `[bench]   prompt 8/8:`, `AGENT_TPS = <v>`, `SPEEDUP = <s>x`, `KERNEL_ROTARY_EMBEDDING … = ACTIVE`, no `CUDA error`/`illegal memory access` | `CUDA error` → FAIL (patch insufficient or a second fault; C1a's kernel list tells which). `COMPILE_STATUS=FAIL`/`PATCH_FAILED`/rc 124 → FAIL-unrelated. |
| C2s | as C1a with `rope_bounds.patch`, `C_PROMPT="Explain the theory of relativity in simple terms." C_MAX_NEW=4`, `C_REF=…/C0/workspace/c0_outputs.json` | `MIN_ROPE_CALLS expected=176 got=176 errors=0`, `MIN_DONE rc=0`, sanitizer.log has no `Invalid __` block and no tool `Error:`; informational: `MIN_TEXT_MATCH_C0=no` is expected (stock numerics kept) | `errors>0` or `got<expected` → FAIL (kernel threw, inject.py fell back: C2 passed for the wrong reason). Any `Invalid __` → FAIL. |
| C1b | `cd $d && PYTORCH_NO_CUDA_MEMORY_CACHING=1 compute-sanitizer … --log-file $d/sanitizer.log python3 bench.py --prompts 1 --verbose` (stock, baseline cached) | same rule as C1a on the real benchmark; expected first block during warmup decode step 1 | as C1a; rc 124 → UNDECIDED (too slow), C1a/C1c carry |
| C3 | as C2 with `rope_bounds.patch` + `attention_harden.patch` | as C2 (and `KERNEL_ATTENTION … = ACTIVE`) | as C2 |
| C3s | as C2s with both patches | as C2s plus `MIN_OP_CALLS` shows `"attention": 22` and `MIN_OP_ERRORS {}` | attention errors > 0 → FAIL (harden checks fired → sdpa fallback) |
| C4 | the control-loop's one episode on the C2 (or C3) baseline, only if C2 (or C3) PASS and ≥ 40 min remain under the watchdog | eval log: `Main task: SUCCESS|PARTIAL (speedup=<v>x)`, no `evaluation error`, no `CUDA error` | otherwise FAIL; NOT_RUN if skipped for budget |

Decision mapping (fixed now): **RoPE confirmed** = C1a PASS or C1c PASS (both naming the RoPE kernel; if they disagree,
the sanitizer's line wins and the disagreement is reported); **patch validated** = C2 PASS and C2s PASS; **C3 adds
information** only through its TPS/text vs C2. "Nothing passes" = C2 FAIL and C3 FAIL with `CUDA error` → the plan's §6
closes Phase 6, and C1's kernel list is the finding.

---

## 4e. What could stop the single GPU run early — and the guard for each

| # | Risk | Guard (in `run_arms.sh` unless noted) |
|---|---|---|
| 1 | Hub access / `HF_HUB_ENABLE_HF_TRANSFER=1` without `hf_transfer` (debug7) | model pre-cached by `pod_setup.sh` step 6; `HF_HUB_OFFLINE=1` for every arm; preflight checks the snapshot exists and imports `hf_transfer` |
| 2 | `compute-sanitizer` missing | preflight searches PATH and `/usr/local/cuda*/bin`, else fetches the 10 MB `.deb` and `dpkg -x`'s it into `$OUT_DIR/sanitizer` (no root); C1c needs no tool |
| 3 | sanitizer broken with driver 595 / torch cu128 | 10-s preflight smoke; sanitizer arms degrade to UNDECIDED, C1c is the attribution |
| 4 | memcheck too slow | minimal driver (3-4 forward passes), cached baseline, `--prompts 1`, `application-only`, `--print-limit 200`, `timeout` 900/1500 s per arm |
| 5 | a crashed arm poisons the CUDA context | each arm is its own process; `set +e`; `timeout --kill-after` |
| 6 | GPU left wedged (Xid) after an illegal access | `gpu_ok` (nvidia-smi + a 1-element CUDA op) before each arm; debug8 shows the pod survived two crashes and ran the probe and the blocking run afterwards |
| 7 | patch does not apply (task_context drift) | patches tested against the pinned 58776e0 copy; `apply.log` + gate FAIL-unrelated; `arena_root verify` (206 files identical) already runs in setup |
| 8 | patched kernels fail to compile on the pod | compile-checked with nvcc 12.9.86 + torch 2.10.0 headers for sm_90 (same versions as the pod); `COMPILE_STATUS=FAIL` is a gate FAIL-unrelated, the session continues |
| 9 | compile time × arms (150 s each for 3 archs) | `TORCH_CUDA_ARCH_LIST=9.0` for the session (sm_90 is what runs on H100); ~60 s per arm |
| 10 | watchdog 75 min / $6 (and the plan's $5 cap) | estimated: setup ~5 min, preflight 1, C0 1, C1a 3-4, C1c 3, C2 2.5, C2s 3, C1b 5-10, C3 2.5, C3s 3 → **25-32 min** (~$2.0-2.5 incl. setup); C4 (~35-45 min) does not fit under $5 with everything else — either drop C1b/C3/C3s or run C4 as its own approved session; arms are ordered so the decisive ones (C0, C1a, C1c, C2, C2s) come first |
| 11 | pod stock refusal / SSH window / container readiness (Amendments 7-9) | existing runner rules; nothing kernel-related to add |
| 12 | wrong `python3` / wrong `HF_HOME`: `/etc/rp_environment` re-exports the container env — on this CPU pod it sets `HF_HOME=/workspace/.cache/huggingface/` and resets `PATH`, so a script that sets `HF_HOME` *before* sourcing it (as the DIAG script's `: "${HF_HOME:=…}"` does) can end up pointing at an empty cache | `run_arms.sh` captures the caller's values first, sources `rp_environment`/`p6_env.sh`, then picks the first `HF_HOME` candidate that actually contains the TinyLlama snapshot (`/workspace/hf` from setup step 6) and the first `python3` that imports torch; preflight prints both (dry-run on this machine: `raw/preflight_dryrun_cpu.log`) |
| 13 | SSH session drop kills the run | run under `nohup`/`tmux`; all output is on `/workspace`; `RUN_DONE` marker + `SUMMARY.txt` |
| 14 | silent kernel fallback masks a failure (inject.py `except`) | C2s/C3s count calls and exceptions; a bench-only "pass" is not accepted without them |
| 15 | sanitizer log lost in stdout noise | `--log-file` per arm; gate reads the file |
| 16 | `baseline_tps.txt` cache confusion between arms | each arm has its own copy and `workspace/`; only C1b/C1c receive C0's cached value on purpose |
| 17 | the stock crash does not reproduce in C1c (layout-dependent) | C1a with caching off is deterministic; C1c's "no crash" is UNDECIDED, not evidence against |
| 18 | disk (`/tmp/arena_build_<pid>` per compile, ~1 MB each) | preflight prints `df`; negligible |
| 19 | output buffering hides progress when killed | `PYTHONUNBUFFERED=1`, `flush=True` in the drivers |
| 20 | `TOKENIZERS_PARALLELISM` fork warnings / hangs | set to `false` as in the DIAG script |

---

## Confidence summary

| Conclusion | Confidence |
|---|---|
| The faulting kernel in debug8 is `rotary_embedding_kernel` on the k launch | ~90% |
| Mechanism: no tail guard (`rotary_embedding.cu:24, :68-70`), 128 stray threads per k decode launch (and per odd-T prefill) | ~90% |
| The plan's stated mechanism (k sized by q's heads; non-contiguous k) is wrong | ~99% (code + A.1) |
| The attention kernel is not the crash under 4.53.3 | ~90% |
| Why warmup survived (caching-allocator segment tail) | ~60% (C1 decides; irrelevant to the fix) |
| `rope_bounds.patch` removes all RoPE out-of-bounds accesses for the benchmark's shapes | ~95% |
| `rope_bounds.patch` compiles and runs on the pod | ~90% |
| C2 passes (no other fault in 3 warmups + 8×128 steps) | ~85% |
| `compute-sanitizer` is present on the image | ~85%; works with driver 595: unknown (preflight smoke) |
| memcheck run time within the arm timeouts | ~85% |
| Patch does not change the measured TPS beyond noise | ~95% |
| C4 fits in the $5 cap together with all other arms | unlikely (~30%); see 4e #10 |

---

## Files

- `REPORT.md` — this report.
- `scripts/a1_cpu_hooks.py` — Step A.1 hooks + stock launcher arithmetic; `raw/a1_cpu_hooks_fp16.json`, `raw/a1_summary.txt`.
- `scripts/a1_rope_numerics_cpu.py` — CPU emulation of stock / patched / 11ea904 RoPE arithmetic vs HF; prompt lengths; `raw/a1_rope_numerics.{json,txt}`.
- `scripts/compile_check.sh` — nvcc 12.9.86 + torch 2.10.0 compile-only check; `raw/compile_{stock,rope_bounds,rope_attn,stock_launchcheck}_sm90.txt`.
- `scripts/sim_main.cpp`, `scripts/cuda_cpu_shim.h` — CPU AddressSanitizer harness for the kernel text; `raw/b_cpu_asan_sim.txt`.
- `patches/rope_bounds.patch` (arm C2), `patches/attention_harden.patch` (arm C3), `patches/stock_launchcheck.patch` (arm C1c); full files in `patches/files/`.
- `gpu_run/run_arms.sh` (one-session orchestrator), `gpu_run/gate.py` (gates), `gpu_run/c0_vanilla.py`, `gpu_run/c_minimal_kernels.py`, copies of the patches; `raw/gate_selftest/` (fixtures + expected output), `raw/preflight_dryrun_cpu.log`.
- `raw/runpod_base_docker-bake.hcl`, `raw/nvidia_cuda_12.9.0_devel_ubuntu2204_Dockerfile`, `raw/nvidia_apt_ubuntu2204_sanitizer_deps.txt` — the compute-sanitizer availability evidence.

GPU run, one command on the pod after `pod_setup.sh` (as root or the p6 user, from any directory):
`nohup bash /workspace/gpu_run/run_arms.sh > /workspace/rootcause_run.out 2>&1 &` then read `/workspace/rootcause/SUMMARY.txt`
(one `GATE <arm> <VERDICT>` line per arm) and the per-arm folders. Copy `gpu_run/` to the pod first; `ARCH_LIST="8.0;8.9;9.0"`
restores the setup's arch list; `bash run_arms.sh C0 C1a C2 C2s` runs a subset.
