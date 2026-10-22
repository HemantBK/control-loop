"""Phase 6 spend, recomputed from the logs by basis (README §11; audits/RESPONSE.md A2, A3).

    uv run --frozen python phases/phase6_researcharena/spend_total.py [--results DIR] [--phase-dir DIR]

Reads every `pods.jsonl` and `run.jsonl` under the results directory (default `results/phase6_researcharena/`) and the
costs recorded in the phase's council and audit files (default `phases/phase6_researcharena/audits/`). Prints, each on
its own line and never mixed:

- MEASURED: GPU = the sum of the `usd` field of every `pods.jsonl` delete line (the driver's wall-clock interval times
  the pod's listed hourly rate; not RunPod's invoice); API = `run.jsonl` cost lines whose note says "measured".
- LIST-PRICE RECOMPUTATION: token counts priced at `control_loop/spend.py`'s list price (the agent's cost, which the
  driver logs on its `monitor` lines).
- ALLOWANCES: `run.jsonl` cost lines whose note says "upper" (the smoke tests' one paid call, counted at its $0.05 cap).
- RECORDED ELSEWHERE: the councils' and the audit's costs as their files state them, each with its basis.
- NOT MEASURED: listed, never added.

`pod_delete` lines in `run.jsonl` repeat the GPU dollars of `pods.jsonl` (one computation writes both) and are only
cross-checked. A `run.jsonl` cost line that fits no rule is printed as unclassified and the exit status is 2; a pod
with a create line and no delete line is printed as open and the exit status is 3. No model call, no network.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parent
REPO = PHASE_DIR.parents[1]
RESULTS = REPO / "results" / "phase6_researcharena"

# The councils' and the audit's costs, as their files record them: (label, file under the phase dir, regex whose group 1
# is the counted figure and group 2 the figure on the other basis, basis of the counted figure, basis of the other).
RECORDED = [
    ("council 2026-10-22 check: Qwen3 call (Codex call unpriced)", "audits/council_2026-10-22_check.md",
     r"\*\*\$([0-9]+(?:\.[0-9]+)?)\*\*\s+\(\$[0-9.]+\);\s+OpenRouter's\s+own\s+usage\s+field\s+reports\s+\$([0-9]+(?:\.[0-9]+)?)",
     "list price, control_loop/spend.py", "OpenRouter usage.cost"),
    ("council 2026-10-22 smoke5: Fable 5.1 + Astra", "audits/council_2026-10-22_smoke5.md",
     r"council\s+cost\s+\$([0-9]+(?:\.[0-9]+)?)\s+\(OpenRouter\s+usage\.cost;\s+\$([0-9]+(?:\.[0-9]+)?)\s+at\s+listed\s+prices\)",
     "billed, OpenRouter usage.cost", "listed prices"),
    ("audit 2026-10-22 GPT-6 Astra (two calls)", "audits/audit_astra.md",
     r"OpenRouter\s+`usage\.cost`\s+\$[0-9.]+\s+\+\s+\$[0-9.]+\s+=\s+\$([0-9]+(?:\.[0-9]+)?);\s+at\s+the\s+listed\s+\$10\s+/\s+\$50\s+per\s+1M:"
     r"\s+\$[0-9.]+\s+\+\s+\$[0-9.]+\s+=\s+\$([0-9]+(?:\.[0-9]+)?)",
     "billed, OpenRouter usage.cost", "listed prices"),
]

# Known costs that no log measures (README §9 items 9 and 10, §11; the check council's Codex section).
NOT_MEASURED = [
    "check run 1 API: the eight episode starts most likely ran the agent before each 120 s timeout; usage not collected",
    "opencode's title requests to google/gemini-nano-banana-2.1, one per agent opencode session (README §9 item 9)",
    "council 2026-10-22 check: the Codex (gpt-6.1-sol) call, 21,077 tokens, no price printed or listed",
    "image builds on GitHub Actions (no RunPod cost)",
]


def _rel(p: Path, base: Path) -> str:
    try:
        return p.relative_to(base).as_posix()
    except ValueError:
        return p.name


def _jsonl(p: Path) -> list[dict]:
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _group(rel: str) -> str:
    """The run a log belongs to: `smoke4/run.jsonl` -> smoke4; `sweep/qwen3_733_run2/launches/check1/run.jsonl` ->
    sweep/qwen3_733_run2."""
    parts = rel.split("/")
    if parts[0] == "sweep" and len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0] if len(parts) > 1 else "."


def compute(results: Path = RESULTS, phase_dir: Path = PHASE_DIR) -> dict:
    gpu_by_run: dict[str, dict] = {}
    pods, open_pods = [], []
    for f in sorted(results.rglob("pods.jsonl")):
        rel = _rel(f, results)
        recs = _jsonl(f)
        deleted = {r["pod_id"] for r in recs if r.get("event") == "delete"}
        for r in recs:
            if r.get("event") == "create" and r["pod_id"] not in deleted:
                open_pods.append(f"{rel}: {r['pod_id']}")
            if r.get("event") != "delete":
                continue
            usd, secs, rate = float(r.get("usd") or 0.0), int(r.get("seconds_billed") or 0), float(r["hourly_rate"])
            pods.append(dict(log=rel, pod_id=r["pod_id"], usd=usd, seconds=secs, rate=rate,
                             frac_s=usd * 3600.0 / rate - secs))
            g = gpu_by_run.setdefault(_group(rel), dict(pods=0, seconds=0, usd=0.0))
            g["pods"] += 1
            g["seconds"] += secs
            g["usd"] += usd

    measured_api, list_price, allowances, unclassified = [], [], [], []
    run_jsonl_gpu = 0.0
    n_run_logs = 0
    for f in sorted(results.rglob("run.jsonl")):
        n_run_logs += 1
        rel = _rel(f, results)
        for r in _jsonl(f):
            c = r.get("cost_usd")
            if c in (None, 0, 0.0):
                continue
            note = str(r.get("note") or "")
            item = dict(log=rel, run=_group(rel), run_id=r.get("run_id"), step=r.get("step"), usd=float(c), note=note)
            if r.get("step") == "pod_delete":
                run_jsonl_gpu += float(c)
            elif "upper" in note:
                allowances.append(item)
            elif "measured" in note:
                measured_api.append(item)
            elif r.get("step") == "monitor":
                list_price.append(item)
            else:
                unclassified.append(item)

    recorded = []
    for label, relpath, rx, basis, other_basis in RECORDED:
        p = phase_dir / relpath
        m = re.search(rx, p.read_text(encoding="utf-8"), re.S) if p.exists() else None
        recorded.append(dict(label=label, file=relpath, found=bool(m), usd=float(m.group(1)) if m else 0.0,
                             other=float(m.group(2)) if m else None, basis=basis, other_basis=other_basis))

    gpu = sum(p["usd"] for p in pods)
    gpu_int = sum(p["seconds"] * p["rate"] / 3600.0 for p in pods)
    m_api = sum(i["usd"] for i in measured_api)
    lp = sum(i["usd"] for i in list_price)
    allow = sum(i["usd"] for i in allowances)
    rec = sum(r["usd"] for r in recorded)
    execution = gpu + m_api + lp + allow
    return dict(pods=pods, gpu_by_run=gpu_by_run, open_pods=open_pods, n_run_logs=n_run_logs,
                gpu=gpu, gpu_seconds=sum(p["seconds"] for p in pods), gpu_int_seconds_usd=gpu_int,
                run_jsonl_gpu=run_jsonl_gpu, measured_api=measured_api, list_price=list_price, allowances=allowances,
                unclassified=unclassified, recorded=recorded,
                measured=gpu + m_api, measured_api_usd=m_api, list_price_usd=lp, allowances_usd=allow,
                execution=execution, recorded_usd=rec, total=execution + rec, not_measured=list(NOT_MEASURED))


def render(t: dict) -> str:
    L = []
    w = 78
    row = lambda label, usd: L.append(f"  {label:<{w}} ${usd:8.4f}")
    L.append(f"Phase 6 spend by basis ({len(t['pods'])} pods.jsonl delete lines, {t['n_run_logs']} run.jsonl files)")
    L.append("")
    L.append("GPU per run (pods.jsonl delete lines):")
    for run, g in sorted(t["gpu_by_run"].items()):
        row(f"{run:<24} {g['pods']:>2} pod(s) {g['seconds']:>6,} s", g["usd"])
    L.append("")
    L.append("MEASURED")
    row(f"GPU: driver wall-clock x listed rate, sum of usd ({len(t['pods'])} pods, {t['gpu_seconds']:,} whole s)", t["gpu"])
    for i in t["measured_api"]:
        row(f"API: {i['run']} {i['run_id']} ({i['step']}, note 'measured')", i["usd"])
    row("measured total", t["measured"])
    L.append("LIST-PRICE RECOMPUTATION (tokens x control_loop/spend.py list price, unverified)")
    by_run: dict[str, float] = {}
    for i in t["list_price"]:
        by_run[i["run"]] = by_run.get(i["run"], 0.0) + i["usd"]
    for run, usd in sorted(by_run.items()):
        n = sum(1 for i in t["list_price"] if i["run"] == run)
        row(f"agent: {run} ({n} episode lines on the driver's monitor step)", usd)
    row("list-price total", t["list_price_usd"])
    L.append("ALLOWANCES / UPPER BOUNDS (not measured; counted at the cap)")
    for i in t["allowances"]:
        row(f"{i['run']}: {i['note'][:60]}", i["usd"])
    row("allowances total", t["allowances_usd"])
    row("EXECUTION TOTAL (measured + list price + allowances)", t["execution"])
    L.append("")
    L.append("RECORDED ELSEWHERE (councils and audit, as their files state them)")
    for r in t["recorded"]:
        if r["found"]:
            row(f"{r['label']} [{r['basis']}; {r['other_basis']} ${r['other']:.4f}]", r["usd"])
        else:
            L.append(f"  {r['label']}: NOT FOUND in {r['file']} (not added)")
    row("councils and audit total", t["recorded_usd"])
    row("TOTAL WITH COUNCILS AND AUDIT", t["total"])
    L.append("")
    L.append("NOT MEASURED (listed, not added)")
    for s in t["not_measured"]:
        L.append(f"  - {s}")
    L.append("")
    L.append("GPU RECONCILIATION")
    fr = [p["frac_s"] for p in t["pods"]] or [0.0]
    L.append(f"  sum of whole seconds x rate / 3600 = ${t['gpu_int_seconds_usd']:.4f}; sum of usd = ${t['gpu']:.4f}; "
             f"difference ${t['gpu'] - t['gpu_int_seconds_usd']:.4f}")
    L.append(f"  = {sum(fr):.2f} s of fractional seconds over {len(t['pods'])} pods (per pod {min(fr):.2f} to {max(fr):.2f} s): "
             "pods.py writes seconds_billed = int(seconds) but usd = round(seconds / 3600 x rate, 4) on the unrounded seconds")
    L.append(f"  run.jsonl pod_delete lines (same computation, unrounded): ${t['run_jsonl_gpu']:.4f}")
    if t["unclassified"]:
        L.append("UNCLASSIFIED run.jsonl cost lines (not added):")
        for i in t["unclassified"]:
            L.append(f"  {i['log']} {i['step']} ${i['usd']:.4f} {i['note'][:60]}")
    if t["open_pods"]:
        L.append("OPEN PODS (create line, no delete line; not added): " + ", ".join(t["open_pods"]))
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", type=Path, default=RESULTS)
    ap.add_argument("--phase-dir", type=Path, default=PHASE_DIR)
    a = ap.parse_args(argv)
    t = compute(a.results, a.phase_dir)
    print(render(t))
    if t["open_pods"]:
        return 3
    return 2 if t["unclassified"] else 0


if __name__ == "__main__":
    sys.exit(main())
