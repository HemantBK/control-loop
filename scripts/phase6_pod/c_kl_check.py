#!/usr/bin/env python3
"""Per-token KL of the agent's kernels against vanilla HF (PLAN Amendment (19), owner 2026-10-24 item 2: gate at 0.01 as
upstream; also record pass/fail at the paper's 0.1). Uses change 05's own functions from bench.py (reference_outputs,
_teacher_forced_logprobs) on the same prompts and continuation length. Reports the per-position KL distribution
(mean, max, 99th percentile) and top-1 agreement, then:
  GATE_0.01   11ea904's rule: mean KL <= 0.01 and top-1 agreement >= 0.95 (the score's gate);
  PAPER_0.1_MEAN  mean per-token KL <= 0.1;   PAPER_0.1_MAX  every token's KL <= 0.1
(the paper says "a per-token KL correctness check at threshold 0.1" without saying mean or max, so both are recorded).
Run from a fresh copy of task_context holding the agent's kernels/ and bindings.cpp."""
import gc, json, os, sys
import torch
sys.path.insert(0, os.getcwd())
from config import ArenaConfig
from bench import load_model_and_tokenizer, compile_kernels, reference_outputs, _teacher_forced_logprobs, apply_seed, ROOT
from inject import inject_agent_kernels

cfg = ArenaConfig(); apply_seed(cfg.seed)
model, tok = load_model_and_tokenizer(cfg)
refs = reference_outputs(model, tok, cfg)
del model; gc.collect(); torch.cuda.empty_cache()
if os.environ.get("C_PREBUILT_SET"):   # re-measure session: the set built once by c_interleave.py
    from c_interleave import load_ops
    ops, err = load_ops(os.environ["C_PREBUILT_SET"]), None
else:
    ops, err = compile_kernels(os.path.join(ROOT, "kernels"), os.path.join(ROOT, "bindings.cpp"), name="kl_check_ops")
print(f"KL_COMPILE {'PASS' if ops else 'FAIL'} {err or ''}"[:400], flush=True)
if not ops:
    sys.exit(2)
model, tok = load_model_and_tokenizer(cfg)
inj = inject_agent_kernels(model, ops)
print("KL_INJECTED", json.dumps(inj), flush=True)
per, agree = [], []
with torch.no_grad():
    for ref in refs:
        logp, _ = _teacher_forced_logprobs(model, ref["input_ids"].to(cfg.device), continuation=ref["continuation"])
        if not torch.isfinite(logp).all():
            print("KL_NONFINITE logits; every check FAILS", flush=True)
            for k in ("GATE_0.01", "PAPER_0.1_MEAN", "PAPER_0.1_MAX"):
                print(f"{k} FAIL")
            sys.exit(3)
        p = ref["logprobs"]
        per.append((p.exp() * (p - logp)).sum(-1))
        agree.append((p.argmax(-1) == logp.argmax(-1)).float())
kl, ag = torch.cat(per), torch.cat(agree)
mean, mx, p99, top1 = kl.mean().item(), kl.max().item(), torch.quantile(kl, 0.99).item(), ag.mean().item()
print(f"KL_PER_TOKEN positions={kl.numel()} mean={mean:.3e} max={mx:.3e} p99={p99:.3e} top1_agree={top1:.4f}", flush=True)
print("GATE_0.01", "PASS" if mean <= cfg.correctness_max_mean_kl and top1 >= cfg.correctness_min_top1_agree else "FAIL")
print("PAPER_0.1_MEAN", "PASS" if mean <= 0.1 else "FAIL")
print("PAPER_0.1_MAX", "PASS" if mx <= 0.1 else "FAIL")
