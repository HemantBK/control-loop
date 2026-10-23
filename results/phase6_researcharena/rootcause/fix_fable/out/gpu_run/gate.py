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

if arm == "parse":   # gate.py parse <sanitizer log>: prints the parsed first block (preflight runs it on the real canary_bad.log)
    print(json.dumps(parse_sanitizer(open(d, errors="replace").read()))); sys.exit(0)

if arm == "preflight":
    p = rd("preflight.log")
    ok = "transformers 4.53.3" in p and "model cached" in p and "PATCH MISSING" not in p and "TASK_CONTEXT MISSING" not in p
    parser_ok = "PARSER_OK" in p
    san_ok = "compute-sanitizer:" in p and "ERROR SUMMARY: 0 errors" in p
    canary = "CANARY_OK" in p
    out("PASS" if ok else "FAIL", "torch/transformers/model/patches present" if ok else "see preflight.log",
        sanitizer="ok" if san_ok else ("UNAVAILABLE" if "UNAVAILABLE" in p else "smoke-failed/unknown"),
        canary="flags-known-OOB" if canary else "FAILED-or-not-run (sanitizer arms UNDECIDED unless they report)",
        parser="ok-on-real-canary-output" if parser_ok else "NOT-VALIDATED")

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
    need = {"C2": ["rope_guard_only.patch", "starter_rope_guard_only.patch"], "C3": ["rope_bounds.patch", "attention_harden.patch"], "C2c": []}[arm]
    if "PATCH_FAILED" in apply_log or any(f"applied {p}" not in apply_log for p in need):
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
    if "PATCH_FAILED" in apply_log or (arm == "C2s" and ("applied rope_guard_only.patch" not in apply_log or "applied starter_rope_guard_only.patch" not in apply_log)):
        out("FAIL", "patch did not apply", apply=apply_log.replace("\n", ";")[:200])
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
        if any(r["crashed"] for r in res.values()): out("FAIL", "CUDA error with the 11ea904 RoPE kernel", **kv)
        if not all(r["ran"] for r in res.values()): out("FAIL", "11ea904 RoPE did not run on every launch (fallback) or a run is incomplete", **kv)
        if all(r["tokens"] == "32" and r["matched"] and r["matched"].endswith("/8") for r in res.values()) and all(r["match"] == "yes" for r in res.values()):
            out("PASS", "11ea904 RoPE: greedy tokens match C0 on 8 prompts x 32 tokens, RoPE-only and with all four ops injected", **kv)
        if res["rope_only"]["match"] == "yes" and res["all_ops"]["match"] == "no":
            out("FAIL", "RoPE-only matches C0 but all-ops does not: the divergence is in another stock op (attention partial warps?), not RoPE", **kv)
        out("FAIL", "greedy tokens differ from C0 (or fewer than 8 prompts x 32 tokens compared)", **kv)
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
    # d is OUT_DIR here: read SUMMARY.txt (last GATE line per arm wins) and print the merged verdict (PLAN Amendment (12))
    summ = rd("SUMMARY.txt")
    def v(a):
        m = re.findall(rf"^GATE {a} (\w+):", summ, re.M); return m[-1] if m else "NOT_RUN"
    def kvf(a, key):
        m = re.findall(rf"^GATE {a} \w+:.*?\b{key}=(\S+)", summ, re.M); return m[-1] if m else "?"
    # (1) defect demonstrated: synthetic reproducers, flag the defect by construction (memcheck names rotary_embedding_kernel)
    demo = [a for a in ("C1r", "C1a") if v(a) == "PASS"]; demo_fail = [a for a in ("C1r", "C1a") if v(a) == "FAIL"]
    print(f"DECISION defect_demonstrated: {'YES' if demo else ('NO' if demo_fail else 'UNDECIDED')} (synthetic reproducers; RoPE in kernels_named: C1r={v('C1r')} C1a={v('C1a')})")
    # (2) debug8 cause reproduced: the real benchmark path (C1c launch-checked blocking run, C1s stock bench.sh, C1b bench under memcheck)
    rep_ = [a for a in ("C1c", "C1s", "C1b") if v(a) == "PASS"]; rep_fail = [a for a in ("C1c", "C1s", "C1b") if v(a) == "FAIL"]
    print(f"DECISION debug8_cause_reproduced: {'YES' if rep_ else ('NO' if rep_fail else 'UNDECIDED')} (real benchmark path: C1c={v('C1c')} C1s={v('C1s')} C1b={v('C1b')}; "
          f"C1c first failing launch / C1b first kernel named: C1b_rope_first={kvf('C1b', 'rope_first')} C1b_kernels={kvf('C1b', 'all_kernels_with_invalid_access')})")
    # (3) rule A (Amendment 12), computed ONLY from C1s, C2, C2s: all other arms are information
    rule_a = v("C1s") == "PASS" and v("C2") == "PASS" and v("C2s") == "PASS"
    print(f"DECISION rule_A: {'PASS' if rule_a else 'FAIL'} (C1s={v('C1s')} C2={v('C2')} C2s={v('C2s')}) -> "
          f"{'reopen Phase 6 on the guard-only baseline' if rule_a else 'do not reopen on this evidence'}"
          + ("" if rule_a else " [" + ", ".join(f"{a}={v(a)}" for a in ("C1s", "C2", "C2s") if v(a) != "PASS") + "]"))
    print(f"DECISION info_only (not in the verdict): C2c={v('C2c')} C2cs={v('C2cs')} C2cr={v('C2cr')} C2r={v('C2r')} C2a={v('C2a')} C3a={v('C3a')} C3={v('C3')} C3s={v('C3s')}")
    sys.exit(0)

out("UNDECIDED", "unknown arm")
