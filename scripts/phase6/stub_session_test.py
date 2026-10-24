"""CPU rehearsal of the re-measure session with a stub GPU (owner, 2026-10-24, item 4: "run the whole session script
end to end on the CPU pod with a stub GPU, including forcing each step to fail, to show every failure path still runs the
remaining checks and the copy. No GPU until that passes").

The real scripts/phase6/remeasure.sh and remeasure.py run against the test suite's fake runpodctl, ssh and nvidia-smi
(tests/test_researcharena_pods.py) and an rsync fake extended for pushes. The pod scripts are the stubs in
scripts/phase6_stub_pod/, which print each step's markers or fail when $P6_FAIL_STEP names them. One case with no
failure, then one forced failure per step. For each case the expected steps must run, the copy must verify where results
exist, and the pod must be deleted, or kept for the watchdog when the copy cannot be verified.

    uv run --frozen python scripts/phase6/stub_session_test.py      (from the repository root; no network, no pod)"""
import importlib.util, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("tpods", REPO / "tests" / "test_researcharena_pods.py")
tp = importlib.util.module_from_spec(spec); sys.modules["tpods"] = tp; spec.loader.exec_module(tp)   # dataclasses need the module registered

RSYNC = r'''#!/usr/bin/env python3
import os, shutil, sys
a = sys.argv[1:]
src, dst = a[-2], a[-1]
def pod_path(spec):
    ip, remote = spec[5:].split(":", 1)
    root = os.path.join(os.environ["FAKE_PODS"], ip)
    if not os.path.isdir(root):
        sys.stderr.write("rsync: connection refused\n"); sys.exit(255)
    return remote.replace("/workspace", os.path.join(root, "workspace"))
if dst.startswith("root@"):          # push: local -> pod
    path = pod_path(dst)
    parent = os.path.dirname(path.rstrip("/"))
    if not os.path.isdir(parent):     # as real rsync: only the last directory of the destination is created
        sys.stderr.write('rsync: [Receiver] mkdir "%s" failed: No such file or directory (2)\n' % dst.split(":", 1)[1].rstrip("/"))
        sys.exit(11)
    if src.endswith("/") and os.path.isdir(src):
        shutil.copytree(src, path.rstrip("/"), dirs_exist_ok=True)
    else:
        os.makedirs(os.path.dirname(path.rstrip("/")) or ".", exist_ok=True); shutil.copy2(src, path)
    sys.exit(0)
path = pod_path(src).rstrip("/")
if not os.path.exists(path):
    sys.stderr.write("rsync: no such file %s\n" % src); sys.exit(23)
if os.path.isdir(path):
    shutil.copytree(path, dst.rstrip("/"), dirs_exist_ok=True)
else:
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True); shutil.copy2(path, dst)
'''

CORE = ["ready", "driver", "setup", "kit", "harness"]
CHECKS = ["prepare", "interleave", "memcheck", "memcheck_initial", "kl", "embedded", "rope", "vanilla", "starter"]
ALL = ["check", "create"] + CORE + CHECKS + ["copy", "delete"]


def run_case(fail):
    t = Path(tempfile.mkdtemp(prefix=f"stubrm_{fail or 'none'}_"))
    b = t / "bin"; b.mkdir()
    for name, text in (("runpodctl", tp.RUNPODCTL), ("ssh", tp.SSH), ("rsync", RSYNC), ("nvidia-smi", tp.NVIDIA_SMI)):
        (b / name).write_text(text); (b / name).chmod(0o755)
    (t / "mock_run_redteam.sh").write_text(tp.MOCK_RUN_REDTEAM); (t / "mock_run_redteam.sh").chmod(0o755)
    (t / "setup_stub.sh").write_text("echo stub setup\n")
    sub = t / "submission"; (sub / "kernels").mkdir(parents=True)
    (sub / "kernels" / "rmsnorm.cu").write_text("// agent kernel (stub)\n"); (sub / "bindings.cpp").write_text("// bindings\n")
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", FAKE_RP_STATE=str(t / "rp"), FAKE_PODS=str(t / "pods"),
               MOCK_RUN_REDTEAM=str(t / "mock_run_redteam.sh"), OPENROUTER_API_KEY=tp.DUMMY_KEY,
               P6_STUB_RUN="1", P6_STUB_BIN=str(b), P6_OUT_DIR=str(t / "out"), P6_POD_SCRIPTS="scripts/phase6_stub_pod",
               P6_SUBMISSION_DIR=str(sub), P6_STUB_SETUP=str(t / "setup_stub.sh"), P6_FAIL_STEP=fail,
               P6_REPO=str(REPO), P6_RUNNER=f"{sys.executable} scripts/phase6/remeasure.py")
    for v in ("FAKE_MAX_PODS", "FAKE_SETUP_FAIL", "FAKE_EXTRA_PODS", "FAKE_NOT_READY_GETS", "FAKE_SSH_FAIL_DIR"):
        env.pop(v, None)
    if fail == "ready_unreachable":   # every ssh probe fails: the pod is up but not reachable
        (t / "sshfail").mkdir(); (t / "sshfail" / "probe").write_text("-1"); env["FAKE_SSH_FAIL_DIR"] = str(t / "sshfail")
    r = subprocess.run(["bash", "scripts/phase6/remeasure.sh"], cwd=REPO, env=env, capture_output=True, text=True, timeout=900)
    log = r.stdout
    ran = [l.split()[1] for l in log.splitlines() if l.startswith("=== ")]
    failed = [l.split()[1] for l in log.splitlines() if l.startswith("STEP_FAILED ")]
    st = json.loads((t / "rp" / "pods.json").read_text()) if (t / "rp" / "pods.json").exists() else {"pods": {}}
    created = len(st["pods"]); alive = sum(1 for p in st["pods"].values() if not p["deleted"])
    vf = t / "out" / "copy_verify.json"
    v = json.loads(vf.read_text()) if vf.exists() else {}
    res = {"ran": ran, "failed": failed, "created": created, "alive": alive, "copy_pass": v.get("pass"),
           "copy_files": v.get("remote_files"), "skipped_checks": "CHECKS_SKIPPED" in log, "log": log, "tmp": str(t)}
    return res


def expect(fail, r):
    """(ok, why) for one case."""
    if fail == "":
        want = ALL
        return (r["ran"] == want and not r["failed"] and r["copy_pass"] and r["created"] == 1 and r["alive"] == 0,
                "every step ran, none failed, copy verified, pod deleted")
    if fail == "check":
        return (r["ran"] == ["check"] and r["created"] == 0, "nothing created")
    if fail == "create":
        return (r["ran"] == ["check", "create"] and r["alive"] == 0, "no pod; nothing further")
    if fail in CORE:
        upto = ALL[:ALL.index(fail) + 1] + ["copy", "delete"]
        return (r["ran"] == upto and r["failed"] == [fail] and r["skipped_checks"] and r["alive"] == 0,
                "checks skipped (core failure), copy ran, pod deleted (no results existed)")
    if fail in CHECKS:
        return (r["ran"] == ALL and r["failed"] == [fail] and r["copy_pass"] and r["alive"] == 0,
                "every later check ran, copy verified, pod deleted")
    if fail == "ready_reachable":
        return (r["ran"] == ALL and not r["failed"] and r["copy_pass"] and r["alive"] == 0,
                "readiness gave up, the real-state check found the pod reachable: used, not deleted; every step ran")
    if fail == "ready_unreachable":
        upto = ALL[:ALL.index("ready") + 1] + ["copy", "delete"]
        return (r["ran"] == upto and r["failed"] == ["ready"] and r["skipped_checks"] and r["alive"] == 0,
                "readiness gave up and every probe failed: unreachable, checks skipped, copy ran, pod deleted")
    if fail == "copy":
        return (r["ran"] == ALL and r["failed"] == ["copy", "delete"] and r["copy_pass"] is False and r["alive"] == 1,
                "copy not verified: delete refused, pod left for the watchdog's copy and hard delete")
    if fail == "delete":
        return (r["ran"] == ALL and r["failed"] == ["delete"] and r["copy_pass"] and r["alive"] == 1,
                "copy verified; the delete failure is reported, the pod is left for the watchdog")
    return (False, "unknown case")


ok_all = True
for fail in [""] + ALL + ["ready_reachable", "ready_unreachable"]:
    r = run_case(fail)
    ok, why = expect(fail, r)
    ok_all &= ok
    print(f"{'PASS' if ok else 'FAIL'}  fail={fail or 'none':10s} ran={len(r['ran']):2d} steps, failed={r['failed']}, "
          f"copy_pass={r['copy_pass']} ({r['copy_files']} files), pods created={r['created']} alive={r['alive']}: {why}")
    if not ok:
        print("      ran:", r["ran"]); print("      log tail:\n" + "\n".join("      " + l for l in r["log"].splitlines()[-12:]))
    else:
        shutil.rmtree(r["tmp"], ignore_errors=True)
print("STUB_SESSION_TEST", "PASS" if ok_all else "FAIL"); sys.exit(0 if ok_all else 1)
