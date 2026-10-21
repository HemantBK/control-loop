"""Repo-relative paths for everything written under results/ (no absolute paths in tracked files).

Commands keep absolute paths in memory where they need them; writers pass their text through `rel_text`
(or use `write_json` / `write_text`) so the repository root never reaches disk. Paths outside the
repository are left as they are. Readers are unchanged: written paths are relative to the repository
root, the cwd every episode and driver runs from.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def rel(path: str | Path) -> str:
    """`path` relative to the repository root if it lies under it; otherwise (or if already relative)
    unchanged."""
    p = Path(path)
    if not p.is_absolute():
        return str(path)
    try:
        return str(p.resolve().relative_to(REPO))
    except ValueError:
        return str(path)


def repo_path(path: str | Path) -> Path:
    """Inverse of `rel` for command arguments: a relative path is taken from the repository root (not the
    cwd: Inspect changes into the task file's directory while it creates and runs a task), an absolute one
    is kept. Returns an absolute path."""
    p = Path(path)
    return p if p.is_absolute() else REPO / p


def rel_text(text: str) -> str:
    """Every occurrence of the repository root in `text` made relative ('<root>/x' -> 'x', '<root>' -> '.')."""
    root = str(REPO)
    return text.replace(root + "/", "").replace(root, ".")


def write_text(path: str | Path, text: str) -> None:
    Path(path).write_text(rel_text(text), encoding="utf-8")


def write_json(path: str | Path, obj, indent: int | None = 2) -> None:
    write_text(path, json.dumps(obj, indent=indent, default=str))


def json_line(obj) -> str:
    """One JSONL line (no newline) with the repository root made relative."""
    return rel_text(json.dumps(obj, default=str))
