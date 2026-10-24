"""No-network tests of the per-session watchdog (control_loop/adapters/researcharena/session_watchdog.py; PLAN Amendment
(19) item 6). The fullrun2 watchdog exited on a failed listing with its pod still running (2026-10-23): a failed listing
must never count as "pod gone"."""
from __future__ import annotations

import subprocess

import pytest

from control_loop.adapters.researcharena import session_watchdog as wd

POD = {"id": "p1", "name": "p6-x", "createdAt": "2026-10-24T10:00:00Z", "costPerHr": 3.99, "uptimeSeconds": 60}
T0 = wd.parse_time(POD["createdAt"])


def drive(listings, limit_s=7200, limit_usd=8.0, max_polls=None):
    """Run the loop over a scripted sequence of listings (a list, or an exception instance to raise)."""
    seq, logs, deleted = list(listings), [], []
    clock = {"t": T0 + 60}

    def lister():
        item = seq.pop(0) if seq else []
        if isinstance(item, Exception):
            raise item
        return item

    def sleep(s):
        clock["t"] += s

    why = wd.run("p6-x", limit_s, limit_usd, logs.append, lister=lister, deleter=lambda i: deleted.append(i) or 0,
                 now=lambda: clock["t"], sleep=sleep, max_polls=max_polls if max_polls is not None else len(listings) + 5)
    return why, logs, deleted


def test_failed_listings_never_end_the_watch():
    err = wd.ListingError("runpodctl pod list rc=1: connection reset")
    why, logs, _ = drive([[POD]] + [err] * 20, max_polls=21)
    assert why == "max polls"                                   # still watching after 20 failed listings
    assert sum("not counted as gone" in l for l in logs) == 20 and not any("gone (" in l for l in logs)


def test_failed_listings_reset_nothing_and_pod_seen_again_keeps_watching():
    err = wd.ListingError("timeout")
    why, logs, _ = drive([[POD], [], err, [], err, [POD], [], []], max_polls=8)
    assert why == "max polls" and not any("watchdog exits" in l for l in logs)


def test_three_consecutive_successful_empty_listings_end_the_watch():
    why, logs, _ = drive([[POD], [], [], []])
    assert why == "gone" and "pod not in listing (1/3)" in logs and "pod not in listing (2/3)" in logs


def test_list_pods_raises_on_nonzero_rc_and_bad_json(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "boom"))
    with pytest.raises(wd.ListingError):
        wd.list_pods()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    with pytest.raises(wd.ListingError):     # empty stdout is not an empty list
        wd.list_pods()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "[]", ""))
    assert wd.list_pods() == []


def test_hard_delete_at_the_dollar_limit():
    why, logs, deleted = drive([[POD]] * 40 + [[], [], []], limit_usd=0.5)
    assert deleted and deleted[0] == "p1" and any("HARD DELETE p1" in l for l in logs) and why == "gone"
