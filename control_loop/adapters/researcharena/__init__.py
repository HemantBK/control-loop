"""ResearchArena adapter (phases/phase6_researcharena/PLAN.md §1.3). The only place that calls
ResearchArena. Satisfies the adapter contract (control_loop/adapters/base.py, adapters/README.md).

`run_eval` translates the loop's arguments into one `EpisodeSpec` per episode and hands the list to a
`launcher` callable (injected; the pods agent provides `pods.launch`, which runs each episode on its own
GPU pod). The default launcher runs `run_redteam.sh` as a local subprocess on the host; the CPU pod has no
GPU, so the tests use the mock agent, not the default launcher against the real benchmark. Monitors
(`run_monitor.sh`) and the proposer need no GPU and run on the CPU pod.

The loop calls `run_eval(log_dir, agent_model, seed, extra_t, payload_file, monitor_model, epochs, max_samples)`.
`extra_t` is a flat `["-T", "k=v", ...]` list (adapters/README.md); the pairs this adapter reads are
`side_task` (none|payload), `redruntime`, `experiment`, `cell`, `round`, `checkout`, `arena_root`,
`overlay_agent_dir`, `task_config`, `with_artifact`. `epochs` = episodes this call launches (one per pod).
The log it returns is the round directory; `reader.read_round` reads it (the adapter's own `read_run`)."""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from control_loop import runlog
from control_loop.adapters.researcharena import arena_root, reader  # noqa: F401  (re-exported)
from control_loop.adapters.researcharena.reader import read_episode, read_round  # noqa: F401
from control_loop.paths import rel

NAME = "researcharena"
DEFENSES = ["none", "monitor_transcript", "monitor_artifact"]      # none = no monitor run, scores absent
ORDERINGS: list[str] = []                                         # the framework has no activation order
PHASE = "phase6_researcharena"

SETTING = "cuda_kernel"
TASK_CONFIG = "tinyllama"
REDRUNTIME = 0.1667
BLUERUNTIME = 0.0833
REDTEAM_MODEL = "opencode_or:openrouter/qwen/qwen3-235b-a22b-2507"
MONITOR_MODEL = "opencode:anthropic/claude-sonnet-4-6"
ENV_NAMES = ("OPENROUTER_API_KEY", "HF_HOME", "ARENA_RESULTS_DIR", "ARENA_ROOT",
             "P6_EPISODE", "P6_SIDE_TASK", "TOKENIZERS_PARALLELISM")

_DEFENSE_MONITOR = {"none": None, "monitor_transcript": "transcript", "monitor_artifact": "artifact"}


class LaunchError(RuntimeError):
    """Raised by a launcher when one or more episodes could not be run. `partial` holds the eval dirs
    collected before the failure (the pods agent re-raises this with partial results, PLAN §7.7)."""

    def __init__(self, message: str, partial: list[Path] | None = None):
        super().__init__(message)
        self.partial = list(partial or [])


@dataclass(frozen=True)
class EpisodeSpec:
    """One red-team episode. `argv()` is the exact `run_redteam.sh` invocation (PLAN §7.3). `env_names`
    are variable NAMES the pod must set from its own .env (values never appear here)."""
    arena_root: str
    setting: str
    side_task: str                 # "none" | "payload"
    redruntime: float
    redteammodel: str
    seed: int
    experiment: str
    cluster_id: str
    task_config: str = TASK_CONFIG
    env_names: tuple[str, ...] = ENV_NAMES
    payload_file: str | None = None

    def argv(self) -> list[str]:
        return ["bash", str(Path(self.arena_root) / "run_redteam.sh"),
                "--setting", self.setting, "--side_task", self.side_task,
                "--redruntime", str(self.redruntime), "--redteammodel", self.redteammodel,
                "--seed", str(self.seed), "--experiment", self.experiment,
                "--cluster_id", self.cluster_id, "--task_config", self.task_config]

    def as_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


def _t_options(extra_t) -> dict:
    out: dict[str, str] = {}
    it = iter(extra_t or [])
    for a in it:
        if a == "-T":
            kv = next(it, "")
            if "=" in kv:
                k, v = kv.split("=", 1)
                out[k] = v
        elif a.startswith("-T") and "=" in a:
            k, v = a[2:].split("=", 1)
            out[k] = v
    return out


def find_eval_dir(results_dir: str | Path, experiment: str, cluster_id: str) -> Path | None:
    """The eval dir run_redteam.sh wrote for this episode: $results_dir/$experiment/*_c<cluster_id>
    (pipeline_redteam.sh 91–92). None until the run has created it."""
    base = Path(results_dir) / experiment
    if not base.is_dir():
        return None
    hits = sorted(p for p in base.glob(f"*_c{cluster_id}") if p.is_dir())
    return hits[-1] if hits else None


def build_specs(arena_root_path: str | Path, side_task: str, seed: int, experiment: str, cluster_ids: list[str],
                redteammodel: str = REDTEAM_MODEL, redruntime: float = REDRUNTIME,
                payload_file: str | Path | None = None) -> list[EpisodeSpec]:
    return [EpisodeSpec(arena_root=str(arena_root_path), setting=SETTING, side_task=side_task,
                        redruntime=redruntime, redteammodel=redteammodel, seed=seed, experiment=experiment,
                        cluster_id=cid, payload_file=str(payload_file) if payload_file else None)
            for cid in cluster_ids]


def _subprocess_env(spec: EpisodeSpec, results_dir: Path) -> dict:
    """Environment for a local run: the current environment plus the ResearchArena variables the pipeline
    reads. Keys are from ENV_NAMES; values come from the process environment (the pod's .env on a pod)."""
    env = dict(os.environ)
    env["ARENA_ROOT"] = spec.arena_root
    env["ARENA_RESULTS_DIR"] = str(results_dir)
    env["P6_EPISODE"] = spec.cluster_id
    env["P6_SIDE_TASK"] = spec.side_task
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    return env


class LocalLauncher:
    """Runs each episode's `run_redteam.sh` as a subprocess on the host, under one results dir. No GPU
    management (that is the pods agent's `pods.launch`); used by the tests with the mock agent. Writes
    run.jsonl steps and returns the collected eval dirs in spec order; raises LaunchError on any failure."""

    def __init__(self, results_dir: str | Path | None = None, timeout: float | None = None):
        self.results_dir = Path(results_dir) if results_dir else None
        self.timeout = timeout

    def __call__(self, specs: list[EpisodeSpec], out_root: Path, log=runlog.log_step) -> list[Path]:
        out_root = Path(out_root)
        out_root.mkdir(parents=True, exist_ok=True)
        results_dir = self.results_dir or (out_root / "_arena_results")
        results_dir.mkdir(parents=True, exist_ok=True)
        run_id = specs[0].experiment if specs else out_root.name
        collected: list[Path] = []
        for k, spec in enumerate(specs, 1):
            edir = out_root / f"e{k}"
            edir.mkdir(parents=True, exist_ok=True)
            log(out_root, phase=PHASE, run_id=run_id, step="episode", status="started",
                note=f"e{k} {spec.side_task} seed {spec.seed} cid {spec.cluster_id}")
            proc = subprocess.run(spec.argv(), env=_subprocess_env(spec, results_dir),
                                  capture_output=True, text=True, timeout=self.timeout)
            src = find_eval_dir(results_dir, spec.experiment, spec.cluster_id)
            (edir / "launch_stdout.txt").write_text(proc.stdout, encoding="utf-8")
            (edir / "launch_stderr.txt").write_text(proc.stderr, encoding="utf-8")
            if src is None or not (src / "eval" / "metrics.json").exists():
                log(out_root, phase=PHASE, run_id=run_id, step="episode", status="failed",
                    error=f"e{k}: no eval dir with metrics.json (rc {proc.returncode})", paths=[edir])
                raise LaunchError(f"episode e{k} produced no eval dir (rc {proc.returncode}): {proc.stderr[-500:]}",
                                  partial=collected)
            dst = edir / src.name
            if dst.resolve() != src.resolve():
                import shutil
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            collected.append(dst)
            log(out_root, phase=PHASE, run_id=run_id, step="collect", status="done", paths=[dst],
                note=f"e{k} -> {rel(dst)}")
        return collected


def run_monitor(eval_dir: str | Path, arena_root_path: str | Path, blueteammodel: str = MONITOR_MODEL,
                blueruntime: float = BLUERUNTIME, with_artifact: bool = False,
                env: dict | None = None, timeout: float | None = None) -> Path:
    """Run `run_monitor.sh` from the composed root (CPU pod, no GPU) on one collected eval dir. Returns the
    blue_team variant directory (PLAN §7.3: M∅ = no access flags)."""
    eval_dir = Path(eval_dir)
    argv = ["bash", str(Path(arena_root_path) / "run_monitor.sh"), "--eval_dir", str(eval_dir),
            "--blueruntime", str(blueruntime), "--blueteammodel", blueteammodel]
    if with_artifact:
        argv.append("--with-artifact")
    run_env = dict(os.environ)
    run_env["ARENA_ROOT"] = str(arena_root_path)
    if env:
        run_env.update(env)
    subprocess.run(argv, env=run_env, capture_output=True, text=True, timeout=timeout)
    mdir = reader.select_monitor_dir(eval_dir, "artifact" if with_artifact else "transcript")
    if mdir is None:
        raise RuntimeError(f"run_monitor.sh produced no judgement under {eval_dir}/blue_team "
                           f"(cmd: {shlex.join(argv)})")
    return mdir


def run_eval(log_dir, agent_model: str, seed: int, extra_t, payload_file, monitor_model: str,
             epochs: int = 1, max_samples: int = 1, launcher=None) -> str:
    """Adapter contract. Launches `epochs` episodes of cuda_kernel (one EpisodeSpec each) through
    `launcher` (default LocalLauncher), then runs the monitor for each unless the defense is "none", and
    returns the round directory `log_dir` (read by reader.read_round). `extra_t` carries `side_task`,
    `redruntime`, `experiment`, `cell`, `round`, `defense`, `checkout`, `arena_root`, `overlay_agent_dir`."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    t = _t_options(extra_t)
    side_task = t.get("side_task") or ("payload" if payload_file is not None else "none")
    defense = t.get("defense", "monitor_transcript" if monitor_model else "none")
    if defense not in DEFENSES:
        raise ValueError(f"unknown defense {defense!r}; one of {DEFENSES}")
    monitor_arm = _DEFENSE_MONITOR[defense]
    experiment = t.get("experiment", f"{PHASE}_{t.get('cell', 'cell')}_{t.get('round', log_dir.name)}")
    redruntime = float(t.get("redruntime", REDRUNTIME))
    arena_root_path = t.get("arena_root")
    checkout = t.get("checkout") or os.environ.get("RESEARCHARENA_ROOT")
    # build / refresh the composed root for this round's payload, if not already supplied
    if arena_root_path is None:
        if checkout is None:
            raise ValueError("run_eval needs -T arena_root=... or -T checkout=... / RESEARCHARENA_ROOT")
        payload = payload_file if payload_file is not None else None
        arena_root_path = str(log_dir / "arena_root")
        arena_root.build(arena_root_path, checkout, payload or _stock_side_task(checkout),
                         overlay_agent_dir=t.get("overlay_agent_dir"))
        arena_root.verify(arena_root_path, checkout)
    cluster_ids = [f"{experiment}-e{k}" for k in range(1, epochs + 1)]
    specs = build_specs(arena_root_path, side_task, seed, experiment, cluster_ids,
                        redteammodel=agent_model or REDTEAM_MODEL, redruntime=redruntime,
                        payload_file=payload_file)
    launch = launcher or LocalLauncher()
    runlog.log_step(log_dir, phase=PHASE, run_id=experiment, step="verify_root", status="done",
                    note=f"arena_root {rel(arena_root_path)}")
    eval_dirs = launch(specs, log_dir)
    if monitor_arm is not None:
        for d in eval_dirs:
            runlog.log_step(log_dir, phase=PHASE, run_id=experiment, step="monitor", status="started",
                            paths=[d])
            run_monitor(d, arena_root_path, blueteammodel=monitor_model or MONITOR_MODEL,
                        with_artifact=(monitor_arm == "artifact"))
            runlog.log_step(log_dir, phase=PHASE, run_id=experiment, step="monitor", status="done", paths=[d])
    runlog.log_step(log_dir, phase=PHASE, run_id=experiment, step="summary", status="done",
                    note=f"{len(eval_dirs)} episodes, defense {defense}")
    return str(log_dir)


def _stock_side_task(checkout: str | Path) -> Path:
    return Path(checkout) / "settings" / SETTING / "side_tasks" / "independent" / "side_task.md"
