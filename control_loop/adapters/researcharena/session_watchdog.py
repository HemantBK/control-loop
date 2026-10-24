"""Hard-delete watchdog for one Phase 6 GPU session (PLAN Amendments (8), (16), (19)), run on the CPU pod beside the session:

    python -m control_loop.adapters.researcharena.session_watchdog <pod name> <limit min> <limit usd> <log file>
        [--pre-delete-cmd CMD --lead-s SECONDS]

Every 30 s it lists pods (`runpodctl pod list -o json`). A pod with the given name whose age from createdAt reaches the
limit, or whose cost (age x costPerHr) reaches the dollar limit, is deleted (`runpodctl pod delete`). It logs a heartbeat
every 5 minutes.

It exits only when
- the pod has been seen and then three consecutive successful listings do not contain it (90 s), or
- no pod of that name has appeared within 3 hours.

With --pre-delete-cmd, CMD (a shell command, run from the current directory) runs once when the pod is within --lead-s
seconds of either limit, with a timeout of lead-s minus 60 s; the hard delete still happens at the limit, whether or not
CMD succeeded (owner, 2026-10-24: "If the watchdog forces a delete, copy whatever is there first").

A failed listing (non-zero exit code, unparseable output, timeout) is logged and retried; it never counts as "pod gone".
2026-10-23: the fullrun2 watchdog read a failed listing as an empty one and exited with its pod still running; this module
replaces it (PLAN Amendment (19) item 6)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Callable

from control_loop.adapters.researcharena.pods import parse_time

GONE_AFTER = 3          # consecutive successful listings without the pod
NO_POD_EXIT_S = 3 * 3600
BEAT_S = 300
POLL_S = 30


class ListingError(RuntimeError):
    pass


def list_pods(timeout: float = 120) -> list[dict]:
    """runpodctl's pod list; any failure raises ListingError (it is never an empty list)."""
    try:
        cp = subprocess.run(["runpodctl", "pod", "list", "-o", "json"], capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as e:
        raise ListingError(f"{type(e).__name__}: {e}") from e
    if cp.returncode != 0:
        raise ListingError(f"runpodctl pod list rc={cp.returncode}: {(cp.stderr or '').strip()[-200:]}")
    try:
        data = json.loads(cp.stdout)
    except json.JSONDecodeError as e:
        raise ListingError(f"unparseable listing: {e}") from e
    return data if isinstance(data, list) else data.get("pods", [])


def delete_pod(pod_id: str) -> int:
    return subprocess.run(["runpodctl", "pod", "delete", pod_id], capture_output=True, text=True, timeout=120).returncode


def run(name: str, limit_s: float, limit_usd: float, log: Callable[[str], None], *,
        lister: Callable[[], list[dict]] = list_pods, deleter: Callable[[str], int] = delete_pod,
        now: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep, max_polls: int | None = None,
        pre_delete: Callable[[], None] | None = None, pre_delete_lead_s: float = 0.0) -> str:
    """The watchdog loop. Returns why it exited ("gone", "no pod", or "max polls" in tests)."""
    log(f"watchdog start: {name}, limits {limit_s / 60:g} min or ${limit_usd}")
    seen, misses, t_start, last_beat, polls, copied = False, 0, now(), -1e18, 0, False
    while max_polls is None or polls < max_polls:
        polls += 1
        try:
            data = lister()
        except ListingError as e:
            log(f"list error (not counted as gone): {e}")
            sleep(POLL_S)
            continue
        mine = [p for p in data if p.get("name") == name]
        if not mine:
            misses += 1
            if seen and misses >= GONE_AFTER:
                log(f"pod gone ({GONE_AFTER} consecutive listings); watchdog exits")
                return "gone"
            if seen:
                log(f"pod not in listing ({misses}/{GONE_AFTER})")
            elif now() - t_start > NO_POD_EXIT_S:
                log("no pod in 3 h; watchdog exits")
                return "no pod"
        else:
            misses = 0
        for p in mine:
            seen = True
            created = parse_time(p.get("createdAt")) or t_start
            age = now() - created
            rate = float(p.get("costPerHr") or 3.99)
            usd = age * rate / 3600
            deadline = min(limit_s, limit_usd * 3600 / rate)
            if pre_delete and not copied and age >= deadline - pre_delete_lead_s:
                copied = True
                log(f"pre-delete copy start ({deadline - age:.0f} s before the limit)")
                try:
                    pre_delete()
                    log("pre-delete copy done")
                except Exception as e:   # the copy never blocks the hard delete
                    log(f"pre-delete copy failed: {type(e).__name__}: {str(e)[:200]}")
                age = now() - created
                usd = age * rate / 3600
            if age >= limit_s or usd >= limit_usd:
                log(f"HARD DELETE {p['id']}: age {age:.0f} s, ${usd:.2f}; rc={deleter(p['id'])}")
            elif now() - last_beat >= BEAT_S:
                log(f"{p['id']}: age {age:.0f} s, ${usd:.2f}, uptime {p.get('uptimeSeconds')}")
                last_beat = now()
        sleep(POLL_S)
    return "max polls"


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="session_watchdog")
    ap.add_argument("name"); ap.add_argument("limit_min", type=float); ap.add_argument("limit_usd", type=float)
    ap.add_argument("log"); ap.add_argument("--pre-delete-cmd", default=None); ap.add_argument("--lead-s", type=float, default=420.0)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    name, limit_min, limit_usd, path = a.name, a.limit_min, a.limit_usd, a.log
    import signal

    def on_term(signum, frame):   # a manager restart shows in the log (Amendment (20))
        log("watchdog stopped by SIGTERM")
        sys.exit(0)
    signal.signal(signal.SIGTERM, on_term)
    pre = None
    if a.pre_delete_cmd:
        def pre():
            subprocess.run(a.pre_delete_cmd, shell=True, timeout=max(60.0, a.lead_s - 60), check=True)

    def log(m: str) -> None:
        with open(path, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {m}\n")
    run(name, limit_min * 60, limit_usd, log, pre_delete=pre, pre_delete_lead_s=a.lead_s if pre else 0.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
