"""Model-spend cap for one Phase 6 agent episode (PLAN Amendment (19) item 4; owner, 2026-10-24: "Model cap $20 with
the 2-minute usage check"). While the episode runs, a thread reads the OpenRouter key's cumulative usage
(`GET https://openrouter.ai/api/v1/key`, field data.usage, US dollars) every `interval_s` seconds. When usage since the
start reaches the cap, it calls `stop()` once (the runner stops the agent on the pod; the pipeline then evaluates what
the agent left). A failed read is logged and retried; it never stops the agent. The key is read from the environment
($OPENROUTER_API_KEY, loaded by `uv run --env-file`), never from a file, and is never logged."""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from typing import Callable

KEY_URL = "https://openrouter.ai/api/v1/key"


def openrouter_usage(timeout: float = 20.0) -> float:
    """Cumulative usage of the key in $OPENROUTER_API_KEY, in US dollars. Raises on any failure."""
    key = os.environ["OPENROUTER_API_KEY"]
    req = urllib.request.Request(KEY_URL, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return float(data["data"]["usage"])


class SpendMonitor:
    def __init__(self, cap_usd: float, stop: Callable[[], None], log: Callable[[str], None], *,
                 fetch: Callable[[], float] = openrouter_usage, interval_s: float = 120.0,
                 wait: Callable[[threading.Event, float], bool] | None = None):
        self.cap, self.stop_fn, self.log, self.fetch, self.interval = cap_usd, stop, log, fetch, interval_s
        self.wait = wait or (lambda ev, s: ev.wait(s))
        self.done = threading.Event()
        self.start_usage: float | None = None
        self.last_usage: float | None = None
        self.stopped = False
        self.errors = 0
        self._thread: threading.Thread | None = None

    def _read(self) -> float | None:
        try:
            u = self.fetch()
            self.last_usage = u
            return u
        except Exception as e:   # a failed read is never a reason to stop the agent
            self.errors += 1
            self.log(f"spend read failed ({type(e).__name__}); retrying in {self.interval:.0f} s")
            return None

    def begin(self) -> float | None:
        """Read the starting usage (retried up to 3 times). Returns it, or None if it could not be read."""
        for _ in range(3):
            u = self._read()
            if u is not None:
                self.start_usage = u
                self.log(f"spend monitor start: usage ${u:.4f}, cap ${self.cap:.2f} over it, every {self.interval:.0f} s")
                return u
        self.log("spend monitor: starting usage unreadable; the cap is measured from the first good read")
        return None

    def check_once(self) -> None:
        u = self._read()
        if u is None:
            return
        if self.start_usage is None:
            self.start_usage = u
            return
        spent = u - self.start_usage
        if spent >= self.cap and not self.stopped:
            self.stopped = True
            self.log(f"SPEND CAP REACHED: ${spent:.4f} >= ${self.cap:.2f}; stopping the agent")
            self.stop_fn()
        else:
            self.log(f"spend ${spent:.4f} of ${self.cap:.2f}")

    def run(self) -> None:
        while not self.wait(self.done, self.interval):
            self.check_once()

    def start(self) -> None:
        if self.start_usage is None:
            self.begin()
        self._thread = threading.Thread(target=self.run, name="spend-monitor", daemon=True)
        self._thread.start()

    def finish(self) -> float | None:
        """Stop the thread; read the final usage. Returns the spend since the start, or None if unknown."""
        self.done.set()
        if self._thread:
            self._thread.join(timeout=60)
        u = self._read()
        if u is None or self.start_usage is None:
            return None
        return u - self.start_usage
