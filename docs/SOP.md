# Standard operating procedure for a phase (SOP)

Written 2026-10-21 on the owner's instruction; kept current by whichever session changes a convention
(dated change log at the end). It binds every phase from Phase 5 on, and Phases 1–4 are checked
against it retrospectively (`audits/sop_check.md` in each phase directory). Owner instructions in
`STATUS.md`'s decisions log take precedence over this document; this document takes precedence over
habit. Paths are relative to the repository root. Operational rules about agents, spend stops and
approvals live outside the repository and are not restated here; where this document says "the
owner decides", that is the stop.

## 1. The life of a phase, in order

| step | what exists at the end of the step | may be paid? |
|---|---|---|
| 1 pre-register | `phases/phaseN_<slug>/PLAN.md` (§2.2) and `README.md` stub (status "not started"); a row in the root `README.md` phase table; STATUS lines | no |
| 2 approve | the owner's decisions as dated lines in a PLAN section "Owner's approval", written before any code or paid call; every foreseeable decision answered by number | no |
| 3 build | adapter/analysis code under `control_loop/`, phase scripts under `phases/<phase>/`, tests under `tests/` that make no API call; whole suite green | no |
| 4 mechanism check | two logs opened by hand (one clean, one attacked unless the phase has no attack), a per-step or per-claim table, every context field verified against the problem definition; `FINDINGS.md` entry; a mismatch stops the phase | yes, small |
| 5 sweep | the pre-registered cells, one paid stream per phase, spend recomputed from the logs before each cell; a contradicted prediction or a met falsifier stops the stream (§9) | yes |
| 6 tables | `sweep_tables.md` and `sweep_summary.json` written by a script in the repo from the logs; a cross-check by a second reader (`control_loop.round_table` or equivalent) | no |
| 7 write-up | `README.md` (§2.4), `pins.md` (§2.5), `FINDINGS.md` corrections entry if anything in earlier entries is now known to be wrong, root README row | no |
| 8 SOP check | `audits/sop_check.md` (§8) by an agent other than the writer; every gap fixed or listed as a task before the audit starts | no |
| 9 audit | at least one fresh audit by an agent with no history of the phase, a different model family where available; `audits/audit_<family>.md` | no (unless the auditor re-runs a mock) |
| 10 response | `audits/RESPONSE.md` (§2.6): every finding fixed, disclosed or not accepted with the reason; counts | no |
| 11 close | root README row "closed"; STATUS Phases line; spend final in `pins.md`; `git status --short` printed for the owner, who commits | no |

Steps never run out of order. A phase whose step 4 fails goes back to step 1 (a dated amendment)
or stops, as the owner decides.

## 2. Documentation standard per phase

### 2.1 The phase directory

`phases/phaseN_<slug>/` with exactly these names:

| file | role | append-only? |
|---|---|---|
| `PLAN.md` | pre-registration and every dated amendment and owner line | after the first paid call, yes (§2.2) |
| `README.md` | the write-up; the only document a reader needs | no, but every change after the audit goes through `RESPONSE.md` or a dated "Corrections" note |
| `FINDINGS.md` | dated lab-notebook entries with log paths and spend, in the order things happened | yes; corrections are new entries |
| `pins.md` | everything the results depend on (§2.5) | no |
| `audits/audit_<family>.md`, `audits/audit_<topic>_<family>.md` | the auditors' reports, verbatim, never edited by the phase | yes |
| `audits/RESPONSE.md` | the phase's answer to every finding (§2.6) | sections appended per audit round |
| `audits/sop_check.md` | the §8 checklist result | re-run and overwritten before each audit round, dated |
| `audits/council_<YYYY-MM-DD>_<topic>.md` | the §9 council opinions, verbatim, and the owner's decision | yes |
| `check.py`, `sweep.py`, `sweep_table.py`, `report.py` | the phase's drivers and readers; nothing in them is specific to one machine | — |
| `RESULTS.md` (Phase 4 only) | legacy name for FINDINGS; new phases use `FINDINGS.md` | yes |
| `HANDOFF.md` (Phase 1 only) | legacy; new phases put hand-over state in STATUS | — |
| `docs/instruments/<name>.md` (repository level) | the instrument document of every attacker and monitor the phase uses (§2.8) | updated, dated |

Names are lower-case, no spaces; the directory number is the phase table's number and never
changes once a plan exists.

### 2.2 PLAN.md: pre-registration

Header line: `# PLAN — Phase N: <title> (written <date>, before any code or run)`. Numbered sections
in this order (a phase may add sections, not drop them):

1. **Design**: the hooks or interfaces used, verified by file and line in the dependency at its
   pinned commit; what changes where (every new or edited file named); what the agents or models see
   (exact tool text, prompts, briefs); the observation model of the proposer or monitor (what it
   sees, what it never sees).
2. **Pre-registered prediction**: the mechanism in one paragraph, then numbered predictions per
   cell with numbers (counts of rounds, thresholds), each one scorable as matched / not matched.
3. **Falsifier**: numbered F1…, each deciding or comparative, each stated under both validity
   rules of the setting (ORBIT: allocation complete; ORBIT halt `all_agents_submitted`; ControlArena:
   V1 scored, V2 submitted); the "undetermined" rule (fewer than 3 valid rounds).
4. **Metrics**: primary first, exactly defined (what counts, what is excluded, ties); secondaries.
5. **Budget**: a table of cells with episodes, estimate and upper bound; price lines quoted from
   `control_loop/spend.py` (labelled unverified where they are); the caps and the stop points; the
   concurrency flag (`--max-samples 8`); what the driver does when a cap would be crossed.
6. **Mechanism check**: the exact two episodes, settings, log paths, what the per-step table shows,
   every context field that is checked and against what, the expected outcome, and "then stop".
7. **Sweep protocol**: cells in order; per-cell settings; briefs; validity; the reading guard (base
   rates from existing logs stated before any run, and the labels a cell can receive); reporting.
8. **Foreseeable decisions for the owner**, recommendation first, numbered D1…; include the
   ambiguity trigger for secondary arms and the per-cell stop.
9. **Threats and limits known in advance**, numbered.
10. **Owner's approval**: dated lines quoting the owner's decision by number. Nothing paid runs
    before this section exists.

Then, in time order, **dated amendments**: `### Amendment <YYYY-MM-DD>: <what>`, each saying what
changed, why, whether any paid call had already run and what it had shown. In-place edits to §1–§9
are allowed only before the first paid call of the phase and are recorded as "revised in place
before any run" with the date. After the first paid call, nothing above the amendments is edited;
a wrong sentence is corrected by an amendment that quotes it. Every number that a later section
depends on (thresholds, taus, base rates) is in the PLAN before the run that uses it.

### 2.3 FINDINGS.md: the notebook

One entry per thing done, heading `## <YYYY-MM-DD>: <what> (PLAN §x)`. Each entry states: the
settings as run (models, seeds, temperature, limits), the log paths (directory level), the spend at
list price from the logs, the tables or the pointer to the file that holds them, what was checked
and the result (counts of matches and mismatches), and the sentence "Nothing below enters a table"
when the entry is a check with n = 1. Entries are never edited; a later entry titled
`## <date>: corrections` names the wrong value, the right value and the source. A paid run with no
FINDINGS entry within the same day is a gap.

### 2.4 README.md: the write-up

Numbered sections, in this order, every one present (write "none" rather than omit):

1. **Question and answer**: the phase-table question, then the headline in one or two sentences in
   the pre-registered wording (matched / not matched, held / not held, falsified / not falsified),
   with the cell count ("in 2 of 5 cells") and the validity rule it holds under.
2. **Provenance and attribution**: frameworks and their pinned versions and licences; what was
   modified (adapters only) and what was not.
3. **Method**: setting, arms, cells, seeds, orderings, models (exact strings), what the proposer or
   monitor saw, the metric, both validity rules, the budget as approved.
4. **Results**: the result table (one row per cell, columns = the pre-registered metrics, with the
   comparator beside), each cell's label from the reading guard, and the per-round table or a
   pointer to `sweep_tables.md`. Every number has a path (§4).
5. **Mechanism evidence**: the per-step or per-claim table from the mechanism check, what the raw
   log showed, and any case where the logged event and the raw request differed.
6. **Controls and comparators**: clean baselines (two runs), static rounds, comparators from earlier
   phases with their paths and the note "across sessions" where they are.
7. **Prediction ledger**: every PLAN §2 prediction and every §3 falsifier, matched / not matched or
   met / not met, per cell, with the number that decided it; secondaries the same.
8. **Limits**: numbered, including the seeded-draw caveat, unsent settings, privileged information,
   effective n.
9. **Known issues**: numbered, open and closed, with where each is disclosed.
10. **Reproduce**: §6 of this document.
11. **Spend**: measured and upper bound, cells, with the reconciliation file.
12. **What changed after the audit**: the audit rounds, counts of fixed / disclosed / not accepted,
    and which numbers or verdicts changed (or "none").

The headline never contains a mechanism claim that the data did not test, a causal word for a
post-hoc comparison, or a number without its denominator.

### 2.5 pins.md

Tables: code (framework versions with commit or wheel hash, Python, inspect-ai, SDKs, this
package's revision as recorded in the eval headers, which code was uncommitted when run); model
strings exactly as passed and as resolved by the provider (from the ModelEvent), per role; seeds
and temperature as *sent* (from `call.request`), not as requested, per role and step, with "not
sent" where a provider dropped them; settings (limits, epochs, flags, driver commands); dates run
(UTC from the eval names) and spend per step with the log directory. What is shared with an earlier
phase is referenced, not repeated.

### 2.6 Audits and responses

An audit is a fresh agent with no history of the phase, a different model family where one is
available, given the write-up, the PLAN, the logs and the tests, and asked to re-derive every
number from the raw logs and to check the pre-registration against the run dates. Its report is
`audits/audit_<family>.md` (or `audit_<topic>_<family>.md` for a partial audit), with findings
numbered (`X1…` for Codex, `C1…` for Claude, `A1…` for a section audit), each with severity
(major / minor / note), the claim, the evidence path, and the suggested remedy. Auditors never edit
phase files. `audits/RESPONSE.md` opens with the date, which audits it answers, how the audits
relate (overlap, disagreement), the status key (**fixed** / **disclosed** / **not accepted** with
reason), the counts, and a table `id | severity | status | what was done | where | merged with`;
then the auditors' outstanding checks and where each now stands. Every finding appears in the table.

### 2.7 Instrument documents

Every attacker (a proposer, a self-modifier, a static payload family) and every monitor or rule (a
judge preset, an allocation rule, a protocol, a transcript monitor, a framework's trusted monitor)
has `docs/instruments/<name>.md`, listed in `docs/instruments/README.md`, written before the first
paid run that uses it (the proposer's first, 2026-10-21) and updated by dated entries. Sections:
**What it measures** (the quantity, the unit, the observation it gets and does not get); **How it is
driven** (model string, seeds and temperature as sent, prompt or brief with its path and hash,
flags); **Limits** (what it cannot see or do, by construction); **Biases** (known systematic errors
with the evidence path: e.g. a judge misreading `view_tasks`, an invented exemption, a brief that
misdescribed the defense, drift to benign text, instance-fitting); **Verifying tests** (the test
functions and mock runs that pin its behaviour, and the mechanism-check tables that verified it on
real logs, by path); **Change history** (dated). A phase README's Method section links the
instrument documents it relies on instead of re-describing them.

### 2.8 Mock end-to-end test per adapter

Each adapter under `control_loop/adapters/<framework>/` has one test that runs the whole chain with
mock models and no API call: the loop (one static round and one proposer round with a scripted
proposer), the monitor or defense under test, the framework's scorer, and the reader that produces
the per-round row, asserting the row's fields against the scripted episode. Named
`tests/test_e2e_<framework>.py`; it is the first thing an auditor runs. A phase that adds a monitor
or a reader extends it.

### 2.9 STATUS.md and the root README

`STATUS.md` has the sections "Where things are", "Phases" (one block per phase, dated lines, last
line = current state), "Results folders", "Running now", "Uncommitted" (one line per task:
`<task-id> (<date>, paid $x | no API call): new …; M …; nothing staged.`), "Decisions log" (one
dated line each; a later correction is a dated bracket, never an edit) and "Open questions for
Hemant" (answered questions keep the question and get a dated bracketed answer). The root
`README.md` phase table has one row per phase: number, name, question, status in one sentence with
the headline, episodes, spend and the write-up path.

## 3. Where evidence lives and how it is named

| kind | where | naming |
|---|---|---|
| ORBIT episode logs | `results/<phase>/<ordering>/{baselines,prop_<proposer>}/<seed>_<preset>/` (Phase 1: `results/` and `results/v2/<ordering>/` as documented in its README) | baselines: `run1/`, `run2/` (8 epochs each); proposer cells: `A0/` static round 0, `A1/`…`A5/` adaptive rounds; one `.eval` per round, name = UTC time as Inspect writes it |
| payloads | inside the proposer cell | `payload_r1.txt`…`payload_r5.txt`, `best_payload.txt`, `baseline.json`, `rounds.jsonl`, `proposer_log.jsonl` (one line per proposer request with requested and sent settings) |
| ControlArena cells | `results/phase4_controlarena/sweep/<cell>/` | `rounds/r0a, r0b, r1…`, `redteam/*.jsonl`, `state.json`, `spend.json`, `CHECK.md`, `summary.json`, `tables.md`, `metric.{json,md}`, `verdict.{json,md}`, `driver.log` |
| transcript-monitor passes (Phase 8) | `results/phase8_transcript_monitor/<variant>/<model>/pass<k>/` | `.eval` logs plus `judgements.jsonl`; `pool_manifest.jsonl`, `stratum_n.jsonl`, `agreement_subset.jsonl`, `check/<variant>/<clean\|A0>.txt` at the phase root |
| mechanism checks | `results/<phase>/check/<preset>/{clean,A0}/` | the reader's report beside it as `report_<preset>.md` or `CHECK.md` |
| runner output | beside the log directory | `<name>.out`; never cited for spend |
| run log | `run.jsonl` in every run directory a driver creates (check, cell, pass), written through `control_loop.runlog` | one JSON line per step: `ts`, `phase`, `run_id`, `step`, `status` (started / done / failed / skipped / stopped), `cost_usd`, `error`, `paths`, `note`; `python -m control_loop.status [results/<phase>]` reads them all; sub-agents report from its output, never from memory |
| tables | `results/<phase>/sweep_tables.md`, `sweep_summary.json`, `round_table_crosscheck.md` | regenerated by `sweep_table.py`; a regenerated table that changes a number is a FINDINGS corrections entry |
| figures | `results/summary/*.png` with the CSV they were drawn from beside them | `<metric>_by_<factor>[_<rule>][_<ordering>].png`, same stem `.csv` |
| spend reconciliation | `results/spend_<YYYY-MM-DD>.md` | by hand from the logs with `control_loop.spend`, cache reads priced |
| audits, responses, SOP checks, council opinions | `phases/<phase>/audits/` | §2.1 |
| decisions | `STATUS.md` decisions log; owner lines in `PLAN.md` | dated |
| kept but out of every table | `results/_<name>/` | leading underscore; listed in STATUS "Results folders" |

Rules: no log is edited, moved or deleted; a re-run gets a new directory (`run2`, `attempt2`,
`_superseded_<name>`); `results/<phase>/` does not exist before the mechanism check; every path in
a document is repo-relative; eval names and dates are UTC unless marked IST; the `.env` file is
never inside the repository and is referenced only as `../.env`.

## 4. Numbers

Every number in a README, FINDINGS, STATUS or the paper traces to (a) a log path, or (b) a table
file generated by a script in the repository from log paths, or (c) a PLAN section for a
pre-registered threshold. A number with none of these is removed, not footnoted. Spend is computed
from the logs' `model_usage` with `control_loop.spend` (input, cache read, cache write, output), is
stated as "measured" and, where an estimate enters (a proposer whose usage is not logged), as an
"upper bound" with the assumption; list prices are labelled unverified until someone verifies them
against the provider's page and records the date. Printed "spend so far" lines from drivers are
never authoritative. Totals carry four decimals in pins and two in prose. Every rate has its
denominator. Both validity rules are reported wherever a rule enters a count. Effective n (distinct
seeded trajectories) is stated beside any count of rounds or epochs.

## 5. What the final paper needs from each phase

From every phase, in its README and recoverable without re-running:

1. the question as asked in the phase table and the one-sentence answer in pre-registered wording;
2. the method in one paragraph (setting, arms, cells, models, metric, validity rules);
3. the result table (cells × pre-registered metrics, comparators beside, labels from the reading
   guard) with its generating script and the log directories;
4. mechanism evidence: one per-step table from a raw log and the sentence that says what the model
   actually received (filtered or not);
5. controls: clean baselines, static rounds, and the comparator from the earlier phase with the
   across-sessions caveat;
6. limits and known issues as numbered lists;
7. what changed after the audit (counts and the verdicts or numbers that moved);
8. spend (measured, upper) and GPU hours where any;
9. the contribution paragraph below, filled in.

**Contribution paragraph template** (one paragraph per phase, no more than 120 words):

> Phase N asked whether <question>. We <method in one clause: ran / built / ported>, on <setting>
> with <arms> over <cells; seeds; orderings> (<episodes> episodes, $<spend>). Pre-registered
> prediction: <prediction>; falsifier: <falsifier>. Result: <headline in pre-registered wording>,
> <key number with denominator> under <validity rule(s)>; <comparator> gave <number>. The mechanism
> check showed <one sentence>. This holds subject to <the two strongest limits>. After <k> audits,
> <what changed, or "no number or verdict changed">. Evidence: `<results path>`, write-up
> `phases/<phase>/README.md`.

## 6. Reproduce-from-README standard

README section 10 gives, in this order: the commit (or "uncommitted at the time of writing, see
pins") and the dependency pins; the environment command (`uv sync --locked`); the test command
(`uv run --locked pytest -q`) with the expected pass count; the mock or no-API command that
exercises the mechanism end to end and its expected output; the exact paid commands for the
mechanism check and for each cell, with `uv run --locked --env-file ../.env`, the flags as run, the
log directory they write, their runtime and their cost; the command that regenerates every table
and figure from the logs and the expected first lines of its output; what cannot be reproduced
exactly and why (an unseeded proposer: replay `payload_r*.txt`; provider routing not pinned), and
how to replay it. Anyone with the repository, the keys and the budget can go from a clean checkout
to the result table by following that section alone.

## 7. What must never happen

- A change to design, prediction, falsifier, metric, threshold or cell list after seeing data that
  is not a dated amendment naming what the data had shown.
- A number in any document without a log path, a generated table or a PLAN section behind it.
- A conclusion, headline or paper sentence outside what the pre-registration can decide; post-hoc
  observations are labelled "post hoc, not a test result" and named as the next hypothesis.
- A paid run before the PLAN section and the owner's approval lines exist, or before the mechanism
  check passed, or without the budget line.
- A log edited, moved, deleted or overwritten; a table edited by hand.
- A source file of ORBIT, ControlArena, ResearchArena, DGM or Inspect modified.
- A secret, an absolute path or an AI-tooling file in a tracked file; the `.env` opened by an agent.
- A commit, push, issue or PR by an agent.
- An audit finding answered by editing the audit; an audit by an agent that wrote any part of the
  phase.
- A comparator across sessions presented as a within-session control.
- "Spend so far" from a driver, or a flat per-call estimate, presented as measured spend.
- A mechanism claim about what a model saw taken from the logged event input when the raw request
  (`call.request`) was available and not read.

## 8. The SOP check before audit

Before step 9, an agent other than the writer fills `audits/sop_check.md`: date, checker, the
items below each marked **pass** / **gap** with the path or the missing thing, and a task list of
the gaps. The audit does not start while a gap that touches a number, a verdict or a pre-registration
is open; other gaps may be listed as tasks and disclosed. Items:

1. PLAN exists with §1–§10 of §2.2, dated, "written before" header; amendments dated and appended;
   owner's approval lines before the first paid call (check the eval timestamps).
2. FINDINGS entries exist for every paid run, with log paths and spend; corrections as entries.
3. README has the twelve sections of §2.4 in order; the headline is in pre-registered wording with
   denominator and validity rule.
4. Every number in README sections 1, 4, 7 and 11 traces per §4 (sample at least twenty, all of
   section 1 and 7).
5. Prediction ledger complete: every PLAN prediction and falsifier scored, per cell.
6. pins.md has the five tables of §2.5; model strings as passed and as resolved; sent settings.
7. Evidence layout and names follow §3; no `_`-prefixed directory enters a table; no absolute
   path in any tracked file (`grep -rn "/Users/\|/root/" --include=*.md --include=*.py --include=*.json`
   over the phase and its results, excluding `.eval` and legacy `.out` files, which are listed).
8. Limits and known issues present and numbered; the seeded-draw caveat and unsent settings stated
   where they apply.
9. Reproduce section meets §6 (commands, expected output, cost, what cannot be reproduced).
10. Spend reconciled from the logs, measured and upper bound, in pins and README, matching STATUS.
11. Contribution paragraph (§5) present at the end of README section 1 or 12.
12. Nothing from §7 occurred (state what was checked for each bullet).
13. Statistical validity (§4): no rate from fewer than 3 distinct draws; the headline cell has a
    3-seed replicate; spread reported beside every pooled number.
14. Instrument documents (§2.7) exist for every attacker and monitor the phase uses and are linked
    from README section 3.
15. Every run directory has a `run.jsonl` and `python -m control_loop.status` lists the phase's
    runs with their costs; the mock end-to-end test (§2.8) exists for the adapter.

Phases 1–4 are checked against the same list; legacy names (`RESULTS.md`, `HANDOFF.md`, Phase 1's
`results/` layout) are recorded as "legacy, mapped" rather than gaps where the content exists.

## 9. The council at a stop

When a mechanism check, a sweep or an audit contradicts a pre-registered prediction or meets a
falsifier, or when the owner has to decide between options on evidence, the manager does the
following before the owner sees it:

1. Writes an **evidence packet**: `phases/<phase>/audits/council_<date>_<topic>.md`, section
   "Evidence": the pre-registered text (PLAN section quoted), the result with its log paths and
   tables, the validity of each round, the spend, and the options as the manager sees them. No
   recommendation yet.
2. Sends the identical packet to **two models other than the manager's own**: Codex (the CLI on the
   pod, read-only task mode, model recorded) and `openrouter/qwen/qwen3-235b-a22b-2507` through a
   small script run with the project keys (each a small paid call, recorded in the phase spend
   under "council"), each asked the same three questions: what does the result mean; what are the
   options; which would you pick and why. Temperature 0 where the provider honours it; the request
   settings recorded.
3. Appends both answers **verbatim** under "Opinions" with model string, date and cost, then its
   own recommendation under "Manager's recommendation", then brings the file to the owner.
4. The owner's decision closes it: recorded under "Decision" with the date and quoted words, and as
   a dated amendment in `PLAN.md` and a line in the STATUS decisions log.

An opinion is advice; a disagreement between the opinions is reported, not resolved by the manager.

## 10. Change log

- 2026-10-21: written (owner's instruction of the same day); §9 council procedure added the same
  day on the owner's instruction; Phases 1–4 retrospective check assigned.
- 2026-10-21 (later the same day), owner's four improvements: §4 statistical-validity rule (3 distinct
  draws, 3-seed headline replicate, spread); §2.7 instrument documents; §3 `run.jsonl` and the status
  command; §2.8 mock end-to-end test per adapter; §8 items 13–15.
