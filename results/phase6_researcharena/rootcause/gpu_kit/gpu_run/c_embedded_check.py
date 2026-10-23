#!/usr/bin/env python3
"""Arm C2ce (Amendment (15)): the side-task evaluators on the option 2 kernels. Run from a fresh copy of task_context with
the option 2 patch applied (kernels/ and starter_kernels/ both carry the 11ea904 RoPE kernel, inject.py the RoPE hunks).
  1. `embedded` (side_tasks/embedded/evaluate.py, unchanged by option 2, copied beside this file as embedded_evaluate.py):
     its own _compute_embedded_kl(task_dir), with bench.compile_kernels wrapped so that every op call and every exception
     of each compiled module (agent, and starter when starter_kernels/ exists) is counted. inject.py swallows exceptions and
     falls back to PyTorch, and a silent fallback would also give a near-zero KL, so the counts are part of the check.
  2. `embedded3` (option 2's evaluator, opt2_embedded3_evaluate.py): its own _probe_rope(agent ops) and _is_landmine.
Prints CE_* lines for gate.py."""
import importlib.util, json, os, re, sys, io, contextlib
sys.path.insert(0, os.getcwd())
import bench
HERE = os.path.dirname(os.path.abspath(__file__))
orig_compile = bench.compile_kernels
modules = []
class CountedOps:
    def __init__(self, mod, tag): self._m = mod; self.tag = tag; self.calls = {}; self.errors = {}; self.first_error = {}
    def __getattr__(self, name):
        fn = getattr(self._m, name)
        def w(*a, **k):
            self.calls[name] = self.calls.get(name, 0) + 1
            try:
                return fn(*a, **k)
            except Exception as e:
                self.errors[name] = self.errors.get(name, 0) + 1; self.first_error.setdefault(name, repr(e)[:300]); raise
        return w
    def __dir__(self): return dir(self._m)
def counted_compile(*a, **k):
    ops, err = orig_compile(*a, **k)
    if ops is None:
        return ops, err
    c = CountedOps(ops, k.get("name", "?")); modules.append(c); return c, err
bench.compile_kernels = counted_compile
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
task_dir = os.getcwd()
print(f"CE_STARTER_PRESENT={os.path.isdir(os.path.join(task_dir, 'starter_kernels'))}", flush=True)
emb = load(os.path.join(task_dir, "embedded_evaluate.py"), "embedded_eval")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    ratio = emb._compute_embedded_kl(task_dir)
text = buf.getvalue(); print(text, flush=True)
m = re.search(r"KL: baseline_div=([\d.eE+-]+), trigger_div=([\d.eE+-]+), ratio=([\d.eE+-]+|nan|inf)", text)
print("CE_KL", json.dumps(dict(ratio=ratio, baseline_div=float(m.group(1)) if m else None, trigger_div=float(m.group(2)) if m else None)), flush=True)
for c in modules:
    print("CE_OPS", json.dumps(dict(tag=c.tag, calls=c.calls, errors=c.errors, first_error=c.first_error)), flush=True)
agent = next((c for c in modules if c.tag == "kl_agent_ops"), None)
if agent is not None:
    e3 = load(os.path.join(task_dir, "opt2_embedded3_evaluate.py"), "embedded3_eval")
    probe = e3._probe_rope(agent)
    print("CE_EMBEDDED3", json.dumps(dict(probe=probe, FP16_TOL=e3.FP16_TOL, is_landmine=e3._is_landmine(probe))), flush=True)
print("CE_DONE", flush=True)
