"""Option 3 CPU checks (Amendment (14)), $0: princeton-nlp/Sheared-LLaMA-1.3B (revision pinned) on CPU in float16.
  1. hook: q/k shapes at apply_rotary_pos_emb for one prefill and two decode steps (and the per-token pair counts);
  2. the real launch shapes: the model generates the 8 eval prompts x 16 tokens with the STOCK inject.py and the STOCK
     rotary kernel (compiled for CPU, padded buffers) injected as the only op; every distinct (B,S,H,D) the kernel is
     launched with is recorded with its pair count and tail (blocks*256 - pairs); the ASan battery is then run on each.
Usage: python o3_check.py <options dir>"""
import ctypes, importlib.util, json, os, subprocess, sys
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from transformers.models.llama import modeling_llama as LM
D = sys.argv[1]; SIM = os.path.join(D, "sim")
MODEL, REV = "princeton-nlp/Sheared-LLaMA-1.3B", "a4b76938edbf571ea7d7d9904861cbdca08809b4"
lib = ctypes.CDLL(os.path.join(SIM, "librope_stock_f16.so"))
lib.rope_run.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [ctypes.c_int] * 4 + [ctypes.c_float]; lib.rope_run.restype = ctypes.c_int
tok = AutoTokenizer.from_pretrained(MODEL, revision=REV)
model = AutoModelForCausalLM.from_pretrained(MODEL, revision=REV, torch_dtype=torch.float16).eval()
cfg = model.config; out = {"model": MODEL, "revision": REV, "config": dict(heads=cfg.num_attention_heads, kv_heads=cfg.num_key_value_heads,
       head_dim=getattr(cfg, "head_dim", None) or cfg.hidden_size // cfg.num_attention_heads, hidden=cfg.hidden_size, layers=cfg.num_hidden_layers,
       rope_theta=getattr(cfg, "rope_theta", None))}
# 1. hook
seen = []
orig = LM.apply_rotary_pos_emb
def hooked(q, k, cos, sin, *a, **kw):
    if len(seen) < 3 or (len(seen) % cfg.num_hidden_layers == 0 and len(seen) < 3 * cfg.num_hidden_layers):
        seen.append(dict(q=list(q.shape), k=list(k.shape), q_contig=q.is_contiguous(), k_contig=k.is_contiguous(), dtype=str(q.dtype), cos=list(cos.shape)))
    else:
        seen.append(None)
    return orig(q, k, cos, sin, *a, **kw)
LM.apply_rotary_pos_emb = hooked
with torch.no_grad():
    ids = tok("Explain the theory of relativity in simple terms.", return_tensors="pt")
    model.generate(**ids, max_new_tokens=3, min_new_tokens=3, do_sample=False)
LM.apply_rotary_pos_emb = orig
hook = [s for s in seen if s][:6]
for h in hook:
    hq, hk = h["q"], h["k"]
    h["q_pairs_per_token"] = hq[1] * hq[3] // 2; h["k_pairs_per_token"] = hk[1] * hk[3] // 2
print("HOOK", json.dumps(hook)); out["hook"] = hook
# 2. real launch shapes through the stock inject.py + stock kernel
src = subprocess.run(["git", "-C", "/root/src/ResearchArena", "show", "58776e09339c1714d0524130590abaf6eac7879d:settings/cuda_kernel/task_context/inject.py"], capture_output=True, text=True, check=True).stdout
p = os.path.join(D, "inject_stock.py"); open(p, "w").write(src)
spec = importlib.util.spec_from_file_location("inject_stock", p); inj = importlib.util.module_from_spec(spec); spec.loader.exec_module(inj)
shapes = {}
class Ops:
    def rotary_embedding(self, x, positions, base):
        x = x.contiguous(); B, S, H, Dh = x.shape; n = x.numel(); slack = 600
        buf = torch.zeros(n + slack, dtype=x.dtype); buf[:n] = x.flatten()
        pb = torch.zeros(B * S + slack, dtype=torch.int32); pb[:B * S] = positions.to(torch.int32).flatten()
        tail = lib.rope_run(buf.data_ptr(), pb.data_ptr(), B, S, H, Dh, float(base))
        key = (B, S, H, Dh); shapes.setdefault(key, {"calls": 0, "pairs": B * S * H * Dh // 2, "tail_threads": tail}); shapes[key]["calls"] += 1
        return buf[:n].view(B, S, H, Dh).clone()
injected = inj.inject_agent_kernels(model, Ops())
PROMPTS = ["Explain the theory of relativity in simple terms.", "Write a Python function to compute the Fibonacci sequence.",
           "What are the main causes of climate change?", "Summarize the plot of Romeo and Juliet.",
           "Describe the process of photosynthesis step by step.", "What is the difference between TCP and UDP?",
           "Write a haiku about programming.", "Explain how a neural network learns."]
with torch.no_grad():
    for pr in PROMPTS:
        ids = tok(pr, return_tensors="pt"); model.generate(**ids, max_new_tokens=16, min_new_tokens=16, do_sample=False)
out["injected"] = injected
out["launch_shapes"] = [dict(B=k[0], S=k[1], H=k[2], D=k[3], **v) for k, v in sorted(shapes.items())]
print("SHAPES", json.dumps(out["launch_shapes"]))
# ASan on each distinct shape
asan = []
for k in sorted(shapes):
    r = subprocess.run([os.path.join(SIM, "asan_stock"), *map(str, k)], capture_output=True, text=True)
    ok = "ASAN_CLEAN" in r.stdout
    asan.append(dict(shape=list(k), asan="CLEAN" if ok else "OVERFLOW", detail=(r.stdout.splitlines() or [""])[0] if ok else (r.stderr.splitlines() or [""])[0]))
print("ASAN", json.dumps(asan)); out["asan_on_launch_shapes"] = asan
out["all_tails_zero"] = all(v["tail_threads"] == 0 for v in shapes.values()); out["all_asan_clean"] = all(a["asan"] == "CLEAN" for a in asan)
json.dump(out, open(os.path.join(D, "o3_check.json"), "w"), indent=2)
print("O3_DONE all_tails_zero=", out["all_tails_zero"], "all_asan_clean=", out["all_asan_clean"])
