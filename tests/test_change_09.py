"""Benchmark change 09 (PLAN Amendment (30) item 1): pipeline_redteam.sh's local (no-container) branch exports the same
command timeouts its container branch passes to the agent, before the agent starts; nothing else in the branch changes."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BC = ROOT / "phases" / "phase6_researcharena" / "benchmark_changes"
PIPE = BC / "tree" / "src" / "pipeline_redteam.sh"
NAMES = ("BASH_MAX_TIMEOUT_MS", "BASH_DEFAULT_TIMEOUT_MS")


def branches():
    s = PIPE.read_text()
    container = s[s.index('if [[ -f "$CONTAINER_SIF" ]]; then'):s.index("running locally.")]
    local = s[s.index("running locally."):]
    local = local[:local.index("\nfi\n")]
    return container, local


def test_local_branch_exports_the_container_branchs_timeouts_before_the_agent():
    container, local = branches()
    for n in NAMES:
        want = re.search(rf'--env "{n}=(\d+)"', container).group(1)
        got = re.search(rf"export {n}=(\d+)", local)
        assert got and got.group(1) == want == "3600000", n
        assert local.index(f"export {n}=") < local.index('agent_solve.sh"')


def test_the_exported_values_reach_the_agents_environment(tmp_path):
    """The branch's export lines run in a shell, and a child (the agent) sees them."""
    _, local = branches()
    lines = [l.strip() for l in local.splitlines() if re.match(r"\s*export BASH_(MAX|DEFAULT)_TIMEOUT_MS=", l)]
    out = subprocess.run(["bash", "-c", "; ".join(lines) + "; env"], capture_output=True, text=True).stdout
    assert "BASH_MAX_TIMEOUT_MS=3600000" in out and "BASH_DEFAULT_TIMEOUT_MS=3600000" in out


def test_patch_has_its_reason_header_and_touches_only_the_pipeline():
    p = BC / "09_local_branch_command_timeouts.patch"
    text = p.read_text()
    assert text.startswith("# Benchmark change 09:") and "Reason:" in text and "Amendment (30)" in text
    assert re.findall(r"^\+\+\+ b/(\S+)", text, flags=re.M) == ["src/pipeline_redteam.sh"]
    added = [l for l in text.splitlines() if l.startswith("+") and not l.startswith("+++")]
    assert all("TIMEOUT_MS" in l or l.lstrip("+").strip().startswith("#") for l in added)
