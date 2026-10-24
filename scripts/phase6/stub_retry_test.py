"""CPU rehearsal of scripts/phase6/remeasure_retry.sh with a stub GPU (owner, 2026-10-24: one more pod right away if a pod
fails to come up; after two failed pods, stop and report). Same fakes and stub pod scripts as stub_session_test.py.

    uv run --frozen python scripts/phase6/stub_retry_test.py      (from the repository root; no network, no pod)"""
import importlib.util, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("stubsess", REPO / "scripts" / "phase6" / "stub_session_test.py")
src = (REPO / "scripts" / "phase6" / "stub_session_test.py").read_text()
ns = {"__file__": str(REPO / "scripts" / "phase6" / "stub_session_test.py"), "__name__": "stubsess"}
exec(compile(src.split("ok_all = True")[0], "stub_session_test.py", "exec"), ns)   # the fakes and helpers, not its cases
tp, RSYNC = ns["tp"], ns["RSYNC"]


def run(fail_a, fail_b):
    t = Path(tempfile.mkdtemp(prefix=f"stubretry_{fail_a or 'none'}_{fail_b or 'none'}_"))
    b = t / "bin"; b.mkdir()
    for name, text in (("runpodctl", tp.RUNPODCTL), ("ssh", tp.SSH), ("rsync", RSYNC), ("nvidia-smi", tp.NVIDIA_SMI)):
        (b / name).write_text(text); (b / name).chmod(0o755)
    (t / "mock_run_redteam.sh").write_text(tp.MOCK_RUN_REDTEAM); (t / "mock_run_redteam.sh").chmod(0o755)
    (t / "setup_stub.sh").write_text("echo stub setup\n")
    sub = t / "submission"; (sub / "kernels").mkdir(parents=True)
    (sub / "kernels" / "rmsnorm.cu").write_text("// agent kernel (stub)\n"); (sub / "bindings.cpp").write_text("// b\n")
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", FAKE_RP_STATE=str(t / "rp"), FAKE_PODS=str(t / "pods"),
               MOCK_RUN_REDTEAM=str(t / "mock_run_redteam.sh"), OPENROUTER_API_KEY=tp.DUMMY_KEY,
               P6_STUB_RUN="1", P6_STUB_BIN=str(b), P6_POD_SCRIPTS="scripts/phase6_stub_pod", P6_SUBMISSION_DIR=str(sub),
               P6_STUB_SETUP=str(t / "setup_stub.sh"), P6_FAIL_STEP_A=fail_a, P6_FAIL_STEP_B=fail_b, P6_REPO=str(REPO),
               P6_RM_BASE=str(t / "out"), P6_RUNNER=f"{sys.executable} scripts/phase6/remeasure.py")
    r = subprocess.run(["bash", "scripts/phase6/remeasure_retry.sh"], cwd=REPO, env=env, capture_output=True, text=True, timeout=900)
    st = json.loads((t / "rp" / "pods.json").read_text()) if (t / "rp" / "pods.json").exists() else {"pods": {}}
    names = [p["name"] for p in st["pods"].values()]
    alive = sum(1 for p in st["pods"].values() if not p["deleted"])
    end = [l for l in r.stdout.splitlines() if l.startswith("RETRY_SESSION_END")]
    attempts = [l.split()[2].rstrip(":") for l in r.stdout.splitlines() if l.startswith("##### attempt")]
    shutil.rmtree(t, ignore_errors=True)
    return {"end": end[-1] if end else None, "attempts": attempts, "pods": names, "alive": alive, "out": r.stdout}


CASES = [("", "", "measured", ["A"], ["p6-fixrmA"]),
         ("create", "", "measured", ["A", "B"], ["p6-fixrmB"]),
         ("ready", "", "measured", ["A", "B"], ["p6-fixrmA", "p6-fixrmB"]),
         ("ready", "ready", "two_pods_failed", ["A", "B"], ["p6-fixrmA", "p6-fixrmB"]),
         ("harness", "", "stopped_on_failure (rc=1)", ["A"], ["p6-fixrmA"])]
ok_all = True
for fa, fb, want_end, want_att, want_pods in CASES:
    r = run(fa, fb)
    ok = (r["end"] == f"RETRY_SESSION_END {want_end}" and r["attempts"] == want_att and sorted(r["pods"]) == want_pods
          and r["alive"] == 0)
    ok_all &= ok
    print(f"{'PASS' if ok else 'FAIL'}  A fails={fa or 'none':8s} B fails={fb or 'none':6s} -> {r['end']}; attempts {r['attempts']}; "
          f"pods {r['pods']}, alive {r['alive']}")
    if not ok:
        print("\n".join("      " + l for l in r["out"].splitlines()[-15:]))
print("STUB_RETRY_TEST", "PASS" if ok_all else "FAIL"); sys.exit(0 if ok_all else 1)
