"""Structured run log: one ``run.jsonl`` per run directory (owner's rule of 2026-10-21, docs/SOP.md §3).

Every driver (check, sweep cell, pass) appends one JSON line per step through :func:`log_step`.
``python -m control_loop.status [root ...]`` reads every ``run.jsonl`` below the given roots and
prints one row per run: the last step, its status, the cumulative cost and the last error. Paths
in the log are repository-relative (``control_loop.paths.rel``); nothing here makes a model call.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from control_loop.paths import rel

FILENAME = "run.jsonl"
STATUSES = ("started", "done", "failed", "skipped", "stopped")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log_step(
    run_dir: str | os.PathLike,
    *,
    phase: str,
    run_id: str,
    step: str,
    status: str,
    cost_usd: float | None = None,
    error: str | None = None,
    paths: Iterable[str | os.PathLike] | None = None,
    note: str | None = None,
    **extra: Any,
) -> dict:
    """Append one line to ``<run_dir>/run.jsonl`` and return the record."""
    if status not in STATUSES:
        raise ValueError(f"status {status!r} not in {STATUSES}")
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    rec: dict[str, Any] = {
        "ts": _now(),
        "phase": phase,
        "run_id": run_id,
        "step": step,
        "status": status,
        "cost_usd": None if cost_usd is None else round(float(cost_usd), 6),
        "error": error,
        "paths": [rel(p) for p in (paths or [])],
        "note": note,
    }
    rec.update(extra)
    with open(run_dir / FILENAME, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def read_run(run_dir: str | os.PathLike) -> list[dict]:
    p = Path(run_dir) / FILENAME
    if not p.exists():
        return []
    out = []
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


@dataclass
class RunSummary:
    run_dir: str
    phase: str
    run_id: str
    steps: int
    last_step: str
    last_status: str
    cost_usd: float
    failed: int
    last_error: str | None
    first_ts: str
    last_ts: str
    paths: list[str] = field(default_factory=list)

    def row(self) -> dict:
        return {
            "run_dir": self.run_dir, "phase": self.phase, "run_id": self.run_id,
            "steps": self.steps, "last_step": self.last_step, "last_status": self.last_status,
            "cost_usd": round(self.cost_usd, 4), "failed": self.failed,
            "last_error": self.last_error, "first_ts": self.first_ts, "last_ts": self.last_ts,
        }


def summarize(records: list[dict], run_dir: str) -> RunSummary | None:
    if not records:
        return None
    cost = sum(r.get("cost_usd") or 0.0 for r in records)
    failed = sum(1 for r in records if r.get("status") == "failed")
    errs = [r.get("error") for r in records if r.get("error")]
    paths: list[str] = []
    for r in records:
        for p in r.get("paths") or []:
            if p not in paths:
                paths.append(p)
    last = records[-1]
    return RunSummary(
        run_dir=rel(run_dir), phase=str(last.get("phase")), run_id=str(last.get("run_id")),
        steps=len(records), last_step=str(last.get("step")), last_status=str(last.get("status")),
        cost_usd=cost, failed=failed, last_error=errs[-1] if errs else None,
        first_ts=str(records[0].get("ts")), last_ts=str(last.get("ts")), paths=paths,
    )


def iter_runs(roots: Iterable[str | os.PathLike]) -> Iterator[RunSummary]:
    for root in roots:
        root = Path(root)
        if root.is_file() and root.name == FILENAME:
            s = summarize(read_run(root.parent), str(root.parent))
            if s:
                yield s
            continue
        for p in sorted(root.rglob(FILENAME)):
            s = summarize(read_run(p.parent), str(p.parent))
            if s:
                yield s


def format_table(runs: Iterable[RunSummary]) -> str:
    rows = [r.row() for r in runs]
    if not rows:
        return "no run.jsonl found"
    cols = ["phase", "run_id", "last_step", "last_status", "steps", "failed", "cost_usd", "last_ts", "run_dir", "last_error"]
    widths = {c: max(len(c), *(len(str(r.get(c) if r.get(c) is not None else "")) for r in rows)) for c in cols}
    line = " | ".join(c.ljust(widths[c]) for c in cols)
    sep = "-+-".join("-" * widths[c] for c in cols)
    body = [" | ".join(str(r.get(c) if r.get(c) is not None else "").ljust(widths[c]) for c in cols) for r in rows]
    # A driver may log cost both on a parent run (a cell) and on its episode sub-runs; sum leaves only.
    dirs = [r["run_dir"].rstrip("/") for r in rows]
    leaf = [r for r, d in zip(rows, dirs) if not any(o != d and o.startswith(d + "/") for o in dirs)]
    total = sum(r["cost_usd"] for r in leaf)
    return "\n".join([line, sep, *body, f"total cost_usd {total:.4f} over {len(leaf)} leaf runs ({len(rows)} rows; a parent run's cost is not added to its sub-runs')"])
