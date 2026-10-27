"""Fleet watchdog for the Phase 6 batch (PLAN Amendment (22), Part A): one long-running process on the CPU pod that
guards every `p6-` pod, whoever created it, and keeps running when the session that started the batch dies.

    python -m control_loop.adapters.researcharena.fleet_watchdog <state dir> [--dry-run] [--fake-pods FILE]
        [--poll-s 30] [--idle-s 900] [--probe-s 60] [--beat-s 60]

Run it under scripts/phase6/watchdog_loop.sh in tmux session `watchdog` (restarted 5 s after any exit). The state dir:
- `batch.json`: {"batch_id", "gpu_cap_usd", "default_cap_usd", "default_cap_min"}, written by the runner;
- `pods/<name>.json`: one per pod the runner created: {"name", "cap_usd", "cap_min", "copy_cmd", "probe_cmd"};
- `seen.json`: every `p6-` pod seen and its last cost (kept across restarts);
- `ledger.jsonl`: one line per pod that left the listing (deleted by the watchdog, or by anyone), with its cost;
- `STOP`: written when the batch's GPU spend reaches gpu_cap_usd; the runner creates no pod while it exists;
- `watchdog.log`: a heartbeat every beat_s and every action.

Every poll it lists pods (`runpodctl pod list -o json`, plus the pods in --fake-pods) and closes a pod (runs its
copy_cmd, then deletes it) when
- its cost (age from createdAt x costPerHr) reaches cap_usd, or its age reaches cap_min; an unregistered `p6-` pod gets
  the batch defaults;
- the batch's GPU spend (the ledger's costs plus the live pods' costs) reaches gpu_cap_usd: every live pod is closed;
- it has been idle for idle_s. Its probe_cmd prints `JOB <name>` for each running job, `GPU <util>` and `APPS <n>`.
  A running job is a pid file under /workspace/jobs with no exit-code file whose process is alive (the job's own
  process, not a tmux pane's command name; owner, 2026-10-25). Idle is no job, GPU 0 and no compute process; a failed
  probe is never idle.

A cap close deletes after one copy attempt, whatever its result. An idle close retries a failed copy on the next two
polls, then deletes anyway. A copy_cmd exits 0 only after its verify step passed.

It never touches a pod whose name does not start with `p6-`, nor the pod it runs on ($RUNPOD_POD_ID or
/etc/rp_environment). A failed listing is logged and retried; it never counts as a pod gone. --dry-run deletes nothing
on RunPod: a real pod gets one "would delete" line; a fake pod is removed from the fake file, as a delete would. Copy
commands run in both modes."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from control_loop.adapters.researcharena.pods import NAME_PREFIX, parse_time

DEFAULT_RATE = 3.99
GONE_AFTER = 3            # consecutive successful listings without the pod
IDLE_COPY_TRIES = 3
def jobs_probe(jobs_dir: str = "/workspace/jobs") -> str:
    return (f"cd {jobs_dir} 2>/dev/null && for p in *.pid; do [ -e \"$p\" ] || continue; n=${{p%.pid}}; "
            "[ -f \"$n.rc\" ] && continue; kill -0 \"$(cat \"$p\")\" 2>/dev/null && echo \"JOB $n\"; done; "
            "echo \"GPU $(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits | head -1)\"; "
            "echo \"APPS $(nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -c .)\"")


JOBS_PROBE = jobs_probe()


class ListingError(RuntimeError):
    pass


def own_pod_id() -> str | None:
    if os.environ.get("RUNPOD_POD_ID"):
        return os.environ["RUNPOD_POD_ID"]
    try:
        m = re.search(r'RUNPOD_POD_ID="?([a-z0-9]+)', Path("/etc/rp_environment").read_text())
        return m.group(1) if m else None
    except OSError:
        return None


def runpod_list(timeout: float = 120) -> list[dict]:
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


def runpod_delete(pod_id: str) -> tuple[bool, str]:
    try:
        cp = subprocess.run(["runpodctl", "pod", "delete", pod_id], capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"{type(e).__name__}"
    return cp.returncode == 0, (cp.stderr or cp.stdout or "").strip()[-200:]


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True))
    tmp.replace(path)


class FakePods:
    """A pod list in a JSON file (the fake batch's "RunPod"): list reads it, delete removes the pod from it."""

    def __init__(self, path: Path):
        self.path = path

    def list(self) -> list[dict]:
        return read_json(self.path, [])

    def delete(self, pod_id: str) -> tuple[bool, str]:
        pods = self.list()
        write_json(self.path, [p for p in pods if p.get("id") != pod_id])
        return True, "fake delete"


def run_shell(cmd: str, timeout: float) -> tuple[int, str]:
    try:
        cp = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return cp.returncode, (cp.stdout or "") + (cp.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def parse_probe(out: str) -> tuple[list[str], int, int]:
    jobs = [l.split(None, 1)[1] for l in out.splitlines() if l.startswith("JOB ") and len(l.split()) > 1]
    gpu = re.search(r"^GPU (\d+)", out, re.M)
    apps = re.search(r"^APPS (\d+)", out, re.M)
    if not gpu or not apps:
        raise ValueError("probe output without GPU/APPS lines")
    return jobs, int(gpu.group(1)), int(apps.group(1))


class Watchdog:
    def __init__(self, state: Path, log: Callable[[str], None], *, dry_run: bool = False,
                 listers: list[Callable[[], list[dict]]] | None = None, real_delete=runpod_delete,
                 fake: FakePods | None = None, shell=run_shell, now: Callable[[], float] = time.time,
                 idle_s: float = 900, probe_s: float = 60, beat_s: float = 60, own_id: str | None = None,
                 copy_timeout_s: float = 600, probe_timeout_s: float = 90):
        self.state, self.log, self.dry, self.now, self.shell = state, log, dry_run, now, shell
        self.fake = fake
        self.listers = listers if listers is not None else [runpod_list] + ([fake.list] if fake else [])
        self.real_delete = real_delete
        self.idle_s, self.probe_s, self.beat_s = idle_s, probe_s, beat_s
        self.own_id = own_id
        self.copy_timeout_s, self.probe_timeout_s = copy_timeout_s, probe_timeout_s
        (state / "pods").mkdir(parents=True, exist_ok=True)
        self.seen: dict[str, dict] = read_json(state / "seen.json", {})
        self.idle_since: dict[str, float] = {}
        self.last_probe: dict[str, float] = {}
        self.copy_tries: dict[str, int] = {}
        self.would_delete: set[str] = set()
        self.closed: set[str] = set()
        self.idle_since = {k: v["idle_since"] for k, v in self.seen.items() if v.get("idle_since") and not v.get("gone")}
        self.last_beat = -1e18
        self.list_errors = 0

    # state
    def batch(self) -> dict:
        b = read_json(self.state / "batch.json", {})
        return {"batch_id": b.get("batch_id", "none"), "gpu_cap_usd": float(b.get("gpu_cap_usd", 0) or 0),
                "default_cap_usd": float(b.get("default_cap_usd", 4.0) or 4.0),
                "default_cap_min": float(b.get("default_cap_min", 60) or 60)}

    def registry(self, name: str) -> dict:
        return read_json(self.state / "pods" / f"{name}.json", {})

    def ledger_usd(self, batch_id: str) -> float:
        total = 0.0
        try:
            for line in (self.state / "ledger.jsonl").read_text().splitlines():
                r = json.loads(line)
                if r.get("batch_id") == batch_id:
                    total += float(r.get("usd") or 0)
        except (OSError, json.JSONDecodeError):
            pass
        return total

    def ledger_add(self, rec: dict) -> None:
        with open(self.state / "ledger.jsonl", "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    def save_idle(self, pid: str) -> None:
        self.seen.setdefault(pid, {})["idle_since"] = self.idle_since.get(pid)
        write_json(self.state / "seen.json", self.seen)

    # actions
    def delete(self, pod: dict) -> bool:
        pid = str(pod["id"])
        if pod.get("_fake"):
            ok, msg = self.fake.delete(pid)
            self.log(f"{'would delete (fake pod removed from the fake list)' if self.dry else 'fake delete'} {pid} ({pod['name']})")
            return ok
        if self.dry:
            if pid not in self.would_delete:
                self.would_delete.add(pid)
                self.log(f"would delete {pid} ({pod['name']}) [dry run]")
            return False
        ok, msg = self.real_delete(pid)
        self.log(f"DELETE {pid} ({pod['name']}): {'ok' if ok else 'FAILED ' + msg}")
        return ok

    def close(self, pod: dict, why: str, idle: bool) -> None:
        name, pid = pod["name"], str(pod["id"])
        if pid in self.closed or (self.dry and not pod.get("_fake") and pid in self.would_delete):
            return                  # deleted already (still in the listing), or its dry-run line is written
        reg = self.registry(name)
        cmd = reg.get("copy_cmd")
        if cmd:
            self.log(f"close {pid} ({name}): {why}; copy start")
            rc, out = self.shell(cmd, self.copy_timeout_s)
            tries = self.copy_tries.get(pid, 0) + 1
            self.copy_tries[pid] = tries
            if rc == 0:
                self.log(f"close {pid} ({name}): copy verified")
            else:
                self.log(f"close {pid} ({name}): copy FAILED rc={rc} (try {tries}): {out.strip()[-200:]}")
                if idle and tries < IDLE_COPY_TRIES:
                    return          # an idle close retries the copy on the next poll
        else:
            self.log(f"close {pid} ({name}): {why}; no copy_cmd registered")
        if self.delete(pod):
            self.closed.add(pid)
            self.seen.setdefault(pid, {})["closed_by"] = why

    def probe_idle(self, pod: dict, now: float) -> bool:
        """True when the pod has been idle for idle_s (probes every probe_s; a failed probe resets nothing and counts
        as busy)."""
        pid = str(pod["id"])
        cmd = self.registry(pod["name"]).get("probe_cmd")
        if not cmd or now - self.last_probe.get(pid, -1e18) < self.probe_s:
            return pid in self.idle_since and now - self.idle_since[pid] >= self.idle_s
        self.last_probe[pid] = now
        rc, out = self.shell(cmd, self.probe_timeout_s)
        try:
            if rc != 0:
                raise ValueError(f"rc={rc}")
            jobs, gpu, apps = parse_probe(out)
        except ValueError as e:
            self.log(f"probe {pid} ({pod['name']}) failed ({e}); not counted as idle")
            self.idle_since.pop(pid, None)
            return False
        if jobs or gpu > 0 or apps > 0:
            if pid in self.idle_since:
                self.log(f"{pid} ({pod['name']}) busy again: jobs {jobs}, GPU {gpu}, apps {apps}")
                self.idle_since.pop(pid, None)
                self.save_idle(pid)
            return False
        if pid not in self.idle_since:
            self.idle_since[pid] = now
            self.save_idle(pid)                # at once: a restart right after must keep this clock (2026-10-26 test)
            self.log(f"{pid} ({pod['name']}) idle from now (no job, GPU 0, no compute process)")
        return now - self.idle_since[pid] >= self.idle_s

    def poll_once(self) -> None:
        now = self.now()
        pods: list[dict] = []
        try:
            for lister in self.listers:
                got = lister()
                if self.fake and lister == self.fake.list:
                    got = [dict(p, _fake=True) for p in got]
                pods += got
        except ListingError as e:
            self.list_errors += 1
            self.log(f"list error (not counted as gone): {e}")
            return
        except Exception as e:          # a lister bug must not stop the watchdog
            self.list_errors += 1
            self.log(f"list error (not counted as gone): {type(e).__name__}: {e}")
            return
        b = self.batch()
        live = [p for p in pods if str(p.get("name") or "").startswith(NAME_PREFIX) and str(p.get("id")) != self.own_id]
        live_ids = {str(p["id"]) for p in live}
        live_usd = 0.0
        for p in live:
            pid = str(p["id"])
            created = parse_time(p.get("createdAt")) or now
            rate = float(p.get("costPerHr") or DEFAULT_RATE)
            age = max(0.0, now - created)
            p["_age"], p["_usd"] = age, age * rate / 3600
            live_usd += p["_usd"]
            s = self.seen.setdefault(pid, {"name": p["name"], "batch_id": b["batch_id"], "fake": bool(p.get("_fake"))})
            s.update(last_usd=round(p["_usd"], 4), last_seen=now, misses=0, rate=rate)
        for pid, s in list(self.seen.items()):        # pods that left the listing
            if pid in live_ids or s.get("gone"):
                continue
            s["misses"] = s.get("misses", 0) + 1
            if s["misses"] >= GONE_AFTER:
                s["gone"] = now
                s["idle_since"] = None
                self.idle_since.pop(pid, None)
                rec = {"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "batch_id": s.get("batch_id"),
                       "pod_id": pid, "name": s.get("name"), "usd": s.get("last_usd", 0.0),
                       "closed_by": s.get("closed_by", "not the watchdog"), "fake": s.get("fake", False)}
                self.ledger_add(rec)
                self.log(f"gone {pid} ({s.get('name')}): ${rec['usd']:.2f}, closed by {rec['closed_by']}")
        for pid in live_ids:
            self.seen[pid]["idle_since"] = self.idle_since.get(pid)   # an idle clock survives a restart
        write_json(self.state / "seen.json", self.seen)
        # pods that left the listing but are not in the ledger yet (3 listings) count at their last cost (2026-10-26:
        # leaving them out undercounted the batch for about 90 s after each delete)
        pending = sum(float(s.get("last_usd") or 0) for k, s in self.seen.items()
                      if k not in live_ids and not s.get("gone") and s.get("batch_id") == b["batch_id"])
        spend = self.ledger_usd(b["batch_id"]) + live_usd + pending
        over_batch = b["gpu_cap_usd"] > 0 and spend >= b["gpu_cap_usd"]
        if over_batch and not (self.state / "STOP").exists():
            (self.state / "STOP").write_text(f"batch GPU spend ${spend:.2f} reached the cap ${b['gpu_cap_usd']:.2f} "
                                             f"at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))}\n")
            self.log(f"BATCH CAP: ${spend:.2f} >= ${b['gpu_cap_usd']:.2f}; STOP written; closing every live pod")
        for p in live:
            pid, reg = str(p["id"]), self.registry(p["name"])
            cap_usd = float(reg.get("cap_usd") or b["default_cap_usd"])
            cap_min = float(reg.get("cap_min") or b["default_cap_min"])
            if not reg:
                self.seen[pid].setdefault("unregistered_logged", False)
                if not self.seen[pid]["unregistered_logged"]:
                    self.seen[pid]["unregistered_logged"] = True
                    self.log(f"UNREGISTERED pod {pid} ({p['name']}): batch defaults ${cap_usd:.2f} / {cap_min:g} min")
            if over_batch:
                self.close(p, "batch cap", idle=False)
            elif p["_usd"] >= cap_usd or p["_age"] >= cap_min * 60:
                self.close(p, f"pod cap (${p['_usd']:.2f} of ${cap_usd:.2f}, {p['_age'] / 60:.1f} of {cap_min:g} min)", idle=False)
            elif self.probe_idle(p, now):
                self.close(p, f"idle {self.idle_s / 60:g} min", idle=True)
        if now - self.last_beat >= self.beat_s:
            self.last_beat = now
            self.log(f"beat: {len(pods)} listed, {len(live)} p6 live, batch {b['batch_id']} ${spend:.2f} of "
                     f"${b['gpu_cap_usd']:.2f}{' STOP' if (self.state / 'STOP').exists() else ''}; idle "
                     + (", ".join(f"{k} {now - v:.0f}s" for k, v in self.idle_since.items()) or "none")
                     + (" [dry run]" if self.dry else ""))


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="fleet_watchdog")
    ap.add_argument("state", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fake-pods", type=Path, default=None)
    ap.add_argument("--poll-s", type=float, default=30)
    ap.add_argument("--idle-s", type=float, default=900)
    ap.add_argument("--probe-s", type=float, default=60)
    ap.add_argument("--beat-s", type=float, default=60)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    a.state.mkdir(parents=True, exist_ok=True)

    def log(m: str) -> None:
        with open(a.state / "watchdog.log", "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {m}\n")

    def on_term(signum, frame):
        log(f"watchdog stopped by signal {signum}")
        sys.exit(0)
    signal.signal(signal.SIGTERM, on_term)
    fake = FakePods(a.fake_pods) if a.fake_pods else None
    own = own_pod_id()
    w = Watchdog(a.state, log, dry_run=a.dry_run, fake=fake, idle_s=a.idle_s, probe_s=a.probe_s, beat_s=a.beat_s,
                 own_id=own)
    log(f"watchdog start (pid {os.getpid()}): own pod {own}, poll {a.poll_s:g} s, idle {a.idle_s:g} s"
        + (", fake pods " + str(a.fake_pods) if fake else "") + (", DRY RUN" if a.dry_run else ""))
    while True:
        try:
            w.poll_once()
        except Exception as e:      # log and keep polling; the restart loop covers a crash outside this
            log(f"poll error {type(e).__name__}: {str(e)[:200]}")
        time.sleep(a.poll_s)


if __name__ == "__main__":
    sys.exit(main())
