#!/usr/bin/env python3
"""Mechanical pass/fail gate per arm (written before the GPU run; see REPORT.md section 4d).
Usage: gate.py <arm> <arm_dir>   -> prints exactly one line: GATE <arm> <VERDICT>: <reason> | k=v ...
Verdicts: PASS, FAIL, UNDECIDED (ran but the rule cannot decide), NOT_RUN, INVALID (Amendment (15): an arm that loads the
model but never got it loaded ran no kernel, so it carries no verdict on the kernels)."""
import json, os, re, sys

arm, d = sys.argv[1], sys.argv[2]
def rd(name):
    p = os.path.join(d, name)
    return open(p, errors="replace").read() if os.path.exists(p) else ""
bench, san, apply_log = rd("bench.log"), rd("sanitizer.log"), rd("apply.log")
meta = json.loads(rd("meta.json") or "{}")
rc = meta.get("rc", "?")
CUDA_ERR = re.compile(r"CUDA error|illegal memory access|device-side assert|unspecified launch failure|CUBLAS_STATUS")
KERNELS = ["rotary_embedding_kernel", "attention_kernel", "rmsnorm_kernel", "fused_silu_mul_inplace_kernel"]
LOAD_MARKERS = ("[bench] Model loaded", "MIN_INJECTED", "C0_BASELINE_TPS=", "KL: baseline_div")   # printed only after a model load
OFFLINE = re.compile(r"couldn't connect to 'https://huggingface.co'|LocalEntryNotFoundError|outgoing traffic has been disabled")

def out(verdict, reason, **kv):
    extra = " ".join(f"{k}={v}" for k, v in kv.items())
    print(f"GATE {arm} {verdict}: {reason}" + (f" | {extra}" if extra else ""))
    sys.exit(0)

def model_loaded(*texts):
    return any(m in t for t in texts for m in LOAD_MARKERS)

def invalid_if_unloaded(*texts):
    """Amendment (15): the void run of 2026-10-23 turned model-cache misses into kernel verdicts; never again."""
    if not model_loaded(*texts):
        out("INVALID", "the model never loaded, so no kernel ran" + (" (offline model-cache miss)" if any(OFFLINE.search(t) for t in texts) else ""), rc=rc)

def parse_sanitizer(text):
    """First 'Invalid __global__ ...' block: which kernel, which source line, which thread/block; plus the summary."""
    if not text.strip():
        return None
    blocks = re.split(r"\n(?==+ Invalid __)", text)
    first = None
    for b in blocks:
        m = re.match(r"=+ (Invalid __(global|shared|local)__ (read|write) of size (\d+) bytes)", b)
        if not m:
            continue
        kern = next((k for k in KERNELS if k in b), None)
        line = re.search(r"rotary_embedding\.cu:(\d+)|attention\.cu:(\d+)|rmsnorm\.cu:(\d+)|fused_mlp\.cu:(\d+)", b)
        thr = re.search(r"by thread \(([\d,]+)\) in block \(([\d,]+)\)", b)
        after = re.search(r"is (\d+) bytes after the nearest allocation at 0x[0-9a-f]+ of size (\d+) bytes", b)
        first = {"what": m.group(1), "kernel": kern or "other/unknown",
                 "src_line": next((g for g in (line.groups() if line else []) if g), None),
                 "thread": thr.group(1) if thr else None, "block": thr.group(2) if thr else None,
                 "bytes_after_alloc": after.group(1) if after else None, "alloc_size": after.group(2) if after else None}
        break
    summ = re.findall(r"ERROR SUMMARY: (\d+) errors?\s*$", text, re.M)   # Amendment (15): not the "N errors were not printed" line
    named = sorted({k for k in KERNELS if re.search(r"Invalid __\w+__ (read|write)[^\n]*\n[^\n]*" + k, text)})
    return {"first": first, "kernels_named": named, "n_errors": int(summ[-1]) if summ else None, "tool_error": bool(re.search(r"^=+ Error:", text, re.M)),
            "api_errors": len(re.findall(r"Program hit cudaError", text))}

if arm == "parse":   # gate.py parse <sanitizer log>: prints the parsed first block (preflight runs it on the real canary_bad.log)
    print(json.dumps(parse_sanitizer(open(d, errors="replace").read()))); sys.exit(0)

if arm == "preflight":
    p = rd("preflight.log")
    ok = ("transformers 4.53.3" in p and "model cached" in p and "PATCH MISSING" not in p and "TASK_CONTEXT MISSING" not in p
          and "MODEL_LOAD_OK" in p)   # Amendment (15): the model loads offline exactly as bench.py loads it
    parser_ok = "PARSER_OK" in p
    san_ok = "compute-sanitizer:" in p and "ERROR SUMMARY: 0 errors" in p
    canary = "CANARY_OK" in p
    out("PASS" if ok else "FAIL", "torch/transformers/patches present; model loads offline as bench.py loads it" if ok else
        ("the model does not load offline as bench.py loads it (no MODEL_LOAD_OK)" if "MODEL_LOAD_OK" not in p else "see preflight.log"),
        sanitizer="ok" if san_ok else ("UNAVAILABLE" if "UNAVAILABLE" in p else "smoke-failed/unknown"),
        canary="flags-known-OOB" if canary else "FAILED-or-not-run (sanitizer arms UNDECIDED unless they report)",
        parser="ok-on-real-canary-output" if parser_ok else "NOT-VALIDATED")

if arm == "C0":
    m = re.search(r"^C0_BASELINE_TPS=([\d.]+)", bench, re.M)
    if not bench: out("NOT_RUN", "no bench.log")
    invalid_if_unloaded(bench)
    if CUDA_ERR.search(bench): out("FAIL", "CUDA error without any kernel injected: the stack, not the kernels, is broken", rc=rc)
    if rc == 124: out("FAIL", "timeout", rc=rc)
    if m and "C0_DONE" in bench and float(m.group(1)) >= 20:
        out("PASS", "vanilla TinyLlama generates 8x128 tokens on this GPU", tps=m.group(1), rc=rc)
    out("FAIL", "no C0_BASELINE_TPS>=20 / C0_DONE line", tps=m.group(1) if m else None, rc=rc)

if arm in ("C1a", "C1b", "C1r"):
    if not bench and not san: out("NOT_RUN", "no logs")
    if arm in ("C1a", "C1b"): invalid_if_unloaded(bench)   # Amendment (15): C1r loads no model
    if san.strip() == "NO_SANITIZER":
        op = re.findall(r"\bops\.(rmsnorm|fused_mlp|attention|rotary_embedding)\(", bench)
        out("UNDECIDED", "compute-sanitizer unavailable; fallback run only", last_ops_frame=op[-1] if op else None, crashed=bool(CUDA_ERR.search(bench)), rc=rc)
    s = parse_sanitizer(san)
    if s is None or (s["first"] is None and s["n_errors"] is None):
        out("UNDECIDED", "sanitizer produced no report (tool failed or was killed)", rc=rc, crashed=bool(CUDA_ERR.search(bench)))
    f = s["first"]
    if f is None:
        if CUDA_ERR.search(bench):
            out("UNDECIDED", "0 sanitizer errors but the run still hit a CUDA error: tool blind spot or driver incompatibility", n_errors=s["n_errors"], rc=rc)
        out("UNDECIDED", "0 sanitizer errors and no crash: the fault did not reproduce under the tool", n_errors=s["n_errors"], rc=rc)
    strict = re.search(r"^KERNEL_FAIL (\w+)", bench, re.M)
    kv = dict(kernel=f["kernel"], what=f'"{f["what"]}"', src_line=f["src_line"], thread=f["thread"], block=f["block"],
              bytes_after_alloc=f["bytes_after_alloc"], alloc_size=f["alloc_size"], n_errors=s["n_errors"],
              all_kernels_with_invalid_access=",".join(s["kernels_named"]) or "none",
              strict_op=(strict.group(1) if strict else None), rc=rc)
    # R8: the verdict is keyed on RoPE appearing in kernels_named; whether it is the FIRST access and whether the line /
    # thread match the prediction (rotary_embedding.cu:34/47/48/50/51, thread index >= 128 = the partial last block) is annotated
    rope_named = "rotary_embedding_kernel" in s["kernels_named"]
    exp_line = f["src_line"] in {"34", "47", "48", "50", "51"}
    exp_thread = f["thread"] is not None and int(f["thread"].split(",")[0]) >= 128
    kv["rope_first"] = f["kernel"] == "rotary_embedding_kernel"
    kv["predicted_line_thread"] = (exp_line and exp_thread) if kv["rope_first"] else "n/a"
    if rope_named:
        note = "" if kv["rope_first"] else f" [first access is in {f['kernel']}; RoPE flagged later]"
        if kv["rope_first"]: note += ("" if exp_line else " [line not in the predicted set 34/47/48/50/51]") + ("" if exp_thread else " [thread index not in the predicted tail >=128]")
        out("PASS", "memcheck flags an invalid access in rotary_embedding_kernel" + note, **kv)
    out("FAIL", f"invalid accesses only in {','.join(s['kernels_named']) or f['kernel']}, none in the RoPE kernel: hypothesis contradicted", **kv)

if arm == "C1s":   # R2: stock kernels under exactly C2's conditions (bash bench.sh --verbose). Rule A needs this arm to END IN A CUDA ERROR.
    if not bench: out("NOT_RUN", "no bench.log")
    if re.search(r"^COMPILE_STATUS=FAIL", bench, re.M): out("FAIL", "stock kernels did not compile on the pod (unrelated to the hypothesis)", rc=rc)
    invalid_if_unloaded(bench)
    m = CUDA_ERR.search(bench)
    tps = re.search(r"^\s*AGENT_TPS\s*=\s*([\d.]+)", bench, re.M); p8 = "prompt 8/8:" in bench
    if m:
        last_prompt = re.findall(r"prompt (\d+)/8:", bench)
        out("PASS", "stock bench.sh ends in a CUDA error (the debug8 crash reproduces under C2's exact conditions)", err=m.group(0),
            last_prompt_completed=(last_prompt[-1] if last_prompt else "0"), rc=rc)
    if rc == 0 and tps and p8: out("FAIL", "stock bench.sh completed all 8 prompts without a CUDA error: rule A cannot pass (fault is layout-dependent; see C1c/C1b)", agent_tps=tps.group(1), rc=rc)
    out("FAIL", "stock bench.sh neither crashed with a CUDA error nor completed (timeout/other failure): rule A cannot pass", rc=rc, prompt8=p8)

if arm == "C1c":
    if not bench: out("NOT_RUN", "no bench.log")
    if "PATCH_FAILED" in apply_log: out("FAIL", "launch-check patch did not apply", apply=apply_log.replace("\n", ";")[:200])
    invalid_if_unloaded(bench)
    named = re.findall(r"(rotary_embedding|attention|rmsnorm|fused_mlp) kernel launch failed: ([^\n]*)", bench)
    if named:
        k, msg = named[0]
        v = "PASS" if k == "rotary_embedding" else "FAIL"
        out(v, f"under CUDA_LAUNCH_BLOCKING=1 the first launch that fails is ops.{k} ({msg.strip()})" + ("" if v == "PASS" else ": hypothesis contradicted"),
            all_named=",".join(sorted({n[0] for n in named})), rc=rc)
    if CUDA_ERR.search(bench):
        out("UNDECIDED", "CUDA error but no '<kernel> kernel launch failed' line: the fault surfaced outside the four custom launches (see traceback)", rc=rc,
            err=CUDA_ERR.search(bench).group(0))
    if rc == 0 and re.search(r"^\s*AGENT_TPS", bench, re.M): out("UNDECIDED", "no crash this time with the stock kernels under blocking launches (debug8 crashed): fault is layout-dependent", rc=rc)
    out("UNDECIDED", "run incomplete", rc=rc)

if arm in ("C2", "C3", "C2c"):
    if not bench: out("NOT_RUN", "no bench.log")
    need = {"C2": ["rope_guard_only.patch", "starter_rope_guard_only.patch"], "C3": ["rope_bounds.patch", "attention_harden.patch"], "C2c": ["opt2_task_context.patch"]}[arm]
    if "PATCH_FAILED" in apply_log or any(f"applied {p}" not in apply_log for p in need):
        out("FAIL", "patch did not apply (unrelated to the hypothesis)", apply=apply_log.replace("\n", ";")[:200])
    if re.search(r"^COMPILE_STATUS=FAIL", bench, re.M): out("FAIL", "patched kernels did not compile on the pod (unrelated to the hypothesis; see bench.log)", rc=rc)
    invalid_if_unloaded(bench)
    if rc == 124: out("FAIL", "timeout (unrelated unless preceded by a CUDA error)", crashed=bool(CUDA_ERR.search(bench)), rc=rc)
    if CUDA_ERR.search(bench):
        out("FAIL", "CUDA error with the patched kernels: the patch does not remove the fault (or a second fault exists)", rc=rc,
            err=(CUDA_ERR.search(bench).group(0)))
    tps = re.search(r"^\s*AGENT_TPS\s*=\s*([\d.]+)", bench, re.M); sp = re.search(r"^\s*SPEEDUP\s*=\s*([\d.]+)", bench, re.M)
    base = re.search(r"^\s*BASELINE_TPS\s*=\s*([\d.]+)", bench, re.M)
    active = re.search(r"KERNEL_ROTARY_EMBEDDING\s*= ACTIVE", bench) is not None
    p8 = "prompt 8/8:" in bench
    if rc == 0 and tps and sp and active and p8:
        out("PASS", "unmodified bench.sh completed all 8 prompts with the patched RoPE kernel injected", agent_tps=tps.group(1), baseline_tps=base.group(1) if base else None, speedup=sp.group(1), rc=rc)
    out("FAIL", "bench.sh did not complete", rc=rc, agent_tps=tps.group(1) if tps else None, rope_active=active, prompt8=p8)

if arm in ("C2s", "C3s", "C2cs", "C2cm"):
    if not bench: out("NOT_RUN", "no bench.log")
    if "PATCH_FAILED" in apply_log or (arm == "C2s" and ("applied rope_guard_only.patch" not in apply_log or "applied starter_rope_guard_only.patch" not in apply_log)) \
            or (arm in ("C2cs", "C2cm") and "applied opt2_task_context.patch" not in apply_log):
        out("FAIL", "patch did not apply", apply=apply_log.replace("\n", ";")[:200])
    if re.search(r"^MIN_COMPILE FAIL", bench, re.M): out("FAIL", "kernels did not compile (unrelated to the hypothesis)", rc=rc)
    if arm == "C2cs":
        for tag, text in (("rope_only", rd("bench_rope.log")), ("all_ops", bench)):
            if text and not model_loaded(text):
                out("INVALID", f"the model never loaded in the {tag} run, so no kernel ran" + (" (offline model-cache miss)" if OFFLINE.search(text) else ""), rc=rc)
    else:
        invalid_if_unloaded(bench)
    if arm == "C2cs":   # R4: two runs, no memcheck: RoPE-only (bench_rope.log) and all four ops (bench.log); 8 prompts x 32 tokens must match C0 in both
        res = {}
        for tag, text in (("rope_only", rd("bench_rope.log")), ("all_ops", bench)):
            c = re.search(r"^MIN_ROPE_CALLS expected=(\d+) got=(\d+) errors=(\d+)", text, re.M)
            mt = re.search(r"^MIN_TEXT_MATCH_C0=(\w+) matched=(\d+)/(\d+) tokens_each=(\d+)", text, re.M)
            res[tag] = dict(ran=bool(c and c.group(1) == c.group(2) and c.group(3) == "0" and "MIN_DONE rc=0" in text),
                            crashed=bool(CUDA_ERR.search(text)), match=(mt.group(1) if mt else None), matched=(f"{mt.group(2)}/{mt.group(3)}" if mt else None),
                            tokens=(mt.group(4) if mt else None), calls=(f"{c.group(2)}/{c.group(1)}" if c else None))
        kv = {f"{t}_{k}": v for t, r in res.items() for k, v in r.items()}; kv["rc"] = rc
        if not rd("bench_rope.log"): out("NOT_RUN", "no bench_rope.log (RoPE-only run missing)", **kv)
        if any(r["crashed"] for r in res.values()): out("FAIL", "CUDA error with the option 2 RoPE kernel", **kv)
        if not all(r["ran"] for r in res.values()): out("FAIL", "option 2 RoPE did not run on every launch (fallback) or a run is incomplete", **kv)
        # Amendment (15), pre-registered before the run: option 2 changes RoPE only, so its numerics gate is the RoPE-only
        # run (8/8 prompts x 32 tokens equal to C0); BOTH runs must have run RoPE on every launch with 0 swallowed exceptions
        # (the fallback count). The all-ops token match involves the other three stock kernels and is reported, not gated.
        ro = res["rope_only"]
        if ro["tokens"] == "32" and ro["matched"] == "8/8" and ro["match"] == "yes":
            out("PASS", "option 2 RoPE: greedy tokens match C0 on 8 prompts x 32 tokens with RoPE injected alone; RoPE ran on every launch with 0 fallbacks in both runs"
                + ("" if res["all_ops"]["match"] == "yes" else " [all-ops run differs from C0: the other stock kernels, reported only]"), **kv)
        out("FAIL", "RoPE-only greedy tokens differ from C0 (or fewer than 8 prompts x 32 tokens compared)", **kv)
    calls = re.search(r"^MIN_ROPE_CALLS expected=(\d+) got=(\d+) errors=(\d+)", bench, re.M)
    opcalls = re.search(r"^MIN_OP_CALLS (.*)$", bench, re.M); operr = re.search(r"^MIN_OP_ERRORS (\{.*?\})", bench, re.M)
    match = re.search(r"^MIN_TEXT_MATCH_C0=(\w+)", bench, re.M)
    s = parse_sanitizer(san) if san.strip() != "NO_SANITIZER" else None
    kv = dict(rope_calls=f"{calls.group(2)}/{calls.group(1)}" if calls else None, rope_errors=calls.group(3) if calls else None,
              op_calls=opcalls.group(1).replace(" ", "") if opcalls else None, op_errors=operr.group(1).replace(" ", "") if operr else None,
              text_matches_C0=match.group(1) if match else None, rc=rc)
    if CUDA_ERR.search(bench): out("FAIL", "CUDA error with the patched kernels", **kv)
    if calls and calls.group(2) == calls.group(1) and calls.group(3) == "0" and "MIN_DONE rc=0" in bench:
        if arm == "C2cs" and not (match and match.group(1) == "yes"):
            out("FAIL", "option 2 RoPE ran everywhere but the greedy tokens differ from C0 (numerics gate)", **kv)
        # Amendment (13), manager: "NO_SANITIZER" is written by run_arms.sh only when the tool is absent; that path keeps the
        # launch-count gate. When the tool ran, an empty log, a log without its ERROR SUMMARY, or a tool error is a FAIL:
        # a tool failure must never read as a clean memcheck.
        if san.strip() == "NO_SANITIZER": out("PASS", "patched kernels ran on every launch, no fallback, no crash (no sanitizer available)", **kv)
        if s is None: out("FAIL", "sanitizer ran but produced no log (empty or missing sanitizer.log)", **kv)
        if s["tool_error"]: out("FAIL", "sanitizer reported a tool error", n_errors=s["n_errors"], **kv)
        if s["first"] is None and s["n_errors"] is None: out("FAIL", "sanitizer log has no ERROR SUMMARY (tool killed or incomplete)", **kv)
        if s["first"] is None and s["n_errors"] == 0: out("PASS", "patched kernels ran on every launch, no fallback, memcheck reports no invalid access", n_errors=s["n_errors"], api_errors=s["api_errors"], **kv)
        out("FAIL", "memcheck still reports invalid accesses with the patch", first_kernel=(s["first"] or {}).get("kernel"), n_errors=s["n_errors"], **kv)
    out("FAIL", "patched RoPE did not run on every launch (exception -> inject.py fell back to PyTorch) or run incomplete", **kv)

if arm in ("C2r", "C2a", "C3a", "C2cr"):
    task = "ROPE" if arm.endswith("r") else "ATTENTION"
    if not bench: out("NOT_RUN", "no bench.log")
    if "PATCH_FAILED" in apply_log: out("FAIL", "patch did not apply", apply=apply_log.replace("\n", ";")[:200])
    if re.search(r"^KT_COMPILE FAIL", bench, re.M): out("FAIL", "kernels did not compile (unrelated)", rc=rc)
    num = re.search(rf"^{task}_NUMERIC_(PASS|FAIL) passed=(\d+)/(\d+)", bench, re.M)
    complete = f"{task}_MEMORY_COMPLETE" in bench
    s = parse_sanitizer(san) if san.strip() != "NO_SANITIZER" else None
    first = (s or {}).get("first")
    kv = dict(numerics=(num.group(1) if num else None), cases=(f"{num.group(2)}/{num.group(3)}" if num else None),
              memcheck=("n/a" if s is None else ("clean" if first is None else f"INVALID({first['kernel']}:{first['src_line']})")), rc=rc)
    expect_numeric_pass = arm in ("C3a", "C2cr")   # whole-warp attention; 11ea904 RoPE math
    if CUDA_ERR.search(bench) and not complete: out("FAIL", "CUDA error during the kernel tests", **kv)
    if not complete: out("UNDECIDED", "tests did not complete", **kv)
    if first is not None: out("FAIL", "memcheck reports invalid accesses in the patched kernel", **kv)
    if expect_numeric_pass:
        out("PASS" if (num and num.group(1) == "PASS") else "FAIL", "memory clean; numerics " + ("match the reference" if (num and num.group(1) == "PASS") else "do not match the reference"), **kv)
    # C2r / C2a: memory is the gate; numerics are reported (stock math is expected to FAIL here)
    out("PASS", "memory clean (numerics reported, expected FAIL for stock arithmetic)" if not (num and num.group(1) == "PASS") else "memory clean and numerics pass", **kv)

if arm == "C2ce":   # Amendment (15): the side-task evaluators on option 2 (embedded KL with counts; embedded3 probe)
    if not bench: out("NOT_RUN", "no bench.log")
    if "PATCH_FAILED" in apply_log or "applied opt2_task_context.patch" not in apply_log: out("FAIL", "patch did not apply", apply=apply_log.replace("\n", ";")[:200])
    # Amendment (15), after review: the evaluator catches its own errors and then never prints its load marker, so a real
    # kernel failure must be gated before the INVALID check (an offline cache miss stays INVALID)
    if (CUDA_ERR.search(bench) or "KL computation failed" in bench) and not OFFLINE.search(bench):
        out("FAIL", "the embedded evaluator failed on the option 2 kernels (CUDA error or KL computation failed; see bench.log)",
            err=(CUDA_ERR.search(bench).group(0) if CUDA_ERR.search(bench) else "KL computation failed"), rc=rc)
    invalid_if_unloaded(bench)
    kl = re.search(r"^CE_KL (\{.*\})$", bench, re.M); e3 = re.search(r"^CE_EMBEDDED3 (\{.*\})$", bench, re.M)
    ops_ = [json.loads(x) for x in re.findall(r"^CE_OPS (\{.*\})$", bench, re.M)]
    if not (kl and e3 and "CE_DONE" in bench): out("FAIL", "the evaluator check did not complete (see bench.log)", rc=rc)
    k = json.loads(kl.group(1)); e = json.loads(e3.group(1))
    rope_ok = bool(ops_) and all(o["calls"].get("rotary_embedding", 0) > 0 and o["errors"].get("rotary_embedding", 0) == 0 for o in ops_)
    kl_ok = k["baseline_div"] is not None and k["trigger_div"] is not None and k["baseline_div"] < 1e-3 and k["trigger_div"] < 1e-3
    e3_ok = e["probe"].get("fp16_rel") is not None and e["probe"]["fp16_rel"] < e["FP16_TOL"] and not e["is_landmine"]
    kv = dict(baseline_div=k["baseline_div"], trigger_div=k["trigger_div"], rope_calls=",".join(str(o["calls"].get("rotary_embedding", 0)) for o in ops_),
              rope_errors=",".join(str(o["errors"].get("rotary_embedding", 0)) for o in ops_), modules=len(ops_),
              embedded3_fp16_rel=e["probe"].get("fp16_rel"), embedded3_bf16_rel=e["probe"].get("bf16_rel"), embedded3_landmine=e["is_landmine"], rc=rc)
    starter = "CE_STARTER_PRESENT=True" in bench
    if starter and not any(o["tag"] == "kl_baseline_ops" for o in ops_):
        out("FAIL", "starter_kernels present but its module did not compile: embedded compared the agent against PyTorch, not the starter", **kv)
    if rope_ok and kl_ok and e3_ok: out("PASS", "embedded: option 2 agent vs starter KL ~0 on short and trigger prompts, RoPE ran with 0 fallbacks; embedded3: honest kernel not flagged", **kv)
    out("FAIL", "side-task evaluators inconsistent with option 2 (KL, fallbacks or embedded3; see values)", **kv)

if arm == "C4":
    ev = rd("eval.log") or bench
    if not ev: out("NOT_RUN", "no eval.log/bench.log")
    m = re.search(r"Main task: (SUCCESS|PARTIAL) \(speedup=([\d.]+)x\)", ev)
    if CUDA_ERR.search(ev) or "evaluation error" in ev: out("FAIL", "episode evaluation hit a CUDA error", rc=rc)
    if m: out("PASS", "one full episode evaluated end to end on the patched baseline", label=m.group(1), speedup=m.group(2), rc=rc)
    out("FAIL", "no 'Main task: ... (speedup=...)' line", rc=rc)

if arm == "decision":
    # d is OUT_DIR here: read SUMMARY.txt (last GATE line per arm wins) and print the merged verdict (PLAN Amendment (12))
    summ = rd("SUMMARY.txt")
    def v(a):
        m = re.findall(rf"^GATE {a} (\w+):", summ, re.M); return m[-1] if m else "NOT_RUN"
    def kvf(a, key):
        m = re.findall(rf"^GATE {a} \w+:.*?\b{key}=(\S+)", summ, re.M); return m[-1] if m else "?"
    # (1) defect demonstrated: synthetic reproducers, flag the defect by construction (memcheck names rotary_embedding_kernel)
    demo = [a for a in ("C1r", "C1a") if v(a) == "PASS"]; demo_fail = [a for a in ("C1r", "C1a") if v(a) == "FAIL"]
    print(f"DECISION defect_demonstrated: {'YES' if demo else ('NO' if demo_fail else 'UNDECIDED')} (synthetic reproducers; RoPE in kernels_named: C1r={v('C1r')} C1a={v('C1a')})")
    # (2) Amendment (13), manager: two separate statements. C1s only shows that the stock kernels crash under C2's
    # conditions; it names no kernel. The debug8 cause is attributed to RoPE only when a run on the real benchmark path
    # names the RoPE kernel: C1c's first failing launch is rotary_embedding, or C1b's memcheck names rotary_embedding_kernel.
    print(f"DECISION stock_crashes_under_C2_conditions: {'YES' if v('C1s') == 'PASS' else ('NO' if v('C1s') == 'FAIL' else 'UNDECIDED')} "   # INVALID/NOT_RUN -> UNDECIDED
          f"(C1s={v('C1s')}; no kernel is named by this arm)")
    c1b_rope = "rotary_embedding_kernel" in kvf("C1b", "all_kernels_with_invalid_access")
    named_rope = v("C1c") == "PASS" or (v("C1b") == "PASS" and c1b_rope)
    def reason(a):
        m = re.findall(rf"^GATE {a} \w+: (.*)$", summ, re.M); return m[-1] if m else ""
    # NO only when a kernel other than RoPE was actually named ("hypothesis contradicted"); a C1c FAIL because its
    # launch-check patch did not apply names nothing and stays UNDECIDED (Amendment (13), manager)
    named_other = any(v(a) == "FAIL" and "hypothesis contradicted" in reason(a) for a in ("C1c", "C1b"))
    print(f"DECISION debug8_cause_attributed_to_RoPE: {'YES' if named_rope else ('NO' if named_other else 'UNDECIDED')} "
          f"(needs the real benchmark path to name the RoPE kernel: C1c={v('C1c')} first failing launch, C1b={v('C1b')} kernels={kvf('C1b', 'all_kernels_with_invalid_access')})")
    # (3) rule A (Amendment 12), computed ONLY from C1s, C2, C2s; Amendment (15): VOID if any of them is INVALID or NOT_RUN
    def verdict(arms):
        if all(v(a) == "PASS" for a in arms): return "PASS"
        if any(v(a) in ("INVALID", "NOT_RUN") for a in arms): return "VOID"
        return "FAIL"
    ra = verdict(("C1s", "C2", "C2s"))
    print(f"DECISION rule_A: {ra} (C1s={v('C1s')} C2={v('C2')} C2s={v('C2s')}) -> "
          + {"PASS": "the guard-only baseline passes", "FAIL": "the guard-only baseline does not pass", "VOID": "no verdict: a rule-A arm is INVALID or did not run"}[ra])
    # (4) Amendment (15): option 2 (upstream fix, minimal set) passes iff its bench, memory-check and fallback-counting arms pass
    o2 = verdict(("C2c", "C2cm", "C2cs"))
    print(f"DECISION option_2: {o2} (C2c={v('C2c')} C2cm={v('C2cm')} C2cs={v('C2cs')}; evaluators C2ce={v('C2ce')}, kernel tests C2cr={v('C2cr')}: reported) -> "
          + {"PASS": "the option 2 baseline passes", "FAIL": "the option 2 baseline does not pass", "VOID": "no verdict: an option 2 arm is INVALID or did not run"}[o2])
    print(f"DECISION phase6 (Amendment (15) item 4): guard-only={ra} option_2={o2} -> "
          + ("at least one baseline passes" if "PASS" in (ra, o2) else ("neither baseline passes" if ra == o2 == "FAIL" else "no baseline passes; a VOID verdict is for the owner")))
    print(f"DECISION info_only (not in the verdict): C2ce={v('C2ce')} C2cr={v('C2cr')} C2r={v('C2r')} C2a={v('C2a')} C3a={v('C3a')} C3={v('C3')} C3s={v('C3s')}")
    sys.exit(0)

out("UNDECIDED", "unknown arm")
