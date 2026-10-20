# ControlArena adapter

control-arena 20.1.0 (PyPI, optional extra `controlarena`), setting `data_poisoning`, micro-protocol
`trusted_monitoring` (default monitor `basic_monitor` on the trusted model) plus the CLI's
end-of-trajectory monitor. Design and amendments: `phases/phase4_controlarena/PLAN.md`.

| file | role |
|---|---|
| `__init__.py` | `NAME`, `DEFENSES`, `ORDERINGS`, `run_eval` (the `FrameworkAdapter` entry point) |
| `dp_task.py` | Inspect task wrapper around `DataPoisoningSetting` |
| `proposer_policy.py` | `proposer_attack_policy` (`@control_agent`) and `RedTeamPolicy` (Phase 1 proposer protocol) |
| `reader.py` | `.eval` reader: per-sample outcome, per-step monitor scores, halt reason, ControlArena safety and usefulness |
| `mock_dp.py` | `cl_mock/dp`, deterministic no-API model for every role |
| `mechanism_check.py` | honest + red-team, mock or real, `--limit 1`, checks delivery, monitor coverage and reader = raw log |

Two ControlArena 20.1.0 behaviours the adapter works around (PLAN §10.1, §10.5):
- the setting README's `control-arena run single` does not exist; the command is `control-arena eval single`;
- `end_of_trajectory_monitor` overwrites the last step's `suspicion_score` metadata; the reader reads
  per-step scores from the monitor's own model calls, and `dp_task.py` runs that scorer on a copy.

Inspect 0.3.263 condenses sample events (request messages in `events_data.calls`, long strings as
`attachment://` refs), so the reader opens logs with `resolve_attachments=True`.

## License

MIT, "Copyright (c) 2025 UK AI Security Institute" (read from
`control_arena-20.1.0.dist-info/licenses/LICENSE` in the installed package, 2026-10-20). Entry to add
to the repository `NOTICE` (outside this phase's write paths, so not added here):

    This product depends on ControlArena (https://github.com/UKGovernmentBEIS/control-arena),
    version 20.1.0, Copyright (c) 2025 UK AI Security Institute, licensed under the MIT License.
    It is installed as an optional dependency and not redistributed.
