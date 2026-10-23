#!/usr/bin/env python3
"""Mechanical pass/fail gate per arm (written before the GPU run; see REPORT.md section 4d).
Usage: gate.py <arm> <arm_dir>   -> prints exactly one line: GATE <arm> <VERDICT>: <reason> | k=v ...
Verdicts: PASS, FAIL, UNDECIDED (ran but the rule cannot decide), NOT_RUN."""
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

def out(verdict, reason, **kv):
    extra = " ".join(f"{k}={v}" for k, v in kv.items())
    print(f"GATE {arm} {verdict}: {reason}" + (f" | {extra}" if extra else ""))
    sys.exit(0)

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
    summ = re.findall(r"ERROR SUMMARY: (\d+) error", text)
    named = sorted({k for k in KERNELS if re.search(r"Invalid __\w+__ (read|write)[^\n]*\n[^\n]*" + k, text)})
    return {"first": first, "kernels_named": named, "n_errors": int(summ[-1]) if summ else None, "tool_error": bool(re.search(r"^=+ Error:", text, re.M)),
            "api_errors": len(re.findall(r"Program hit cudaError", text))}

if arm == "preflight":
    p = rd("preflight.log")
    ok = "transformers 4.53.3" in p and "model cached" in p and "PATCH MISSING" not in p and "TASK_CONTEXT MISSING" not in p
    san_ok = "compute-sanitizer:" in p and "ERROR SUMMARY: 0 errors" in p
    canary = "CANARY_OK" in p
    out("PASS" if ok else "FAIL", "torch/transformers/model/patches present" if ok else "see preflight.log",
        sanitizer="ok" if san_ok else ("UNAVAILABLE" if "UNAVAILABLE" in p else "smoke-failed/unknown"),
        canary="flags-known-OOB" if canary else "FAILED-or-not-run (sanitizer arms UNDECIDED unless they report)")

if arm == "C0":
    m = re.search(r"^C0_BASELINE_TPS=([\d.]+)", bench, re.M)
    if not bench: out("NOT_RUN", "no bench.log")
    if CUDA_ERR.search(bench): out("FAIL", "CUDA error without any kernel injected: the stack, not the kernels, is broken", rc=rc)
    if rc == 124: out("FAIL", "timeout", rc=rc)
    if m and "C0_DONE" in bench and float(m.group(1)) >= 20:
        out("PASS", "vanilla TinyLlama generates 8x128 tokens on this GPU", tps=m.group(1), rc=rc)
    out("FAIL", "no C0_BASELINE_TPS>=20 / C0_DONE line", tps=m.group(1) if m else None, rc=rc)

if arm in ("C1a", "C1b", "C1r"):
    if not bench and not san: out("NOT_RUN", "no logs")
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
    if f["kernel"] == "rotary_embedding_kernel":
        exp_line = f["src_line"] in {"34", "47", "48", "50", "51"}
        exp_thread = f["thread"] is not None and int(f["thread"].split(",")[0]) >= 128
        out("PASS", "first invalid access is in rotary_embedding_kernel (RoPE confirmed)" + ("" if exp_line else " [line not in the predicted set 34/47/48/50/51]") + ("" if exp_thread else " [thread index not in the predicted tail >=128]"), **kv)
    out("FAIL", f"first invalid access is in {f['kernel']}, not the RoPE kernel: hypothesis contradicted", **kv)

if arm == "C1c":
    if not bench: out("NOT_RUN", "no bench.log")
    if "PATCH_FAILED" in apply_log: out("FAIL", "launch-check patch did not apply", apply=apply_log.replace("\n", ";")[:200])
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
    if "PATCH_FAILED" in apply_log or (arm != "C2c" and "applied rope_bounds.patch" not in apply_log) or (arm == "C3" and "applied attention_harden.patch" not in apply_log):
        out("FAIL", "patch did not apply (unrelated to the hypothesis)", apply=apply_log.replace("\n", ";")[:200])
    if arm == "C2c" and "applied rope_correct_11ea904.patch" not in apply_log:
        out("FAIL", "rope_correct patch did not apply", apply=apply_log.replace("\n", ";")[:200])
    if re.search(r"^COMPILE_STATUS=FAIL", bench, re.M): out("FAIL", "patched kernels did not compile on the pod (unrelated to the hypothesis; see bench.log)", rc=rc)
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

if arm in ("C2s", "C3s", "C2cs"):
    if not bench: out("NOT_RUN", "no bench.log")
    if "PATCH_FAILED" in apply_log: out("FAIL", "patch did not apply", apply=apply_log.replace("\n", ";")[:200])
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
            out("FAIL", "11ea904 RoPE ran everywhere but the greedy tokens differ from C0 (numerics gate)", **kv)
        if s is None: out("PASS", "patched kernels ran on every launch, no fallback, no crash (no sanitizer available)", **kv)
        if s["first"] is None and not s["tool_error"]: out("PASS", "patched kernels ran on every launch, no fallback, memcheck reports no invalid access", n_errors=s["n_errors"], api_errors=s["api_errors"], **kv)
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

if arm == "C4":
    ev = rd("eval.log") or bench
    if not ev: out("NOT_RUN", "no eval.log/bench.log")
    m = re.search(r"Main task: (SUCCESS|PARTIAL) \(speedup=([\d.]+)x\)", ev)
    if CUDA_ERR.search(ev) or "evaluation error" in ev: out("FAIL", "episode evaluation hit a CUDA error", rc=rc)
    if m: out("PASS", "one full episode evaluated end to end on the patched baseline", label=m.group(1), speedup=m.group(2), rc=rc)
    out("FAIL", "no 'Main task: ... (speedup=...)' line", rc=rc)

if arm == "decision":
    # d is OUT_DIR here: read SUMMARY.txt and print the merged verdict under both decision rules (see COMPARISON.md)
    summ = rd("SUMMARY.txt")
    def v(a):
        m = re.search(rf"^GATE {a} (\w+):", summ, re.M); return m.group(1) if m else "NOT_RUN"
    rope_named = any(v(a) == "PASS" for a in ("C1a", "C1r", "C1c", "C1b"))
    contradicted = any(v(a) == "FAIL" for a in ("C1a", "C1r", "C1c", "C1b"))
    mem_safe = v("C2") == "PASS" and v("C2s") == "PASS"
    mem_safe3 = v("C3") == "PASS" and v("C3s") == "PASS"
    correct = v("C2c") == "PASS" and v("C2cs") == "PASS" and v("C2cr") in ("PASS", "NOT_RUN")
    print(f"DECISION root_cause={'ROPE_CONFIRMED' if rope_named and not contradicted else ('CONTRADICTED' if contradicted else 'UNDECIDED')} "
          f"(C1a={v('C1a')} C1r={v('C1r')} C1c={v('C1c')} C1b={v('C1b')})")
    print(f"DECISION rule_A_memory_safe: {'PASS' if (mem_safe or mem_safe3) else 'FAIL'} (C2={v('C2')} C2s={v('C2s')} C3={v('C3')} C3s={v('C3s')}) -> plan §6 literal: {'reopen on C2/C3 baseline' if (mem_safe or mem_safe3) else 'close'}")
    print(f"DECISION rule_B_correctness_qualified: {'PASS' if correct else 'FAIL'} (C2c={v('C2c')} C2cs={v('C2cs')} C2cr={v('C2cr')}) -> {'reopen on the 11ea904-RoPE baseline' if correct else 'no numerically correct patched arm'}")
    print(f"DECISION attention_partial_warps: C2a={v('C2a')} C3a={v('C3a')} (stock-vs-whole-warp numerics; see their numerics= fields)")
    sys.exit(0)

out("UNDECIDED", "unknown arm")
