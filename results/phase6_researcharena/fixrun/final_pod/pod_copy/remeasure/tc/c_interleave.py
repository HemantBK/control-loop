#!/usr/bin/env python3
"""Interleaved re-measure (PLAN Amendment (19); owner, 2026-10-24, after fullrun3's x1.420 was voided for measurement
interference). One kernel set per process, as the evaluator measures one per model load:

    python3 c_interleave.py build SET            compile SET once into $P6_RM_BUILD/SET (later loads reuse it)
    python3 c_interleave.py pass SET [--warmup]  load TinyLlama, inject SET, run bench.py's benchmark_generation
                                                 (--warmup: 3 prompts, untimed, nothing recorded)

SET: initial (task_context/baseline_kernels, change 04's snapshot of the initial kernels), agent (the agent's submitted
kernels/ and bindings.cpp, $P6_RM/submission/task_snapshot), starter (task_context/starter_kernels), vanilla (nothing
injected). Run from a fresh copy of the composed task_context. A timed pass prints one PASS_RESULT JSON line: set,
avg tok/s, per-prompt tok/s, start and end (epoch s), its pid (to tell its own GPU process from others), injected ops."""
import argparse, glob, json, os, re, sys, time, io, contextlib
import torch
sys.path.insert(0, os.getcwd())
from config import ArenaConfig
from bench import load_model_and_tokenizer, benchmark_generation, apply_seed
from inject import inject_agent_kernels

RM = os.environ.get("P6_RM", "/workspace/remeasure")
BUILD = os.environ.get("P6_RM_BUILD", "/workspace/rm_build")
TC = os.getcwd()
SETS = {"initial": (f"{TC}/baseline_kernels", f"{TC}/baseline_kernels/bindings.cpp"),
        "agent": (f"{RM}/submission/task_snapshot/kernels", f"{RM}/submission/task_snapshot/bindings.cpp"),
        "starter": (f"{TC}/starter_kernels", f"{TC}/starter_kernels/bindings.cpp")}


def load_ops(s):
    """bench.py's compile flags; a fixed build dir per set, so the first call compiles and later calls only load."""
    from torch.utils.cpp_extension import load
    kd, b = SETS[s]
    bd = f"{BUILD}/{s}"; os.makedirs(bd, exist_ok=True)
    return load(name=f"p6rm_{s}", sources=[b] + sorted(glob.glob(f"{kd}/*.cu")), build_directory=bd,
                extra_cuda_cflags=["-O3", "--use_fast_math", "-lineinfo"], extra_cflags=["-O3"], verbose=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "pass"]); ap.add_argument("set", choices=["initial", "agent", "starter", "vanilla"])
    ap.add_argument("--warmup", action="store_true")
    a = ap.parse_args()
    if a.cmd == "build":
        t0 = time.time(); load_ops(a.set); print(f"BUILD_OK {a.set} {time.time() - t0:.0f}s", flush=True); return
    cfg = ArenaConfig(); apply_seed(cfg.seed)
    model, tok = load_model_and_tokenizer(cfg)
    inj = {}
    if a.set != "vanilla":
        inj = inject_agent_kernels(model, load_ops(a.set))
    if a.warmup:
        benchmark_generation(model, tok, cfg, 3)
        print(f"WARMUP_DONE {a.set} injected={json.dumps(inj)}", flush=True); return
    import inject as _inj   # change 07: per-kernel custom calls and fallbacks over this timed pass
    if hasattr(_inj, "reset_kernel_counts"):
        _inj.reset_kernel_counts()
    buf = io.StringIO()
    t0 = time.time()
    with contextlib.redirect_stdout(buf):
        r = benchmark_generation(model, tok, cfg)
    t1 = time.time()
    sys.stdout.write(buf.getvalue())
    per = [float(x) for x in re.findall(r"\(([\d.]+) tok/s\)", buf.getvalue())]
    print("PASS_RESULT " + json.dumps({"set": a.set, "avg_tps": r["avg_tokens_per_sec"], "per_prompt_tps": per,
                                       "start": t0, "end": t1, "pid": os.getpid(), "injected": inj,
                                       "kernel_counts": getattr(_inj, "KERNEL_COUNTS", None),
                                       "first_fallback": getattr(_inj, "FIRST_FALLBACK", None)}), flush=True)


if __name__ == "__main__":
    main()
