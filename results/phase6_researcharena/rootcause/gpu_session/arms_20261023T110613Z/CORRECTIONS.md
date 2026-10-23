# Corrections to this session's SUMMARY.txt (PLAN Amendment (15), 2026-10-23)

SUMMARY.txt is left exactly as the gate printed it. These corrections apply on top of it:

1. **The session is VOID.** The owner ruled it so in Amendment (15), knowingly overriding the pre-registered wording ("neither
   crashed nor completed" → FAIL; rule A "FAIL: anything else"). The reason is the cache-path defect: no arm that loads the
   model reached a kernel. The printed `DECISION rule_A: FAIL` is therefore void.
2. **C1a** was printed as `UNDECIDED: 0 sanitizer errors and no crash: the fault did not reproduce under the tool`. That is
   false: its sanitizer.log shows the target exited with an error before any kernel launched, because the model never
   loaded. Read it as INVALID (no kernel ran).
3. **`DECISION stock_crashes_under_C2_conditions: NO`** should read UNDECIDED: C1s never loaded the model.
4. **C1r's `n_errors=568`** came from the "N errors were not printed" line. The sanitizer's own `ERROR SUMMARY` is 768
   errors.
5. **C0, C1s, C1c, C2, C2s, C2c, C2cs and C3s** carry no kernel verdict: each is INVALID (the model never loaded). C1c was printed "UNDECIDED: run incomplete"; its bench.log ends in the offline OSError.

The kit used for the next session prints INVALID and VOID verdicts itself (gpu_kit/gpu_run/gate.py, Amendment (15)).
