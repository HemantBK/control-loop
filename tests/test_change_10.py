"""Benchmark change 10 (PLAN Amendment (34)): the local (no-container) branch of pipeline_redteam.sh exports opencode's own
shell-tool timeout, OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS=3600000, before the agent starts (change 09's
BASH_*_TIMEOUT_MS are not read by opencode). Every script that ships the patches picks up 00-10."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BC = ROOT / "phases" / "phase6_researcharena" / "benchmark_changes"
PIPE = BC / "tree" / "src" / "pipeline_redteam.sh"
NAME = "OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS"
GLOB = "[0-9][0-9]_*.patch"
SHIPPERS = ["scripts/phase6_pod/harness.sh", "scripts/phase6/cell_step.py", "scripts/phase6/remeasure.py",
            "scripts/phase6/supervised.py"]


def local_branch():
    s = PIPE.read_text()
    local = s[s.index("running locally."):]
    return local[:local.index("\nfi\n")]


def test_local_branch_exports_opencodes_timeout_before_the_agent():
    local = local_branch()
    got = re.search(rf"export {NAME}=(\d+)", local)
    assert got and got.group(1) == "3600000"
    assert local.index(f"export {NAME}=") < local.index('agent_solve.sh"')
    assert NAME not in PIPE.read_text().replace(local, "")   # the container branch is unchanged


def test_the_export_reaches_the_agents_environment():
    lines = [l.strip() for l in local_branch().splitlines() if l.strip().startswith(f"export {NAME}=")]
    assert len(lines) == 1
    out = subprocess.run(["bash", "-c", lines[0] + "; env"], capture_output=True, text=True).stdout
    assert f"{NAME}=3600000" in out.splitlines()


def test_patch_has_its_reason_header_and_touches_only_the_pipeline():
    text = (BC / "10_opencode_command_timeout.patch").read_text()
    assert text.startswith("# Benchmark change 10:") and "Reason:" in text and "Amendment (34)" in text
    assert re.findall(r"^\+\+\+ b/(\S+)", text, flags=re.M) == ["src/pipeline_redteam.sh"]
    added = [l for l in text.splitlines() if l.startswith("+") and not l.startswith("+++")]
    assert [l for l in added if not l.lstrip("+").strip().startswith("#")] == [f"+        export {NAME}=3600000"]
    assert not [l for l in text.splitlines() if l.startswith("-") and not l.startswith("---")]


def test_the_patch_glob_ships_00_to_10_in_order():
    assert [p.name[:2] for p in sorted(BC.glob(GLOB))] == [f"{i:02d}" for i in range(11)]
    for f in SHIPPERS:
        s = (ROOT / f).read_text()
        assert "0*.patch" not in s and GLOB in s, f


@pytest.mark.skipif(not os.environ.get("RESEARCHARENA_ROOT"), reason="RESEARCHARENA_ROOT not set (pinned checkout absent)")
def test_the_chain_from_the_pinned_checkout_gives_the_tree_file(tmp_path):
    """Every patch applied in order to real copies of the pinned files (as harness.sh does) gives tree/'s pipeline."""
    src = Path(os.environ["RESEARCHARENA_ROOT"])
    patches = sorted(BC.glob(GLOB))
    for rel in {m for p in patches for m in re.findall(r"^\+\+\+ b/(\S+)", p.read_text(), flags=re.M)}:
        if (src / rel).is_file():
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / rel, tmp_path / rel)
    for p in patches:
        r = subprocess.run(["patch", "-p1", "-s", "-f", "--no-backup-if-mismatch", "-i", str(p)], cwd=tmp_path,
                           capture_output=True, text=True)
        assert r.returncode == 0, (p.name, r.stdout, r.stderr)
    assert (tmp_path / "src" / "pipeline_redteam.sh").read_bytes() == PIPE.read_bytes()


@pytest.mark.skipif(not shutil.which("opencode"), reason="opencode not installed")
def test_installed_opencode_reads_the_variable_and_not_change_09s():
    data = Path(os.path.realpath(shutil.which("opencode"))).read_bytes()
    assert NAME.encode() in data
    assert b"BASH_DEFAULT_TIMEOUT_MS" not in data.replace(NAME.encode(), b"")


def test_pod_setup_fails_when_opencode_does_not_read_the_variable(tmp_path):
    """pod_setup.sh step 2 ends with a guard on the installed opencode; run it against a stand-in binary without the name."""
    s = (ROOT / "control_loop" / "adapters" / "researcharena" / "pod_setup.sh").read_text()
    step2 = s[s.index("step2() {"):]
    step2 = step2[:step2.index("\n}\n") + 3]
    guard = [l for l in step2.splitlines() if NAME in l or "OPENCODE_IGNORES_TIMEOUT_VAR" in l]
    assert len(guard) == 2 and "return 1" in guard[1]
    fake = tmp_path / "bin" / "opencode"; fake.parent.mkdir(); fake.write_text("#!/bin/sh\necho 9.9.9\n"); fake.chmod(0o755)
    body = "f() {\n" + "\n".join(guard) + "\n}\nf; echo rc=$?"
    out = subprocess.run(["bash", "-c", body], capture_output=True, text=True,
                         env={"PATH": f"{fake.parent}:/usr/bin:/bin"}).stdout
    assert "OPENCODE_IGNORES_TIMEOUT_VAR" in out and "rc=1" in out
    fake.write_text(f"#!/bin/sh\n# {NAME}\n")
    out = subprocess.run(["bash", "-c", body], capture_output=True, text=True,
                         env={"PATH": f"{fake.parent}:/usr/bin:/bin"}).stdout
    assert out.strip() == "rc=0"
