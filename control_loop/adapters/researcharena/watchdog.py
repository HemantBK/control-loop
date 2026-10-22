"""Phase 6 pod watchdog (phases/phase6_researcharena/PLAN.md §1.6(b), §7.7(4)): run on the CPU pod every 10 minutes.

    python -m control_loop.adapters.researcharena.watchdog [--dry-run] [--max-age-min 60] [--out results/phase6_researcharena/watchdog]

Lists pods with `runpodctl pod list -o json` and deletes every pod whose name starts with `p6-` and whose age
(createdAt, else uptimeSeconds) exceeds the limit. It never touches a pod whose name does not start with the
prefix (the CPU pod it runs on is `ubuntu-cpu-8c-32g`). Each delete is appended to `<out>/pods.jsonl` and logged
as a `pod_delete` step in `<out>/run.jsonl` with the cost (age x costPerHr); nothing is logged when there is
nothing to do (a one-line summary goes to stdout). `--dry-run` prints what it would delete and deletes nothing.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from control_loop import runlog
from control_loop.adapters.researcharena.pods import H100_RATE_USD, NAME_PREFIX, PHASE, _utc, parse_time

DEFAULT_OUT = Path("results") / PHASE / "watchdog"


def list_pods() -> list[dict]:
    cp = subprocess.run(["runpodctl", "pod", "list", "-o", "json"], capture_output=True, text=True, timeout=120)
    if cp.returncode != 0:
        raise RuntimeError(f"runpodctl pod list rc={cp.returncode}: {cp.stderr.strip()[-300:]}")
    data = json.loads(cp.stdout or "[]")
    return data if isinstance(data, list) else []


def age_seconds(pod: dict, now: float) -> float | None:
    t = parse_time(pod.get("createdAt"))
    if t is not None:
        return max(0.0, now - t)
    up = pod.get("uptimeSeconds")
    return float(up) if isinstance(up, (int, float)) else None


def stale(pods: list[dict], now: float, max_age_s: float, prefix: str = NAME_PREFIX) -> list[tuple[dict, float]]:
    """(pod, age) for every pod whose name starts with `prefix` and whose age exceeds `max_age_s`. A pod whose
    name does not start with the prefix is never returned, whatever its age; a pod with no readable age is
    treated as stale only if it carries the prefix (it must not outlive the launch that made it)."""
    out = []
    for p in pods:
        name = str(p.get("name") or "")
        if not name.startswith(prefix):
            continue
        age = age_seconds(p, now)
        if age is None or age > max_age_s:
            out.append((p, age if age is not None else float("inf")))
    return out


def delete(pod_id: str) -> tuple[bool, str]:
    cp = subprocess.run(["runpodctl", "pod", "delete", pod_id], capture_output=True, text=True, timeout=120)
    return cp.returncode == 0, (cp.stderr or cp.stdout).strip()[-300:]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-age-min", type=float, default=60.0)
    ap.add_argument("--prefix", default=NAME_PREFIX)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    if not a.prefix:
        print("refusing to run with an empty prefix", file=sys.stderr)
        return 2
    now = time.time()
    try:
        pods = list_pods()
    except Exception as e:   # the watchdog must not crash silently in cron: log and exit non-zero
        runlog.log_step(a.out, phase=PHASE, run_id="watchdog", step="pod_delete", status="failed", error=str(e))
        print(f"watchdog: {e}", file=sys.stderr)
        return 1
    victims = stale(pods, now, a.max_age_min * 60.0, a.prefix)
    print(f"watchdog {_utc(now)}: {len(pods)} pod(s) listed, {len(victims)} {a.prefix}* older than {a.max_age_min:g} min"
          + (" (dry run)" if a.dry_run else ""))
    rc = 0
    for p, age in victims:
        pid, name = str(p.get("id")), str(p.get("name"))
        rate = float(p.get("costPerHr") or H100_RATE_USD)
        usd = (age if age != float("inf") else 0.0) / 3600.0 * rate
        if a.dry_run:
            print(f"  would delete {pid} ({name}, age {age / 60:.0f} min, ${rate}/h)")
            continue
        ok, msg = delete(pid)
        rec = {"time": _utc(now), "event": "delete", "pod_id": pid, "name": name, "gpu_type": p.get("gpuDisplayName"),
               "data_center": p.get("dataCenterId"), "episode_id": None, "hourly_rate": rate,
               "seconds_billed": None if age == float("inf") else int(age), "usd": round(usd, 4), "run_id": "watchdog",
               "ok": ok}
        a.out.mkdir(parents=True, exist_ok=True)
        with (a.out / "pods.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        runlog.log_step(a.out, phase=PHASE, run_id="watchdog", step="pod_delete", status="done" if ok else "failed",
                        cost_usd=usd if ok else None, error=None if ok else msg,
                        note=f"watchdog deleted {pid} ({name}) at age {age / 60:.0f} min" if ok else f"could not delete {pid} ({name})",
                        pod_id=pid)
        print(f"  {'deleted' if ok else 'FAILED to delete'} {pid} ({name}, age {age / 60:.0f} min){'' if ok else ': ' + msg}")
        rc = rc or (0 if ok else 1)
    return rc


if __name__ == "__main__":
    sys.exit(main())
