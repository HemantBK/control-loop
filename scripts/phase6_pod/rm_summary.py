#!/usr/bin/env python3
"""Summary of one interleaved comparison (owner, 2026-10-24): each pair's tok/s and ratio, the median ratio, and, per
timed pass, what the monitor saw in its window: SM clock (mean / min), GPU utilisation, other GPU compute processes, and
the highest 1-minute load average. Usage: rm_summary.py <passes.jsonl> <label> <set A> <set B>; reads
$P6_RM/monitor_gpu.csv and monitor_cpu.log; writes <label>/summary.json and prints a table."""
import json, os, statistics, sys

passes_f, label, A, B = sys.argv[1:5]
RM = os.environ.get("P6_RM", "/workspace/remeasure")
P = [json.loads(l) for l in open(passes_f) if l.strip()]
gpu = []
try:
    for line in open(f"{RM}/monitor_gpu.csv"):
        f = [x.strip() for x in line.split(",")]
        try:
            gpu.append((float(f[0]), float(f[1]), float(f[3])))   # monitor.sh columns: epoch, SM MHz, mem MHz, util %, mem util %, temp, W
        except (ValueError, IndexError):
            continue
except FileNotFoundError:
    pass
cpu = []   # (epoch, load1, [other gpu pids])
try:
    cur = None
    for line in open(f"{RM}/monitor_cpu.log"):
        if line.startswith("== "):
            parts = line.split()
            cur = [float(parts[1]), float(parts[3]), []]; cpu.append(cur)
        elif cur is not None and line.strip() and line.split(",")[0].strip().isdigit():
            cur[2].append(int(line.split(",")[0]))
except FileNotFoundError:
    pass


def window(p):
    g = [x for x in gpu if p["start"] <= x[0] <= p["end"]]
    c = [x for x in cpu if p["start"] <= x[0] <= p["end"]]
    others = sorted({pid for x in c for pid in x[2] if pid != p["pid"]})
    return {"sm_mhz_mean": round(statistics.mean(x[1] for x in g), 0) if g else None,
            "sm_mhz_min": min(x[1] for x in g) if g else None,
            "util_mean": round(statistics.mean(x[2] for x in g), 1) if g else None,
            "load1_max": max(x[1] for x in c) if c else None, "other_gpu_pids": others, "samples": len(g)}


pairs, rows = [], []
a_runs = [p for p in P if p["set"] == A]; b_runs = [p for p in P if p["set"] == B]
for i, (pa, pb) in enumerate(zip(a_runs, b_runs), 1):
    ratio = pb["avg_tps"] / pa["avg_tps"]
    pairs.append({"pair": i, A: round(pa["avg_tps"], 2), B: round(pb["avg_tps"], 2), "ratio": round(ratio, 4),
                  f"{A}_window": window(pa), f"{B}_window": window(pb),
                  f"{A}_per_prompt": pa["per_prompt_tps"], f"{B}_per_prompt": pb["per_prompt_tps"],
                  f"{A}_kernel_counts": pa.get("kernel_counts"), f"{B}_kernel_counts": pb.get("kernel_counts"),
                  f"{A}_first_fallback": pa.get("first_fallback"), f"{B}_first_fallback": pb.get("first_fallback")})
med = statistics.median(p["ratio"] for p in pairs) if pairs else None
out = {"label": label, "A": A, "B": B, "pairs": pairs, "median_ratio": med, "n_pairs": len(pairs)}
os.makedirs(f"{RM}/{label}", exist_ok=True)
json.dump(out, open(f"{RM}/{label}/summary.json", "w"), indent=2)
print(f"{'pair':>4} {A + ' tok/s':>14} {B + ' tok/s':>14} {'ratio':>7}   window ({A} | {B}): SM MHz mean/min, util %, load1 max, other GPU pids")
for p in pairs:
    wa, wb = p[f"{A}_window"], p[f"{B}_window"]
    print(f"{p['pair']:>4} {p[A]:>14} {p[B]:>14} {p['ratio']:>7}   {wa['sm_mhz_mean']}/{wa['sm_mhz_min']}, {wa['util_mean']}, "
          f"{wa['load1_max']}, {wa['other_gpu_pids']} | {wb['sm_mhz_mean']}/{wb['sm_mhz_min']}, {wb['util_mean']}, {wb['load1_max']}, {wb['other_gpu_pids']}")
for p in pairs:   # change 07: which kernels ran in each timed pass
    for side in (A, B):
        c = p.get(f"{side}_kernel_counts") or {}
        fb = sum(v.get("fallback", 0) for v in c.values())
        print(f"COUNTS pair {p['pair']} {side}: " + ", ".join(f"{k} {v.get('custom', 0)}/{v.get('fallback', 0)}"
              + (f" (+{v['decode_pytorch']} decode PyTorch)" if "decode_pytorch" in v else "") for k, v in sorted(c.items()))
              + f"; fallbacks {fb}" + (f" first {p.get(side + '_first_fallback')}" if fb else ""))
print(f"MEDIAN_RATIO {label} {B}/{A} = {med}")
