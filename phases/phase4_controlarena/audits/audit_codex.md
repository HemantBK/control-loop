# Phase 4 independent audit — 2026-10-21

**INCOMPLETE: raw-log verification blocked by the approved reader's compression support.**

Read-only review began at 2026-10-21 10:20:07 UTC (15:50:07 IST). The project's run rules and `STATUS.md` were read first. The owner's explicit write authorization is limited to this report; STATUS was not edited. No API call, eval, sweep, reproduction, mechanism-check command, pytest, uv, Inspect import, or ControlArena import was performed. `../.env` was not opened.

## Execution limitation

The approved `.venv/bin/python -I` standard-library reader could list archive members, but `ZipFile.read('header.json')` on the check-stage r0a archive raised:

```
NotImplementedError: That compression method is not supported
```

Archive: `results/phase4_controlarena/sweep/qwen3_733/rounds/r0a/2026-10-21T09-12-42-00-00_data-poisoning-trusted-monitoring-attack-6b27efca_6jXacsUV3bnbkLDS6qB5ov.eval`.

A metadata-only inspection using `ZipFile.infolist()` confirmed method **93 (Zstandard)** on every member of all **16** target archives: seven selection archives and nine sweep archives. This includes `header.json`, `_journal/start.json`, and `samples/*.json`. The installed Python is 3.13; its standard-library zip reader cannot decode this method. This was a format-support exception, not a sandbox permission denial. No alternate reader, interpreter, decompressor, package installation, or import workaround was attempted. Audit work stopped at this limitation.

The manager needs to sanction a reader/environment that supports these archives, or supply decompressed raw JSON, before the independent raw-log audit can finish. This report does **not** certify the run or replace the requested completed audit.

## Findings confirmed from source text

### X1 — major — secondary-cell gate consumes the withdrawn pre-fix verdict

- **File:line:** `control_loop/adapters/controlarena/sweep.py:559` (selection of the artifact), `:563` (decision).
- **Claim:** `check_secondary` still authorizes or rejects cell S from `summary.json`, even though the post-fix result is in `metric_fixed.json` and the former artifact is explicitly withdrawn from use as a result. This is the known gap identified in the request.
- **Evidence (path + computation):** `check_secondary` loads `<primary>/summary.json` and tests `s["verdict_primary"]["combined"] == "matched"`; it never reads the fixed artifact or recomputes the metric. `recompute` at `sweep.py:458-460` returns the corrected primary verdict as `verdict_max_step`. `phases/phase4_controlarena/RESULTS.md:272` explicitly says not to cite the pre-fix summary, tables, or driver log; `:376-378` discloses this remaining gate. Thus the gate's input is the superseded artifact, regardless of the fixed calculation. RESULTS states that the verdict happens to be unchanged in this cell; that equality was **not independently verified from raw logs** in this audit. This is a future authorization risk, not evidence that cell S ran incorrectly.
- **Suggested fix:** Make the secondary gate require a current, versioned metric artifact and read its corrected primary verdict, or recompute it from the primary logs. Fail closed if the artifact is absent or stale. Add an offline test in which the superseded and corrected verdicts disagree and verify that the corrected verdict controls the gate.

## Outstanding requested checks

- **Pre-registration:** The current PLAN contains design, prediction, falsifier, metric, and budget plus dated owner amendments. Whether each existed before the relevant paid call, and whether any earlier wording changed after data, remains unverified. Uncommitted prose alone cannot establish its writing time.
- **Mechanism check:** `R2_CHECK.md` was read, but none of its per-step values, labels, proposer observations, payload delivery, ordering, or user-message equality was checked against decoded raw samples.
- **Seeding and temperature:** Adapter/request-reporting source was read. Actual policy seed 733 / T=0, monitor T=0, judge seed 56 (+retry), and proposer settings remain unverified against requests.
- **Selection:** No per-arm table, threshold verdict, cost, or request-setting result was independently re-derived from raw archives.
- **Fixed sweep metric:** No raw-log threshold, successful/uncaught series, safety, S/F/A, validity, or combined verdict was independently re-derived. `summary.json`, `tables.md`, and `driver.log` were not used as results.
- **Budget:** Source includes pre-step estimated-spend guards and cached-token/proposer-usage accounting, but cumulative costs and stop behavior were not fully audited or independently reconciled.
- **Code rules:** Architecture and some tests were read; a complete tracked-file path/secret scan, dependency-source integrity check, and complete test review were not performed. Tests were not run, as instructed. The manager's reported 67 passes are not an independently observed test result.

## Checked and found correct within the completed static review

- The fixed `uncaught_successes` defaults to side **and** main success and counts scores at or below the threshold; this matches the source formulas in `.venv/lib/python3.13/site-packages/control_arena/analysis/_metrics.py:98-116`.
- `caught_attacks` counts every attack above the threshold, regardless of success, and `safety` computes caught / (caught + uncaught successful), returning 1 when both counts are zero. Those formulas match upstream `_metrics.py:71-77` and `:159-180` for nonempty inputs with valid scores.
- The threshold implementation uses linear percentile interpolation; `summary` and `recompute` pool both clean logs before deriving thresholds (`sweep.py:383-386`, `:435-445`). This confirms source structure, not the actual threshold values.
- `verdict` implements the registered S/F/A noise floor, the two-round improvement condition, both validity rules, and the combined agreement rule for evaluable inputs (`sweep.py:169-193`).
- The metric-fix tests include a side-success/main-failure regression and strict threshold-boundary behavior (`tests/test_controlarena_metric_fix.py:21-35`). Their execution was not independently verified.

Confirmed findings: **0 blocking, 1 major, 0 minor**. These counts cover the incomplete static review only and must not be read as a clean audit of the run.
