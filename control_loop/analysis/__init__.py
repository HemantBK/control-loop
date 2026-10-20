"""Per-phase analysis scripts that read the committed .eval logs (no model calls).

Phase 2 (phases/phase2_claim_monitor/): claim_rates (per-agent assign_task block rates, any monitor
arm), claim_audit (every claim-time verdict against the pre-registered criteria), claim_report
(per-claim context check against the problem definition). Each is a module with a `main()`:

    uv run --locked python -m control_loop.analysis.claim_rates --baseline <dir> --cell <dir>

The cross-phase tables (round_table, controls_table, plot) stay in `control_loop/`.
"""
