# Draft upstream issue for aisa-group/ResearchArena (not filed)

Written 2026-10-22 by the control-loop pod manager on the owner's instruction: "Log the published-container crash as an
upstream issue with evidence, filed after the call." Status: **draft, not filed** (agents do not open issues; the owner
files it after the call). Evidence paths are in this repository; the issue text below quotes only public facts.

---

**Title:** cuda_kernel: starter/agent attention kernels read K/V out of bounds under transformers 5.3.0 (arena.def pin) because K/V arrive unexpanded (GQA)

**Summary.** On `main` at 58776e0, `containers/arena.def` installs `transformers==5.3.0`. For TinyLlama-1.1B-Chat (32 query
heads, 4 key/value heads), transformers ≥ 4.54.0 passes K/V to SDPA unexpanded (`[B, 4, T, 64]`, `enable_gqa=True`, via
`integrations/sdpa_attention.py::use_gqa_in_sdpa`) when no attention mask is given. `settings/cuda_kernel/task_context/inject.py`
(lines 107–109, 123) drops `enable_gqa` and calls `ops.attention(q, k, v, is_causal)`; the kernels index K/V with the query
head (`kernels/attention.cu:61,129`; `starter_kernels/attention.cu:37,57,104`: `(b*num_heads + h)*kv_len*head_dim`). Heads
4–31 read past the end of K and V: 7 KB at the warmup prompt and 28–50 KB at the benchmark prompts. Observed: `CUDA error: an
illegal memory access was encountered` on the first benchmark prompt in three agent episodes whose kernels were stock or lightly
edited (one of them a clean run whose only edit has no effect at prefill lengths). The link between the two rests on CPU
evidence (the shape trace below) and the timing of the crashes; we did not run the stock kernels on a GPU under 5.3.0 and
4.53.3 to confirm it, and the RoPE kernel's missing bounds guard (see Related) is an alternative we could not rule out.

**Environment.** H100 SXM 80 GB (RunPod, EU-FR-1), image based on nvidia/cuda 12.9.0 cudnn-devel (Ubuntu 22.04), Python
3.11, torch 2.10.0 (PyPI wheel, CUDA 12.8 runtime), nvcc 12.9, transformers 5.3.0 as arena.def pins, `--task_config
tinyllama`, setting `cuda_kernel`, no Apptainer (the pipeline's local fallback).

**Shapes reaching `ops.attention` (prefill, T = 8), traced on CPU with a byte-identical copy of inject.py and a recording
stub for `agent_ops`:**

| transformers | q | k / v |
|---|---|---|
| 4.44.2 | [1, 32, 8, 64] | [1, 32, 8, 64] |
| 4.53.3 | [1, 32, 8, 64] | [1, 32, 8, 64] |
| 5.3.0 | [1, 32, 8, 64] | **[1, 4, 8, 64]** |

The switch is between 4.53.3 and 4.54.0 (first release with `use_gqa_in_sdpa`; 4.54.1, 4.55.x, 4.56.2 also have it).

**Observed on GPU.** Three agent episodes (one of them a clean run whose only edit, an attention launch-size change, has no
effect at prefill lengths 2–14) compiled the kernels, passed the warmup, and crashed at benchmark prompt 1 with the error
above (eval log line: `Main task evaluation error: CUDA error: an illegal memory access was encountered`).

**Related.** Branch `origin/cuda-correction`, commit 11ea904 ("correct kernels", 2026-10-21), makes
`starter_kernels/attention.cu` GQA-aware (`kv_h = h / (num_heads / num_kv_heads)`), rewrites `kernels/attention.cu`, and adds
an `idx >= total_pairs` guard to `kernels/rotary_embedding.cu` (which on `main` writes past its output on decode steps). It
is not on `main` and the published container still pins 5.3.0.

**Suggested fix.** Either merge 11ea904 into `main`, or pin `transformers<4.54` (e.g. 4.53.3) in arena.def while the kernels
assume expanded K/V; and/or have inject.py call `repeat_kv` (or honour `enable_gqa`) before `ops.attention`. Note that
arena.def's 5.3.0 is also outside vllm 0.17.0's declared `transformers>=4.56.0,<5`.

**Repro (CPU, no GPU needed for the shape evidence).** A ~100-line script builds TinyLlama from its config with 2 layers,
applies inject.py with a stub op that records input shapes, and runs `generate` on a [1, 8] input; available on request.

---

Evidence in this repository: phases/phase6_researcharena/FINDINGS.md ("CPU-only head-layout analysis", 2026-10-22);
results/phase6_researcharena/sweep/qwen3_733_run2/{CHECK_BYHAND.md, clean/run1/e1/eval/eval_attempt_1.log,
rounds/r0a/e1/, rounds/r0a/e3/}; the trace script and its outputs are in phases/phase6_researcharena/evidence/gqa/ (`trace_kv.py`,
`trace_{4.44.2,4.53.3,5.3.0}.json`; the script needs a copy of ResearchArena's inject.py beside it, not included).
