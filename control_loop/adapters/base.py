"""The adapter contract (documented in control_loop/adapters/README.md).

An adapter is a module or object with these attributes. The ORBIT adapter
(`control_loop.adapters.orbit`) satisfies it as a module; the next adapters
(ControlArena, ResearchArena, DGM, SHADE-Arena) can be modules or classes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable


@runtime_checkable
class FrameworkAdapter(Protocol):
    NAME: str                  # short id used in results paths and tables, e.g. "orbit"
    DEFENSES: Sequence[str]    # defense arms the adapter can run; "none" must be one of them
    ORDERINGS: Sequence[str]   # activation orders the adapter can impose (may be empty)

    def run_eval(self, log_dir: Path, agent_model: str, seed: int, extra_t: Sequence[str],
                 payload_file: Path | None, monitor_model: str,
                 epochs: int = 1, max_samples: int = 1) -> str:
        """Run one episode (or `epochs` episodes) of the framework's task and return the
        path of the log it wrote. `payload_file` is None for a clean run; otherwise the
        coalition's objective text for this round. `extra_t` are framework task options
        the loop passes through unchanged (defense arm, seed, ordering, coalition)."""
        ...
