#!/usr/bin/env python3
"""Minimal reproduction used by the sanitizer arms (C1a, C2s, C3s): compile the kernels in ./kernels with bench.py's own
compile_kernels (bench.py:117-149, same flags incl. -lineinfo), load TinyLlama as bench.py does, inject with the task's
own inject.py, wrap every agent op with a call/exception counter (inject.py:124 and :168 swallow exceptions and fall back
to PyTorch, so a "pass" must also show the kernels really ran), then generate PROMPT with MAX_NEW tokens
(prefill + MAX_NEW-1 decode steps) and compare the greedy tokens with the no-kernel model.
Run from a fresh copy of task_context. Env: C_PROMPT (default "Hello"; "all" = the 8 eval prompts), C_MAX_NEW (default 3),
C_OPS (all|rope: inject all four ops or only rotary_embedding, R4), C_REF (path of c0_outputs.json, optional)."""
import json, os, sys, time, traceback
import torch
sys.path.insert(0, os.getcwd())
from config import ArenaConfig
from bench import load_model_and_tokenizer, compile_kernels, apply_seed, ROOT
from inject import inject_agent_kernels

PROMPT = os.environ.get("C_PROMPT", "Hello")
MAX_NEW = int(os.environ.get("C_MAX_NEW", "3"))
OPS_MODE = os.environ.get("C_OPS", "all")        # R4: "rope" = inject only rotary_embedding (inject.py:18 probes hasattr), "all" = all four
cfg = ArenaConfig(); apply_seed(cfg.seed)
PROMPTS = list(cfg.eval_prompts) if PROMPT == "all" else [PROMPT]   # R4: C_PROMPT=all -> the benchmark's 8 prompts
print(f"MIN torch={torch.__version__} caching={'off' if os.environ.get('PYTORCH_NO_CUDA_MEMORY_CACHING') else 'on'} prompt={PROMPT!r} n_prompts={len(PROMPTS)} max_new={MAX_NEW} ops={OPS_MODE}", flush=True)
print(f"MIN_OPS_MODE={OPS_MODE}", flush=True)
t0 = time.time()
if os.environ.get("C_PREBUILT_SET"):   # re-measure session (2026-10-24): the set built once by c_interleave.py
    from c_interleave import load_ops
    ops, err = load_ops(os.environ["C_PREBUILT_SET"]), None
else:
    ops, err = compile_kernels(os.path.join(ROOT, "kernels"), os.path.join(ROOT, "bindings.cpp"), name="agent_ops")
print(f"MIN_COMPILE {'PASS' if ops else 'FAIL'} in {time.time()-t0:.0f}s {err or ''}", flush=True)
if not ops:
    sys.exit(2)

STRICT = os.environ.get("C_STRICT", "0") == "1"   # merged from the second tester's Strict proxy (gpu_probe.py)
class KernelFailure(BaseException):
    """BaseException so that inject.py's `except Exception` (:124, :168) cannot swallow it and fall back."""
class Counted:
    """Wraps the compiled module so every op call and every exception is counted (and the first exception printed).
    In strict mode (C_STRICT=1) every op is followed by torch.cuda.synchronize(), so a faulting launch is reported
    inside the op that launched it, and the failure escapes inject.py's fallback as a BaseException."""
    def __init__(self, mod): self._m = mod; self.calls = {}; self.errors = {}; self.first_error = {}
    def __getattr__(self, name):
        if OPS_MODE == "rope" and name in ("rmsnorm", "fused_mlp", "attention"):
            raise AttributeError(name)      # R4: hasattr() -> False, inject.py leaves that op on PyTorch
        fn = getattr(self._m, name)
        def w(*a, **k):
            self.calls[name] = self.calls.get(name, 0) + 1
            try:
                r = fn(*a, **k)
                if STRICT: torch.cuda.synchronize()
                return r
            except Exception as e:
                self.errors[name] = self.errors.get(name, 0) + 1
                self.first_error.setdefault(name, repr(e)[:300])
                if STRICT:
                    print(f"KERNEL_FAIL {name} {repr(e)[:300]}", flush=True)
                    raise KernelFailure(name) from e
                raise
        return w
    def __dir__(self): return dir(self._m)
counted = Counted(ops)
print(f"MIN_STRICT={'1' if STRICT else '0'}", flush=True)

model, tok = load_model_and_tokenizer(cfg)
inj = inject_agent_kernels(model, counted, verbose=True)
print("MIN_INJECTED", json.dumps(inj), flush=True)
rc = 0; n_match = 0; n_cmp = 0; T_total = 0
ref_path = os.environ.get("C_REF")
refs = json.load(open(ref_path))["outputs"] if ref_path and os.path.exists(ref_path) else {}
try:
    for pi, prompt in enumerate(PROMPTS):
        x = tok(prompt, return_tensors="pt").to(cfg.device)
        T = x["input_ids"].shape[1]; T_total += T
        print(f"MIN_PROMPT {pi+1}/{len(PROMPTS)} T={T} (k RoPE pairs at prefill = {T*4*32}, tail threads = {(-T*4*32) % 256}; at decode 128 pairs, tail 128)", flush=True)
        with torch.no_grad():
            y = model.generate(**x, max_new_tokens=MAX_NEW, min_new_tokens=MAX_NEW, do_sample=False, max_length=None)
        torch.cuda.synchronize()
        new_ids = y[0, T:].tolist()
        print(f"MIN_GENERATED {pi+1} ids={new_ids} text={tok.decode(y[0, T:])!r}", flush=True)
        ref = refs.get(prompt)
        if ref:
            n_cmp += 1; same = ref["new_token_ids"][:MAX_NEW] == new_ids; n_match += int(same)
            print(f"MIN_PROMPT_MATCH {pi+1} {'yes' if same else 'no'} ref={ref['new_token_ids'][:MAX_NEW]}", flush=True)
    if n_cmp:
        print(f"MIN_TEXT_MATCH_C0={'yes' if n_match == n_cmp else 'no'} matched={n_match}/{n_cmp} tokens_each={MAX_NEW}", flush=True)
except BaseException as e:   # KernelFailure (strict mode) or a CUDA AcceleratorError
    rc = 1
    print("MIN_EXCEPTION", repr(e)[:400], flush=True)
    traceback.print_exc()
print("MIN_OP_CALLS", json.dumps(counted.calls), flush=True)
print("MIN_OP_ERRORS", json.dumps(counted.errors), json.dumps(counted.first_error), flush=True)
exp_rope = 2 * model.config.num_hidden_layers * MAX_NEW * len(PROMPTS)   # q and k, every layer, every forward pass, every prompt
print(f"MIN_ROPE_CALLS expected={exp_rope} got={counted.calls.get('rotary_embedding', 0)} errors={counted.errors.get('rotary_embedding', 0)}", flush=True)
print("MIN_DONE rc=%d" % rc, flush=True)
sys.exit(rc)
