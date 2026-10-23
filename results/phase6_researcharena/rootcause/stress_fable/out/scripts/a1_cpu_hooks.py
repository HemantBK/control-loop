#!/usr/bin/env python3
"""
Step A.1 (CPU, no custom kernels): TinyLlama-1.1B-Chat in the benchmark's dtype (float16) with hooks at
  (1) transformers.models.llama.modeling_llama.apply_rotary_pos_emb  (the symbol inject.py:149/172 replaces)
  (2) transformers.cache_utils.DynamicCache.update                     (the KV-cache update, cache_utils.py:557 in 4.53.3)
  (3) torch.nn.functional.scaled_dot_product_attention                 (the attention op inject.py:132 replaces)
  (4) model.model.rotary_emb.forward                                   (where cos/sin are computed from position_ids)
Logs shape / stride / is_contiguous() / dtype of q, k (and cos, sin, position_ids, cache tensors) for one prefill and
two decode steps, then applies the stock launcher's grid/block arithmetic (rotary_embedding.cu:61-70) and the kernel's
index arithmetic (rotary_embedding.cu:24-51) to those exact tensors to count out-of-bounds threads and the addresses
they touch. No GPU and no CUDA kernel is involved.
"""
import json, os, sys, time
import torch
import torch.nn.functional as F

MODEL_ID = os.environ.get("ARENA_MODEL_ID", "TinyLlama/TinyLlama-1.1B-Chat-v1.0")
DTYPE_NAME = os.environ.get("A1_DTYPE", "float16")   # the benchmark's dtype (config.py:26)
PROMPTS = ["Hello", "Explain the theory of relativity in simple terms."]  # bench.py:76 warmup, config.py:44 prompt 1
MAX_NEW = 3   # prefill + 2 decode steps
OUT = sys.argv[1] if len(sys.argv) > 1 else "a1_cpu_hooks.json"

def desc(t):
    if t is None:
        return None
    if not torch.is_tensor(t):
        return repr(t)
    return {"shape": list(t.shape), "stride": list(t.stride()), "contiguous": t.is_contiguous(),
            "dtype": str(t.dtype).replace("torch.", ""), "numel": t.numel(), "nbytes": t.numel() * t.element_size()}

log = []        # every hook event
state = {"step": -1, "layer_calls": 0}

# ---------------------------------------------------------------- stock launcher / kernel arithmetic (CPU re-implementation)
def stock_launch_math(x_t, positions):
    """x_t: the tensor inject.py:162-163 hands to ops.rotary_embedding ([B, T, H, D] contiguous).
    Reproduces rotary_embedding.cu:62-70 (sizes, total_pairs, blocks) and :24-45 (per-thread index math) and
    reports what threads with idx >= total_pairs would touch. Also checks the in-bounds threads never leave the tensor."""
    B, T, H, D = x_t.shape
    half = D // 2
    total_pairs = B * T * H * half
    threads = 256
    blocks = (total_pairs + threads - 1) // threads
    launched = blocks * threads
    oob = launched - total_pairs
    numel = x_t.numel()
    pos_numel = positions.numel()
    worst_x = -1; worst_pos = -1; first_oob_thread = None
    pos_oob_reads = 0; x_oob_rw = 0
    for idx in range(total_pairs, launched):
        pair_idx = idx % half; tmp = idx // half; head = tmp % H; tmp2 = tmp // H
        seq = tmp2 % T; batch = tmp2 // T
        pidx = batch * T + seq
        base_idx = ((batch * T + seq) * H + head) * D
        i0 = base_idx + 2 * pair_idx; i1 = i0 + 1
        if pidx >= pos_numel: pos_oob_reads += 1
        if i1 >= numel: x_oob_rw += 1
        worst_x = max(worst_x, i1); worst_pos = max(worst_pos, pidx)
        if first_oob_thread is None:
            first_oob_thread = {"idx": idx, "block": idx // threads, "thread": idx % threads, "batch": batch, "seq": seq,
                                "head": head, "pair_idx": pair_idx, "positions_index": pidx, "x_i0": i0, "x_i1": i1}
    # in-bounds threads: max index touched
    max_in = -1
    for idx in (0, total_pairs - 1):
        pair_idx = idx % half; tmp = idx // half; head = tmp % H; tmp2 = tmp // H
        seq = tmp2 % T; batch = tmp2 // T
        max_in = max(max_in, ((batch * T + seq) * H + head) * D + 2 * pair_idx + 1)
    return {"B": B, "T": T, "H": H, "D": D, "half_dim": half, "total_pairs": total_pairs, "threads": threads,
            "blocks": blocks, "launched_threads": launched, "oob_threads": oob,
            "x_numel": numel, "x_bytes": numel * x_t.element_size(),
            "positions_numel": pos_numel, "positions_bytes": pos_numel * 4,
            "oob_threads_reading_positions_past_end": pos_oob_reads,
            "oob_threads_rw_x_past_end": x_oob_rw,
            "highest_x_index_touched": worst_x, "x_bytes_past_end": max(0, (worst_x + 1 - numel)) * x_t.element_size(),
            "highest_positions_index_read": worst_pos,
            "first_oob_thread": first_oob_thread,
            "in_bounds_threads_max_index": max_in, "in_bounds_threads_stay_inside": max_in < numel}

# ---------------------------------------------------------------- hooks
import transformers
import transformers.models.llama.modeling_llama as llama_mod
from transformers.cache_utils import DynamicCache

_orig_rope = llama_mod.apply_rotary_pos_emb
def hooked_rope(q, k, cos, sin, position_ids=None, unsqueeze_dim=1):
    ev = {"hook": "apply_rotary_pos_emb", "step": state["step"], "call": state["layer_calls"],
          "q": desc(q), "k": desc(k), "cos": desc(cos), "sin": desc(sin), "position_ids_arg": desc(position_ids)}
    if state["layer_calls"] == 0:   # layer 0 of each step: also the injected wrapper's view of things (inject.py:158-165)
        batch, seq_len = q.shape[0], q.shape[2]
        positions = torch.arange(seq_len, dtype=torch.int32).unsqueeze(0).expand(batch, -1)
        q_t = q.permute(0, 2, 1, 3).contiguous(); k_t = k.permute(0, 2, 1, 3).contiguous()
        ev["inject_positions_arange"] = {"desc": desc(positions), "values": positions.flatten().tolist()[:16]}
        ev["q_t"] = desc(q_t); ev["k_t"] = desc(k_t)
        ev["stock_launch_q"] = stock_launch_math(q_t, positions)
        ev["stock_launch_k"] = stock_launch_math(k_t, positions)
    log.append(ev)
    state["layer_calls"] += 1
    return _orig_rope(q, k, cos, sin, position_ids, unsqueeze_dim)
llama_mod.apply_rotary_pos_emb = hooked_rope

_orig_update = DynamicCache.update
def hooked_update(self, key_states, value_states, layer_idx, cache_kwargs=None):
    before = self.key_cache[layer_idx] if len(self.key_cache) > layer_idx else None
    out = _orig_update(self, key_states, value_states, layer_idx, cache_kwargs)
    if layer_idx == 0:
        log.append({"hook": "DynamicCache.update", "step": state["step"], "layer_idx": layer_idx,
                    "key_states_in": desc(key_states), "value_states_in": desc(value_states),
                    "key_cache_before": desc(before), "key_cache_after": desc(out[0]),
                    "cache_position": desc((cache_kwargs or {}).get("cache_position")),
                    "cache_position_values": (cache_kwargs or {}).get("cache_position").tolist() if (cache_kwargs or {}).get("cache_position") is not None else None,
                    "branch": "append (no torch.cat)" if before is None else ("torch.cat (cache_utils.py:557)" if before.numel() else "fill")})
    return out
DynamicCache.update = hooked_update

_orig_sdpa = F.scaled_dot_product_attention
def hooked_sdpa(query, key, value, attn_mask=None, dropout_p=0.0, is_causal=False, scale=None, **kw):
    if state.get("sdpa_calls_this_step", 0) == 0:
        log.append({"hook": "scaled_dot_product_attention", "step": state["step"], "q": desc(query), "k": desc(key),
                    "v": desc(value), "attn_mask": desc(attn_mask), "is_causal": bool(is_causal), "scale": scale,
                    "extra_kwargs": sorted(kw.keys()),
                    "inject_would_call_ops_attention": query.size(-2) == key.size(-2)})
    state["sdpa_calls_this_step"] = state.get("sdpa_calls_this_step", 0) + 1
    return _orig_sdpa(query, key, value, attn_mask=attn_mask, dropout_p=dropout_p, is_causal=is_causal, scale=scale, **kw)
F.scaled_dot_product_attention = hooked_sdpa

def main():
    from transformers import AutoModelForCausalLM, AutoTokenizer
    dtype = {"float16": torch.float16, "bfloat16": torch.bfloat16, "float32": torch.float32}[DTYPE_NAME]
    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, torch_dtype=dtype, device_map="cpu")
    model.eval()
    info = {"transformers": transformers.__version__, "torch": torch.__version__, "dtype": DTYPE_NAME,
            "attn_implementation": model.config._attn_implementation,
            "num_attention_heads": model.config.num_attention_heads, "num_key_value_heads": model.config.num_key_value_heads,
            "head_dim": model.config.hidden_size // model.config.num_attention_heads, "layers": model.config.num_hidden_layers,
            "rope_theta": model.config.rope_theta}
    print("INFO", json.dumps(info), flush=True)

    rot = model.model.rotary_emb
    _orig_rot_fwd = rot.forward
    def hooked_rot(x, position_ids):
        cos, sin = _orig_rot_fwd(x, position_ids)
        log.append({"hook": "rotary_emb.forward", "step": state["step"], "position_ids": desc(position_ids),
                    "position_ids_values": position_ids.flatten().tolist()[:32], "cos": desc(cos), "sin": desc(sin)})
        return cos, sin
    rot.forward = hooked_rot

    # count forward passes to label prefill / decode steps
    _orig_model_fwd = model.forward
    def counted_fwd(*a, **kw):
        state["step"] += 1; state["layer_calls"] = 0; state["sdpa_calls_this_step"] = 0
        ids = kw.get("input_ids")
        log.append({"hook": "model.forward", "step": state["step"], "input_ids": desc(ids),
                    "position_ids": desc(kw.get("position_ids")), "cache_position": desc(kw.get("cache_position")),
                    "cache_position_values": kw["cache_position"].tolist() if kw.get("cache_position") is not None else None,
                    "attention_mask": desc(kw.get("attention_mask"))})
        return _orig_model_fwd(*a, **kw)
    model.forward = counted_fwd

    results = {"info": info, "prompts": []}
    for p in PROMPTS:
        state["step"] = -1
        log.clear()
        inputs = tok(p, return_tensors="pt")
        t0 = time.time()
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=MAX_NEW, min_new_tokens=MAX_NEW, do_sample=False, max_length=None)
        results["prompts"].append({"prompt": p, "input_ids": inputs["input_ids"][0].tolist(), "T": inputs["input_ids"].shape[1],
                                   "generated_ids": out[0].tolist(), "text": tok.decode(out[0]), "seconds": round(time.time() - t0, 1),
                                   "events": list(log)})
        print(f"PROMPT {p!r}: T={inputs['input_ids'].shape[1]} forward passes={state['step']+1} time={time.time()-t0:.1f}s", flush=True)
    json.dump(results, open(OUT, "w"), indent=1)
    print("WROTE", OUT)

if __name__ == "__main__":
    main()
