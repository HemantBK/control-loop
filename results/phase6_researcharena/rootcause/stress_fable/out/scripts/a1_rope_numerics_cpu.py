#!/usr/bin/env python3
"""
CPU emulation of the RoPE kernels' index and angle arithmetic (no CUDA), on the real q/k tensors of TinyLlama layer 0.
Compares, against transformers' own apply_rotary_pos_emb (the function inject.py replaces):
  (a) the stock kernel (rotary_embedding.cu:24-51) driven as inject.py:158-165 drives it (positions = arange(seq_len),
      interleaved pairs (2i, 2i+1)), restricted to its in-bounds threads;
  (b) the Step-B bounds patch (same arithmetic as (a), only the tail threads removed) -> identical numbers to (a);
  (c) the 11ea904 kernel (rotate_half pairs (i, i+d/2), real position ids) -> should match HF.
Also enumerates, for every bench prompt length and for decode, the stock launcher's out-of-bounds thread count.
"""
import json, math, os, sys
import torch
import transformers.models.llama.modeling_llama as llama_mod
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_ID = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
OUT = sys.argv[1] if len(sys.argv) > 1 else "a1_rope_numerics.json"
PROMPTS = ["Hello", "Explain the theory of relativity in simple terms.", "Write a Python function to compute the Fibonacci sequence.",
           "What are the main causes of climate change?", "Summarize the plot of Romeo and Juliet.",
           "Describe the process of photosynthesis step by step.", "What is the difference between TCP and UDP?",
           "Write a haiku about programming.", "Explain how a neural network learns."]

def emulate(x_t, positions, base, layout, in_bounds_only=True):
    """x_t [B,T,H,D] contiguous; positions [B,T] int32. Returns a float32 copy with the rotation applied, as the
    kernel would write it (fp32 math, cast back to x dtype). layout: 'interleaved' (stock) or 'half' (11ea904/HF)."""
    B, T, H, D = x_t.shape; half = D // 2
    x = x_t.reshape(-1).float().clone()
    pos = positions.reshape(-1).tolist()
    total = B * T * H * half
    for idx in range(total):
        pair = idx % half; tmp = idx // half; head = tmp % H; tmp2 = tmp // H; seq = tmp2 % T; batch = tmp2 // T
        m = pos[batch * T + seq]
        theta = 1.0 / (base ** ((2.0 * pair) / D))
        ang = m * theta
        c, s = math.cos(ang), math.sin(ang)
        b = ((batch * T + seq) * H + head) * D
        if layout == "interleaved":
            i0, i1 = b + 2 * pair, b + 2 * pair + 1
        else:
            i0, i1 = b + pair, b + pair + half
        x0, x1 = x[i0].item(), x[i1].item()
        x[i0] = x0 * c - x1 * s
        x[i1] = x1 * c + x0 * s
    return x.to(x_t.dtype).reshape(B, T, H, D)

def main():
    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, torch_dtype=torch.float16, device_map="cpu").eval()
    base = float(model.config.rope_theta)
    res = {"rope_theta": base, "prompt_lengths": {}, "launch_table": [], "numerics": []}
    # 1) prompt lengths and the stock launcher's tail for k (4 heads) and q (32 heads), prefill and decode
    for p in PROMPTS:
        T = tok(p, return_tensors="pt")["input_ids"].shape[1]
        res["prompt_lengths"][p] = T
    for T in sorted(set(res["prompt_lengths"].values()) | {1}):
        for name, H in (("q", 32), ("k", 4)):
            tp = T * H * 32; blocks = (tp + 255) // 256
            res["launch_table"].append({"T": T, "tensor": name, "H": H, "total_pairs": tp, "blocks": blocks,
                                        "oob_threads": blocks * 256 - tp, "bytes_past_end": (blocks * 256 - tp) * 2 * 2})
    # 2) numerics on the real layer-0 tensors, prefill T=12 and the first decode step
    captured = []
    orig = llama_mod.apply_rotary_pos_emb
    def hook(q, k, cos, sin, position_ids=None, unsqueeze_dim=1):
        out = orig(q, k, cos, sin, position_ids, unsqueeze_dim)
        if len(captured) < 2:   # layer 0 of prefill, then layer 0 of decode 1 (22 layers apart)
            captured.append((q.detach().clone(), k.detach().clone(), cos.detach().clone(), sin.detach().clone(), out[0].detach().clone(), out[1].detach().clone()))
        return out
    llama_mod.apply_rotary_pos_emb = hook
    rot = model.model.rotary_emb; orig_rot = rot.forward; pids = []
    def rot_hook(x, position_ids):
        pids.append(position_ids.detach().clone()); return orig_rot(x, position_ids)
    rot.forward = rot_hook
    # capture layer 0 only: take every 22nd call
    calls = {"n": 0}
    def hook22(q, k, cos, sin, position_ids=None, unsqueeze_dim=1):
        out = orig(q, k, cos, sin, position_ids, unsqueeze_dim)
        if calls["n"] % 22 == 0 and len(captured) < 2:
            captured.append((q.detach().clone(), k.detach().clone(), cos.detach().clone(), sin.detach().clone(), out[0].detach().clone(), out[1].detach().clone()))
        calls["n"] += 1
        return out
    llama_mod.apply_rotary_pos_emb = hook22
    inputs = tok(PROMPTS[1], return_tensors="pt")
    with torch.no_grad():
        model.generate(**inputs, max_new_tokens=2, min_new_tokens=2, do_sample=False, max_length=None)
    for step, (q, k, cos, sin, q_hf, k_hf) in enumerate(captured):
        real_pos = pids[step].to(torch.int32)
        B, Hq, T, D = q.shape
        arange_pos = torch.arange(T, dtype=torch.int32).unsqueeze(0).expand(B, -1)
        entry = {"step": "prefill" if step == 0 else "decode1", "T": T, "real_position_ids": real_pos.flatten().tolist(),
                 "inject_arange_positions": arange_pos.flatten().tolist()}
        for name, x, ref in (("q", q, q_hf), ("k", k, k_hf)):
            x_t = x.permute(0, 2, 1, 3).contiguous()
            ref_t = ref.permute(0, 2, 1, 3).contiguous().float()
            stock = emulate(x_t, arange_pos, base, "interleaved").float()
            fix_pos_only = emulate(x_t, real_pos, base, "interleaved").float()
            fix_layout_only = emulate(x_t, arange_pos, base, "half").float()
            full = emulate(x_t, real_pos, base, "half").float()
            entry[name] = {
                "max_abs_diff_vs_HF": {
                    "stock_kernel_math (arange positions, interleaved pairs) [= Step-B bounds patch]": (stock - ref_t).abs().max().item(),
                    "real positions, interleaved pairs": (fix_pos_only - ref_t).abs().max().item(),
                    "arange positions, rotate_half pairs": (fix_layout_only - ref_t).abs().max().item(),
                    "real positions, rotate_half pairs [= 11ea904 kernel + its inject.py change]": (full - ref_t).abs().max().item()},
                "ref_abs_max": ref_t.abs().max().item()}
        res["numerics"].append(entry)
        print(json.dumps(entry, indent=1))
    json.dump(res, open(OUT, "w"), indent=1)
    print("prompt lengths:", res["prompt_lengths"])
    for r in res["launch_table"]:
        if r["oob_threads"]:
            print("OOB:", r)
    print("WROTE", OUT)

if __name__ == "__main__":
    main()
