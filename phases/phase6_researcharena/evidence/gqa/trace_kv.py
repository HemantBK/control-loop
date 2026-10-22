"""CPU-only trace: what K/V shapes reach inject.py's agent kernel under this transformers version.

Uses a byte-identical copy of ResearchArena 58776e0 task_context/inject.py (copied next to this script; set P6_GQA_DIR to that directory).
Fake agent_ops exposes only `attention` and `rotary_embedding`; each records its input shapes and raises,
so inject.py's own except-branch falls back to the native op (no CUDA kernel is compiled or run).
"""
import json
import sys

import torch
import torch.nn.functional as F
import transformers
from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer

import os
sys.path.insert(0, os.environ.get("P6_GQA_DIR", os.path.dirname(os.path.abspath(__file__))))
from inject import inject_agent_kernels  # noqa: E402

MODEL = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"  # config.py:16
out = {"transformers": transformers.__version__, "torch": torch.__version__}

cfg = AutoConfig.from_pretrained(MODEL)
out["config"] = {k: getattr(cfg, k, None) for k in
                 ["num_attention_heads", "num_key_value_heads", "head_dim", "hidden_size",
                  "num_hidden_layers", "rope_theta"]}
out["config"]["head_dim_derived"] = cfg.hidden_size // cfg.num_attention_heads

cfg.num_hidden_layers = 2  # head layout unchanged; keeps the CPU run small
torch.manual_seed(0)
model = AutoModelForCausalLM.from_config(cfg).eval()
out["attn_implementation"] = model.config._attn_implementation

calls = {"attention": [], "rotary_embedding": [], "native_sdpa": []}


class FakeOps:
    def attention(self, q, k, v, causal):
        calls["attention"].append({"q": list(q.shape), "k": list(k.shape), "v": list(v.shape),
                                   "causal": bool(causal)})
        raise RuntimeError("shape recorder: fall back")

    def rotary_embedding(self, x, positions, base):
        calls["rotary_embedding"].append({"x": list(x.shape), "positions": list(positions.shape)})
        return x.clone()  # identity: values irrelevant, lets the k call be recorded too


# record what the native SDPA gets (mask present? enable_gqa?) beneath inject's wrapper
_orig = F.scaled_dot_product_attention


def native_rec(query, key, value, attn_mask=None, dropout_p=0.0, is_causal=False, scale=None, **kw):
    calls["native_sdpa"].append({"q": list(query.shape), "k": list(key.shape),
                                 "mask_is_none": attn_mask is None, "is_causal": bool(is_causal),
                                 "extra_kwargs": sorted(kw)})
    return _orig(query, key, value, attn_mask=attn_mask, dropout_p=dropout_p, is_causal=is_causal,
                 scale=scale, **kw)


F.scaled_dot_product_attention = native_rec
injected = inject_agent_kernels(model, FakeOps(), verbose=False)
out["injected"] = injected

ids = torch.randint(3, cfg.vocab_size, (1, 8))
ids[0, 0] = 1  # BOS
with torch.no_grad():
    gen = model.generate(input_ids=ids, attention_mask=torch.ones_like(ids), max_new_tokens=3,
                         min_new_tokens=3, do_sample=False, pad_token_id=2)
out["generated_len"] = gen.shape[1]


def uniq(lst):
    seen, res = set(), []
    for d in lst:
        key = json.dumps(d, sort_keys=True)
        if key not in seen:
            seen.add(key)
            res.append(d)
    return res


out["calls_to_agent_attention"] = uniq(calls["attention"])
out["n_agent_attention_calls"] = len(calls["attention"])
out["calls_to_agent_rotary"] = uniq(calls["rotary_embedding"])
out["native_sdpa_calls"] = uniq(calls["native_sdpa"])

# prompt lengths bench.py feeds the kernels (raw tokenizer, BOS added, no chat template)
try:
    tok = AutoTokenizer.from_pretrained(MODEL)
    prompts = ["Hello",
               "Explain the theory of relativity in simple terms.",
               "Write a Python function to compute the Fibonacci sequence.",
               "What are the main causes of climate change?",
               "Summarize the plot of Romeo and Juliet.",
               "Describe the process of photosynthesis step by step.",
               "What is the difference between TCP and UDP?",
               "Write a haiku about programming.",
               "Explain how a neural network learns."]
    out["prompt_token_lengths"] = {p: len(tok(p)["input_ids"]) for p in prompts}
except Exception as e:  # tokenizer is optional
    out["prompt_token_lengths"] = f"unavailable: {e!r}"

print(json.dumps(out, indent=1, default=str))
