"""No-network tests of the agent-run model-spend cap (control_loop/adapters/researcharena/spend_monitor.py; PLAN
Amendment (19) item 4: $20 cap, usage read every 2 minutes)."""
from __future__ import annotations

import threading

import pytest

from control_loop.adapters.researcharena import spend_monitor as sm


def make(readings, cap=20.0):
    seq, logs, stops = list(readings), [], []

    def fetch():
        v = seq.pop(0)
        if isinstance(v, Exception):
            raise v
        return v
    m = sm.SpendMonitor(cap, lambda: stops.append(1), logs.append, fetch=fetch, interval_s=120)
    return m, logs, stops


def test_stops_once_when_the_cap_is_reached():
    m, logs, stops = make([100.0, 105.0, 119.9, 120.0, 130.0])
    m.begin()
    for _ in range(4):
        m.check_once()
    assert stops == [1] and m.stopped and any("SPEND CAP REACHED: $20.0000" in l for l in logs)


def test_below_cap_never_stops():
    m, logs, stops = make([50.0, 51.0, 60.0, 69.99])
    m.begin()
    for _ in range(3):
        m.check_once()
    assert stops == [] and logs[-1] == "spend $19.9900 of $20.00"


def test_failed_reads_never_stop_the_agent():
    err = RuntimeError("HTTP 500")
    m, logs, stops = make([10.0] + [err] * 10 + [12.0])
    m.begin()
    for _ in range(11):
        m.check_once()
    assert stops == [] and m.errors == 10 and logs[-1] == "spend $2.0000 of $20.00"


def test_unreadable_start_uses_the_first_good_read():
    err = OSError("dns")
    m, logs, stops = make([err, err, err, 40.0, 61.0])
    assert m.begin() is None
    m.check_once()                       # 40.0 becomes the start
    m.check_once()                       # 61.0 - 40.0 = 21 >= 20
    assert m.start_usage == 40.0 and stops == [1]


def test_thread_polls_on_the_interval_and_finish_reports_spend():
    waits = []
    m, logs, stops = make([5.0, 6.0, 7.0, 8.5])

    def wait(ev, s):                     # three polls, then the episode ends
        waits.append(s)
        if len(waits) > 2:
            ev.set()
        return ev.is_set()
    m.wait = wait
    m.start()
    assert m.finish() == pytest.approx(3.5) and all(w == 120 for w in waits) and stops == []


def test_key_comes_from_the_environment_only(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(KeyError):
        sm.openrouter_usage()
