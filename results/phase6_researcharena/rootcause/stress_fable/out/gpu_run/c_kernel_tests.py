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
ops, err = compile_kernels(os.path.join(ROOT, "kernels"), os.path.join(ROOT, "bindings.cpp"), name="agent_ops")
print(f"KT_COMPILE {'PASS' if ops else 'FAIL'} in {time.time()-t0:.0f}s {err or ''}", flush=True)
if not ops: sys.exit(2)
torch.manual_seed(42)
oks = []
if a.task == "rope":
    for dtype in (torch.float16, torch.bfloat16, torch.float32):
        for b, s, h in ((1, 1, 4), (1, 1, 32), (1, 12, 4), (1, 13, 4), (2, 3, 4)):
            x = torch.randn(b, h, s, 64, device="cuda", dtype=dtype).transpose(1, 2)          # [b,s,h,64], non-contiguous
            pos = torch.arange(12, 12 + s, device="cuda", dtype=torch.int32)[None].expand(b, -1).contiguous()
            try:
                y = ops.rotary_embedding(x, pos, 10000.0); torch.cuda.synchronize()
            except Exception as e:
                print(f"ROPE_CASE {dtype} {[b,s,h,64]} EXCEPTION {repr(e)[:200]}", flush=True); oks.append(False); continue
            f = pos.float()[..., None] * 10000.0 ** (-torch.arange(32, device="cuda").float() * 2 / 64)
            c = f.cos().to(dtype)[:, :, None]; sn = f.sin().to(dtype)[:, :, None]
            hf = torch.cat([x[..., :32] * c - x[..., 32:] * sn, x[..., 32:] * c + x[..., :32] * sn], -1)
            ok = bool(y.shape == x.shape and torch.isfinite(y).all() and torch.allclose(y, hf, atol=.02, rtol=.02))
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
