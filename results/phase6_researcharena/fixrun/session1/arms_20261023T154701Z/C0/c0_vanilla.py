#!/usr/bin/env python3
"""Arm C0: HF TinyLlama with no kernels injected, measured exactly as bench.py measures (same warmup, prompts,
max_new_tokens, dtype, seed). Also records the greedy token ids per prompt as the reference for later text comparison,
and writes workspace/baseline_tps.txt so later arms can skip bench.py's own baseline pass when told to.
Run from a fresh copy of task_context: `python3 c0_vanilla.py`."""
import json, os, sys, time
import torch
sys.path.insert(0, os.getcwd())
from config import ArenaConfig
from bench import load_model_and_tokenizer, benchmark_generation, apply_seed

cfg = ArenaConfig()
apply_seed(cfg.seed)
print(f"C0 torch={torch.__version__} cuda={torch.version.cuda} gpu={torch.cuda.get_device_name(0)}", flush=True)
model, tok = load_model_and_tokenizer(cfg)
res = benchmark_generation(model, tok, cfg, None)
print(f"C0_BASELINE_TPS={res['avg_tokens_per_sec']:.2f}", flush=True)
os.makedirs(cfg.workspace_dir, exist_ok=True)
with open(os.path.join(cfg.workspace_dir, "baseline_tps.txt"), "w") as f:
    f.write(f"{res['avg_tokens_per_sec']:.4f}\n")
# reference greedy outputs (first 32 new tokens of each prompt) for the correctness comparison in C2/C3
outs = {}
with torch.no_grad():
    for p in cfg.eval_prompts:
        x = tok(p, return_tensors="pt").to(cfg.device)
        y = model.generate(**x, max_new_tokens=32, min_new_tokens=32, do_sample=False, max_length=None)
        outs[p] = {"new_token_ids": y[0, x["input_ids"].shape[1]:].tolist(), "text": tok.decode(y[0, x["input_ids"].shape[1]:])}
        print(f"C0_TEXT {p[:40]!r}: {outs[p]['text'][:80]!r}", flush=True)
json.dump({"baseline_tps": res, "outputs": outs}, open(os.path.join(cfg.workspace_dir, "c0_outputs.json"), "w"), indent=1)
torch.cuda.synchronize()
print("C0_DONE", flush=True)
