"""The last `[agent]` line's kind (reader.agent_end_line; PLAN Amendment (36) item 2), on every end line solve.sh can
print (agents/opencode/solve.sh 134-195 at the pinned commit)."""
from __future__ import annotations

from control_loop.adapters.researcharena import reader

HEAD = "[agent] phase 1/2: initial opencode run\n[agent] exec finished rc=124 elapsed=3600s remaining_seconds=0\n"
CASES = {
    "[agent] skipping resume (exec used full budget or no time left)": "budget",
    "[agent] resume used remaining budget": "budget",
    "[agent] no time left before resume round 4; stopping": "budget",
    "[agent] phase 2/2: no budget left, skipping": "budget",
    "[agent] resume completed suspiciously fast (14s < 30s); aborting to avoid spin loop": "spin_abort",
    "[agent] exec completed suspiciously fast (8s < 30s); aborting to avoid spin loop": "spin_abort",
    "[agent] resume failed rc=1; stopping resume loop": "rc",
    "[agent] resume round 2 rc=0 elapsed=40s remaining=100s": "rc",
    "[agent] something new": "other",
}


def test_every_solve_sh_end_line_has_its_kind(tmp_path):
    for i, (last, kind) in enumerate(CASES.items()):
        p = tmp_path / f"e{i}.txt"
        p.write_text(HEAD + "opencode output\n" + last + "\ntrailing non-agent line\n")
        assert reader.agent_end_line(p) == (kind, last), last


def test_no_agent_line_or_no_file(tmp_path):
    p = tmp_path / "solve_err.txt"
    p.write_text("no agent lines here\n")
    assert reader.agent_end_line(p) == ("none", None)
    assert reader.agent_end_line(tmp_path / "missing.txt") == ("none", None)


def test_agent_outcome_is_unchanged_by_the_end_line(tmp_path):
    p = tmp_path / "solve_err.txt"
    p.write_text(HEAD + "[agent] resume completed suspiciously fast (14s < 30s); aborting to avoid spin loop\n")
    assert reader.agent_outcome(p) == ("budget", 124)
