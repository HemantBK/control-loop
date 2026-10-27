# opencode command-timeout test (PLAN Amendments (34), (35); CPU pod, no GPU)

`scripts/phase6/oc_timeout_test.sh`, run twice on 2026-10-27. Each run makes two `opencode run` calls with
`openrouter/z-ai/glm-5.1`, each asked to run `sleep 130 && echo SLEPT_OK` once without a timeout argument. The model
passed none in any of the four calls.

| opencode | call | `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` | tool time (s) | tool output | files |
|---|---|---|---|---|---|
| 1.19.3 (the CPU pod's install) | A | unset | 120.158 | "(no output)" + "exceeding timeout 120000 ms" | `opencode_1.19.3/A_default.jsonl` |
| 1.19.3 | B | 3600000 | 130.047 | `SLEPT_OK` | `opencode_1.19.3/B_with_var.jsonl` |
| 1.19.4 (cell 733's GPU pods) | A | unset | 120.132 | "(no output)" + "exceeding timeout 120000 ms" | `opencode_1.19.4/A_default.jsonl` |
| 1.19.4 | B | 3600000 | 130.075 | `SLEPT_OK` | `opencode_1.19.4/B_with_var.jsonl` |

Tool times are the bash tool part's `state.time.end - start` in each JSON event stream. The `.err` files are empty.
