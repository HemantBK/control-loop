"""Phase 6 re-measure session (PLAN Amendment (19); owner, 2026-10-24): fullrun3's x1.420 is void (measurement
interference). One H100 pod re-measures the agent's copied kernels, interleaved with the initial kernels, then runs the
follow-up checks, then a verified copy, then delete.

    uv run --frozen --env-file ../.env python scripts/phase6/remeasure.py <step>      (from the repository root)

Steps: check | create | ready | driver | setup | kit | harness | prepare | interleave | memcheck | kl | embedded |
vanilla | starter | copy | delete | status. Every remote step is a detached job on the pod (pods._Launch.ssh).

Delete rule: once any result-producing step (prepare onwards) has started, `delete` needs a verified copy
(copy_verify.json pass); it tries the copy twice more first and otherwise refuses (the watchdog copies again and
hard-deletes at its limit). If the session failed before any result existed (create..harness), the pod is deleted after
a best-effort copy: there is nothing on it to lose.

Stub mode (P6_STUB_RUN=1; the CPU-pod rehearsal of the whole session, owner's item 4): runpodctl/ssh/rsync/nvidia-smi
must be the test shims (the runner refuses otherwise), sleeps are short, results go to $P6_OUT_DIR, the pod scripts come
from $P6_POD_SCRIPTS, the submission from $P6_SUBMISSION_DIR, and $P6_FAIL_STEP forces that step to fail (runner steps
here; pod-script steps in the stub scripts)."""
import dataclasses, hashlib, json, os, shlex, shutil, subprocess, sys, time
from dataclasses import replace
from pathlib import Path

from control_loop import runlog
from control_loop.adapters.researcharena import pods
from control_loop.adapters.researcharena import sweep as sw
from control_loop.adapters.researcharena.copy_verify import verify

STUB = os.environ.get("P6_STUB_RUN") == "1"
LOCAL = os.environ.get("P6_LOCAL_TARGET") == "1"   # real ssh/rsync to this CPU pod (owner, 2026-10-24)
FAIL = os.environ.get("P6_FAIL_STEP", "") if STUB else ""
OUT = Path(os.environ["P6_OUT_DIR"]) if STUB else Path(os.environ.get("P6_RM_OUT", str(Path("results") / pods.PHASE / "fixrun" / "remeasure")))
STATE, STEPS, VERIFY, COPY = OUT / "state.json", OUT / "steps", OUT / "copy_verify.json", OUT / "pod_copy"
SESSION = OUT / "session_state.json"
NAME, RUN_ID = os.environ.get("P6_RM_NAME", "p6-fixrm"), os.environ.get("P6_RM_RUN_ID", "fixrm")
BC = Path("phases") / pods.PHASE / "benchmark_changes"
POD_SCRIPTS = Path(os.environ.get("P6_POD_SCRIPTS", "scripts/phase6_pod")) if STUB else Path("scripts/phase6_pod")
SUBMISSION = Path(os.environ["P6_SUBMISSION_DIR"]) if STUB else \
    Path("results") / pods.PHASE / "fixrun" / "fullrun3" / "pod_copy" / "eval_dir" / "red_team" / "task_snapshot"
REMOTE_SCRIPTS, RM = "/workspace/pod_rm", "/workspace/remeasure"
PROCS = "/workspace/src/control-loop/control_loop/adapters/researcharena/procs.py"
CHECKS = {"prepare": ("rm_prepare", ["PREPARE_OK"], 1800), "interleave": ("rm_interleave", ["MEDIAN_RATIO"], 1500),
          "memcheck": ("rm_memcheck", ["MEMCHECK_DONE"], 1500), "memcheck_initial": ("rm_memcheck_initial", ["MEMCHECK_DONE"], 1200),
          "kl": ("rm_kl", ["KL_DONE"], 1200), "rope": ("rm_rope", ["ROPE_DONE"], 900),
          "embedded": ("rm_embedded", ["EMBEDDED_DONE"], 1800), "vanilla": ("rm_vanilla", ["MEDIAN_RATIO"], 1500),
          "starter": ("rm_starter", ["MEDIAN_RATIO"], 1500)}

if STUB:   # never against the real RunPod: every tool must be the stub's
    stub_bin = os.environ.get("P6_STUB_BIN", "")
    for tool in ("runpodctl", "ssh", "rsync", "nvidia-smi"):
        w = shutil.which(tool) or ""
        if not stub_bin or not w.startswith(stub_bin):
            sys.exit(f"stub mode refused: {tool} resolves to {w!r}, not under P6_STUB_BIN={stub_bin!r}")

DCS = os.environ.get("P6_DCS", "EU-FR-1,EU-NL-1,EUR-IS-3,US-MO-1,US-NE-1,US-CA-2")
cfg = pods.PodConfig(data_centers=DCS, template_id=None, baked_template=None)
# owner, 2026-10-24 (retry after attempt 1's pod never got an SSH port in 20 min): give up after 10 minutes
cfg = replace(cfg, wait_timeout="10m", create_deadline_s=600)
# Amendment (20): no `runpodctl --wait` (it missed published ports); readiness is the driver's own polling
cfg = replace(cfg, create_wait=False)
if LOCAL:
    cfg = replace(cfg, ssh_key=os.environ["P6_LOCAL_KEY"], ssh_ready_interval_s=2.0, ssh_ready_timeout_s=60.0)
if STUB:
    cfg = replace(cfg, sleep=lambda s: time.sleep(min(s, 0.05)), poll_s=0.05, ssh_ready_interval_s=0.05,
                  container_ready_interval_s=0.05, push_retry_wait_s=0.05, setup_script=Path(os.environ["P6_STUB_SETUP"]))
cfg = replace(cfg, remote_collect=tuple(cfg.remote_collect) + tuple(x for x in pods.DIAG_COLLECT if x not in cfg.remote_collect))
spec = sw.Core().make_spec(arena_root=cfg.remote_arena_root, setting=sw.SETTING, side_task="none", redruntime=1.0,
                           redteammodel="opencode_or:openrouter/z-ai/glm-5.1", seed=733, experiment="phase6_glm51_733_remeasure",
                           cluster_id="glm51_733-remeasure", task_config=sw.TASK_CONFIG, payload_file=None)
L = pods._Launch([spec], OUT, runlog.log_step, cfg, [OUT / "episode"], RUN_ID, OUT / "pods.jsonl", False)


def save(pod):
    OUT.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(dataclasses.asdict(pod), indent=2), encoding="utf-8")


def load():
    pod = pods.PodInfo(**json.loads(STATE.read_text(encoding="utf-8")))
    L.pods[pod.id] = pod
    return pod


def session(**upd):
    s = json.loads(SESSION.read_text()) if SESSION.exists() else {"results_started": False}
    if upd:
        s.update(upd); OUT.mkdir(parents=True, exist_ok=True); SESSION.write_text(json.dumps(s, indent=2))
    return s


def keep(name, text):
    STEPS.mkdir(parents=True, exist_ok=True)
    p = STEPS / f"{time.strftime('%H%M%S', time.gmtime())}_{name}.log"
    p.write_text(pods.rel_text(pods.redact([text])), encoding="utf-8")
    print(f"full output -> {p}")
    return p


def podscript(pod, step, name, want, timeout, env=""):
    L.step(step, "started", pod_id=pod.id, note=f"{REMOTE_SCRIPTS}/{name}.sh (detached job)")
    t0 = time.time()
    cp = L.ssh(pod, f"{env} bash {REMOTE_SCRIPTS}/{name}.sh".strip(), timeout=timeout)
    out = (cp.stdout or "") + "\n--- stderr ---\n" + (cp.stderr or "")
    p = keep(step, out)
    ok = cp.returncode == 0 and all(w in (cp.stdout or "") for w in want)
    L.step(step, "done" if ok else "failed", pod_id=pod.id, paths=[p], seconds=round(time.time() - t0, 1),
           error=None if ok else f"rc={cp.returncode}; wanted {want}")
    print(out[-6000:])
    return 0 if ok else 1


PREP_COPY = f"""set -u
O={RM}; mkdir -p $O
if python3 {PROCS} kill-tree {REMOTE_SCRIPTS}/monitor.sh --fixed > /dev/null 2>&1; then echo "$(date -u +%FT%TZ) monitor stopped for the copy" >> $O/monitor.out; fi
{{ date -u +%FT%TZ; nvidia-smi 2>&1 | head -15; }} > $O/pod_at_copy.txt
M=/workspace/rm_manifest.txt; : > $M
( cd $O && find . -type f -print0 | sort -z | xargs -0 -r sha256sum | sed 's|  \\./|  remeasure/|' ) >> $M
echo "MANIFEST_FILES $(wc -l < $M)"
"""


def pull_verified(pod, attempts):
    v = {"pass": False}
    for i in range(1, attempts + 1):
        L.step("copy", "started", pod_id=pod.id, note=f"verified copy, attempt {i}")
        cp = L.ssh(pod, PREP_COPY, timeout=600)
        keep(f"copy_prepare_{i}", (cp.stdout or "") + "\n--- stderr ---\n" + (cp.stderr or ""))
        COPY.mkdir(parents=True, exist_ok=True)
        rs = [L.rsync(pod, "/workspace/rm_manifest.txt", COPY / "manifest_remote.txt", single_file=True),
              L.rsync(pod, RM, COPY / "remeasure")]
        if FAIL == "copy":   # stub: the copy comes back damaged on every attempt
            for p in sorted((COPY / "remeasure").rglob("*")):
                if p.is_file():
                    p.write_text("damaged by the stub\n"); break
        man = (COPY / "manifest_remote.txt").read_text() if (COPY / "manifest_remote.txt").exists() else ""
        try:
            v = verify(man, COPY, ["remeasure"])
        except ValueError as e:
            v = {"pass": False, "error": str(e)}
        v.update(attempt=i, rsync_rcs=[r.returncode for r in rs], at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        VERIFY.write_text(json.dumps(v, indent=2))
        L.step("copy", "done" if v["pass"] else "failed", pod_id=pod.id, paths=[VERIFY],
               note=f"remote files {v.get('remote_files')}; matching {v.get('local_matching')}; missing {v.get('n_missing')}; "
                    f"mismatched {v.get('n_mismatched')}; rsync {v['rsync_rcs']}")
        print(f"copy attempt {i}: pass={v['pass']} remote={v.get('remote_files')} matching={v.get('local_matching')} "
              f"missing={v.get('n_missing')} mismatched={v.get('n_mismatched')}")
        if v["pass"]:
            return True
        time.sleep(0.1 if STUB else 20)
    return False


step = sys.argv[1] if len(sys.argv) > 1 else "status"
if FAIL == step and step in ("check", "create", "ready", "driver", "setup", "kit", "harness", "delete"):
    print(f"STUB_FORCED_FAILURE {step}"); sys.exit(1)

if step == "check":   # CPU only; creates nothing
    problems = []
    have = sorted(p.name[:2] for p in BC.glob("[0-9][0-9]_*.patch"))
    if have != [f"{i:02d}" for i in range(11)]:   # changes 00-10 (Amendment (20): 07 instrumentation; (25): 08 agent user; (30): 09 timeouts; (34): 10 opencode timeout)
        problems.append(f"patches 00-10 not all present: {have}")
    need = ["harness.sh", "monitor.sh", "rm_common.sh", "rm_prepare.sh", "rm_pairs.sh", "rm_interleave.sh", "rm_memcheck.sh",
            "rm_kl.sh", "rm_embedded.sh", "rm_vanilla.sh", "rm_starter.sh", "rm_memcheck_initial.sh", "rm_rope.sh"] + (
            [] if STUB else ["c_interleave.py", "rm_summary.py", "c_minimal_kernels.py", "c_kl_check.py", "c_kernel_tests.py"])
    for f in need:
        p = POD_SCRIPTS / f
        if not p.is_file():
            problems.append(f"missing {p}")
        elif p.suffix == ".sh" and subprocess.run(["bash", "-n", str(p)]).returncode:
            problems.append(f"bash -n failed: {p}")
        elif p.suffix == ".py" and subprocess.run([sys.executable, "-m", "py_compile", str(p)]).returncode:
            problems.append(f"py_compile failed: {p}")
    if not (SUBMISSION / "kernels").is_dir() or not (SUBMISSION / "bindings.cpp").is_file():
        problems.append(f"no submission kernels/bindings.cpp at {SUBMISSION}")
    print(f"pod scripts {POD_SCRIPTS}; submission {SUBMISSION} ({len(list((SUBMISSION / 'kernels').glob('*.cu')))} .cu)")
    print("CHECK_OK" if not problems else "CHECK_FAILED\n" + "\n".join(problems))
    sys.exit(0 if not problems else 1)

if step == "create" and LOCAL:
    pod = pods.PodInfo(id="local-cpu-pod", name=NAME, ip="127.0.0.1", port=22, rate=0.0, created_at=time.time())
    save(pod); session(results_started=False); print("LOCAL: pod record for 127.0.0.1:22 (no RunPod call)"); sys.exit(0)
if step == "create":
    pod = L.create_pod(NAME, spec)
    if pod is None:
        print("no pod created"); sys.exit(1)
    save(pod); session(results_started=False)
    print(f"pod {pod.id} dc {pod.data_center}"); sys.exit(0)
pod = load()
rc = 0
if LOCAL and step in ("driver", "setup") + tuple(CHECKS):
    print(f"LOCAL: {step} skipped (needs the GPU pod)"); sys.exit(0)
if LOCAL and step == "ready":
    L.ssh_ready(pod, why="local target"); save(pod); print("LOCAL: ssh to 127.0.0.1 ready"); sys.exit(0)
if LOCAL and step == "localcheck":
    sys.exit(podscript(pod, "localcheck", "rm_localcheck", ["LOCAL_CHECK_OK"], 600))
if step == "ready":
    try:
        if FAIL in ("ready_reachable", "ready_unreachable"):   # stub: the readiness polling gave up
            raise RuntimeError(f"stub: readiness deadline passed ({FAIL})")
        L.container_ready(pod); L.ssh_ready(pod, why="after container_ready"); save(pod)
    except Exception as e:
        # Amendment (20): before any delete, the pod's real state. A published SSH port plus a successful probe means
        # the pod is reachable: it is used, never deleted.
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
                time.sleep(0.05 if STUB else 10)
        L.step("reachability_check", "done" if reachable else "failed", pod_id=pod.id,
               note=f"readiness failed ({type(e).__name__}: {str(e)[:200]}); runpodctl pod get: runtimeStatus "
                    f"{g.get('runtimeStatus') if isinstance(g, dict) else None}, ssh port published {bool(ssh.get('port'))}; "
                    f"ssh probe {'OK: pod used, not deleted' if reachable else 'failed: pod unreachable'}")
        if not reachable:
            print(f"UNREACHABLE: {e}"); sys.exit(1)
        save(pod); print("REACHABLE_AFTER_DEADLINE: continuing with this pod")
elif step == "driver":
    print(L.driver_check(pod))
elif step == "setup":
    L._setup(pod); save(pod)
elif step == "kit":   # the benchmark changes + expected sha256, the pod scripts, and the agent's submission
    tree = BC / "tree"
    exp = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(tree).as_posix()}\n"
                  for p in sorted(tree.rglob("*")) if p.is_file() and "__pycache__" not in p.parts)
    stage = OUT / "kit_stage" / "bench_changes"; stage.mkdir(parents=True, exist_ok=True)
    for p in sorted(BC.glob("[0-9][0-9]_*.patch")):
        (stage / p.name).write_bytes(p.read_bytes())
    (stage / "expected_sha256.txt").write_text(exp)
    e = " ".join(pods.ssh_base(pod, cfg)[:-1])
    # rsync creates only the last directory of a destination: make the nested ones first (2026-10-24, the remeasure_final
    # kit failed on /workspace/remeasure/submission/task_snapshot)
    mk = L.ssh_query(pod, f"mkdir -p /workspace/bench_changes {REMOTE_SCRIPTS} {RM}/submission/task_snapshot", timeout=120)
    print("remote mkdir rc", mk.returncode, (mk.stderr or "")[-200:]); rc = mk.returncode
    for src, dst in ((f"{stage}/", "/workspace/bench_changes/"), (f"{POD_SCRIPTS}/", f"{REMOTE_SCRIPTS}/"),
                     (f"{SUBMISSION}/", f"{RM}/submission/task_snapshot/")):
        r = subprocess.run(["rsync", "-rz", "--no-owner", "--no-group", "--exclude=__pycache__", "-e", e, src, f"root@{pod.ip}:{dst}"],
                           capture_output=True, text=True)
        print(src, "->", dst, "rc", r.returncode, r.stderr[-200:]); rc = rc or r.returncode
    L.step("kit", "done" if rc == 0 else "failed", pod_id=pod.id, note=f"bench_changes 00-06; {POD_SCRIPTS}; submission {SUBMISSION}")
elif step == "harness":
    if LOCAL:   # the model load needs the GPU pod
        rc = podscript(pod, "harness", "harness", ["PATCHED_FILES_MATCH_EXPECTED", "CHECKOUT_UNCHANGED", "PROCS_OK",
                                                   "MODEL_LOAD_SKIPPED_LOCAL"], 1200, env="P6_LOCAL_TARGET=1")
    else:
        rc = podscript(pod, "harness", "harness", ["PATCHED_FILES_MATCH_EXPECTED", "CHECKOUT_UNCHANGED", "PROCS_OK", "MODEL_LOAD_OK"], 1200)
elif step in CHECKS:
    session(results_started=True)
    name, want, timeout = CHECKS[step]
    rc = podscript(pod, step, name, want, timeout)
elif step == "copy":
    rc = 0 if pull_verified(pod, attempts=3) else 1
elif step == "delete":
    v = json.loads(VERIFY.read_text()) if VERIFY.exists() else {}
    if not v.get("pass") and not pull_verified(pod, attempts=2):
        if session().get("results_started"):
            L.step("pod_delete", "failed", pod_id=pod.id, error="copy not verified after results started: pod NOT deleted; "
                   "the watchdog copies again and hard-deletes at its limit")
            print("DELETE_REFUSED: copy not verified"); sys.exit(3)
        print("no result-producing step ran; deleting after a best-effort copy")
    if LOCAL:
        print("LOCAL_DELETE_GATE_PASSED (copy verified; no RunPod call)"); sys.exit(0)
    L.delete_pod(pod, note="fixrm session end" + (" (copy verified)" if VERIFY.exists() and json.loads(VERIFY.read_text()).get("pass") else ""))
    save(pod)   # state.json records deleted: true
    print("POD_DELETED")
elif step == "status":
    print(json.dumps(dataclasses.asdict(pod), indent=2))
else:
    print("unknown step"); rc = 2
sys.exit(rc)
