#!/bin/bash
# CPU test of rm_summary.py on synthetic passes and monitor logs: 3 pairs, one pass window with a low SM clock and a
# foreign GPU process; expected median ratio 1.1 and the interference visible in that pass's window.
set -u
T=$(mktemp -d); export P6_RM=$T; O=$T/interleave; mkdir -p $O
python3 - $T <<'PY'
import json, sys
T = sys.argv[1]; t0 = 1000.0
rows = [("initial", 100.0), ("agent", 110.0), ("initial", 100.0), ("agent", 120.0), ("initial", 100.0), ("agent", 105.0)]
with open(f"{T}/interleave/passes.jsonl", "w") as f:
    for i, (s, tps) in enumerate(rows):
        f.write(json.dumps({"set": s, "avg_tps": tps, "per_prompt_tps": [tps] * 8, "start": t0 + i * 40, "end": t0 + i * 40 + 30,
                            "pid": 500 + i, "injected": {}}) + "\n")
with open(f"{T}/monitor_gpu.csv", "w") as g, open(f"{T}/monitor_cpu.log", "w") as c:
    for k in range(0, 240, 2):
        t = t0 + k; sm = 900 if 40 <= k <= 70 else 1980
        g.write(f"{t},{sm},2619,{60 if sm > 1000 else 95},30,40,250\n")
        c.write(f"== {t} load {'9.5' if 40 <= k <= 70 else '1.0'} 1.0 1.0\n")
        c.write(f"{501 if 40 <= k <= 70 else 999}, python3, 2000 MiB\n")
        if 40 <= k <= 70: c.write("777, python3, 3000 MiB\n")
PY
python3 "$(dirname "$0")/rm_summary.py" $O/passes.jsonl interleave initial agent | tee $T/out.txt
python3 - $T <<'PY'
import json, sys
s = json.load(open(f"{sys.argv[1]}/interleave/summary.json"))
p2 = s["pairs"][0]["agent_window"]
ok = abs(s["median_ratio"] - 1.1) < 1e-9 and [p["ratio"] for p in s["pairs"]] == [1.1, 1.2, 1.05] \
     and p2["sm_mhz_min"] == 900 and 777 in p2["other_gpu_pids"] and p2["load1_max"] == 9.5
print("RM_SUMMARY_TEST", "PASS" if ok else f"FAIL {s['median_ratio']} {p2}")
PY
rm -rf $T
