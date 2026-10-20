# Adapters

`control_loop` is a red-team loop (`loop.py`), a payload proposer (`proposer.py`) and an analysis
(`results.py`, `round_table.py`, `controls_table.py`, `plot.py`). None of those should know which
benchmark framework runs the episode. Everything that does know lives in one package per framework
under `control_loop/adapters/`. One adapter exists, `orbit/`; five are planned (README section 11):
ControlArena, ResearchArena, DGM, SHADE-Arena, and ORBIT itself for scenarios other than JiraTicket.

## What an adapter provides

The contract is `control_loop/adapters/base.py` (`FrameworkAdapter`, a `Protocol`). An adapter is a
module or object with:

| attribute | type | meaning |
|---|---|---|
| `NAME` | `str` | short id, used in results paths and table headings (`orbit`) |
| `DEFENSES` | `Sequence[str]` | the defense arms it can run; must include `"none"` |
| `ORDERINGS` | `Sequence[str]` | activation orders it can impose; may be empty if the framework has no turn order |
| `run_eval(log_dir, agent_model, seed, extra_t, payload_file, monitor_model, epochs=1, max_samples=1) -> str` | function | run one episode (or `epochs` episodes) and return the path of the log it wrote |

`run_eval` is the whole runtime boundary. The loop calls it once for the clean baseline
(`payload_file=None`, `epochs=8`), once for the static round 0 and once per adaptive round, always
with the same `extra_t` for one cell, so clean and attacked episodes are paired by construction.
`payload_file` is a UTF-8 text file holding the coalition's objective paragraph for that round; the
adapter decides how that text reaches the agents (ORBIT: a subclassed attack reads it at injection
time). `extra_t` is a flat list of framework task options the loop passes through unchanged
(`["-T", "defense_preset=…", "-T", "ordering=…", …]` for Inspect tasks); an adapter for a framework
without Inspect's `-T` convention should accept the same list and translate it.

The log the adapter returns must be readable by `control_loop.results.read_run`, which today means
an Inspect `.eval` log whose samples carry the fields the analysis uses (see below). That is the
second, weaker boundary: `results.py` reads Inspect logs and looks for ORBIT's scorer names and
event types. A non-Inspect framework needs either an Inspect task wrapper (the route ORBIT,
ControlArena and SHADE-Arena share, since all three are Inspect-native) or a `read_run` of its own
that returns the same `RunResult` dataclass.

## What `results.read_run` needs from a log

Per sample: the final per-agent reward and the team reward; which agents are the coalition; the
final allocation (which agent holds which ticket, or the framework's equivalent of "resources
captured"); whether every agent finished (the framework's own completion signal, not a count of
`submit` calls); each defense intervention with its boundary (`model_input`, `model_output`,
`tool_call`), verdict and turn; the coalition's first claim attempt and first successful claim and
the outsiders' first successful claim; secret-channel sends; the optimum for the problem instance.
`clean_distribution` then turns a multi-epoch clean log into the arm baseline (per-agent means, sd,
validity under both rules). An adapter whose framework lacks one of these fields should return the
`RunResult` field as `None` or `NaN`; every table already handles both.

## Turn order

`ORDERINGS` names the activation orders the adapter can impose. For ORBIT they are `early`, `late`
and `claimslast` (`orbit/orderings.py`), each both an execution plan handed to the task and a step
list the analysis uses to map agent spans to global turns. A new adapter that supports orderings
should expose the same pair (`execution_plan(name)` and `steps(name, max_turns)`); one that does not
should set `ORDERINGS = []`, and the loop's `--ordering` flag is then rejected for it.

## The ORBIT adapter as the worked example

- `orbit/__init__.py`: `NAME`, `DEFENSES`, `ORDERINGS`, `TASK` (the Inspect task path),
  `COMMON_T` and `COMMON_EVAL` (the task and generation settings every episode shares) and
  `run_eval`, which launches `python -m inspect_ai eval` in a subprocess with the repository root
  as cwd.
- `orbit/jira_adaptive.py`: the Inspect task. It subclasses ORBIT's `CollusionAttack` so the
  payload comes from the file named by `coalition_payload_file`, swaps that subclass into ORBIT's
  attack registry under the name `collusion` (ORBIT's JiraTicket task hardcodes that name and its
  paired scorer accepts only it), registers two monitor variants (fixed judge prompt with and
  without the model-input screen, optionally seeded) and wraps ORBIT's `_get_defenses` so the
  presets `llm_monitor_fixed` and `llm_monitor_fixed_actions` resolve to them. The patches are
  process-local: they run when Inspect imports the task file inside the episode's subprocess.
- `orbit/orderings.py`: the three activation orders.

Checked after the move to a standalone repository: with ORBIT installed from git as a package
rather than present as a sibling directory, importing `jira_adaptive` still replaces
`orbit.attacks.registry._REGISTRY["collusion"]` and registers the two defense types, and a
mock-model episode (`tests/test_orbit_adapter.py`, no API calls) delivers the file payload to the
coalition agents' system prompts.

## Adding the next adapter

1. Create `control_loop/adapters/<name>/` with an `__init__.py` that satisfies `FrameworkAdapter`.
2. Put every import of the framework inside that package; the loop and the analysis must not
   import it.
3. If the framework is not Inspect-native, add a `read_run` that returns `results.RunResult`, and
   give `results.read_run` a way to dispatch on the log type (today it assumes Inspect).
4. Record the framework's license in `NOTICE` by reading its LICENSE file, not from memory.
5. Add a no-API smoke test beside `tests/test_orbit_adapter.py`.
6. Pre-register the cell design in `PLAN.md` before any paid run (HANDOFF section 5).
