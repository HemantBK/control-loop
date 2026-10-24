"""Phase 6 full run 3 (PLAN Amendment (19)): one clean one-hour episode with GLM-5.1 through OpenCode on an H100, with
benchmark changes 00-06 (baseline = the initial kernels; 11ea904's correctness gate; Baseline B RoPE), the $20 model
cap checked every 2 minutes, and the follow-up checks for done criteria 2-4 plus the secondary speed-ups.

    uv run --frozen --env-file ../.env python scripts/phase6/fullrun3.py <step>      (from the repository root)

Steps, one per invocation: check | create | ready | driver | setup | kit | harness | dryrun | watch | episode | post |
pull | delete | status. `check` runs on the CPU pod only and creates nothing: it validates the spec, the kit and the
pod scripts, and reads the OpenRouter key's usage once. Every remote step runs as a detached job on the pod
(pods._Launch.ssh). Log: results/phase6_researcharena/fixrun/fullrun3/run.jsonl; outputs under steps/."""
import dataclasses, hashlib, json, os, shlex, subprocess, sys, time
from dataclasses import replace
from pathlib import Path

from control_loop import runlog
from control_loop.adapters.researcharena import pods
from control_loop.adapters.researcharena import sweep as sw
from control_loop.adapters.researcharena.spend_monitor import SpendMonitor, openrouter_usage

OUT = Path("results") / pods.PHASE / "fixrun" / "fullrun3"
STATE, STEPS = OUT / "state.json", OUT / "steps"
NAME, RUN_ID = "p6-fixfull3", "fixfull3"
BC = Path("phases") / pods.PHASE / "benchmark_changes"
POD_SCRIPTS = Path("scripts") / "phase6_pod"
REMOTE_SCRIPTS, REMOTE_OUT = "/workspace/pod3", "/workspace/fullrun3"
AGENT = "opencode_or:openrouter/z-ai/glm-5.1"     # Amendment (19) item 4
REDRUNTIME = 1.0                                   # Amendment (19) item 2
MODEL_CAP_USD, SPEND_EVERY_S = 20.0, 120.0         # Amendment (19) item 4; owner's approval 2026-10-24
EXPERIMENT, CLUSTER = "phase6_glm51_733_fullrun3_clean", "glm51_733-fullrun3-clean-e1"
PROCS = "/workspace/src/control-loop/control_loop/adapters/researcharena/procs.py"
# solve.sh and every process it started (opencode, the agent's tool commands such as its own bench.py), then any opencode
# left; the pipeline then evaluates what the agent left (procs.py kill-tree, Amendment (19) items 4 and 6)
STOP_AGENT_CMD = (f"python3 {PROCS} kill-tree solve.sh --fixed; sleep 2; python3 {PROCS} kill-tree 'opencode run' --fixed; true")
KIT_FILES = ["harness.sh", "watch_start.sh", "post_agent.sh", "c0_vanilla.py", "c_minimal_kernels.py", "c_kl_check.py"]

DCS = os.environ.get("P6_DCS", "EU-FR-1,EU-NL-1,EUR-IS-3,US-MO-1,US-NE-1,US-CA-2")
cfg = pods.PodConfig(data_centers=DCS, template_id=None, baked_template=None)
assert cfg.image == "runpod/base:1.4.1-cuda1290-ubuntu2204", cfg.image
cfg = replace(cfg, remote_collect=tuple(cfg.remote_collect) + tuple(x for x in pods.DIAG_COLLECT if x not in cfg.remote_collect))
spec = sw.Core().make_spec(arena_root=cfg.remote_arena_root, setting=sw.SETTING, side_task="none", redruntime=REDRUNTIME,
                           redteammodel=AGENT, seed=733, experiment=EXPERIMENT, cluster_id=CLUSTER,
                           task_config=sw.TASK_CONFIG, payload_file=None)
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


def podscript(pod, name, want, timeout, env=""):
    L.step(name, "started", pod_id=pod.id, note=f"{REMOTE_SCRIPTS}/{name}.sh (detached job)")
    t0 = time.time()
    cp = L.ssh(pod, f"{env} bash {REMOTE_SCRIPTS}/{name}.sh".strip(), timeout=timeout)
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


POST_ENV = f"P6_OUT={REMOTE_OUT} P6_EXPERIMENT={shlex.quote(EXPERIMENT)} P6_CLUSTER={shlex.quote(CLUSTER)}"

# Verified copy before any delete (owner, 2026-10-24). On the pod: the agent's final kernels/, bindings.cpp, their diff
# against the initial kernels and the snapshot's git history go to $REMOTE_OUT/agent_final/; then a sha256 manifest of
# every regular file under the eval dir (transcript, evaluator output, task_snapshot) and under $REMOTE_OUT (follow-up
# logs and numbers, KL, memcheck, launch counts, last_bench watcher log). The CPU pod rsyncs both roots, re-hashes and
# compares (control_loop/adapters/researcharena/copy_verify.py). The spend log is written on the CPU pod.
COPY, VERIFY = OUT / "pod_copy", OUT / "copy_verify.json"
COPY_TAGS = ["eval_dir", "fullrun3"]
PREP_COPY = f"""set -u
EV=$(ls -d /workspace/results/{EXPERIMENT}/*_c{CLUSTER} 2>/dev/null | head -1); echo "EVAL_DIR ${{EV:-none}}"
O={REMOTE_OUT}; mkdir -p $O/agent_final; TC=/workspace/arena_root/settings/cuda_kernel/task_context
# the last_bench watcher stops first, so its log cannot change between the manifest and the copy
if python3 {PROCS} kill-tree {REMOTE_OUT}/watch.sh --fixed > /dev/null 2>&1; then echo "$(date -u +%FT%TZ) WATCH_STOPPED_FOR_COPY" >> $O/last_bench_events.log; fi
SNAP=${{EV:-/nonexistent}}/red_team/task_snapshot
if [ -d "$SNAP/kernels" ]; then
  rm -rf $O/agent_final/kernels; cp -r $SNAP/kernels $O/agent_final/kernels; cp $SNAP/bindings.cpp $O/agent_final/ 2>/dev/null
  {{ diff -ruN $TC/kernels $SNAP/kernels; diff -u $TC/bindings.cpp $SNAP/bindings.cpp; }} > $O/agent_final/kernels.diff
  export GIT_OPTIONAL_LOCKS=0   # read the agent's repo without writing its index (Amendment (20))
  git -C $SNAP log --stat > $O/agent_final/git_log.txt 2>&1
  R0=$(git -C $SNAP rev-list --max-parents=0 HEAD 2>/dev/null | tail -1)
  [ -n "$R0" ] && git -C $SNAP diff $R0 > $O/agent_final/git_diff_from_initial_commit.txt 2>&1
  git -C $SNAP status --short > $O/agent_final/git_status.txt 2>&1
  echo "AGENT_FINAL_OK $(wc -l < $O/agent_final/kernels.diff) diff lines"
else echo "NO_SNAPSHOT_KERNELS"; fi
M=/workspace/copy_manifest.txt; : > $M
[ -n "$EV" ] && ( cd $EV && find . -type f -print0 | sort -z | xargs -0 -r sha256sum | sed 's|  \\./|  eval_dir/|' ) >> $M
( cd $O && find . -type f -print0 | sort -z | xargs -0 -r sha256sum | sed 's|  \\./|  fullrun3/|' ) >> $M
echo "MANIFEST_FILES $(wc -l < $M)"
"""


def pull_verified(pod, attempts=3):
    from control_loop.adapters.researcharena.copy_verify import verify
    v = {"pass": False}
    for i in range(1, attempts + 1):
        L.step("copy", "started", pod_id=pod.id, note=f"verified copy, attempt {i}")
        cp = L.ssh(pod, PREP_COPY, timeout=900)
        out = cp.stdout or ""
        keep(f"copy_prepare_{i}", out + "\n--- stderr ---\n" + (cp.stderr or ""))
        ev = next((l.split(" ", 1)[1] for l in out.splitlines() if l.startswith("EVAL_DIR ")), "none")
        COPY.mkdir(parents=True, exist_ok=True)
        rs = [L.rsync(pod, "/workspace/copy_manifest.txt", COPY / "manifest_remote.txt", single_file=True),
              L.rsync(pod, REMOTE_OUT, COPY / "fullrun3")]
        if ev != "none":
            rs.append(L.rsync(pod, ev, COPY / "eval_dir"))
        rsync_rcs = [r.returncode for r in rs]
        man = (COPY / "manifest_remote.txt").read_text() if (COPY / "manifest_remote.txt").exists() else ""
        try:
            v = verify(man, COPY, COPY_TAGS if ev != "none" else ["fullrun3"])
        except ValueError as e:
            v = {"pass": False, "error": str(e)}
        v.update(attempt=i, eval_dir=ev, rsync_rcs=rsync_rcs, at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        VERIFY.write_text(json.dumps(v, indent=2))
        L.step("copy", "done" if v["pass"] else "failed", pod_id=pod.id, paths=[VERIFY],
               note=f"remote files {v.get('remote_files')} by root {v.get('remote_files_by_root')}; matching "
                    f"{v.get('local_matching')}; missing {v.get('n_missing')}; mismatched {v.get('n_mismatched')}; rsync {rsync_rcs}")
        print(f"copy attempt {i}: pass={v['pass']} remote={v.get('remote_files')} matching={v.get('local_matching')} "
              f"missing={v.get('n_missing')} mismatched={v.get('n_mismatched')} by_root={v.get('remote_files_by_root')}")
        if v["pass"]:
            return True
        time.sleep(20)
    return False
step = sys.argv[1] if len(sys.argv) > 1 else "status"

if step == "check":   # CPU only; creates nothing
    problems = []
    patches = sorted(p.name for p in BC.glob("0*.patch"))
    if patches != [f"0{i}_" + n for i, n in enumerate(["rope_bounds_guard.patch", "evaluator_remeasure_from_clean_copy.patch",
                   "bench_starter_kernels_lookup.patch", "attention_whole_warps_and_race.patch", "baseline_is_initial_kernels.patch",
                   "correctness_gate.patch", "baseline_b_rope.patch"])]:
        problems.append(f"patches: {patches}")
    for f in KIT_FILES:
        p = POD_SCRIPTS / f
        if not p.is_file():
            problems.append(f"missing kit file {p}")
        elif p.suffix == ".sh" and subprocess.run(["bash", "-n", str(p)]).returncode != 0:
            problems.append(f"bash -n failed: {p}")
        elif p.suffix == ".py" and subprocess.run([sys.executable, "-m", "py_compile", str(p)]).returncode != 0:
            problems.append(f"py_compile failed: {p}")
    n_sha = expected_sha().count("\n")
    if spec.redruntime != 1.0 or spec.redteammodel != AGENT or spec.side_task != "none":
        problems.append(f"spec: {spec.redruntime} {spec.redteammodel} {spec.side_task}")
    argv = " ".join(spec.argv())
    for w in ("--redruntime 1.0", "--redteammodel opencode_or:openrouter/z-ai/glm-5.1", "--side_task none", "--seed 733"):
        if w not in argv:
            problems.append(f"argv lacks {w!r}: {argv}")
    try:
        u = openrouter_usage()
        usage = f"${u:.4f}"
    except Exception as e:
        usage = None; problems.append(f"usage read failed: {type(e).__name__}")
    print(f"patches {len(patches)}; expected sha256 lines {n_sha}; kit files {len(KIT_FILES)}; usage readable: {usage}")
    print(f"episode argv: {argv}")
    print(f"stop command: {STOP_AGENT_CMD}")
    print(f"post env: {POST_ENV}")
    print("CHECK_OK" if not problems else "CHECK_FAILED\n" + "\n".join(problems))
    sys.exit(0 if not problems else 1)

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
    L.container_ready(pod); t_c = time.time()
    L.ssh_ready(pod, why="after container_ready"); save(pod)
    print(f"create call -> container {t_c - origin:.0f} s -> ssh ready {time.time() - origin:.0f} s")
elif step == "driver":
    print(L.driver_check(pod))
elif step == "setup":
    L._setup(pod); save(pod)
    print((OUT / "pods" / pod.id / "setup.log").read_text()[-4000:])
elif step == "kit":
    stage = OUT / "kit_stage" / "bench_changes"; stage.mkdir(parents=True, exist_ok=True)
    for p in sorted(BC.glob("0*.patch")):
        (stage / p.name).write_bytes(p.read_bytes())
    exp = expected_sha(); (stage / "expected_sha256.txt").write_text(exp)
    e = " ".join(pods.ssh_base(pod, cfg)[:-1])
    for src, dst in ((f"{stage}/", "/workspace/bench_changes/"), (f"{POD_SCRIPTS}/", f"{REMOTE_SCRIPTS}/")):
        r = subprocess.run(["rsync", "-rz", "--no-owner", "--no-group", "--exclude=__pycache__", "-e", e, src, f"root@{pod.ip}:{dst}"],
                           capture_output=True, text=True)
        print(src, "->", dst, "rc", r.returncode, r.stderr[-200:]); rc = rc or r.returncode
    L.step("kit", "done" if rc == 0 else "failed", pod_id=pod.id, note=f"bench_changes 00-06 + expected sha256 ({exp.count(chr(10))} files); {POD_SCRIPTS}")
elif step == "harness":
    rc = podscript(pod, "harness", ["PATCHED_FILES_MATCH_EXPECTED", "CHECKOUT_UNCHANGED", "INOTIFY_OK", "PROCS_OK", "MODEL_LOAD_OK"], 1200)
elif step == "dryrun":   # the pipeline's own --dry_run with this run's arguments
    cmd = pods.run_prelude(spec, cfg) + f"; cd {shlex.quote(spec.arena_root)} && {shlex.join(spec.argv())} --dry_run"
    L.step("dryrun", "started", pod_id=pod.id)
    cp = L.ssh(pod, cmd, timeout=600)
    p = keep("dryrun", (cp.stdout or "") + "\n--- stderr ---\n" + (cp.stderr or ""))
    ok = cp.returncode == 0 and "glm-5.1" in (cp.stdout or "")
    L.step("dryrun", "done" if ok else "failed", pod_id=pod.id, paths=[p], error=None if ok else f"rc={cp.returncode}")
    print((cp.stdout or "")[-3000:], (cp.stderr or "")[-1000:]); rc = 0 if ok else 1
elif step == "watch":
    rc = podscript(pod, "watch_start", ["watcher started"], 300, env=f"P6_OUT={REMOTE_OUT} P6_WATCH_S=5400")
elif step == "episode":
    pod.setup_done = True

    def stop_agent():
        cp = L.ssh_query(pod, STOP_AGENT_CMD, timeout=120)
        L.step("spend_cap", "done", pod_id=pod.id, note=f"agent stopped at the ${MODEL_CAP_USD:.0f} model cap: rc={cp.returncode} "
               + (cp.stdout or "")[-400:].replace("\n", " | "))

    mlog = OUT / "spend_monitor.log"; OUT.mkdir(parents=True, exist_ok=True)

    def log(m):
        with mlog.open("a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {m}\n")
    mon = SpendMonitor(MODEL_CAP_USD, stop_agent, log, interval_s=SPEND_EVERY_S)
    mon.start()
    try:
        ok, err = L.run_episode(pod, 0, spec, 1)
    finally:
        spent = mon.finish()
    L.step("agent_model_spend", "done", pod_id=pod.id, cost=None if spent is None else round(spent, 4),   # 2026-10-24: was cost_usd=, a duplicate keyword (fullrun3 incident)
           note=f"measured: OpenRouter key usage delta over the episode (start ${mon.start_usage}, end ${mon.last_usage}); "
                f"cap ${MODEL_CAP_USD:.0f}{'; CAP REACHED, agent stopped' if mon.stopped else ''}; read errors {mon.errors}")
    print(f"model spend over the episode: {spent}; cap reached: {mon.stopped}")
    if not ok:
        L.fail_episode(0, spec, pod, 1, err)
        print("EPISODE FAILED:", err); rc = 1
    else:
        print("episode done")
elif step == "post":
    rc = podscript(pod, "post_agent", ["POST_DONE"], 3600, env=POST_ENV)
elif step == "pull":
    rc = 0 if pull_verified(pod, attempts=3) else 1
elif step == "delete":   # only after a verified copy (owner, 2026-10-24); two more copy attempts first if none passed
    v = json.loads(VERIFY.read_text()) if VERIFY.exists() else {}
    if not v.get("pass") and not pull_verified(pod, attempts=2):
        L.step("pod_delete", "failed", pod_id=pod.id, error="copy not verified: pod NOT deleted; the watchdog copies "
               "again and hard-deletes at its limit")
        print("DELETE_REFUSED: copy not verified"); sys.exit(3)
    L.delete_pod(pod, note="fixfull3 session end (copy verified)")
    save(pod)   # state.json records deleted: true
elif step == "status":
    print(json.dumps(dataclasses.asdict(pod), indent=2))
else:
    print("unknown step"); rc = 2
sys.exit(rc)
