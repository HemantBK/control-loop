#!/usr/bin/env python3
"""Standalone kernel tests (merged from the second tester's gpu_probe.py rope_test/attention_test, adapted to this
session's layout): compile ./kernels with bench.py's compile_kernels, then call the ops directly on exact shapes.
  --task rope      : the exact decode-K reproducer first ((1,1,4,64): 128 pairs, 256 threads), then (1,1,32,64),
                     (1,12,4,64), (1,13,4,64), (2,3,4,64) in fp16/bf16/fp32 with REAL positions (12..), compared
                     with HF's rotate_half RoPE. Under memcheck the stock kernel must report invalid accesses on the
                     first case; a bounds-only patch is memory-clean but NUMERIC_FAIL (interleaved pairs); 11ea904's
                     kernel is NUMERIC_PASS.
  --task attention : N in 1,2,12,13,14,31,32,33,255,256,257 (32 expanded heads) vs fp32 SDPA; the stock kernel runs
                     partial warps for N<32 (undefined shuffle lanes), the warps patch does not.
Prints one <ARM>_<TASK>_CASE line per case, <TASK>_MEMORY_COMPLETE, and <TASK>_NUMERIC_PASS|FAIL. Exit 0/3."""
import argparse, os, sys, time
import torch, torch.nn.functional as F
sys.path.insert(0, os.getcwd())
from bench import compile_kernels, ROOT
ap = argparse.ArgumentParser(); ap.add_argument("--task", choices=["rope", "attention"], required=True); a = ap.parse_args()
t0 = time.time()
if os.environ.get("C_PREBUILT_SET"):   # re-measure session (2026-10-24): the set built once by c_interleave.py
    from c_interleave import load_ops
    ops, err = load_ops(os.environ["C_PREBUILT_SET"]), None
else:
    ops, err = compile_kernels(os.path.join(ROOT, "kernels"), os.path.join(ROOT, "bindings.cpp"), name="agent_ops")
print(f"KT_COMPILE {'PASS' if ops else 'FAIL'} in {time.time()-t0:.0f}s {err or ''}", flush=True)
if not ops: sys.exit(2)
torch.manual_seed(42)
oks = []
if a.task == "rope":
    for dtype in (torch.float16, torch.bfloat16, torch.float32):
        for b, s, h in ((1, 1, 4), (1, 1, 32), (1, 12, 4), (1, 13, 4), (2, 3, 4)):
            x = torch.randn(b, h, s, 64, device="cuda", dtype=dtype).transpose(1, 2).contiguous()   # [b,s,h,64], dense, as inject.py:162-163 passes it (R3)
            pos = torch.arange(12, 12 + s, device="cuda", dtype=torch.int32)[None].expand(b, -1).contiguous()
            try:
                y = ops.rotary_embedding(x, pos, 10000.0); torch.cuda.synchronize()
            except Exception as e:
                print(f"ROPE_CASE {dtype} {[b,s,h,64]} EXCEPTION {repr(e)[:200]}", flush=True); oks.append(False); continue
            # R3: reference in fp32 from the same input, tolerance per dtype = the dtype's own rounding of |y|<=~5 inputs
            # rotated (fp16 ulp at 4 = 0.0039, bf16 ulp at 4 = 0.031) plus the kernel's fast-math sin/cos (~1e-6 rad);
            # fp32 1e-4 absorbs __sincosf/__expf vs torch's sin/cos/pow.
            xf = x.float()
            f = pos.float()[..., None] * 10000.0 ** (-torch.arange(32, device="cuda").float() * 2 / 64)
            c = f.cos()[:, :, None]; sn = f.sin()[:, :, None]
            hf = torch.cat([xf[..., :32] * c - xf[..., 32:] * sn, xf[..., 32:] * c + xf[..., :32] * sn], -1)
            atol = {torch.float32: 1e-4, torch.float16: 1e-2, torch.bfloat16: 6e-2}[dtype]
            ok = bool(y.shape == x.shape and torch.isfinite(y).all() and torch.allclose(y.float(), hf, atol=atol, rtol=atol))
            print(f"ROPE_CASE {dtype} {[b,s,h,64]} {ok} maxabs {float((y.float()-hf.float()).abs().max()):.4f}", flush=True); oks.append(ok)
else:
    for n in (1, 2, 12, 13, 14, 31, 32, 33, 255, 256, 257):
        for causal in (False, True):
            q, k, v = [torch.randn(1, 32, n, 64, device="cuda", dtype=torch.float16) for _ in range(3)]
            try:
                y = ops.attention(q, k, v, causal); torch.cuda.synchronize()
            except Exception as e:
                print(f"ATTENTION_CASE {n} {causal} EXCEPTION {repr(e)[:200]}", flush=True); oks.append(False); continue
            ref = F.scaled_dot_product_attention(q.float(), k.float(), v.float(), is_causal=causal).half()
            ok = bool(torch.isfinite(y).all() and torch.allclose(y, ref, atol=.02, rtol=.02))
            print(f"ATTENTION_CASE {n} {causal} {ok} maxabs {float((y.float()-ref.float()).abs().max()):.4f}", flush=True); oks.append(ok)
print(f"{a.task.upper()}_MEMORY_COMPLETE cases={len(oks)}", flush=True)
print(f"{a.task.upper()}_NUMERIC_{'PASS' if all(oks) else 'FAIL'} passed={sum(oks)}/{len(oks)}", flush=True)
sys.exit(0 if all(oks) else 3)
