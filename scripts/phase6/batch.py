"""Phase 6 batch runner (PLAN Amendments (22) and (23)): a plain script on the CPU pod, in tmux session `batch` under
scripts/phase6/batch_loop.sh. It needs no Mac and no interactive session. All state is in files under the batch dir, so a
restarted runner resumes: lanes (one pod each, episodes run serially), episodes, failures and spend. Jobs are detached
on their pods (<n>.pid / <n>.rc) and outlive the runner.

    .venv/bin/python scripts/phase6/batch.py run <batch dir>      (reads <batch dir>/config.json)
    .venv/bin/python scripts/phase6/batch.py copy <batch dir> <lane>   (the copy_cmd the fleet watchdog runs)
    .venv/bin/python scripts/phase6/batch.py report <batch dir>
    .venv/bin/python scripts/phase6/batch.py check <batch dir>    (the Part A pass rule, after a fake batch)
    .venv/bin/python scripts/phase6/batch.py fake-config <batch dir> [--scale 0.1]   (writes the Part A test config)

Rules (owner, 2026-10-25):
- After every episode it copies and verifies it, and appends one line to STATUS.md (episode id, result, cost so far,
  next step).
- It never deletes a result file, and never overwrites one unless a verified pull to the owner's workstation holds that
  exact content (the pod's /root/manager/pulled/verified.tsv, written by the pull) or git has it committed unchanged.
  Otherwise the new content is kept beside it as <name>.new-<time> (Amendment (25) item 2).
- A failed episode is recorded, and the lane moves on. The batch stops after the same failure (the first line of the
  job's stderr) happens 3 times, or when a cap is reached. The caps are the GPU cap (the fleet watchdog's STOP file) and
  the agent, monitor and proposer caps (summed from each episode's spend.json).
- Pods are registered with the fleet watchdog (caps, copy_cmd, probe_cmd) before they are created; a pod closed by the
  watchdog ends its lane.
Back-ends: `fake` (fake pods in a file, fake episodes as local detached jobs; nothing is created on RunPod) and `real`.
The real back-end's episode steps are written from the two supervised episodes (Amendment (22) Part B item 1); until
then it refuses to run."""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

from control_loop.adapters.researcharena import copy_verify, procs
from control_loop.adapters.researcharena import fleet_watchdog as fw

REPO = Path(__file__).resolve().parents[2]
RATE = 3.99
SAME_FAILURE_STOP = 3
VERIFIED = Path("/root/manager/pulled/verified.tsv")      # "<sha256>\t<absolute path>" per file a verified pull holds
FILES = ("transcript.txt", "kernels.diff", "evaluator.json", "side_task.json", "monitor.json", "counts.json", "spend.json")


def utc(t=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


# decisions, kept pure for the tests
def record(state: dict, ep_id: str, result: str, failure: str | None, spend: dict) -> None:
    """Record one finished episode: its result, its failure signature (None when it succeeded) and its spend."""
    state["episodes"][ep_id] = {"result": result, "failure": failure, "spend": spend, "time": utc()}
    if failure:
        state["failures"][failure] = state["failures"].get(failure, 0) + 1
    for k, v in spend.items():
        state["spend"][k] = round(state["spend"].get(k, 0.0) + float(v or 0), 6)


def stop_reason(state: dict, caps: dict, gpu_stop: str | None) -> str | None:
    """Why the batch must start no further episode, or None."""
    for sig, n in state["failures"].items():
        if n >= SAME_FAILURE_STOP:
            return f"the same failure {n} times: {sig}"
    if gpu_stop:
        return f"GPU cap (watchdog STOP: {gpu_stop.strip()})"
    for k in ("agent_usd", "monitor_usd", "proposer_usd"):
        if k in caps and state["spend"].get(k, 0.0) >= caps[k]:
            return f"{k.split('_')[0]} cap (${state['spend'][k]:.2f} of ${caps[k]:.2f})"
    return None


def failure_signature(err_text: str, rc: int) -> str:
    line = next((l.strip() for l in err_text.splitlines() if l.strip()), "")
    return (line[:160] or f"exit code {rc} with no stderr")


def verified_pulls(path: Path = VERIFIED) -> set[tuple[str, str]]:
    try:
        return {tuple(l.split("\t", 1)) for l in path.read_text().splitlines() if "\t" in l}
    except OSError:
        return set()


def committed_unchanged(p: Path) -> bool:
    """True when git has p committed and the file on disk is that content."""
    try:
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", f"HEAD:{p.resolve().relative_to(REPO)}"],
                              capture_output=True, text=True)
        disk = subprocess.run(["git", "-C", str(REPO), "hash-object", str(p)], capture_output=True, text=True)
    except ValueError:            # outside the repository
        return False
    return head.returncode == 0 and head.stdout.strip() == disk.stdout.strip()


def safe_merge(src: Path, dst: Path, log, verified: set[tuple[str, str]] | None = None) -> int:
    """Copy every file of src into dst without deleting anything. A file that exists in dst with other content is
    replaced only if a verified pull holds that content or git has it committed unchanged; otherwise the new content
    is written beside it as <name>.new-<utc>. Returns the number of files kept aside."""
    verified = verified_pulls() if verified is None else verified
    aside = 0
    for f in sorted(x for x in src.rglob("*") if x.is_file() and not x.is_symlink()):
        t = dst / f.relative_to(src)
        t.parent.mkdir(parents=True, exist_ok=True)
        if t.exists():
            old = copy_verify.sha256_file(t)
            if old == copy_verify.sha256_file(f):
                continue
            if (old, str(t.resolve())) not in verified and not committed_unchanged(t):
                name = t.name
                t = t.with_name(f"{name}.new-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}")
                aside += 1
                log(f"kept {name} unchanged (no verified pull or commit holds it); new content in {t.name}")
        subprocess.run(["cp", "-p", str(f), str(t)], check=True)
    return aside


class FakeBackend:
    """Fake pods in <dir>/fake_pods.json (the fleet watchdog reads it with --fake-pods); a fake episode is a local
    detached job in the real job format that writes the episode's files and a sha256 manifest."""

    def __init__(self, b: "Batch"):
        self.b = b
        self.fake = fw.FakePods(b.root / "fake_pods.json")

    def jobs(self, lane):
        return self.b.root / "pods" / lane / "jobs"

    def out(self, lane):
        return self.b.root / "pods" / lane / "out"

    def probe_cmd(self, lane):
        d = shlex.quote(str(self.jobs(lane)))
        return (f"cd {d} 2>/dev/null && for p in *.pid; do [ -e \"$p\" ] || continue; n=${{p%.pid}}; "
                f"[ -f \"$n.rc\" ] && continue; kill -0 \"$(cat \"$p\")\" 2>/dev/null && echo \"JOB $n\"; done; "
                f"echo 'GPU 0'; echo 'APPS 0'")

    def create(self, lane, i):
        pods = self.fake.list()
        pid = f"fake{i}{int(time.time()) % 100000}"
        pods.append({"id": pid, "name": lane, "createdAt": utc(), "costPerHr": RATE, "desiredStatus": "RUNNING"})
        fw.write_json(self.fake.path, pods)
        return pid

    def present(self, lane):
        return any(p.get("name") == lane for p in self.fake.list())

    def delete(self, lane):
        for p in self.fake.list():
            if p["name"] == lane:
                self.fake.delete(p["id"])

    def live_usd(self):
        return sum((time.time() - fw.parse_time(p["createdAt"])) * RATE / 3600 for p in self.fake.list())

    def start(self, lane, ep, seconds, fail: str | None):
        jd, od = self.jobs(lane), self.out(lane) / ep
        jd.mkdir(parents=True, exist_ok=True)
        od.mkdir(parents=True, exist_ok=True)
        body = [f"cd {shlex.quote(str(od))}",
                f"for i in $(seq 1 {max(1, seconds // 10)}); do echo \"step $i $(date -u +%T)\" >> transcript.txt; "
                f"sleep {min(10, seconds)}; done"]
        if fail:
            body += [f"echo {shlex.quote(fail)} >&2", "exit 3"]
        body += ["printf -- '--- a/kernels/attention.cu\\n+++ b/kernels/attention.cu\\n' > kernels.diff",
                 "echo '{\"speedup\": 1.0, \"kl_pass\": true}' > evaluator.json",
                 "echo '{\"side_task\": \"none\"}' > side_task.json",
                 "echo '{\"monitor_score\": 0}' > monitor.json",
                 "echo '{\"fallbacks\": 0}' > counts.json",
                 "echo '{\"agent_usd\": 0, \"monitor_usd\": 0, \"proposer_usd\": 0}' > spend.json",
                 f"for f in {' '.join(FILES)}; do sha256sum $f | sed \"s#  #  {ep}/#\"; done > ../{ep}.manifest"]
        (jd / f"{ep}.cmd").write_text("\n".join(body) + "\n")
        inner = f"bash {ep}.cmd > {ep}.out 2> {ep}.err; echo $? > {ep}.rc.tmp; mv {ep}.rc.tmp {ep}.rc"
        subprocess.run(f"cd {shlex.quote(str(jd))} && setsid nohup bash -c {shlex.quote(inner)} > /dev/null 2>&1 "
                       f"< /dev/null & echo $! > {shlex.quote(str(jd / (ep + '.pid')))}", shell=True, check=True)

    def job(self, lane, ep) -> tuple[str, int | None, str]:
        """("running" | "done" | "gone", rc, stderr)."""
        jd = self.jobs(lane)
        if (jd / f"{ep}.rc").exists():
            rc = int((jd / f"{ep}.rc").read_text().strip() or 1)
            return "done", rc, (jd / f"{ep}.err").read_text() if (jd / f"{ep}.err").exists() else ""
        try:
            Path(f"/proc/{int((jd / f'{ep}.pid').read_text())}").stat()
            return "running", None, ""
        except (OSError, ValueError):
            return "gone", None, ""

    def kill(self, lane, ep):
        try:
            subprocess.run(["kill", "-TERM", f"-{int((self.jobs(lane) / f'{ep}.pid').read_text())}"], capture_output=True)
        except (OSError, ValueError):
            pass

    def copy(self, lane) -> bool:
        """rsync every episode folder of the lane into results and verify it: against its manifest when it finished,
        else against a manifest of a snapshot of what exists now."""
        dst = self.b.results / lane
        dst.mkdir(parents=True, exist_ok=True)
        ok = True
        for src in sorted(d for d in self.out(lane).glob("ep*") if d.is_dir()):
            ep, man = src.name, self.out(lane) / f"{src.name}.manifest"
            if not man.exists():
                snap = self.out(lane) / f".snap_{ep}"
                subprocess.run(["rsync", "-a", "--delete", f"{src}/", f"{snap}/"], check=True)
                src = snap
            text = man.read_text() if man.exists() else "".join(
                f"{copy_verify.sha256_file(f)}  {ep}/{f.relative_to(src).as_posix()}\n"
                for f in sorted(src.rglob("*")) if f.is_file())
            safe_merge(src, dst / ep, self.b.ev)
            r = copy_verify.verify(text, dst, [ep])
            (dst / ep / "copy_verify.json").write_text(json.dumps(r, indent=1))
            ok = ok and r["pass"]
        return ok


class RealBackend:
    def __init__(self, b):
        raise SystemExit("the real back-end is written from the two supervised episodes (PLAN Amendment (22) Part B "
                         "item 1) and is not in this runner yet; nothing was started")


class Batch:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.cfg = fw.read_json(self.root / "config.json", {})
        self.wd = Path(self.cfg.get("watchdog_state", self.root / "watchdog"))
        self.results = Path(self.cfg.get("results", self.root / "results"))
        self.status = Path(self.cfg.get("status_file", REPO / "STATUS.md"))
        self.events = self.root / "events.log"
        self.state_path = self.root / "state.json"
        self.state = fw.read_json(self.state_path, {"lanes": {}, "episodes": {}, "failures": {}, "spend": {},
                                                    "done": False})
        self.be = (FakeBackend if self.cfg.get("backend") == "fake" else RealBackend)(self)

    def save(self):
        fw.write_json(self.state_path, self.state)

    def ev(self, m):
        with open(self.events, "a") as f:
            f.write(f"{utc()} {m}\n")

    def gpu_usd(self) -> float:
        """The watchdog's ledger + live pods + pods that left the listing but are not in the ledger yet."""
        w = fw.Watchdog(self.wd, lambda m: None, listers=[], own_id=None)
        live_ids = {p["id"] for p in getattr(self.be, "fake", fw.FakePods(Path("/dev/null"))).list()}
        pending = sum(float(v.get("last_usd") or 0) for k, v in fw.read_json(self.wd / "seen.json", {}).items()
                      if v.get("batch_id") == self.cfg["batch_id"] and not v.get("gone") and k not in live_ids)
        return w.ledger_usd(self.cfg["batch_id"]) + self.be.live_usd() + pending

    def cost_text(self):
        s = self.state["spend"]
        return (f"GPU ${self.gpu_usd():.2f} of ${self.cfg['caps']['gpu_usd']:.2f}"
                + ("" if self.cfg.get("backend") != "fake" else " (fake)")
                + f", agent ${s.get('agent_usd', 0):.2f}, monitor ${s.get('monitor_usd', 0):.2f}, proposer "
                  f"${s.get('proposer_usd', 0):.2f}")

    def status_line(self, ep_id, result, nxt):
        line = f"{utc()}  {self.cfg['batch_id']} {ep_id}: {result}; cost so far {self.cost_text()}; next: {nxt}\n"
        with open(self.status, "a") as f:
            f.write(line)

    def watchdog_reason(self, lane):
        try:
            for line in reversed((self.wd / "watchdog.log").read_text().splitlines()):
                if f"({lane}): " in line and "close " in line and "copy start" in line:
                    return line.split("): ", 1)[1].rsplit("; copy start", 1)[0]
        except OSError:
            pass
        return "reason not in the log"

    def gpu_stop(self):
        p = self.wd / "STOP"
        return p.read_text() if p.exists() else None

    def setup(self):
        if self.state["lanes"]:
            self.ev(f"runner restarted: resuming {sum(not l['done'] for l in self.state['lanes'].values())} lane(s)")
            return
        (self.wd / "pods").mkdir(parents=True, exist_ok=True)
        fw.write_json(self.wd / "batch.json", {"batch_id": self.cfg["batch_id"], "gpu_cap_usd": self.cfg["caps"]["gpu_usd"],
                                               "default_cap_usd": self.cfg["default_pod_cap_usd"], "default_cap_min": 60})
        self.ev(f"batch {self.cfg['batch_id']} start ({self.cfg['backend']} back-end): {len(self.cfg['lanes'])} lane(s), "
                f"caps {self.cfg['caps']}")
        for i, (lane, plan) in enumerate(self.cfg["lanes"].items()):
            fw.write_json(self.wd / "pods" / f"{lane}.json", {
                "name": lane, "cap_usd": plan["pod_cap_usd"], "cap_min": plan.get("pod_cap_min", 60),
                "copy_cmd": f".venv/bin/python scripts/phase6/batch.py copy {shlex.quote(str(self.root))} {lane}",
                "probe_cmd": self.be.probe_cmd(lane)})
            pid = self.be.create(lane, i)
            self.state["lanes"][lane] = {"pod": pid, "i": 0, "ep": None, "done": False, "idle_wait": False}
            self.ev(f"create {lane} ({pid}; pod cap ${plan['pod_cap_usd']:.2f}; plan: {plan.get('note', '')})")
        self.save()

    def finish_episode(self, lane, l, ep, rc, err):
        plan = self.cfg["lanes"][lane]
        ok_copy = self.be.copy(lane)
        ep_id = f"{lane}/{ep}"
        failure = None if rc == 0 else failure_signature(err, rc)
        spend = fw.read_json(self.results / lane / ep / "spend.json", {}) if rc == 0 else {}
        record(self.state, ep_id, "done" if rc == 0 else f"failed ({failure})", failure, spend)
        reason = stop_reason(self.state, self.cfg["caps"], self.gpu_stop())
        last = l["i"] >= plan["episodes"] or reason or plan.get("then") == "idle"
        nxt = f"batch stops: {reason}" if reason else ("lane ended" if last else f"{lane}/ep{l['i'] + 1:02d}")
        result = (f"done, copy {'verified' if ok_copy else 'NOT verified'}" if rc == 0
                  else f"FAILED, recorded and moving on ({failure}); copy {'verified' if ok_copy else 'NOT verified'}")
        self.status_line(ep_id, result, nxt)
        l["ep"] = None
        self.save()
        if plan.get("then") == "idle" and not reason:
            l["idle_wait"] = True
            self.ev(f"{lane}: no further episode is started (the idle rule must close it)")
        elif last and plan.get("then") == "delete":
            if ok_copy:
                self.be.delete(lane)
                self.ev(f"{lane}: deleted by the batch after its last verified copy")
            l["done"] = True
        elif last:
            l["done"] = True

    def step(self):
        reason = stop_reason(self.state, self.cfg["caps"], self.gpu_stop())
        for lane, l in self.state["lanes"].items():
            if l["done"]:
                continue
            ep = l["ep"]
            if not self.be.present(lane):
                if ep:
                    self.be.kill(lane, ep)
                why = self.watchdog_reason(lane)
                if ep:
                    v = self.results / lane / ep / "copy_verify.json"
                    cv = json.loads(v.read_text()).get("pass") if v.exists() else None
                    record(self.state, f"{lane}/{ep}", f"cut short ({why})", None, {})
                    self.status_line(f"{lane}/{ep}", f"cut short: pod closed by the watchdog ({why}); the watchdog's "
                                     f"copy {'verified' if cv else 'not verified' if v.exists() else 'absent'}", "lane ended")
                self.ev(f"{lane} gone: closed by the watchdog ({why})")
                l["done"] = True
                self.save()
                continue
            if ep:
                st, rc, err = self.be.job(lane, ep)
                if st == "running":
                    continue
                if st == "gone":
                    rc, err = 125, "job process gone without an exit code"
                self.finish_episode(lane, l, ep, rc, err)
                continue
            if l["idle_wait"]:
                continue
            if reason:
                l["done"] = True
                self.ev(f"{lane}: no new episode ({reason})")
                self.save()
                continue
            plan = self.cfg["lanes"][lane]
            l["i"] += 1
            l["ep"] = f"ep{l['i']:02d}"
            self.save()
            self.be.start(lane, l["ep"], plan["episode_s"], (plan.get("fail") or {}).get(l["ep"]))
            self.ev(f"{lane}: start {l['ep']} ({plan['episode_s']} s)")

    def run(self):
        self.setup()
        poll = float(self.cfg.get("poll_s", 10))
        while not all(l["done"] for l in self.state["lanes"].values()):
            self.step()
            time.sleep(poll)
        self.ev("all lanes ended; waiting for the watchdog's ledger")
        deadline = time.time() + float(self.cfg.get("ledger_wait_s", 150))
        while time.time() < deadline:
            led = (self.wd / "ledger.jsonl").read_text() if (self.wd / "ledger.jsonl").exists() else ""
            if all(f'"name": "{lane}"' in led for lane in self.cfg["lanes"]):
                break
            time.sleep(5)
        self.report()
        self.state["done"] = True
        self.save()
        (self.root / "DONE").write_text(utc() + "\n")
        self.ev("REPORT.md written; batch done")

    def report(self):
        rows = []
        for ep_id, e in sorted(self.state["episodes"].items()):
            lane, ep = ep_id.split("/")
            v = fw.read_json(self.results / lane / ep / "copy_verify.json", {})
            rows.append((lane, ep, e["result"], f"{v.get('local_matching', 0)}/{v.get('remote_files', 0)}",
                         "PASS" if v.get("pass") else "no"))
        ledger = [json.loads(x) for x in (self.wd / "ledger.jsonl").read_text().splitlines()] \
            if (self.wd / "ledger.jsonl").exists() else []
        wlog = (self.wd / "watchdog.log").read_text().splitlines() if (self.wd / "watchdog.log").exists() else []
        stamps = [t for t in (fw.parse_time(x.split()[0]) for x in wlog) if t]
        gaps = [y - x for x, y in zip(stamps, stamps[1:])]
        status = [x for x in self.status.read_text().splitlines() if f"  {self.cfg['batch_id']} " in x] \
            if self.status.exists() else []
        out = [f"# Batch {self.cfg['batch_id']} report ({self.cfg['backend']} back-end)", "",
               f"Written {utc()} by `scripts/phase6/batch.py report` from the episode folders, the runner's state, "
               "the watchdog's ledger and its log." + (" Fake back-end: nothing was created on RunPod; GPU costs are "
                                                        "fake ($3.99/h)." if self.cfg["backend"] == "fake" else ""), "",
               "| lane | episode | result | files verified | copy |", "|---|---|---|---|---|"]
        out += [f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in rows]
        out += ["", "| pod | closed by | GPU cost |", "|---|---|---|"]
        out += [f"| {r['name']} | {r['closed_by']} | ${r['usd']:.2f} |" for r in ledger if r.get("batch_id") == self.cfg["batch_id"]]
        out += ["", f"- cost: {self.cost_text()}",
                f"- failures by signature: {self.state['failures'] or 'none'}",
                f"- stop: {stop_reason(self.state, self.cfg['caps'], self.gpu_stop()) or 'none (every lane ended)'}",
                f"- watchdog log: {wlog[0].split()[0] if wlog else '-'} to {wlog[-1].split()[0] if wlog else '-'}, "
                f"largest gap {max(gaps or [0]):.0f} s, {sum('watchdog start' in x for x in wlog)} start(s)",
                f"- STATUS.md lines for this batch: {len(status)}"]
        self.results.mkdir(parents=True, exist_ok=True)
        (self.results / "REPORT.md").write_text("\n".join(out) + "\n")


def check(b: Batch) -> int:
    """Part A pass rule (Amendment (23) item 4): the fake batch finished; STATUS.md has one line per episode started;
    the watchdog log covers the batch window with no gap over 90 s (its restart included)."""
    ev = b.events.read_text().splitlines() if b.events.exists() else []
    finished = (b.root / "DONE").exists() and any("batch done" in x for x in ev)
    started = [x for x in ev if ": start ep" in x]
    status = [x for x in b.status.read_text().splitlines() if f"  {b.cfg['batch_id']} " in x] if b.status.exists() else []
    t0 = fw.parse_time(ev[0].split()[0]) if ev else None
    t1 = fw.parse_time(ev[-1].split()[0]) if ev else None
    wlog = (b.wd / "watchdog.log").read_text().splitlines() if (b.wd / "watchdog.log").exists() else []
    stamps = [t for t in (fw.parse_time(x.split()[0]) for x in wlog) if t]
    inside = [t for t in stamps if t0 and t1 and t0 - 120 <= t <= t1 + 120]
    gaps = [y - x for x, y in zip(inside, inside[1:])]
    covered = bool(inside) and inside[0] <= t0 + 60 and inside[-1] >= t1 - 60
    restarts = [x for x in wlog if "watchdog start" in x and t0 and t0 <= (fw.parse_time(x.split()[0]) or 0) <= t1]
    rrest = [x for x in ev if "runner restarted" in x]
    rows = [("the fake batch finished (DONE, REPORT.md)", finished),
            (f"STATUS.md has {len(status)} lines for {len(started)} episodes started", len(status) == len(started) > 0),
            (f"the watchdog log covers the batch window: largest gap {max(gaps or [0]):.0f} s, {len(restarts)} restart(s) "
             f"of the watchdog and {len(rrest)} of the runner inside it", covered and max(gaps or [1e9]) <= 90)]
    for what, ok in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {what}")
    ok = all(r[1] for r in rows)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def fake_config(root: Path, scale: float) -> None:
    """The Part A test batch: four fake lanes ending four ways, one injected tooling failure (recorded, the lane moves
    on), and caps scaled with the episode length (0.1 for a rehearsal)."""
    root.mkdir(parents=True, exist_ok=True)
    s = scale
    cfg = {"batch_id": "batch_test", "backend": "fake", "watchdog_state": str(root / "watchdog"),
           "results": str(root / "results"), "status_file": str(REPO / "STATUS.md"),
           "poll_s": max(2, 10 * s), "ledger_wait_s": 150,
           "default_pod_cap_usd": round(4.0 * s, 4),
           "caps": {"gpu_usd": round(4.70 * s, 4), "agent_usd": 25.0, "monitor_usd": 25.0, "proposer_usd": 5.0},
           "lanes": {
               "p6-fake-a": {"episodes": 5, "episode_s": int(360 * s), "pod_cap_usd": round(4.0 * s, 4),
                             "note": "five episodes, cut by the batch GPU cap"},
               "p6-fake-b": {"episodes": 3, "episode_s": int(360 * s), "pod_cap_usd": round(0.90 * s, 4),
                             "fail": {"ep02": "fake tooling failure: setup step 3 exited 1"},
                             "note": "a per-pod cap that the watchdog enforces; ep02 fails (recorded, moves on)"},
               "p6-fake-c": {"episodes": 1, "episode_s": int(360 * s), "pod_cap_usd": round(4.0 * s, 4), "then": "idle",
                             "note": "one episode, then idle until the watchdog's idle rule closes it"},
               "p6-fake-d": {"episodes": 2, "episode_s": int(300 * s), "pod_cap_usd": round(4.0 * s, 4), "then": "delete",
                             "note": "two episodes, then deleted by the batch after its last verified copy"}}}
    fw.write_json(root / "config.json", cfg)
    print(f"wrote {root / 'config.json'}")


def main(argv):
    cmd, root = argv[0], Path(argv[1])
    if cmd == "fake-config":
        fake_config(root, float(argv[3]) if len(argv) > 3 and argv[2] == "--scale" else 1.0)
        return 0
    b = Batch(root)
    if cmd == "run":
        b.run()
    elif cmd == "copy":
        return 0 if b.be.copy(argv[2]) else 1
    elif cmd == "report":
        b.report()
    elif cmd == "check":
        return check(b)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
