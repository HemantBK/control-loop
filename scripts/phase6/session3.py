"""Phase 6 session 3 (PLAN Amendment (19) items 3 and 8): one H100 pod, benchmark changes 00-06, and the do-nothing check
under Baseline B. Then the pod is deleted and the result goes to the owner before any agent run.

    uv run --frozen --env-file ../.env python scripts/phase6/session3.py <step>      (from the repository root)

Steps, one per invocation: create | ready | driver | setup | kit | harness | donothing | pull | delete | status.
Every remote step runs as a detached job on the pod (pods._Launch.ssh, Amendment (18) item 4). Log:
results/phase6_researcharena/fixrun/session3/run.jsonl; full step outputs under steps/; pod state in state.json."""
import dataclasses, hashlib, json, os, subprocess, sys, time
from dataclasses import replace
from pathlib import Path

from control_loop import runlog
from control_loop.adapters.researcharena import pods
from control_loop.adapters.researcharena import sweep as sw

OUT = Path("results") / pods.PHASE / "fixrun" / "session3"
STATE, STEPS = OUT / "state.json", OUT / "steps"
NAME, RUN_ID = "p6-fixs3", "fixs3"
BC = Path("phases") / pods.PHASE / "benchmark_changes"
POD_SCRIPTS = Path("scripts") / "phase6_pod"
REMOTE_SCRIPTS = "/workspace/pod3"
AGENT = "opencode_or:openrouter/z-ai/glm-5.1"     # Amendment (19) item 4; used from the agent run on, not in this session
REDRUNTIME = 1.0                                   # Amendment (19) item 2 (the paper's one hour)

DCS = os.environ.get("P6_DCS", "EU-FR-1,EU-NL-1,EUR-IS-3,US-MO-1,US-NE-1,US-CA-2")
cfg = pods.PodConfig(data_centers=DCS, template_id=None, baked_template=None)
assert cfg.image == "runpod/base:1.4.1-cuda1290-ubuntu2204", cfg.image
cfg = replace(cfg, remote_collect=tuple(cfg.remote_collect) + tuple(x for x in pods.DIAG_COLLECT if x not in cfg.remote_collect))
spec = sw.Core().make_spec(arena_root=cfg.remote_arena_root, setting=sw.SETTING, side_task="none", redruntime=REDRUNTIME,
                           redteammodel=AGENT, seed=733, experiment="phase6_glm51_733_fixs3_donothing",
                           cluster_id="glm51_733-fixs3-donothing", task_config=sw.TASK_CONFIG, payload_file=None)
L = pods._Launch([spec], OUT, runlog.log_step, cfg, [OUT / "episode"], RUN_ID, OUT / "pods.jsonl", False)


def save(pod):
    OUT.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(dataclasses.asdict(pod), indent=2), encoding="utf-8")


def load():
    pod = pods.PodInfo(**json.loads(STATE.read_text(encoding="utf-8")))
    L.pods[pod.id] = pod
    return pod


def keep(name, text):
    STEPS.mkdir(parents=True, exist_ok=True)
    p = STEPS / f"{time.strftime('%H%M%S', time.gmtime())}_{name}.log"
    p.write_text(pods.rel_text(pods.redact([text])), encoding="utf-8")
    print(f"full output -> {p}")
    return p


def podscript(name, want, timeout):
    L.step(name, "started", pod_id=pod.id, note=f"{REMOTE_SCRIPTS}/{name}.sh (detached job)")
    t0 = time.time()
    cp = L.ssh(pod, f"bash {REMOTE_SCRIPTS}/{name}.sh", timeout=timeout)
    out = (cp.stdout or "") + "\n--- stderr ---\n" + (cp.stderr or "")
    p = keep(name, out)
    ok = cp.returncode == 0 and all(w in (cp.stdout or "") for w in want)
    L.step(name, "done" if ok else "failed", pod_id=pod.id, paths=[p], seconds=round(time.time() - t0, 1),
           error=None if ok else f"rc={cp.returncode}; wanted {want}")
    print(out[-6000:])
    return 0 if ok else 1


step = sys.argv[1] if len(sys.argv) > 1 else "status"
if step == "create":
    t0 = time.time()
    pod = L.create_pod(NAME, spec)
    if pod is None:
        print("no pod created"); sys.exit(1)
    save(pod)
    print(f"pod {pod.id} dc {pod.data_center} create returned after {time.time() - t0:.0f} s")
    sys.exit(0)
pod = load()
rc = 0
if step == "ready":
    origin = pod.create_called_at or pod.created_at
    w = L.container_ready(pod); t_c = time.time()
    s = L.ssh_ready(pod, why="after container_ready"); save(pod)
    print(f"create call -> container {t_c - origin:.0f} s -> ssh ready {time.time() - origin:.0f} s")
elif step == "driver":
    print(L.driver_check(pod))
elif step == "setup":
    L._setup(pod); save(pod)
    print((OUT / "pods" / pod.id / "setup.log").read_text()[-4000:])
elif step == "kit":   # the benchmark changes (with the expected sha256 of every patched file) and the pod scripts
    tree = BC / "tree"
    exp = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(tree).as_posix()}\n"
                  for p in sorted(tree.rglob("*")) if p.is_file() and "__pycache__" not in p.parts)
    stage = OUT / "kit_stage" / "bench_changes"; stage.mkdir(parents=True, exist_ok=True)
    for p in sorted(BC.glob("0*.patch")):
        (stage / p.name).write_bytes(p.read_bytes())
    (stage / "expected_sha256.txt").write_text(exp)
    e = " ".join(pods.ssh_base(pod, cfg)[:-1])
    for src, dst in ((f"{stage}/", "/workspace/bench_changes/"), (f"{POD_SCRIPTS}/", f"{REMOTE_SCRIPTS}/")):
        r = subprocess.run(["rsync", "-rz", "--no-owner", "--no-group", "--exclude=__pycache__", "-e", e, src, f"root@{pod.ip}:{dst}"],
                           capture_output=True, text=True)
        print(src, "->", dst, "rc", r.returncode, r.stderr[-200:]); rc = rc or r.returncode
    L.step("kit", "done" if rc == 0 else "failed", pod_id=pod.id,
           note=f"bench_changes {sorted(p.name for p in BC.glob('0*.patch'))} + expected sha256 ({exp.count(chr(10))} files); {POD_SCRIPTS}")
elif step == "harness":
    rc = podscript("harness", ["PATCHED_FILES_MATCH_EXPECTED", "CHECKOUT_UNCHANGED", "INOTIFY_OK", "MODEL_LOAD_OK"], 1200)
elif step == "donothing":
    rc = podscript("do_nothing", ["DO_NOTHING_VERDICT"], 3300)
    if rc == 0 and "DO_NOTHING_VERDICT PASS" not in sorted(STEPS.glob("*_do_nothing.log"))[-1].read_text():
        rc = 3   # the script ran but the pre-registered rule failed: stop and report (Amendment (19) item 8)
elif step == "pull":
    r = L.rsync(pod, "/workspace/session3/", OUT / "pod_session3")
    print("pull rc", r.returncode, r.stderr[-300:] if r.stderr else ""); rc = r.returncode
elif step == "delete":
    L.delete_pod(pod, note="fixs3 session end")
elif step == "status":
    print(json.dumps(dataclasses.asdict(pod), indent=2))
else:
    print("unknown step"); rc = 2
sys.exit(rc)
