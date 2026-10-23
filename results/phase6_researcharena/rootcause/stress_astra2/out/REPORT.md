# Independent kernel correctness review — continuation

## Summary and decision

**Confirmed source defect (high confidence): stock RoPE launches 256 threads for the decode K tensor's 128 pairs without checking `idx`.** Threads 128–255 read `positions[1]` past a one-element position tensor and read/write K elements 256–511 past a 256-element output. This is **512 bytes of out-of-bounds FP16 writes per decode K launch**, not an eightfold K overrun.

**The plan's specific shared-Q-head and noncontiguous-input explanations are contradicted (high confidence):** `inject.py:162–165` already makes q/k contiguous and launches them separately; `kernels/rotary_embedding.cu:62–68` derives each launch from that input's own shape. The broader “RoPE before cache caused the crash” suspicion is strongly supported, but identifying the origin of the *historical GPU fault* remains **unknown pending sanitizer**. No GPU was used here.

The completed A.1 CPU evidence was read and reused, **not rerun**. It used actual TinyLlama weights, Torch 2.10.0+cu128 / transformers 4.53.3, FP16, 22 layers, one 12-token prefill and two decode steps. RoPE sees **32 Q / 4 K heads**; attention sees **32 / 32**. Decode K has a demonstrable tail overrun despite correct per-input shape handling.

Delivered: isolated safety-only RoPE patch, separate one-line attention launch fix, unchanged stock arm, complete compiled extension modules for all three arms, CPU regression checks, GPU probe, sanitizer canary, mechanical gate parser, and bounded session script. **NVCC 12.8.93 compiled/linked/imported C1/C2/C3 for sm_80 on CPU; no device execution tested.**

**Do not equate a memory-safe run with a correct baseline.** Stock RoPE also rotates adjacent rather than half-vector pairs and resets decode positions. Those are deliberately unchanged by the minimal safety patch. CPU reference math already proves incompatibility with Llama. C2/C3 are expected to fail the separate numerical gate; C4 should then be skipped. The plan's “any patched arm passes, reopen” rule needs this correctness qualification before approval.

**C4 readiness blocker:** this checkout contains only task_context, not a full-episode runner. A concrete adapter invocation and exact contract are provided in `EPISODE_CONTRACT.md`; the owner must supply/validate that adapter before provisioning. A benchmark is not represented here as a full episode. No model API was called. A live-agent episode would require a scope amendment to the no-model-API rule; an offline frozen replay must be labelled as such.

## Evidence conventions and work order

Unless qualified, source citations are relative to `~/ResearchArena/58776e0/settings/cuda_kernel/task_context/` (“stock”). `fix:` means the corresponding `11ea904` tree. `raw/` and `evidence/` are under this deliverable directory. Numbered stock source snapshots are included in `evidence/`; originals remain unchanged. The full supplied fix diff is `upstream-11ea904.patch`.

Read first: `~/context/00_rootcause_plan.md`, saved `4a_initial.md`, `probe_cpu.py`, and all completed A.1 output. Continued in requested order: alternatives → A source/diff review → B patch/compile/tests → arm critique → gates → early-stop guards. Initial candidate notes are preserved. This is an independent report; no comparison with the second tester has happened. Confidence labels describe evidence, not calibrated probabilities.

## 4a. Alternatives and discriminating evidence

The following are plausible mechanism classes, not an assertion that an exhaustive universe of software/hardware faults can be enumerated. A source-level correctness defect is distinguished from a likely cause of this address fault.

| Alternative | Evidence and discriminator from missing RoPE tail guard | Assessment / confidence |
|---|---|---|
| Attention K/V indexed with Q head count | `attention.cu:34–37,61–63,129–130,144–148`. If K/V arrive with 4 heads, heads 4–31 go OOB. Hook the **actual** attention arguments and memcheck that symbol. Saved native A.1 `raw/A1.jsonl:8,15,22`, plus `evidence/debug8_head_probe.log`, show expanded 32-head inputs on 4.53.3. | Real portability bug; not supported for this pinned path. High confidence. |
| Attention partial-warp shuffle inputs | `attention.cu:71–72,85–87,102–103,111–112` use full masks, while `:154` launches `min(kv_len,256)` threads. N=12 launches 12 threads; shuffling values from inactive source lanes is undefined. Test N=1,2,12,13,14,31,32,33,255,256,257 against FP32 SDPA; compare C2 versus C3 and synccheck. | Source defect implicated independently; numerical failure likely, direct address-fault attribution unknown. High confidence defect, low confidence historical cause. Synccheck may not diagnose every undefined shuffle; numerical test remains essential. |
| FP16/BF16/FP32 or positions dtype mismatch | RoPE `:72–77`, attention `:157–164`, RMSNorm `:77–83` dispatch scalar types; not hard-coded half buffers. Typed data_ptr rejects mismatches rather than silently casting. Position pointer is int32; wrapper `inject.py:159–161` makes int32. Probe logs float16, int64 *native* IDs; distinguish wrapper-created IDs from HF IDs. | No dtype mismatch on measured path, high confidence. Float arithmetic / fast math can affect accuracy, not explain the proven offset violation. |
| Wrapper layout, alias, dangling pointer | RoPE wrapper `inject.py:162–167` permutes/contiguates inputs and returns permuted **owned clone** outputs (`rotary_embedding.cu:61`); attention makes contiguous inputs `inject.py:120–123`, new output `attention.cu:151`; MLP returns an owned matmul result `fused_mlp.cu:42–43,61`. Trace storage spans and sync while tensors live. Expanded positions for B>1 have zero batch stride (`inject.py:161`) and are not made contiguous in stock. | No dangling-pointer evidence for B=1. Noncontiguous public-op inputs are a general hazard, not the measured RoPE cause. High confidence for observed layout, medium for excluding all lifetime faults. |
| Other grid/block/resource/integer errors | Attention grid `(B,H,Nq)`, threads and shared bytes at `:153–155`; RMSNorm block `min(hidden,1024)` at `rmsnorm.cu:74–75`; MLP int numel at `fused_mlp.cu:45–48`. Check device grid.z, shared-memory limits, int range and empty tensors. Invalid launch/resource errors are distinct from memcheck global OOB. | TinyLlama D=64, H=32, N=12, hidden=2048 do not approach limits. High confidence short-shape exclusion; arbitrary lengths unsupported. |
| Wrong sequence length / position semantics | `inject.py:158–161` constructs 0..S−1, so each decode uses position 0 instead of 12 or 13. RoPE `:44–45` pairs adjacent elements; HF `raw/modeling_llama.py:105–109,132–135` rotates halves. Compare valid-index outputs at nonzero positions to HF independently of memory checks. | Confirmed correctness bugs, not direct OOB causes. High confidence. |
| Cos/sin cache too short | Custom RoPE ignores cos/sin (`inject.py:156–165`); only fallback `:169` uses them. Probe `raw/A1.jsonl:5,12,19` has cos/sin length matching Q length (12,1,1), which is correct for sliced/current positions. Guard against wrongly requiring cos length to equal cumulative KV length. | Not a direct custom-kernel explanation on this path. High confidence. |
| Cache update itself | `raw/cache_utils.py:550–558` stores first K/V then concatenates subsequent states; debug8 `evidence/debug8_blocking.log:89–95` reports cat at line 557. C0 must run identical cached decode; insert synchronization after each custom op before cache. | Native CPU works; previous GPU native baseline also succeeded (`debug8_blocking.log:5–14`). GPU cache bug not logically impossible, but weak evidence. Medium confidence. |
| Earlier RMSNorm / previous-layer MLP corruption | RMSNorm accesses row×hidden and loop-bounded d (`rmsnorm.cu:22–30,60–64`), MLP has explicit idx<N (`fused_mlp.cu:21–29`). RMSNorm has same partial-warp design issue for other hidden sizes, but 2048 launches 1024 full-warp threads. Full-model memcheck plus strict per-op sync distinguishes these from RoPE. | Lower suspicion on TinyLlama, not runtime-excluded. Medium confidence. |
| Stream/device mismatch | Stock launch syntax omits stream/CUDAGuard (`rotary_embedding.cu:75`, `attention.cu:160`, `rmsnorm.cu:80`, `fused_mlp.cu:53`). CUDA launches default stream even if PyTorch current stream differs. Check on default vs custom stream / multi-GPU; require current device 0 and default stream for this one-run scope. | General contract bug; current single-device path less suggestive. Medium confidence, no general stream-safety claim. |
| Exceptions swallowed; later sticky CUDA error misattributed | `inject.py:124–130,168–169` catch **all Exception** and try native fallback. A blocking error from RoPE can be swallowed, then reported at cache cat; CUDA_LAUNCH_BLOCKING does not override Python exception handling. Use proxy synchronization and a BaseException-derived diagnostic failure to escape those catch blocks. | High confidence masking mechanism exists; exact sequence in old log unknown. |
| Global monkeypatch survives model reload | `inject.py:148–173` patches module-level function; `restore_model:214–220` does nothing. `bench.py:226–250` may inject baseline then agent in same process. Fresh model is not fresh module state. Fresh OS process per arm and native reference first distinguish this. | Real contamination risk; high confidence. Debug8 native baseline path avoids baseline injection. |
| Stale binary / cached TPS / wrong source arm | `bench.py:190–194` accepts cached scalar TPS; `:196–224` can silently change baseline to native HF; build path and load at `:117–149`. Compare source hashes, build names and actual function counters, not “INJECTED” strings. | High confidence experimental confound, not proven crash cause. |
| CUDA stack, compiler ABI, hardware, allocator layout | Version pins and image tag are not device-health proof. Source has unchecked launches; debug8 only identifies a later runtime error. C0 + known-good/bad sanitizer canaries, architecture rebuild, GPU health/Xid checks discriminate. Torch allocator slabs may hide tensor-local overruns from memcheck; disable caching during diagnostics. | Unknown runtime contribution. High confidence that these controls are needed. |
| Dropped attention mask/dropout/scale/GQA options | `inject.py:107–123` forwards only causal flag to custom attention. Padding masks or nonstandard scale may be ignored; decode intentionally falls back. Compare padded/custom-scale paths separately, log mask and flags. | Real semantic compatibility limitation; no clear direct address-fault mechanism in this unpadded default-scale test. High confidence. |
| Different execution path or version than recorded | Torch SDPA vs eager/FlashAttention, torch.compile, model config, batch/prompt and EOS early stop all change exercised ops. `bench.py:54–60` doesn't explicitly select SDPA; probe and logs confirm actual SDPA for this pin. Force SDPA and exactly two cached decodes; check op counts, config hash. | High confidence confound. A mere successful short generate may never decode. |

Separate from alternatives, **RoPE rounded tail** is the strongest source-level cause: `rotary_embedding.cu:24–34,68–70`. It is RoPE, but *not* the plan's shared-head hypothesis. The original earlier notes already identified it; this continuation confirms it against saved actual shapes rather than claiming a new CPU forward.

## A.1. Completed CPU model trace and exact launch arithmetic

Environment `raw/A1.jsonl:1–2`: Python env `~/work/venv`, Torch 2.10.0+cu128, transformers 4.53.3, 8 CPU threads, model dtype **float16 supported on this CPU**, no dtype fallback. Model snapshot currently cached at revision `fe8a4ea1ffedaf415f4da2f062534de366a451e6`. Probe used model identifier without explicit revision; pin this saved revision for the GPU transfer. Input token IDs are saved, not assumed from a string alone.

Native HF, **no injected kernels**. Hooks: Llama apply_rotary_pos_emb, DynamicCache.update (in/out), F.scaled_dot_product_attention, and LlamaRotaryEmbedding.forward for actual position_ids. Cache doesn't receive q: logged q at cache is the corresponding RoPE output, explicitly tracked by the probe. Each of the three hooks fired **22 times per step**, but only layer 0 metadata is printed (`raw/A1.jsonl:9,16,23`); do not describe this as a full per-layer metadata dump. Native full-model logits were finite (`probe_cpu.py` asserts this).

All q/k in the following table are FP16. `C` = contiguous, `NC` = noncontiguous. Shapes and strides are ordered `[B,H,S,D]`. The unusual stride on singleton dimensions is legal; do not classify singleton decode tensors as noncontiguous by visual inspection.

| Step / hook | q shape ; stride ; C? | k shape ; stride ; C? |
|---|---|---|
| Prefill RoPE input | [1,32,12,64]; [24576,64,2048,1]; NC | [1,4,12,64]; [3072,64,256,1]; NC |
| Prefill cache in/out | [1,32,12,64]; [24576,64,2048,1]; NC | [1,4,12,64]; [3072,64,256,1]; NC |
| Prefill attention | [1,32,12,64]; [24576,768,64,1]; C | [1,32,12,64]; [24576,768,64,1]; C |
| Decode 1 RoPE input | [1,32,1,64]; [2048,64,2048,1]; C | [1,4,1,64]; [256,64,256,1]; C |
| Decode 1 cache in | [1,32,1,64]; [2048,64,64,1]; C | [1,4,1,64]; [256,64,64,1]; C |
| Decode 1 cache out | same q | [1,4,13,64]; [3328,832,64,1]; C |
| Decode 1 attention | same q | [1,32,13,64]; [26624,832,64,1]; C |
| Decode 2 RoPE input | [1,32,1,64]; [2048,64,2048,1]; C | [1,4,1,64]; [256,64,256,1]; C |
| Decode 2 cache in | [1,32,1,64]; [2048,64,64,1]; C | [1,4,1,64]; [256,64,64,1]; C |
| Decode 2 cache out | same q | [1,4,14,64]; [3584,896,64,1]; C |
| Decode 2 attention | same q | [1,32,14,64]; [28672,896,64,1]; C |

Raw citations: `raw/A1.jsonl:5–8,12–15,19–22`. V metadata also logged. Cos/sin at RoPE and cache are FP16 contiguous `[1,12,64]`, stride `[768,64,1]` during prefill, then `[1,1,64]`, stride `[64,64,1]`. Actual position_ids are int64 contiguous `[1,12]`, stride `[12,1]`, values 0..11; then `[1,1]`, stride `[1,1]`, values 12 and 13 (`:4,11,18`). Cache_position is int64 contiguous `[12]` then `[1]`, stride `[1]`. Cos/sin and IDs are not arguments to SDPA; their upstream records apply to that step.

### Python reproduction of stock launch/index expressions

`probe_cpu.py: launch()` reads the stock source, asserts its total_pairs formula and extracts threads=256; it emulates `inject.py:162–165` followed by `rotary_embedding.cu:24–51,62–70`. Inputs after wrapper are contiguous `[B,S,H,D]`:

* Prefill Q stride [24576,2048,64,1], K stride [3072,256,64,1].
* Decode Q stride [2048,2048,64,1], K stride [256,256,64,1].
* `pairs=B*S*H*(D//2)`, `grid.x=(pairs+255)//256`, block `(256,1,1)`.

| Tensor / step | Valid pairs | Grid | Launched pairs | Tensor elements | Max accessed element | Invalid x element offsets | Invalid position reads |
|---|---:|---|---:|---:|---:|---:|---:|
| Prefill Q | 12288 | (48,1,1) | 12288 | 24576 | 24575 | 0 | 0 |
| Prefill K | 1536 | (6,1,1) | 1536 | 3072 | 3071 | 0 | 0 |
| Decode 1 Q | 1024 | (4,1,1) | 1024 | 2048 | 2047 | 0 | 0 |
| Decode 1 K | 128 | (1,1,1) | 256 | 256 | 511 | 256 | 128 |
| Decode 2 Q | 1024 | (4,1,1) | 1024 | 2048 | 2047 | 0 | 0 |
| Decode 2 K | 128 | (1,1,1) | 256 | 256 | 511 | 256 | 128 |

“Invalid x element offsets” counts 256 unique scalar offsets, each **read and written** by the kernel. First bad thread idx=128 decodes to fictitious batch=1, seq=0, head=0, pair=0. It reads `positions[1]` (`:34`), then accesses x[256],x[257] (`:43–51`). Last bad pair accesses x[510],x[511]. The allocation has 256 half elements =512 bytes. Thus 128 bad threads, 128 OOB position reads, 256 OOB half reads and 256 OOB half writes. Not 8× K. Any odd `B*S` at H=4,D=64 has the same half-block tail; an aligned prefill or passing warmup does not exonerate the kernel.

**What this establishes:** logical tensor-bound violation, **high confidence**. It does not predict the exact physical allocator neighbour or whether a particular launch faults immediately. Allocation padding/caching, memory layout, and error propagation can make it appear later. The step-1 native input token is EOS=2, but the probe deliberately calls forward twice rather than stopping generation; it therefore exercises both decode shapes.

## A.2. Stock RoPE code review

* K is **not** sized from Q: separate calls `inject.py:164–165`, dimensions from x `rotary_embedding.cu:62–65`, pair count `:68`.
* Raw kernel assumes dense `[B,S,H,D]`: flat base expression `:43`, no strides supplied. Stock launcher `:61` uses clone (may preserve noncontiguous strides); benchmark wrapper supplies contiguous inputs at `inject.py:162–163`.
* **No bounds check** between idx computation `:24` and position read `:34`, or stores `:50–51`.
* Round-up launch `:68–70,75`; exactly 256 threads per block, no total_pairs parameter to the kernel.
* Dispatch float/double plus half/bfloat16 `:72–74`; scalar arithmetic is float `:35–41,47–51`; positions int32 `:18,77`. Fast math compile flags at `bench.py:143`.
* Adjacent pairs `:44–45` are wrong for this Llama implementation; decode position reset is in Python, not CUDA. Host has no rank/shape/device/index-overflow checks. No explicit current-stream handling, launch error check, or synchronization `:75–84`.

**Verdict:** shared-head/noncontiguous-at-launch mechanisms contradicted; missing-tail-guard mechanism proven from source and actual CPU shapes. Historical RoPE attribution strong but GPU confirmation outstanding. High confidence in source conclusion; medium-high in historical attribution.

## A.3. Stock attention code review

* Dense BHND indexing and equal Q/K/V head count assumed at `attention.cu:34–37,61,129`; no stride arguments. Launcher takes B,H,Nq,D from Q and Nkv from K at `:144–148`, with no validation of other dimensions. Wrapper contiguates inputs (`inject.py:120–122`). No general GQA handling.
* Grid=(B,H,Nq), threads=min(Nkv,256), dynamic shared=(Nkv+D)*4 (`:153–155`). At actual prefill: grid=(1,32,12), block=(12,1,1), shared=304 bytes. Each loop has j<Nkv or d<D (`:49,56,95,120,126,128`). Shared warp array is 32 floats (`:75`), adequate for <=256 threads.
* No tensor-bound guard on base_q/base_k/base_v; safety depends on host shape/layout contract. In the observed expanded-head shapes these offsets fit. No launch resource validation.
* Full-mask shuffles on partial warps (`:72,87,103,112`) read inactive lanes at N=12 (also warmup N=2), a separate correctness defect. C3 rounds thread count up to full warps, retaining parallel reductions and existing neutral values, without importing the entire fix branch's slower serial algorithm.
* Scalar dispatch matches RoPE (`:157–164`), float accumulation/scaling/softmax (`:60–65,96,127–132`). Default-stream launch at `:160`.
* Decode does **not execute this custom attention** on cached Nq!=Nkv: `inject.py:110–118` falls back to native SDPA. A.1 logged the native attention op, not proof of custom decode execution. On this test the injected expected attention count is 22, not 66.

**Conclusion:** attention is implicated enough to justify a **separate** patch, but not the GQA patch for this pin. Confidence high for partial-warp defect; historical address-fault contribution unknown.

## A.4. Injection and cache ordering

HF projection transpose → RoPE → cache update is explicit in `raw/modeling_llama.py:228–241`; attention dispatch follows at `:243–255`. `raw/sdpa_attention.py:40–42` expands KV heads; `:49–51` contiguates; `:66–74` calls SDPA. This explains why attention-only head probes cannot characterize RoPE inputs. The plan's “every transformers version” claim is broader than this evidence: verified only for the saved 4.53.3 implementation, not all releases/architectures.

Custom RoPE takes q/k only after separate permute+contiguous, constructs int32 positions from S, ignores supplied cos/sin, makes **new clone outputs**, then permutes them back (`inject.py:156–167`, `rotary_embedding.cu:61,84`). Returned prefill tensors may be noncontiguous; that matches native projection/RoPE layouts and torch.cat can handle them. No output uses a freed Python buffer by construction. Custom attention returns new empty_like(Q) filled by the device; fused MLP overwrites its own gate projection, not the caller's hidden_states. RMSNorm likewise allocates output.

`except Exception` around RoPE and attention can conceal the original kernel fault. The supplied blocking traceback (`evidence/debug8_blocking.log:86–95`) therefore does **not** localize it to torch.cat. Our diagnostic proxy syncs each custom op and raises a BaseException-derived KernelFailure outside those catch clauses. Fresh processes avoid global monkeypatch contamination. This instrumentation is diagnostic only, not throughput measurement.

## A.5. What 11ea904 changed, and what it does not prove

Complete supplied diff: `upstream-11ea904.patch`; focused diffs in `raw/upstream_{rope,attention,inject,bench}.diff`.

1. **RoPE** `fix:kernels/rotary_embedding.cu:27,31,80–92`: passes total_pairs, returns for idx>=total_pairs. This directly fixes our tail proof. `:46–52` replaces fast exponent/trig with double pow/sincos and float angle; `:56–57` changes adjacent pairing to half-vector pairing. This also changes numerical results and speed, not merely bounds.
2. **Positions/injection** `fix:inject.py:151–168,178–184`: pins original unpatched function, hooks model rotary forward to retain real position_ids, converts/expands/contiguates them. `:108–119` also falls back on explicit attention masks, not just cached decode. These address decode offsets, repeated injection, and mask semantics.
3. **Attention** `fix:kernels/attention.cu:44–45,62,109,129–130`: maps query head to KV group and validates divisibility. `:73–96` replaces warp reductions with serial thread-0 max/sum; removes shared Q staging. Shared bytes become Nkv*4 (`:137`). This removes the partial-warp reduction problem too, but bundles GQA support and algorithm/performance changes. A passing full branch would not isolate which mattered.
4. **Other kernels** `upstream-11ea904.patch:698–819` changes cuBLAS-backed MLP to a naive fused dot-product implementation; `:820–919` rewrites RMSNorm and rounds its block size to full warps. Starter attention/RoPE/RMSNorm also change (`:1030–end`). Thus this is not merely “a two-kernel bounds fix.”
5. **Benchmark/evaluation** `fix:bench.py:117–166` adds teacher-forced correctness, `:242–295` caches native references and requires local starters without native fallback, `:319–324` checks agent correctness. `fix:config.py:41–61` adds four prompts, 32 correctness tokens, mean-KL<=0.01 and top1>=0.95. Supplied diff `:2–142` stages a pristine harness, drops submitted cached results, runs a fresh benchmark subprocess with 2400s timeout, and gates score on correctness. Other instruction/side-task changes are present but not adopted.

The branch corroborates specific defects, **not** runtime proof of the old crash. It still lacks general stream/device/stride validation and uses float arithmetic under half output rounding; no claim of universal correctness is warranted. Confidence high for the diff description, unknown for GPU behaviour.

## B. Minimal patches, tests, and measurement scope

### Arm isolation

`arms/C1/` is an exact copy of stock (hashes `raw/stock_sha256.txt` and `raw/C1_sha256.txt` match). `arms/C2/` changes only `kernels/rotary_embedding.cu`. `arms/C3/` adds only the attention launch change. `make_patches.py` reconstructs these copies and full diffs. It never modifies the pinned trees. No blanket replacement by 11ea904.

The existing Python wrapper already fulfills the requested **separate q/k launches using their own shapes and contiguous inputs** (`inject.py:162–165`); there is no reason to duplicate or rewrite it. The added C++ contiguous calls also cover direct op callers and expanded positions. The minimal causal repair is the total_pairs parameter + early return; small host checks reject wrong rank, device, int32 positions, odd/zero D, mismatched position shape, and index sizes beyond safe int32 range. Empty input returns its clone rather than launching zero blocks. Bounds are checked **before the position read**, not just before the stores.

Scope remains single-device/default-stream inference, positive supported short dimensions and standard TinyLlama base. No claim of general stream-safety, dynamic RoPE scaling, training, arbitrary masks or arbitrary unexpanded GQA support. Safety patch does not repair stock math. This is deliberate experimental isolation, not a proposed complete upstream correctness release.

### Full diff: C1 → C2 (also in `rope-safety.patch`)
```diff
--- a/kernels/rotary_embedding.cu
+++ b/kernels/rotary_embedding.cu
@@ -11,6 +11,7 @@
 #include <cuda_runtime.h>
 #include <cuda_fp16.h>
 #include <math.h>
+#include <climits>
 
 template <typename scalar_t>
 __global__ void rotary_embedding_kernel(
@@ -19,9 +20,11 @@
     int seq_len,
     int num_heads,
     int head_dim,
-    float base
+    float base,
+    int total_pairs
 ) {
     int idx = blockIdx.x * blockDim.x + threadIdx.x;
+    if (idx >= total_pairs) return;
     int half_dim = head_dim / 2;
 
     int pair_idx = idx % half_dim;
@@ -58,7 +61,18 @@
     torch::Tensor positions,   // [batch, seq_len] int32
     double base
 ) {
+    TORCH_CHECK(x.is_cuda() && positions.is_cuda(), "RoPE requires CUDA tensors");
+    TORCH_CHECK(x.device() == positions.device(), "RoPE device mismatch");
+    TORCH_CHECK(x.dim() == 4 && positions.dim() == 2, "RoPE rank mismatch");
+    TORCH_CHECK(positions.scalar_type() == at::kInt, "RoPE positions must be int32");
+    TORCH_CHECK(x.size(3) > 0 && x.size(3) % 2 == 0, "RoPE requires even head_dim");
+    TORCH_CHECK(positions.size(0) == x.size(0) && positions.size(1) == x.size(1),
+                "RoPE positions shape mismatch");
+    TORCH_CHECK(x.numel() <= INT_MAX - 512, "RoPE indexing exceeds int32 range");
+    x = x.contiguous();
+    positions = positions.contiguous();
     auto output = x.clone();
+    if (x.numel() == 0) return output;
     int batch = x.size(0);
     int seq_len = x.size(1);
     int num_heads = x.size(2);
@@ -76,7 +90,7 @@
                 output.data_ptr<scalar_t>(),
                 positions.data_ptr<int>(),
                 seq_len, num_heads, head_dim,
-                static_cast<float>(base)
+                static_cast<float>(base), total_pairs
             );
         }
     );

```

### Full diff: C2 → C3 (also in `attention-warps.patch`)

```diff
--- a/kernels/attention.cu
+++ b/kernels/attention.cu
@@ -151,7 +151,8 @@
     auto output = torch::empty_like(Q);
 
     dim3 grid(batch, heads, q_len);
-    int threads = min(kv_len, 256);
+    // Full-mask shuffles require full warps, including the first reduction warp.
+    int threads = min(((kv_len + 31) / 32) * 32, 256);
     int smem_size = (kv_len + head_dim) * sizeof(float);
 
     AT_DISPATCH_FLOATING_TYPES_AND2(

```
