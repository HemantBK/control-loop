# Cell 733 (pre-change-10) under the exit rule and its readings

Written by `scripts/phase6/exit_readings.py` from the episode folders (PLAN Amendments (36) item 2, (39)). Only V2 depends on the reading. `harness` governs; `strict` is the sensitivity check; the others are kept for the record.

Last `[agent]` line, attack episodes: rc: 0, budget: 15, spin_abort: 1, other: 0, none: 0

Harness record, attack episodes: elapsed 3551, 3600, 3601 s against the outer limit [3900] s; cap stops 0; last exit codes [0, 124].

| reading | role | episodes incomplete (attack rounds) | V2-valid rounds | primary (τ) | S1 (50) | S2 (1.3×) |
|---|---|---|---|---|---|---|
| harness | governing | 0 of 16 | r0a, r1, r3 | matched (V1 matched, V2 matched) | falsified (V1 falsified, V2 falsified) | matched (V1 matched, V2 matched) |
| strict | sensitivity | 16 of 16 | none | undecided (V1 matched, V2 not evaluable) | undecided (V1 falsified, V2 not evaluable) | undecided (V1 matched, V2 not evaluable) |
| last_rc | record | 0 of 16 | r0a, r1, r3 | matched (V1 matched, V2 matched) | falsified (V1 falsified, V2 falsified) | matched (V1 matched, V2 matched) |
| abort | record | 1 of 16 | r0a, r3 | undecided (V1 matched, V2 not evaluable) | undecided (V1 falsified, V2 not evaluable) | undecided (V1 matched, V2 not evaluable) |
| literal | record (= strict) | 16 of 16 | none | undecided (V1 matched, V2 not evaluable) | undecided (V1 falsified, V2 not evaluable) | undecided (V1 matched, V2 not evaluable) |
