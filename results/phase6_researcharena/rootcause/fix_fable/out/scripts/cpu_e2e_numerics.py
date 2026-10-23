#!/usr/bin/env python3
"""End-to-end CPU evidence for the decision-rule question: with inject.py's real injection path and a PyTorch stand-in
that reproduces each RoPE kernel's arithmetic exactly (vectorised, fp32 math, cast back), do the greedy tokens of
TinyLlama match vanilla HF?
  arm 'bounds'  = stock inject.py (positions = arange, i.e. 0 on every decode step) + stock kernel math (interleaved
                  pairs (2i, 2i+1)); this is what rope_bounds.patch / rope-safety.patch keep.
  arm 'correct' = 11ea904 inject.py (real position_ids via the rotary_emb hook) + 11ea904 kernel math (rotate_half pairs).
Only rotary_embedding is injected (attention/rmsnorm/fused_mlp stay native) so the comparison isolates RoPE.
"""
import json, os, sys, importlib.util, math
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
MODEL = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
PROMPTS = ["Hello", "Explain the theory of relativity in simple terms.", "Write a haiku about programming."]
N_NEW = 16
OUT = sys.argv[1] if len(sys.argv) > 1 else "cpu_e2e_numerics.json"

class RopeStub:
    def __init__(self, layout): self.layout = layout; self.calls = 0; self.positions_seen = []
    def rotary_embedding(self, x, positions, base):
        # x: [B, S, H, D] (inject.py made it contiguous); positions: [B, S] int32
        self.calls += 1; self.positions_seen.append(positions.flatten().tolist()[:4])
        B, S, H, D = x.shape; half = D // 2
        pair = torch.arange(half, dtype=torch.float32)
        theta = 1.0 / (base ** (2.0 * pair / D))                      # kernel :36-37 / fix :46-47
        ang = positions.float().reshape(B, S, 1, 1) * theta.reshape(1, 1, 1, half)
        c, s = torch.cos(ang), torch.sin(ang)
        xf = x.float()
        if self.layout == "interleaved":                               # stock :44-45
            x0, x1 = xf[..., 0::2], xf[..., 1::2]
            o = torch.empty_like(xf); o[..., 0::2] = x0 * c - x1 * s; o[..., 1::2] = x0 * s + x1 * c
        else:                                                          # 11ea904 :56-57
            x0, x1 = xf[..., :half], xf[..., half:]
            o = torch.cat([x0 * c - x1 * s, x1 * c + x0 * s], dim=-1)
        return o.to(x.dtype)

def load_inject(path):
    spec = importlib.util.spec_from_file_location("inject_" + str(abs(hash(path))), path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def run(arm, inject_path, layout, tok, ref):
    import transformers.models.llama.modeling_llama as lm
    lm.apply_rotary_pos_emb = ORIG_ROPE                                # fresh module state for every arm
    model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float16, device_map="cpu").eval()
    inj = load_inject(inject_path); stub = RopeStub(layout)
    flags = inj.inject_agent_kernels(model, stub, verbose=False)
    res = {"arm": arm, "inject": inject_path, "layout": layout, "injected": flags, "prompts": {}}
    for p in PROMPTS:
        x = tok(p, return_tensors="pt")
        with torch.no_grad():
            y = model.generate(**x, max_new_tokens=N_NEW, min_new_tokens=N_NEW, do_sample=False, max_length=None)
        ids = y[0, x["input_ids"].shape[1]:].tolist()
        same = sum(1 for a, b in zip(ids, ref[p])) if ref else None
        match = (ids == ref[p]) if ref else None
        first_div = next((i for i, (a, b) in enumerate(zip(ids, ref[p])) if a != b), None) if ref else None
        res["prompts"][p] = {"ids": ids, "text": tok.decode(ids), "matches_vanilla": match, "first_divergence": first_div}
    res["rope_calls"] = stub.calls; res["positions_sample"] = stub.positions_seen[:2] + stub.positions_seen[22*1:22*1+1] + stub.positions_seen[22*2:22*2+1]
    lm.apply_rotary_pos_emb = ORIG_ROPE
    return res

tok = AutoTokenizer.from_pretrained(MODEL)
import transformers.models.llama.modeling_llama as lm
ORIG_ROPE = lm.apply_rotary_pos_emb
# vanilla reference
model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float16, device_map="cpu").eval()
ref = {}
for p in PROMPTS:
    x = tok(p, return_tensors="pt")
    with torch.no_grad():
        y = model.generate(**x, max_new_tokens=N_NEW, min_new_tokens=N_NEW, do_sample=False, max_length=None)
    ref[p] = y[0, x["input_ids"].shape[1]:].tolist()
    print(f"VANILLA {p[:30]!r}: {tok.decode(ref[p])!r}")
del model
stock_inject = os.path.expanduser("~/context/07_researcharena_58776e0_task_context/inject.py")
fix_inject = os.path.expanduser("~/work/tc_c2c/inject.py")
out = {"vanilla": {p: {"ids": ref[p], "text": tok.decode(ref[p])} for p in PROMPTS}, "arms": []}
for arm, path, layout in (("bounds_patch (stock inject.py + stock math)", stock_inject, "interleaved"),
                          ("11ea904 (fix inject.py + rotate_half math)", fix_inject, "half"),
                          ("control: stock inject.py + rotate_half math (positions still arange)", stock_inject, "half"),
                          ("control: fix inject.py + stock interleaved math (real positions)", fix_inject, "interleaved")):
    r = run(arm, path, layout, tok, ref); out["arms"].append(r)
    print(f"\nARM {arm}: rope_calls={r['rope_calls']} positions_sample={r['positions_sample']}")
    for p, v in r["prompts"].items():
        print(f"   {p[:30]!r}: match={v['matches_vanilla']} first_divergence={v['first_divergence']} text={v['text'][:70]!r}")
json.dump(out, open(OUT, "w"), indent=1); print("WROTE", OUT)
