"""Final allocation in results.read_run: the sample store (JiraTicketState:assignments)
wins when present; the tool-text parse ("Task X assigned to Y.") is the fallback.
No API calls."""
from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from control_loop import results as R

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = (ROOT / "results/phase3_allocation_monitor/early/prop_sonnet55/733_allocation_rule_autoallow/A1"
             / "2026-10-20T14-11-27-00-00_jira-adaptive_ZyG7xA9QtsKJgvUs6aZTjV.eval")
# P5_MOCK_LOGS: the Phase 5 mock-log directory (the session scratch phase5/mock_logs on the pod); test skipped when unset
_MOCK_LOGS = os.environ.get("P5_MOCK_LOGS")
MOCK_PROTOCOL = Path(_MOCK_LOGS) / "claim_protocol_ref" / "episode_a" if _MOCK_LOGS else None

pytestmark = pytest.mark.skipif(not COMMITTED.exists(), reason="committed phase 3 log not present")


def _tool_text_owner(sample) -> dict[str, str]:
    out = {}
    for e in sample.events:
        if e.event == "tool" and e.function == "assign_task":
            m = re.match(r"Task (\S+) assigned to (\S+)\.", str(e.result or ""))
            if m:
                out[m.group(1)] = m.group(2)
    return out


@pytest.fixture(scope="module")
def committed_log():
    return R.read_eval_log(str(COMMITTED))


def test_store_present_store_wins_and_agrees_with_tool_text(committed_log):
    s = committed_log.samples[0]
    store = s.store["JiraTicketState:assignments"]
    assert isinstance(store, dict) and store
    r = R.read_run(COMMITTED)
    assert r.final_owner == {t: o for t, o in store.items() if o and o != "unassigned"}
    assert r.final_owner == _tool_text_owner(s)  # the two sources agree on an old-style log
    assert r.coalition_tickets == sum(1 for o in r.final_owner.values() if o in r.coalition)
    assert r.total_tickets == 4


def test_store_absent_falls_back_to_tool_text(committed_log, monkeypatch):
    s = committed_log.samples[0]
    expected = _tool_text_owner(s)
    assert expected
    saved = dict(s.store)
    del s.store["JiraTicketState:assignments"]
    try:
        monkeypatch.setattr(R, "read_eval_log", lambda _p: committed_log)
        r = R.read_run(COMMITTED)
    finally:
        s.store.clear(); s.store.update(saved)
    assert r.final_owner == expected
    assert r.coalition_tickets == sum(1 for o in expected.values() if o in r.coalition)


def test_helper_on_minimal_fake_sample():
    assert R.final_allocation_from_store(SimpleNamespace(store={})) is None
    assert R.final_allocation_from_store(SimpleNamespace(store=None)) is None
    fake = SimpleNamespace(store={"JiraTicketState:assignments": {"TASK-1": "dev_0", "TASK-2": "unassigned", "TASK-3": None}})
    assert R.final_allocation_from_store(fake) == {"TASK-1": "dev_0"}


@pytest.mark.skipif(MOCK_PROTOCOL is None or not MOCK_PROTOCOL.exists(),
                    reason="P5_MOCK_LOGS unset or the phase 5 mock protocol log not on this host")
def test_mock_protocol_log_has_owners_from_store():
    p = R.latest_log(MOCK_PROTOCOL)
    log = R.read_eval_log(p)
    s = log.samples[0]
    assert _tool_text_owner(s) == {}  # protocol episode: no "assigned to" tool text
    r = R.read_run(p)
    store = s.store["JiraTicketState:assignments"]
    assert r.final_owner and r.final_owner == {t: o for t, o in store.items() if o and o != "unassigned"}
    assert r.coalition_tickets == sum(1 for o in r.final_owner.values() if o in r.coalition) > 0
