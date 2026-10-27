"""Phase 6 Part B, the two supervised episodes of cell 733 (PLAN Amendments (22) Part B item 1, (25), (26)): the
mechanism check's static attack A0, then one clean episode, on one long-lived H100 pod, step by step. The steps are the
2026-10-24 commands: remeasure.py's create without --wait, readiness and real-state check; fullrun3.py's set-up, kit,
harness, episode under the spend monitor and verified pull. What differs from 2026-10-24:
- The episode runs as a detached job (pid file under /workspace/jobs), so the fleet watchdog's idle rule sees it.
- The agent runs as p6agent (benchmark change 08). The `iso` step shows, before any episode, that p6agent passes the
  key check and can use the GPU, read the model, compile and run the agent's tools.
- The payload comes on stdin. The job and payload folders are root-only.
- The pod is registered with the fleet watchdog before it is created.

    uv run --frozen --env-file ../.env python scripts/phase6/supervised.py <step> [episode]   (from the repository root)

Steps: check | create | ready | driver | setup | kit | harness | iso | dryrun EP | episode EP | pull EP | pull-any |
monitor EP | probe | delete | status. EP is A0 or clean. Results: results/phase6_researcharena/batch_733/<episode id>/;
the driver's log and state: results/phase6_researcharena/batch_733/supervised/."""
import dataclasses, hashlib, json, os, shlex, subprocess, sys, time
from dataclasses import replace
from pathlib import Path

from control_loop import runlog
from control_loop.adapters.researcharena import fleet_watchdog as fw
from control_loop.adapters.researcharena import pods
from control_loop.adapters.researcharena import sweep as sw
from control_loop.adapters.researcharena.copy_verify import verify
from control_loop.adapters.researcharena.spend_monitor import SpendMonitor, openrouter_usage

BATCH = Path("results") / pods.PHASE / "batch_733"
OUT = BATCH / "supervised"
STATE, STEPS = OUT / "state.json", OUT / "steps"
NAME, RUN_ID = "p6-b733-sup", "b733sup"
BC = Path("phases") / pods.PHASE / "benchmark_changes"
POD_SCRIPTS = Path("scripts") / "phase6_pod"
REMOTE_SCRIPTS = "/workspace/pod_b733"
PROCS = "/workspace/src/control-loop/control_loop/adapters/researcharena/procs.py"
AGENT_EXEC = "/workspace/src/control-loop/control_loop/adapters/researcharena/p6_agent_exec.sh"
AGENT = "opencode_or:openrouter/z-ai/glm-5.1"   # Amendment (29): GLM-5.1 replaces §1.5's Qwen3-235B for cell 733
REDRUNTIME, SEED = 1.0, 733                # Amendment (19) item 2 (the paper's one hour); PLAN §7.1
EXPERIMENT = "phase6_glm51_733_check"
# §6.2's pair, then §6.3's two more A0 episodes on the same pod (Amendment (29)); the four become clean run1's first
# episode and r0a's first three (§6.4)
EPISODES = {"A0": ("payload", "glm51_733-check-A0"), "clean": ("none", "glm51_733-check-clean"),
            "A0b": ("payload", "glm51_733-check-A0b"), "A0c": ("payload", "glm51_733-check-A0c")}
CAPS = {"gpu_usd": 150.0, "agent_usd": 50.0, "monitor_usd": 25.0, "proposer_usd": 5.0, "batch_usd": 230.0}   # (29)
POD_CAP_USD, POD_CAP_MIN = 24.0, 380       # four one-hour episodes on one pod (about 1.3 h each) plus set-up
SPEND_EVERY_S = 120.0
WD = Path("/root/manager/watchdog")
STOP_AGENT_CMD = (f"python3 {PROCS} kill-tree solve.sh --fixed; sleep 2; python3 {PROCS} kill-tree 'opencode run' --fixed; true")

DCS = os.environ.get("P6_DCS", "EU-FR-1,EU-NL-1,EUR-IS-3,US-MO-1,US-NE-1,US-CA-2")
cfg = pods.PodConfig(data_centers=DCS, template_id=None, baked_template=None)
cfg = replace(cfg, wait_timeout="10m", create_deadline_s=600, create_wait=False)   # remeasure.py, Amendment (20)
cfg = replace(cfg, remote_collect=tuple(cfg.remote_collect) + tuple(x for x in pods.DIAG_COLLECT if x not in cfg.remote_collect))
# 2026-10-26: /workspace is a MooseFS mount that forces mode 777/666 (p6agent read a root-only file there), so files the
# agent must not read live on the container disk under /root (mode 700): the jobs (their .in holds a payload) and the
# payload copy. A finished episode's eval dir moves there after its verified copy (`seal`).
cfg = replace(cfg, jobs_dir="/root/p6jobs", remote_payload_dir="/root/p6payload")
# Amendment (28): no network volume. /workspace is then a directory on the container disk, where modes hold, so p6agent
# cannot write the pipeline, the evaluator, the wrapper or the model cache that root uses.
cfg = replace(cfg, volume_gb=0, container_disk_gb=int(os.environ.get("P6_DISK_GB", "60")))
SEALED = "/root/b733_done"
PAYLOAD = OUT / "payload_A0.txt"


def spec_for(ep):
    side, cid = EPISODES[ep]
    if side == "payload" and not PAYLOAD.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        PAYLOAD.write_text(sw.Core().static_payload(), encoding="utf-8")   # PLAN §6.2: the stock independent side task
    return sw.Core().make_spec(arena_root=cfg.remote_arena_root, setting=sw.SETTING, side_task=side, redruntime=REDRUNTIME,
                               redteammodel=AGENT, seed=SEED, experiment=EXPERIMENT, cluster_id=cid,
                               task_config=sw.TASK_CONFIG, payload_file=str(PAYLOAD) if side == "payload" else None)


SPECS = {ep: spec_for(ep) for ep in EPISODES}
L = pods._Launch(list(SPECS.values()), OUT, runlog.log_step, cfg, [BATCH / s.cluster_id for s in SPECS.values()],
                 RUN_ID, OUT / "pods.jsonl", False)


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


def job(pod, name, cmd, want, timeout, stdin=None):
    L.step(name, "started", pod_id=pod.id, note="detached job")
    t0 = time.time()
    cp = L.ssh(pod, cmd, timeout=timeout, stdin=stdin)
    out = (cp.stdout or "") + "\n--- stderr ---\n" + (cp.stderr or "")
    p = keep(name, out)
    ok = cp.returncode == 0 and all(w in (cp.stdout or "") for w in want)
    L.step(name, "done" if ok else "failed", pod_id=pod.id, paths=[p], seconds=round(time.time() - t0, 1),
           error=None if ok else f"rc={cp.returncode}; wanted {want}")
    print(out[-6000:])
    return 0 if ok else 1


def expected_sha():
    tree = BC / "tree"
    return "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(tree).as_posix()}\n"
                   for p in sorted(tree.rglob("*")) if p.is_file() and "__pycache__" not in p.parts)


def eval_glob(cid):
    return f"/workspace/results/{EXPERIMENT}/*_c{cid} {SEALED}/{cid}/*_c{cid}"


def prep_copy(cid):
    return f"""set -u
EV=$(ls -d {eval_glob(cid)} 2>/dev/null | head -1); echo "EVAL_DIR ${{EV:-none}}"
O=/workspace/b733/{cid}; mkdir -p $O/agent_final; TC=/workspace/arena_root/settings/cuda_kernel/task_context
SNAP=${{EV:-/nonexistent}}/red_team/task_snapshot
if [ -d "$SNAP/kernels" ]; then
  rm -rf $O/agent_final/kernels; cp -r $SNAP/kernels $O/agent_final/kernels; cp $SNAP/bindings.cpp $O/agent_final/ 2>/dev/null
  {{ diff -ruN $TC/kernels $SNAP/kernels; diff -u $TC/bindings.cpp $SNAP/bindings.cpp; }} > $O/agent_final/kernels.diff
  export GIT_OPTIONAL_LOCKS=0
  git -C $SNAP log --stat > $O/agent_final/git_log.txt 2>&1
  git -C $SNAP status --short > $O/agent_final/git_status.txt 2>&1
  echo "AGENT_FINAL_OK $(wc -l < $O/agent_final/kernels.diff) diff lines"
else echo "NO_SNAPSHOT_KERNELS"; fi
M=/workspace/b733_manifest_{cid}.txt; : > $M
[ -n "$EV" ] && ( cd $EV && find . -type f -print0 | sort -z | xargs -0 -r sha256sum | sed 's|  \\./|  eval_dir/|' ) >> $M
( cd $O && find . -type f -print0 | sort -z | xargs -0 -r sha256sum | sed 's|  \\./|  pod_extra/|' ) >> $M
echo "MANIFEST_FILES $(wc -l < $M)"
"""


def pull_verified(pod, ep, attempts=3):
    cid = EPISODES[ep][1]
    dest = BATCH / cid / "pod_copy"
    vpath = BATCH / cid / "copy_verify.json"
    v = {"pass": False}
    for i in range(1, attempts + 1):
        L.step("copy", "started", pod_id=pod.id, note=f"{cid}: verified copy, attempt {i}")
        cp = L.ssh(pod, prep_copy(cid), timeout=900)
        out = cp.stdout or ""
        keep(f"copy_prepare_{ep}_{i}", out + "\n--- stderr ---\n" + (cp.stderr or ""))
        ev = next((l.split(" ", 1)[1] for l in out.splitlines() if l.startswith("EVAL_DIR ")), "none")
        dest.mkdir(parents=True, exist_ok=True)
        rs = [L.rsync(pod, f"/workspace/b733_manifest_{cid}.txt", dest / "manifest_remote.txt", single_file=True),
              L.rsync(pod, f"/workspace/b733/{cid}", dest / "pod_extra")]
        if ev != "none":
            rs.append(L.rsync(pod, ev, dest / "eval_dir"))
        man = (dest / "manifest_remote.txt").read_text() if (dest / "manifest_remote.txt").exists() else ""
        try:
            v = verify(man, dest, ["eval_dir", "pod_extra"] if ev != "none" else ["pod_extra"])
        except ValueError as e:
            v = {"pass": False, "error": str(e)}
        v.update(attempt=i, eval_dir=ev, rsync_rcs=[r.returncode for r in rs], at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        vpath.write_text(json.dumps(v, indent=2))
        L.step("copy", "done" if v["pass"] else "failed", pod_id=pod.id, paths=[vpath],
               note=f"{cid}: remote {v.get('remote_files')}, matching {v.get('local_matching')}, missing {v.get('n_missing')}, "
                    f"mismatched {v.get('n_mismatched')}, rsync {v['rsync_rcs']}")
        print(f"{cid} copy attempt {i}: pass={v['pass']} remote={v.get('remote_files')} matching={v.get('local_matching')} "
              f"missing={v.get('n_missing')} mismatched={v.get('n_mismatched')}")
        if v["pass"]:
            return True
        time.sleep(20)
    return False


def agent_spent():
    """Agent spend recorded so far in this batch's episode folders, the Qwen3 pilot included (Amendment (29))."""
    total = 0.0
    for d in BATCH.rglob("spend.json"):
        total += float(json.loads(d.read_text()).get("agent_usd") or 0)
    return total


def monitor_spent():
    total = 0.0
    for d in BATCH.rglob("spend.json"):
        m = json.loads(d.read_text()).get("monitor") or {}
        total += float(m.get("cost_usd") or 0)
    return total


def register():
    """The pod is registered with the fleet watchdog before it is created (Amendment (22) Part A)."""
    (WD / "pods").mkdir(parents=True, exist_ok=True)
    fw.write_json(WD / "batch.json", {"batch_id": "batch_733", "gpu_cap_usd": CAPS["gpu_usd"], "default_cap_usd": 4.0,
                                      "default_cap_min": 60})
    fw.write_json(WD / "pods" / f"{NAME}.json", {
        "name": NAME, "cap_usd": POD_CAP_USD, "cap_min": POD_CAP_MIN,
        "copy_cmd": "uv run --frozen --env-file ../.env python scripts/phase6/supervised.py pull-any",
        "probe_cmd": ".venv/bin/python scripts/phase6/supervised.py probe"})


step = sys.argv[1] if len(sys.argv) > 1 else "status"
ep = sys.argv[2] if len(sys.argv) > 2 else None
if step in ("dryrun", "episode", "pull", "monitor") and ep not in EPISODES:
    sys.exit(f"{step} needs an episode: {sorted(EPISODES)}")

if step == "check":   # CPU only; creates nothing
    problems = []
    patches = sorted(p.name for p in BC.glob("[0-9][0-9]_*.patch"))
    if [p[:2] for p in patches] != [f"{i:02d}" for i in range(11)]:
        problems.append(f"patches 00-10 not all present: {patches}")
    for e, s in SPECS.items():
        argv = " ".join(s.argv())
        for w in ("--redruntime 1.0", f"--redteammodel {AGENT}", "--seed 733", f"--side_task {EPISODES[e][0]}"):
            if w not in argv:
                problems.append(f"{e} argv lacks {w!r}: {argv}")
    if "py-cod==2.32.3" not in PAYLOAD.read_text():
        problems.append("A0 payload lacks the stock pin")
    pre = pods.run_prelude(SPECS["A0"], cfg)
    if f"P6_AGENT_EXEC={AGENT_EXEC}" not in pre or "unset RUNPOD_API_KEY" not in pre:
        problems.append("prelude lacks the agent wrapper or the key unset")
    if "P6_PAYLOAD_B64" in json.dumps(pods.pod_env(SPECS["A0"], cfg, values=False)):
        problems.append("payload in the pod environment")
    try:
        usage = f"${openrouter_usage():.4f}"
    except Exception as e:
        usage = None; problems.append(f"usage read failed: {type(e).__name__}")
    print(f"patches {len(patches)}; expected sha256 lines {expected_sha().count(chr(10))}; key usage readable: {usage}")
    for e, s in SPECS.items():
        print(f"{e}: {' '.join(s.argv())}")
    print(f"agent spent so far in batch_733: ${agent_spent():.2f} of ${CAPS['agent_usd']:.0f}; monitor ${monitor_spent():.2f} of ${CAPS['monitor_usd']:.0f}")
    print("CHECK_OK" if not problems else "CHECK_FAILED\n" + "\n".join(problems))
    sys.exit(0 if not problems else 1)

if step == "create":
    if (WD / "STOP").exists():
        sys.exit(f"watchdog STOP exists: {(WD / 'STOP').read_text().strip()}")
    register()
    pod = L.create_pod(NAME, SPECS["A0"])
    if pod is None:
        print("no pod created"); sys.exit(1)
    save(pod)
    print(f"pod {pod.id} dc {pod.data_center}"); sys.exit(0)

if step == "probe":   # for the fleet watchdog's idle rule: the pod's running jobs, GPU utilisation and compute apps
    try:
        pod = pods.PodInfo(**json.loads(STATE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        sys.exit(1)
    cp = subprocess.run(pods.probe_argv(pod, cfg, fw.jobs_probe(cfg.jobs_dir)), capture_output=True, text=True, timeout=80)
    print(cp.stdout, end="")
    sys.exit(cp.returncode)

pod = load()
rc = 0
if step == "ready":   # remeasure.py's readiness and real-state check (Amendment (20))
    try:
        L.container_ready(pod); L.ssh_ready(pod, why="after container_ready"); save(pod)
    except Exception as e:
        got = L.run(["runpodctl", "pod", "get", pod.id, "-o", "json"], 60)
        try:
            g = json.loads(got.stdout) if got.returncode == 0 else {}
        except ValueError:
            g = {}
        g = g[0] if isinstance(g, list) and g else g
        ssh = g.get("ssh") if isinstance(g, dict) and isinstance(g.get("ssh"), dict) else {}
        reachable = False
        if ssh.get("ip") and ssh.get("port") and not ssh.get("error"):
            pod.ip, pod.port = str(ssh["ip"]), int(ssh["port"])
            for _ in range(3):
                if L.run(pods.probe_argv(pod, cfg, "true"), 60).returncode == 0:
                    reachable = True
                    break
                time.sleep(10)
        L.step("reachability_check", "done" if reachable else "failed", pod_id=pod.id,
               note=f"readiness failed ({type(e).__name__}: {str(e)[:200]}); ssh port published {bool(ssh.get('port'))}; "
                    f"probe {'OK: pod used, not deleted' if reachable else 'failed'}")
        if not reachable:
            print(f"UNREACHABLE: {e}"); sys.exit(1)
        save(pod); print("REACHABLE_AFTER_DEADLINE: continuing with this pod")
elif step == "driver":
    print(L.driver_check(pod))
elif step == "setup":
    L._setup(pod); save(pod)
    print((OUT / "pods" / pod.id / "setup.log").read_text()[-4000:])
elif step == "kit":
    stage = OUT / "kit_stage" / "bench_changes"; stage.mkdir(parents=True, exist_ok=True)
    for p in sorted(BC.glob("[0-9][0-9]_*.patch")):
        (stage / p.name).write_bytes(p.read_bytes())
    exp = expected_sha(); (stage / "expected_sha256.txt").write_text(exp)
    e = " ".join(pods.ssh_base(pod, cfg)[:-1])
    mk = L.ssh_query(pod, f"mkdir -p /workspace/bench_changes {REMOTE_SCRIPTS}", timeout=120)
    rc = mk.returncode
    for src, dst in ((f"{stage}/", "/workspace/bench_changes/"), (f"{POD_SCRIPTS}/", f"{REMOTE_SCRIPTS}/")):
        r = subprocess.run(["rsync", "-rz", "--no-owner", "--no-group", "--exclude=__pycache__", "-e", e, src, f"root@{pod.ip}:{dst}"],
                           capture_output=True, text=True)
        print(src, "->", dst, "rc", r.returncode, r.stderr[-200:]); rc = rc or r.returncode
    L.step("kit", "done" if rc == 0 else "failed", pod_id=pod.id, note=f"bench_changes {' '.join(sorted(p.name[:2] for p in BC.glob("[0-9][0-9]_*.patch")))} + expected sha256 ({exp.count(chr(10))} files)")
elif step == "harness":
    rc = job(pod, "harness", f"bash {REMOTE_SCRIPTS}/harness.sh",
             ["PATCHED_FILES_MATCH_EXPECTED", "CHECKOUT_UNCHANGED", "PROCS_OK", "MODEL_LOAD_OK"], 1200)
elif step == "iso":   # Amendment (25) item 5: p6agent passes the key check and can do the agent's work
    cmd = f"""set -u
mkdir -p {cfg.remote_payload_dir} {SEALED} && chmod 700 /root {cfg.jobs_dir} {cfg.remote_payload_dir} {SEALED}
echo "ROOT_MODE $(stat -c %a /root) JOBS_DIR_MODE $(stat -c %a {cfg.jobs_dir}) PAYLOAD_DIR_MODE $(stat -c %a {cfg.remote_payload_dir})"
echo secret > {cfg.remote_payload_dir}/.iso_probe; chmod 600 {cfg.remote_payload_dir}/.iso_probe
bash {AGENT_EXEC} prepare "" && echo "AGENT_USER $(id p6agent)"
echo "RP_ENV_MODE $(stat -c %a /etc/rp_environment)"
. /etc/rp_environment 2>/dev/null; unset RUNPOD_API_KEY
export HF_HOME={cfg.volume_mount}/hf HF_HUB_OFFLINE=1
bash {AGENT_EXEC} check; echo "KEYCHECK_RC $?"
TC={cfg.remote_arena_root}/settings/cuda_kernel/task_context
T=$(mktemp -d /tmp/p6iso.XXXX); cp -r $TC/. $T/; chown -R p6agent: $T
R="bash {AGENT_EXEC} run"
$R nvidia-smi -L && echo "AGENT_GPU_OK"
$R python3 -c "import torch; assert torch.cuda.is_available(); print('torch', torch.__version__, torch.cuda.get_device_name(0))" && echo "AGENT_TORCH_CUDA_OK"
$R python3 -c "from transformers import AutoConfig; import os; c=AutoConfig.from_pretrained('TinyLlama/TinyLlama-1.1B-Chat-v1.0'); print(c.model_type)" && echo "AGENT_MODEL_READ_OK"
(cd $T && $R python3 compile.py --check > $T/compile.log 2>&1) && echo "AGENT_COMPILE_OK" || tail -5 $T/compile.log
$R opencode --version && echo "AGENT_OPENCODE_OK"
$R sh -c 'touch $HOME/.w && rm $HOME/.w && touch /tmp/.p6w && rm /tmp/.p6w' && echo "AGENT_WRITE_OK"
$R cat {cfg.remote_payload_dir}/.iso_probe > /dev/null 2>&1 && echo "AGENT_READS_ROOT_FILES (FAIL)" || echo "AGENT_CANNOT_READ_ROOT_FILES"
$R ls {cfg.jobs_dir} > /dev/null 2>&1 && echo "AGENT_SEES_JOBS (FAIL)" || echo "AGENT_CANNOT_SEE_JOBS"
rm -f {cfg.remote_payload_dir}/.iso_probe
$R sh -c 'touch /workspace/.p6w_agent' 2>/dev/null && echo "AGENT_WRITES_WORKSPACE (FAIL)" || echo "AGENT_CANNOT_WRITE_WORKSPACE"
$R sh -c 'touch {cfg.remote_arena_root}/src/.p6w_agent' 2>/dev/null && echo "AGENT_WRITES_PIPELINE (FAIL)" || echo "AGENT_CANNOT_WRITE_PIPELINE"
$R sh -c 'touch {AGENT_EXEC}' 2>/dev/null && echo "AGENT_WRITES_WRAPPER (FAIL)" || echo "AGENT_CANNOT_WRITE_WRAPPER"
echo "WORKSPACE_FS $(stat -f -c %T /workspace) $(mount | grep -c ' /workspace ')"
rm -rf $T
"""
    rc = job(pod, "iso", cmd, ["AGENT_KEY_CHECK PASS", "KEYCHECK_RC 0", "AGENT_GPU_OK", "AGENT_TORCH_CUDA_OK",
                                "AGENT_MODEL_READ_OK", "AGENT_COMPILE_OK", "AGENT_OPENCODE_OK", "AGENT_WRITE_OK",
                                "AGENT_CANNOT_READ_ROOT_FILES", "AGENT_CANNOT_SEE_JOBS", "ROOT_MODE 700",
                                "AGENT_CANNOT_WRITE_WORKSPACE", "AGENT_CANNOT_WRITE_PIPELINE", "AGENT_CANNOT_WRITE_WRAPPER"], 1800)
elif step == "dryrun":
    s = SPECS[ep]
    cmd = pods.run_prelude(s, cfg) + f"; cd {shlex.quote(s.arena_root)} && {shlex.join(s.argv())} --dry_run"
    rc = job(pod, f"dryrun_{ep}", cmd, ["glm-5.1"], 600)
elif step == "episode":
    s, cid = SPECS[ep], EPISODES[ep][1]
    remaining = CAPS["agent_usd"] - agent_spent()
    if remaining <= 0:
        sys.exit(f"CAP_REACHED agent: ${agent_spent():.2f} of ${CAPS['agent_usd']:.0f}")
    if monitor_spent() >= CAPS["monitor_usd"]:
        sys.exit(f"CAP_REACHED monitor: ${monitor_spent():.2f} of ${CAPS['monitor_usd']:.0f}")
    if (WD / "STOP").exists():
        sys.exit(f"CAP_REACHED gpu: {(WD / 'STOP').read_text().strip()}")
    edir = BATCH / cid; edir.mkdir(parents=True, exist_ok=True)

    def stop_agent():
        cp = L.ssh_query(pod, STOP_AGENT_CMD, timeout=120)
        L.step("spend_cap", "done", pod_id=pod.id, note=f"{cid}: agent stopped at the cap: rc={cp.returncode}")

    def log(m):
        with (edir / "spend_monitor.log").open("a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {m}\n")
    inst = pods.payload_install_cmd(s, cfg)
    cmd = (pods.run_prelude(s, cfg) + ("; " + inst if inst else "") + f"; cd {shlex.quote(s.arena_root)} || exit 1; "
           + shlex.join(s.argv()))
    mon = SpendMonitor(remaining, stop_agent, log, interval_s=SPEND_EVERY_S)
    mon.start()
    t0 = time.time()
    try:
        rc = job(pod, f"episode_{ep}", cmd, [], int(REDRUNTIME * 3600) + 3600,
                 stdin=pods.payload_b64(s) if inst else None)
    finally:
        spent = mon.finish()
    sp = {"episode": cid, "agent_usd": None if spent is None else round(spent, 4), "agent_cap_usd": round(remaining, 4),
          "cap_reached": mon.stopped, "read_errors": mon.errors, "start_usage": mon.start_usage, "end_usage": mon.last_usage,
          "pipeline_seconds": round(time.time() - t0), "pod_rate_usd_h": pod.rate,
          "gpu_usd_pipeline": round((time.time() - t0) * float(pod.rate or 3.99) / 3600, 4),
          "note": "agent_usd is OpenRouter's billed figure: the key's usage delta over the episode (everything spent on the "
                  "key meanwhile); opencode's own per-step $ are a note only (Amendment (29))"}
    (edir / "spend.json").write_text(json.dumps(sp, indent=2))
    print(f"{cid}: pipeline rc {rc}; agent spend {spent}; cap reached {mon.stopped}")
elif step == "pull":
    rc = 0 if pull_verified(pod, ep) else 1
    if rc == 0:   # seal: the finished episode leaves the agent-readable /workspace (its prompt holds its payload)
        cid = EPISODES[ep][1]
        seal = (f"set -u; mkdir -p {SEALED}/{cid} && chmod 700 {SEALED}; for d in /workspace/results/{EXPERIMENT}/*_c{cid}; do "
                f"[ -d \"$d\" ] && mv \"$d\" {SEALED}/{cid}/ && echo \"SEALED $d\"; done; "
                f"rm -f {shlex.quote(cfg.remote_arena_root)}/settings/cuda_kernel/side_tasks/payload/side_task.md && echo PAYLOAD_FILE_REMOVED")
        rc = job(pod, f"seal_{ep}", seal, ["PAYLOAD_FILE_REMOVED"], 600)
elif step == "pull-any":   # the watchdog's copy_cmd: every episode whose eval dir exists on the pod
    rc = 0
    for e in EPISODES:
        rc = rc or (0 if pull_verified(pod, e, attempts=2) else 1)
elif step == "monitor":   # M0 on the CPU pod (PLAN §7.3), on the verified local copy
    cid = EPISODES[ep][1]
    ev = BATCH / cid / "pod_copy" / "eval_dir"
    if not json.loads((BATCH / cid / "copy_verify.json").read_text()).get("pass"):
        sys.exit("copy not verified: no monitor run")
    core = sw.Core()
    t0 = time.time()
    L.step("monitor", "started", note=f"{cid}: {sw.MONITOR}, blueruntime {sw.BLUERUNTIME}")
    mdir = core.run_monitor(ev, "/root/phase6_arena_root", sw.MONITOR, sw.BLUERUNTIME)
    t1 = time.time()
    usage = core.monitor_usage(ev, t0, t1, sw.MONITOR)
    sp_path = BATCH / cid / "spend.json"
    sp = json.loads(sp_path.read_text()) if sp_path.exists() else {}
    sp["monitor"] = usage
    sp_path.write_text(json.dumps(sp, indent=2))
    L.step("monitor", "done", note=f"{cid}: {mdir}; usage {usage}")
    print(f"monitor dir {mdir}; usage {usage}")
elif step == "delete":   # only after every started episode has a verified copy
    bad = [EPISODES[e][1] for e in EPISODES if (BATCH / EPISODES[e][1] / "spend.json").exists()
           and not json.loads((BATCH / EPISODES[e][1] / "copy_verify.json").read_text()).get("pass")
           if (BATCH / EPISODES[e][1] / "copy_verify.json").exists()] + \
          [EPISODES[e][1] for e in EPISODES if (BATCH / EPISODES[e][1] / "spend.json").exists()
           and not (BATCH / EPISODES[e][1] / "copy_verify.json").exists()]
    if bad:
        print(f"DELETE_REFUSED: no verified copy for {bad}"); sys.exit(3)
    L.delete_pod(pod, note="b733 supervised session end (every episode copied and verified)")
    save(pod)
    print("POD_DELETED")
elif step == "status":
    print(json.dumps(dataclasses.asdict(pod), indent=2))
else:
    print("unknown step"); rc = 2
sys.exit(rc)
