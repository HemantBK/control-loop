"""Idle guard for the last Phase 6 pod (PLAN Amendment (21) item 6; owner, 2026-10-24): every 60 s, over ssh, read the
running steps (a log without an exit-code file), the GPU's utilisation and its compute processes. The pod is idle when no step is running, utilisation is 0 and there are no compute processes. After
15 minutes idle: run the runner's copy step (verified), then its delete step, and exit. A failed ssh read is not counted
as idle. Exits when the pod is gone.
    uv run --frozen --env-file ../.env python scripts/phase6/idle_guard.py <out dir> <log file>      (P6_RM_* env as the runner)"""
import json, os, subprocess, sys, time

OUT, LOG = sys.argv[1], sys.argv[2]
IDLE_S, POLL_S = 900, 60
SHELLS = {"bash", "sh", "zsh", "dash"}


def log(m):
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {m}\n")


def state():
    p = json.load(open(f"{OUT}/state.json"))
    return p


def probe(p):
    # 2026-10-24: a job is running while a step started by p6pod.sh has a log but no exit-code file. The pane's command
    # cannot tell: every step runs inside a bash subshell, so it always reads "bash" (the first final pod was deleted
    # during a running step for that reason).
    cmd = ("cd /workspace/remeasure/logs 2>/dev/null && for f in *.log; do [ -e \"$f\" ] && [ ! -f \"${f%.log}.rc\" ] && echo \"${f%.log}\"; done; "
           "echo; echo ---; "
           "nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits; echo ---; "
           "nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -c . || true")
    r = subprocess.run(["ssh", "-i", os.path.expanduser("~/.runpod/ssh/runpodctl-ssh-key"), "-o", "StrictHostKeyChecking=no",
                        "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=20",
                        "-p", str(p["port"]), f"root@{p['ip']}", cmd], capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        return None
    parts = r.stdout.split("---")
    panes = [x.strip() for x in parts[0].split() if x.strip()]
    util = int((parts[1].strip().splitlines() or ["0"])[0] or 0)
    apps = int((parts[2].strip().splitlines() or ["0"])[-1] or 0)
    job = bool(panes)   # names of steps still running (log without .rc)
    return job, util, apps, panes


def runner(step):
    env = dict(os.environ)
    return subprocess.run(["uv", "run", "--frozen", "--env-file", "../.env", "python", "scripts/phase6/remeasure.py", step],
                          env=env, capture_output=True, text=True, timeout=1800)


log(f"idle guard start: idle limit {IDLE_S} s, poll {POLL_S} s")
idle_since = None
while True:
    p = state()
    if p.get("deleted"):
        log("pod deleted; idle guard exits"); break
    try:
        s = probe(p)
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        s = None; log(f"probe error {type(e).__name__}")
    if s is None:
        log("probe failed (not counted as idle)")
    else:
        job, util, apps, panes = s
        idle = not job and util == 0 and apps == 0
        if idle:
            idle_since = idle_since or time.time()
            if time.time() - idle_since >= IDLE_S:
                log(f"IDLE {IDLE_S} s (panes {panes}, util {util}, compute apps {apps}): copy, verify, delete")
                c = runner("copy"); log(f"copy rc={c.returncode}: {c.stdout.strip().splitlines()[-1:] if c.stdout else ''}")
                d = runner("delete"); log(f"delete rc={d.returncode}: {d.stdout.strip().splitlines()[-1:] if d.stdout else ''}")
                break
        else:
            if idle_since:
                log(f"busy again (panes {panes}, util {util}, apps {apps})")
            idle_since = None
    time.sleep(POLL_S)
