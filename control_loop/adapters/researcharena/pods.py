"""Phase 6 GPU orchestration (phases/phase6_researcharena/PLAN.md §1.6, §7.7, §10): create, dispatch, sync,
collect, terminate, log. Nothing here imports ResearchArena; the only external programs are `runpodctl`,
`ssh` and `rsync`, found on PATH (tests put shims there).

    launch(specs, out_root, log=runlog.log_step, dry_run=False, *, dests=None, pods_log=None, run_id=None, cfg=None)

Per launch of k <= 4 episode specs (the core's `EpisodeSpec`, duck-typed here: arena_root, side_task, redruntime,
seed, experiment, cluster_id, payload_file, env_names, argv()):

1. create k pods with the §10.7 single-H100 command (`runpodctl pod create ... --wait --wait-timeout 20m`, one per
   episode, in parallel, names `p6-<cell>-<round>-e<k>`); if fewer than k come up within the deadline the remaining
   episodes run serially on the pods obtained (logged); never more than MAX_PODS pods exist at once;
2. per pod, first a container readiness gate (`runpodctl pod get` every 10 s until uptimeSeconds > 0 and the ssh port
   is published, ip:port refreshed from it, within create_deadline_s of the create call; Amendment 2026-10-23 (7)), then
   an SSH readiness probe (`ssh ... true`, ConnectTimeout 15, every 10 s, two successes in a row, up
   to 180 s; Amendment 2026-10-23 (6) item 3), a driver check (`nvidia-smi`; max CUDA below cfg.min_cuda is a setup
   failure, `DriverTooOld`, not counted as an attempt; Amendment (7)), the code push (retried once after an ssh transport failure), then over SSH: `pod_setup.sh` streamed on stdin (unless `cfg.baked_template`; with `cfg.template_id`, the
   prebuilt Phase 6 image's template, it still runs and skips steps 1-6 itself), then the round's payload is
   written and `run_redteam.sh` started under nohup; every `cfg.poll_s` seconds the eval dir is rsynced (partial
   logs survive a lost pod); the episode is finished when `<eval dir>/eval/metrics.json` exists;
3. the eval dir is collected to `dests[i]` (default `out_root/e<i+1>/`), the runner output beside it as `e<k>.out`,
   and the pod is deleted (`runpodctl pod delete <id>`) right after its last episode (target: within 2 minutes of
   collection; hard rule 10 minutes; the 60-minute watchdog is the backstop);
4. a failed episode (crash, timeout, unreachable pod) moves its partial logs to `<round dir>/_failed/<episode id>/`,
   the pod is deleted, and one fresh pod re-runs the episode; a second failure leaves the slot empty (the round is
   then n-1, invalid under V1; the caller reads `launch.json`);
5. every create and delete is appended to `pods_log` (default `out_root/pods.jsonl`): time, event, pod id, name,
   GPU type, data center, episode id, hourly rate, seconds billed, $; run.jsonl in `out_root` gets the steps
   pod_create / container_ready / ssh_ready / driver_check / push_repo / setup / episode / collect / pod_delete (GPU $
   on pod_delete), through `log`
   (SOP §3); a setup failure (SSH, push or pod_setup.sh) first saves `runpodctl pod get` (env values dropped) and
   container diagnostics into `out_root/pods/<id>/diagnostics.txt` (step `diagnostics`), then the pod is deleted.

Cleanup is idempotent: whatever raises, every pod this launch created is deleted (and `runpodctl pod list` is
reconciled by name) before `LaunchError(msg, partial)` is raised with the eval dirs collected so far.
`dry_run=True` prints every command it would run, with placeholders for the pod id/ip/port and `<from env>` for
every secret, creates nothing, and writes the same run.jsonl lines with status "skipped".

Secrets: the RunPod key is read by runpodctl from its own config; the OpenRouter key reaches a GPU pod only through
`--env`, built at call time from this process's environment, and is never written to any log (commands are
rendered with `<from env>` wherever they are printed or logged).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from control_loop import runlog
from control_loop.paths import REPO, rel, rel_text

PHASE = "phase6_researcharena"
MAX_PODS = 4                                   # PLAN §1.6(d), §5: at most the pods of one round at a time
NAME_PREFIX = "p6-"                            # the watchdog deletes only pods with this prefix
# PLAN Amendment 2026-10-22 (2), superseding §10.2's runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404: no runpod/pytorch
# tag pairs CUDA 12.9 with torch 2.10 (Docker Hub runpod/pytorch tags read 2026-10-22: cu1290 with torch 2.6.0-2.9.1,
# 2.12.1, 2.13.0 only), so the base is RunPod's CUDA 12.9 devel image (nvidia/cuda:12.9.0-cudnn-devel-ubuntu22.04 +
# deadsnakes Pythons + sshd; last_updated 2026-10-16) and pod_setup.sh step 3 installs torch==2.10.0 (cu129 wheels).
IMAGE = "runpod/base:1.4.1-cuda1290-ubuntu2204"
MIN_CUDA = "12.9"                              # the image's NVIDIA_REQUIRE_CUDA; the host driver must support 12.9
# PLAN Amendment 2026-10-22 (4): a RunPod template whose image (docker/phase6/, ghcr.io/hemantbk/control-loop-phase6)
# holds pod_setup.sh steps 1-6. Its id comes from $P6_TEMPLATE_ID; pods then use `--template-id` instead of `--image`
# and pod_setup.sh still runs (it detects the image by /etc/p6_image.json and skips steps 1-6).
TEMPLATE_ENV = "P6_TEMPLATE_ID"
TEMPLATE_CONTAINER_DISK_GB = 60                # the template's container disk (docker/phase6/README.md); create
                                               # fields override the template's, so the same value is sent
# files pod_setup.sh / smoke_test.sh leave on the pod, collected into <out>/pods/<pod id>/ after setup and after the
# smoke test (missing ones are listed in the run log, never fatal)
REMOTE_COLLECT = ("/workspace/p6_setup_compile.log", "/workspace/p6_compile.log", "/workspace/p6_fuse_mode",
                  "/workspace/p6_env.sh")
GPU_ID = "NVIDIA H100 80GB HBM3"               # PLAN §10.1 (H100 SXM, Secure Cloud)
DATA_CENTERS = "EU-FR-1,EU-NL-1"               # PLAN §10.6
H100_RATE_USD = 3.99                           # PLAN §5, RunPod on-demand Secure Cloud, read 2026-10-21 (estimates only;
                                               # the measured rate is runpodctl's costPerHr on the created pod)
SECRET_ENV = ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "RUNPOD_API_KEY")
REDACTED = "<from env>"
DEFAULT_ENV_NAMES = ("OPENROUTER_API_KEY", "HF_HOME", "ARENA_RESULTS_DIR", "ARENA_ROOT", "P6_EPISODE",
                     "P6_SIDE_TASK", "TOKENIZERS_PARALLELISM")                  # PLAN §10.4
POD_ID_RE = re.compile(r"\b[a-z0-9]{14}\b")
HERE = Path(__file__).resolve().parent


class LaunchError(RuntimeError):
    """Raised after cleanup; `partial` = the eval dirs collected before the failure (in spec order)."""

    def __init__(self, msg: str, partial: list[Path] | None = None):
        super().__init__(msg)
        self.partial = list(partial or [])


class DriverTooOld(RuntimeError):
    """The pod's NVIDIA driver supports a CUDA version below cfg.min_cuda (or `nvidia-smi` gave none): a setup failure
    that is not counted as an attempt (owner, 2026-10-23; PLAN Amendment 2026-10-23 (7))."""


DRIVER_NOT_COUNTED = "not counted as an attempt (owner 2026-10-23)"


def cuda_tuple(v: str) -> tuple[int, ...] | None:
    """'12.9' -> (12, 9); compared numerically, so '12.10' > '12.9'. None if not of the form N[.N...]."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)*)\s*", str(v or ""))
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def parse_nvidia_smi(query_out: str, smi_out: str) -> dict:
    """`nvidia-smi --query-gpu=name,driver_version --format=csv,noheader` and plain `nvidia-smi` output ->
    {gpu, driver, cuda} (None where absent). cuda is the 'CUDA Version: X.Y' of the header: the highest CUDA version the
    driver supports."""
    gpu = driver = None
    for ln in (query_out or "").splitlines():
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) >= 2 and parts[0] and re.match(r"^\d+(\.\d+)+$", parts[1]):
            gpu, driver = parts[0], parts[1]
            break
    m = re.search(r"CUDA Version\s*:\s*(\d+\.\d+)", smi_out or "")
    return dict(gpu=gpu, driver=driver, cuda=m.group(1) if m else None)


@dataclass
class PodConfig:
    image: str = IMAGE
    baked_template: str | None = None          # a RunPod template id baked from a pod that ran setup steps 1-6 (§10.5);
                                               # setup is skipped entirely (legacy; nothing is baked this way)
    # Amendment 2026-10-22 (4): the prebuilt-image template; setup still runs (steps 1-6 skipped on the pod)
    template_id: str | None = field(default_factory=lambda: os.environ.get(TEMPLATE_ENV) or None)
    template_container_disk_gb: int = TEMPLATE_CONTAINER_DISK_GB
    gpu_id: str = GPU_ID
    gpu_count: int = 1
    cloud_type: str = "SECURE"
    data_centers: str = DATA_CENTERS
    min_cuda: str = MIN_CUDA
    container_disk_gb: int = 40
    volume_gb: int = 30
    volume_mount: str = "/workspace"
    ports: str = "22/tcp"
    # 2026-10-22, owner's decision (PLAN Amendment (4) item 2): 20 minutes for the first pull of the prebuilt image
    # (was 10m / 600 s; diag1's pod got no SSH port within 10 minutes)
    wait_timeout: str = "20m"                  # --wait-timeout; PLAN §7.7(2)
    # 2026-10-24 (Amendment (20)): False = `pod create` without --wait; readiness is then left to container_ready and
    # ssh_ready (three re-measure pods were reachable while --wait reported "ssh port not allocated yet")
    create_wait: bool = True
    create_deadline_s: int = 1200              # pods not up by then are not waited for (serial fallback)
    poll_s: float = 120.0                      # rsync + completion check interval (PLAN §7.7(3): every 2 minutes)
    episode_margin_s: int = 1800               # episode timeout = redruntime hours + this (setup, eval, collection)
    setup_timeout_s: int = 1800
    ssh_timeout_s: int = 120
    delete_retries: int = 3
    rate_usd_per_h: float = H100_RATE_USD      # used only when runpodctl reports no costPerHr
    ssh_key: str = "~/.runpod/ssh/runpodctl-ssh-key"   # runpodctl's key; its public half is in the account (PUBLIC_KEY)
    remote_results: str = "/workspace/results"
    remote_arena_root: str = "/workspace/arena_root"
    remote_payload_dir: str = "/workspace/p6"
    setup_script: Path = HERE / "pod_setup.sh"
    smoke_script: Path = HERE / "smoke_test.sh"
    diag_script: Path | None = None             # None = DIAG_SCRIPT below (tests pass a stub file)
    diag_timeout_s: int = 3600                  # the whole diagnostic script over ssh (three bench runs at most)
    researcharena_commit: str = "58776e09339c1714d0524130590abaf6eac7879d"   # PLAN §1.1
    control_loop_commit: str = "local"          # "local" = push this host's control_loop/ tree (the adapter is not yet
                                                # pushed anywhere); a commit sha once pins.md records one
    control_loop_repo: str = "https://github.com/HemantBK/control-loop"
    # pinned in pins.md (1.19.3); 2026-10-22: read from $OPENCODE_VERSION when set (the manager exports it), else
    # "" = latest (pod_setup.sh step 2). Before this, an exported OPENCODE_VERSION never reached the pods.
    opencode_version: str = field(default_factory=lambda: os.environ.get("OPENCODE_VERSION", ""))
    unreachable_polls: int = 3                  # consecutive failed ssh polls before the pod counts as lost
    jobs_dir: str = "/workspace/jobs"           # detached remote steps (owner 2026-10-23, item 4): files per job
    job_poll_s: float = 15.0                    # poll interval once a detached job has run 21 s
    # PLAN Amendment 2026-10-23 (6) item 3 (smoke5 council): SSH readiness before the code push, one push retry
    ssh_ready_timeout_s: float = 180.0          # poll `ssh ... true` for up to this long after pod_create
    ssh_ready_interval_s: float = 10.0          # between probes
    ssh_ready_needed: int = 2                   # consecutive successes before setup proceeds
    ssh_ready_connect_timeout_s: int = 15       # ConnectTimeout of each probe
    push_retry_wait_s: float = 15.0             # wait before the one push retry after an ssh transport failure
    # PLAN Amendment 2026-10-23 (7) (smoke6b; owner's ruling): `runpodctl pod get` is polled after pod_create until the
    # container is up (uptimeSeconds > 0) and the ssh mapping is published (ssh.ip and ssh.port, no ssh.error); bounded by
    # create_deadline_s counted from the create call. Only then does the ssh_ready window start.
    container_ready_interval_s: float = 10.0
    remote_collect: tuple = REMOTE_COLLECT
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    now: Callable[[], float] = field(default=time.time, repr=False)
    echo: Callable[[str], None] = field(default=lambda s: print(s, flush=True), repr=False)


@dataclass
class PodInfo:
    id: str
    name: str
    ip: str
    port: int
    rate: float
    created_at: float
    data_center: str | None = None
    gpu_type: str | None = None
    episode_id: str | None = None
    deleted: bool = False
    setup_done: bool = False
    create_called_at: float | None = None       # cfg.now() at the create call (the container_ready deadline's origin)


def _utc(ts: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if ts is None else ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(s: Any) -> float | None:
    """runpodctl prints createdAt as '2026-10-21T13:56:55Z' (pod list) or '2026-10-21 13:56:55.212 +0000 UTC'
    (pod get). Returns epoch seconds, None if unparseable."""
    if not s or not isinstance(s, str):
        return None
    t = s.strip().replace(" UTC", "").replace("Z", "+00:00")
    if " " in t and "T" not in t:
        t = t.replace(" ", "T", 1).replace(" +", "+").replace(" -", "-")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            d = datetime.strptime(t, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d.timestamp()
        except ValueError:
            continue
    return None


# --- commands ----------------------------------------------------------------------------------------------------

def spec_argv(spec: Any) -> list[str]:
    """`spec.argv()` (the core's EpisodeSpec), else PLAN §7.3 from the fields."""
    if hasattr(spec, "argv"):
        return list(spec.argv())
    return ["bash", "run_redteam.sh", "--setting", getattr(spec, "setting", "cuda_kernel"),
            "--side_task", spec.side_task, "--redruntime", str(spec.redruntime), "--redteammodel", spec.redteammodel,
            "--seed", str(spec.seed), "--experiment", spec.experiment, "--cluster_id", spec.cluster_id,
            "--task_config", getattr(spec, "task_config", "tinyllama")]


def payload_b64(spec: Any) -> str | None:
    p = getattr(spec, "payload_file", None)
    if not p:
        return None
    return base64.b64encode(Path(p).read_bytes()).decode("ascii")


def pod_env(spec: Any, cfg: PodConfig, values: bool) -> dict[str, str]:
    """The `--env` object of PLAN §10.4/§10.7: names from the spec, fixed values for the paths, secrets from this
    process's environment when `values` (KeyError -> LaunchError by the caller), `<from env>` otherwise."""
    fixed = {"HF_HOME": f"{cfg.volume_mount}/hf", "ARENA_RESULTS_DIR": cfg.remote_results,
             "ARENA_ROOT": cfg.remote_arena_root, "P6_EPISODE": spec.cluster_id, "P6_SIDE_TASK": spec.side_task,
             "TOKENIZERS_PARALLELISM": "false"}
    env: dict[str, str] = {}
    for name in getattr(spec, "env_names", DEFAULT_ENV_NAMES):
        if name in fixed:
            env[name] = fixed[name]
        elif values:
            env[name] = os.environ[name]
        else:
            env[name] = REDACTED
    # 2026-10-25 (Amendment (25) item 5): pods can read each other's environment, so the payload is never in --env;
    # payload_install_cmd writes it from ssh stdin
    return env


def create_argv(name: str, env: dict[str, str], cfg: PodConfig) -> list[str]:
    """The §10.7 create command as an argv (env already rendered or redacted). With a template (`template_id`, or the
    legacy `baked_template`) `--template-id` replaces `--image`; the other fields are still sent and override the
    template's (RunPod: create fields override the template, env merged per key)."""
    if cfg.baked_template and cfg.template_id:
        raise ValueError("both baked_template and template_id set; use template_id (Amendment 2026-10-22 (4))")
    tmpl = cfg.template_id or cfg.baked_template
    src = ["--template-id", tmpl] if tmpl else ["--image", cfg.image]
    disk = cfg.template_container_disk_gb if cfg.template_id else cfg.container_disk_gb
    return ["runpodctl", "pod", "create", "--name", name, *src,
            "--gpu-id", cfg.gpu_id, "--gpu-count", str(cfg.gpu_count),
            "--cloud-type", cfg.cloud_type, "--data-center-ids", cfg.data_centers, "--min-cuda-version", cfg.min_cuda,
            "--container-disk-in-gb", str(disk), "--volume-in-gb", str(cfg.volume_gb),
            "--volume-mount-path", cfg.volume_mount, "--ports", cfg.ports, "--ssh",
            "--env", json.dumps(env, sort_keys=True),
            *(["--wait", "--wait-timeout", cfg.wait_timeout] if cfg.create_wait else []), "-o", "json"]


def redact(argv: Sequence[str]) -> str:
    """Shell rendering of an argv with every secret value replaced (for logs and dry runs)."""
    out = []
    for a in argv:
        s = str(a)
        for name in SECRET_ENV:
            v = os.environ.get(name)
            if v and v in s:
                s = s.replace(v, REDACTED)
        out.append(s)
    return rel_text(shlex.join(out))


def ssh_base(pod: PodInfo, cfg: PodConfig) -> list[str]:
    return ["ssh", "-i", os.path.expanduser(cfg.ssh_key), "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=20",
            "-o", "ServerAliveInterval=30", "-p", str(pod.port), f"root@{pod.ip}"]


def probe_argv(pod: PodInfo, cfg: PodConfig, cmd: str = "true") -> list[str]:
    """`ssh_base` with ConnectTimeout cfg.ssh_ready_connect_timeout_s (the readiness probe, Amendment 2026-10-23 (6))."""
    base = ssh_base(pod, cfg)
    i = base.index("ConnectTimeout=20")
    base[i] = f"ConnectTimeout={cfg.ssh_ready_connect_timeout_s}"
    return base + [cmd]


# Container diagnostics saved before a pod that failed setup is deleted (no journalctl in a RunPod container); every
# command may fail without failing the script.
DIAG_ON_FAILURE_CMD = (
    "echo '== ps -ef | head -50'; ps -ef 2>&1 | head -50; "
    "echo '== ls -la /workspace'; ls -la /workspace 2>&1; "
    "echo '== ss -tlnp'; (ss -tlnp 2>&1 || netstat -tlnp 2>&1); "
    "echo '== sshd'; ps -ef 2>&1 | grep '[s]shd'; "
    "for f in /var/log/*; do [ -f \"$f\" ] && { echo \"== tail -100 $f\"; tail -100 \"$f\" 2>&1; }; done; true")


def redact_pod_json(obj: Any) -> Any:
    """`runpodctl pod get` JSON with every env value dropped (names kept): any key named env/envs/environment."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in ("env", "envs", "environment"):
                if isinstance(v, dict):
                    out[k] = {str(n): REDACTED for n in v}
                elif isinstance(v, list):
                    out[k] = [(str(x).split("=", 1)[0] + "=" + REDACTED) if isinstance(x, str)
                              else (dict(key=x.get("key") or x.get("name"), value=REDACTED) if isinstance(x, dict) else REDACTED)
                              for x in v]
                else:
                    out[k] = REDACTED
            else:
                out[k] = redact_pod_json(v)
        return out
    if isinstance(obj, list):
        return [redact_pod_json(x) for x in obj]
    return obj


def rsync_argv(pod: PodInfo, remote: str, local: Path, cfg: PodConfig, single_file: bool = False) -> list[str]:
    e = shlex.join(ssh_base(pod, cfg)[:-1])    # everything but the host
    src = f"root@{pod.ip}:{remote}" + ("" if single_file else "/")
    return ["rsync", "-az", "--timeout=60", "-e", e, src, str(local) + ("" if single_file else "/")]


def episode_remote_out(spec: Any, cfg: PodConfig) -> str:
    return f"{cfg.remote_results}/{spec.experiment}"


def run_prelude(spec: Any, cfg: PodConfig) -> str:
    """Exports for an ssh session (RunPod's per-pod env is in /etc/rp_environment; sourced if present so the
    OpenRouter key from --env reaches the agent without ever travelling over ssh). RunPod also puts a pod-scoped
    RUNPOD_API_KEY there, which reads every pod of the account with its env (measured 2026-10-25, Amendment (23) item
    6); it is unset at once, so no job started through this prelude, and no agent, inherits it."""
    exports = {"HF_HOME": f"{cfg.volume_mount}/hf", "ARENA_RESULTS_DIR": cfg.remote_results,
               "ARENA_ROOT": spec.arena_root, "P6_EPISODE": spec.cluster_id, "P6_SIDE_TASK": spec.side_task,
               "TOKENIZERS_PARALLELISM": "false",
               # 2026-10-24 (Amendment (20)): the episode and its evaluator load the model offline, from the pod cache
               "HF_HUB_OFFLINE": "1",
               # 2026-10-25 (Amendment (25) item 5, benchmark change 08): the agent runs as an unprivileged user
               "P6_AGENT_EXEC": f"{cfg.volume_mount}/src/control-loop/control_loop/adapters/researcharena/p6_agent_exec.sh",
               # the pipeline's setting hook runs `git init && git commit` (CORE_NOTES §8): an identity is needed
               "GIT_AUTHOR_NAME": "phase6", "GIT_AUTHOR_EMAIL": "phase6@control-loop.invalid",
               "GIT_COMMITTER_NAME": "phase6", "GIT_COMMITTER_EMAIL": "phase6@control-loop.invalid"}
    ex = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in exports.items())
    return (f"[ -f /etc/rp_environment ] && . /etc/rp_environment; unset RUNPOD_API_KEY; export {ex}; "
            f"mkdir -p {shlex.quote(episode_remote_out(spec, cfg))} {shlex.quote(cfg.remote_payload_dir)}")


def payload_install_cmd(spec: Any, cfg: PodConfig, b64: str | None = None) -> str | None:
    """Install the round's paragraph as the composed root's payload side task (PLAN §1.4(1)). The base64 text comes on
    the ssh session's stdin (run_episode passes payload_b64(spec)), never in the pod's environment or a command line
    (other pods read environments; /proc/*/cmdline is world-readable). The file is root-only, and the per-episode copy is
    removed (Amendment (25) item 5): the pipeline, as root, builds the agent's prompt from it, and the agent runs as an
    unprivileged user (benchmark change 08). `b64` is unused and kept for callers."""
    if not getattr(spec, "payload_file", None):
        return None
    dst = f"{spec.arena_root}/settings/cuda_kernel/side_tasks/payload/side_task.md"
    tmp = f"{cfg.remote_payload_dir}/payload_{spec.cluster_id}.txt"
    return (f"(umask 077 && base64 -d > {shlex.quote(tmp)}) && mkdir -p {shlex.quote(os.path.dirname(dst))} && "
            f"cp --remove-destination {shlex.quote(tmp)} {shlex.quote(dst)} && chmod 600 {shlex.quote(dst)} && "
            f"rm -f {shlex.quote(tmp)}")


def start_cmd(spec: Any, cfg: PodConfig) -> str:
    out = f"{episode_remote_out(spec, cfg)}/{spec.cluster_id}.out"
    # 2026-10-22: `cd X && nohup ... &` backgrounded the whole `cd && nohup` list as a subshell that kept the ssh
    # session's stdout open until the episode ended, so every start hit ssh_timeout_s (check stage of 2026-10-22).
    # `cd X || exit 1;` then a plain `nohup ... &` backgrounds only the redirected job and returns at once.
    return (f"cd {shlex.quote(spec.arena_root)} || exit 1; nohup {shlex.join(spec_argv(spec))} > {shlex.quote(out)} 2>&1 "
            f"< /dev/null & echo $!")


# Owner, 2026-10-23 (item 4, after fullrun2's post step lost its ssh connection with rc=255 while its script ran on):
# every remote step runs detached. `_Launch.ssh` writes the command (base64) and its stdin to cfg.jobs_dir, starts it
# under `setsid nohup` with stdout/stderr/exit code in files there, returns at once, and then polls with short ssh
# calls that tolerate dropped connections. The job's files stay on the pod (<name>.cmd/.in/.out/.err/.rc/.pid).
JOB_MARK = ": p6job"     # first token of every launch command (the test shim keys on it)


def job_launch_cmd(name: str, cmd: str, jobs_dir: str) -> str:
    """One ssh command: stage <name>.cmd (from base64) and <name>.in (this ssh session's stdin), then start
    `bash <name>.cmd < <name>.in` under setsid nohup with its output in files; prints the job's pid. Only the
    setsid job is backgrounded (`;`-separated list, then `cmd &`), so the ssh session returns at once."""
    b64 = base64.b64encode(cmd.encode("utf-8")).decode("ascii")
    d, n = shlex.quote(jobs_dir), name
    inner = (f"bash {n}.cmd < {n}.in > {n}.out 2> {n}.err; echo $? > {n}.rc.tmp; mv {n}.rc.tmp {n}.rc")
    return (f"{JOB_MARK} {n} {b64}; mkdir -p {d} && cd {d} || exit 1; rm -f {n}.rc {n}.rc.tmp {n}.out {n}.err {n}.pid; "
            f"printf %s {b64} | base64 -d > {n}.cmd; cat > {n}.in; "
            f"setsid nohup bash -c {shlex.quote(inner)} > /dev/null 2>&1 < /dev/null & echo $! > {n}.pid; cat {n}.pid")


def job_poll_cmd(name: str, jobs_dir: str) -> str:
    """Prints `RC <n>` once the job has exited, else `RUNNING`, or `GONE` when the process is dead without an rc."""
    d, n = shlex.quote(jobs_dir), name
    return (f"cd {d} 2>/dev/null || {{ echo NOJOB; exit 0; }}; if [ -f {n}.rc ]; then echo RC $(cat {n}.rc); "
            f"elif [ -f {n}.pid ] && kill -0 $(cat {n}.pid) 2>/dev/null; then echo RUNNING; "
            f"elif [ -f {n}.pid ]; then sleep 2; [ -f {n}.rc ] && echo RC $(cat {n}.rc) || echo GONE; else echo NOJOB; fi")


def job_kill_cmd(name: str, jobs_dir: str) -> str:
    """setsid made the job's pid its process-group id: TERM the whole group, KILL it 10 s later."""
    d, n = shlex.quote(jobs_dir), name
    return (f"cd {d} && p=$(cat {n}.pid 2>/dev/null) && [ -n \"$p\" ] && "
            f"{{ kill -TERM -- -$p 2>/dev/null; sleep 10; kill -KILL -- -$p 2>/dev/null; true; }}")


JOB_POLL_DELAYS_S = (1, 2, 3, 5, 10)   # then every cfg.job_poll_s


def find_cmd(spec: Any, cfg: PodConfig) -> str:
    """The eval dir ends in `_c<cluster_id>` (CORE_NOTES §2; pipeline_redteam.sh 79-92)."""
    return f"ls -d {shlex.quote(episode_remote_out(spec, cfg))}/*_c{shlex.quote(spec.cluster_id)} 2>/dev/null | head -1"


def setup_env_prefix(cfg: PodConfig, spec: Any | None = None) -> str:
    env = {"RESEARCHARENA_COMMIT": cfg.researcharena_commit, "CONTROL_LOOP_COMMIT": cfg.control_loop_commit,
           "CONTROL_LOOP_REPO": cfg.control_loop_repo, "OPENCODE_VERSION": cfg.opencode_version,
           "ARENA_ROOT": cfg.remote_arena_root, "ARENA_RESULTS_DIR": cfg.remote_results,
           "HF_HOME": f"{cfg.volume_mount}/hf", "P6_PAYLOAD_DIR": cfg.remote_payload_dir}
    return " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())


# --- the launch --------------------------------------------------------------------------------------------------

def ssh_ready_text(ph: PodInfo, cfg: PodConfig) -> str:
    """The dry-run line of the readiness probe and the setup-failure handling (Amendment 2026-10-23 (6) item 3)."""
    return (shlex.join(probe_argv(ph, cfg)) + f"   (every {cfg.ssh_ready_interval_s:.0f} s until {cfg.ssh_ready_needed} in a row, "
            f"up to {cfg.ssh_ready_timeout_s:.0f} s, else setup failure; push retried once after {cfg.push_retry_wait_s:.0f} s "
            "and a re-probe on an ssh transport failure; on any setup failure `runpodctl pod get` (env dropped) and container "
            "diagnostics -> pods/<pod-id>/diagnostics.txt before the pod is deleted)")


def container_ready_text(cfg: PodConfig) -> str:
    """The dry-run line of the container readiness gate (Amendment 2026-10-23 (7))."""
    return (f"runpodctl pod get <pod-id> -o json   (every {cfg.container_ready_interval_s:.0f} s until uptimeSeconds > 0 and "
            f"ssh has ip and port and no error; ip:port refreshed from it; up to {cfg.create_deadline_s} s from the create "
            "call, else setup failure with diagnostics and deletion; the ssh_ready window starts only after this)")


DRIVER_QUERY_CMD = "nvidia-smi --query-gpu=name,driver_version --format=csv,noheader"
DRIVER_SEP = "== nvidia-smi"
DRIVER_CHECK_CMD = f"{DRIVER_QUERY_CMD} 2>&1; echo '{DRIVER_SEP}'; nvidia-smi 2>&1"


def driver_check_text(ph: PodInfo, cfg: PodConfig) -> str:
    """The dry-run line of the driver check (Amendment 2026-10-23 (7))."""
    return (shlex.join(ssh_base(ph, cfg) + [DRIVER_CHECK_CMD]) + f"   (raw output -> pods/<pod-id>/nvidia_smi.txt; gpu, driver "
            f"and max CUDA version logged; max CUDA below {cfg.min_cuda} or unparsed: setup failure 'driver below "
            f"{cfg.min_cuda}: {DRIVER_NOT_COUNTED}', diagnostics, pod deleted; before the code push and pod_setup.sh)")


class _Launch:
    def __init__(self, specs: Sequence[Any], out_root: Path, log: Callable, cfg: PodConfig, dests: list[Path],
                 run_id: str, pods_log: Path, dry_run: bool):
        self.specs, self.out_root, self.log_fn, self.cfg = list(specs), Path(out_root), log, cfg
        self.dests, self.run_id, self.pods_log, self.dry_run = dests, run_id, Path(pods_log), dry_run
        self.lock = threading.RLock()
        self.pods: dict[str, PodInfo] = {}
        self.names: set[str] = set()
        self.results: dict[int, dict] = {}          # spec index -> {status, dest, pod_id, attempts, error}
        self.names_for: dict[int, str] = {}
        self.serial_note: str | None = None

    # logging
    def step(self, step: str, status: str, *, cost: float | None = None, error: str | None = None,
             paths: Sequence[Any] = (), note: str | None = None, **extra: Any) -> None:
        with self.lock:
            self.log_fn(self.out_root, phase=PHASE, run_id=self.run_id, step=step, status=status, cost_usd=cost,
                        error=None if error is None else rel_text(str(error))[:2000], paths=list(paths),
                        note=None if note is None else rel_text(note), **extra)

    def say(self, msg: str) -> None:
        self.cfg.echo(rel_text(f"[{_utc()}] [{self.run_id}] {msg}"))

    def pods_event(self, event: str, pod: PodInfo, seconds: float | None = None, usd: float | None = None) -> None:
        rec = {"time": _utc(self.cfg.now()), "event": event, "pod_id": pod.id, "name": pod.name, "gpu_type": pod.gpu_type,
               "data_center": pod.data_center, "episode_id": pod.episode_id, "hourly_rate": pod.rate,
               "seconds_billed": None if seconds is None else int(seconds), "usd": None if usd is None else round(usd, 4),
               "run_id": self.run_id}
        with self.lock:
            self.pods_log.parent.mkdir(parents=True, exist_ok=True)
            with self.pods_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, sort_keys=True) + "\n")

    # subprocesses (runpodctl / ssh / rsync by name: PATH shims in the tests)
    def run(self, argv: list[str], timeout: float, stdin: str | None = None) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            return subprocess.CompletedProcess(argv, 124, e.stdout or "", f"timeout after {timeout}s")
        except FileNotFoundError as e:
            return subprocess.CompletedProcess(argv, 127, "", str(e))

    def ssh_query(self, pod: PodInfo, cmd: str, timeout: float | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
        """One attached ssh call. Only for short read-only queries (probes, `ls`, `kill -0`, job polls) and for
        starting an already-detached job; every step that does work goes through `ssh` (detached)."""
        return self.run(ssh_base(pod, self.cfg) + [cmd], timeout or self.cfg.ssh_timeout_s, stdin)

    _job_seq = 0
    _job_lock = threading.Lock()

    def ssh(self, pod: PodInfo, cmd: str, timeout: float | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
        """Run `cmd` on the pod as a detached job (setsid nohup; stdout, stderr and exit code in files under
        cfg.jobs_dir) and wait for it with short polls, so a dropped connection costs a poll, not the step. Returns
        a CompletedProcess like an attached call: the job's exit code, stdout and stderr. 124 = `timeout` passed (the
        job's process group is then killed); 255 = the job could not be started or its result never became
        readable (ssh down for the whole wait); 137 = the job's process vanished without an exit code."""
        c = self.cfg
        timeout = float(timeout or c.ssh_timeout_s)
        with _Launch._job_lock:
            _Launch._job_seq += 1
            name = f"job_{int(c.now())}_{os.getpid()}_{_Launch._job_seq}"
        argv = ssh_base(pod, c) + [f"<detached job {name}>"]
        t0 = c.now()
        started, err = False, ""
        for _ in range(3):   # a launch whose ssh dropped may still have started: check the pid file before retrying
            cp = self.ssh_query(pod, job_launch_cmd(name, cmd, c.jobs_dir), timeout=c.ssh_timeout_s, stdin=stdin or "")
            if cp.returncode == 0 and (cp.stdout or "").strip():
                started = True
                break
            err = (cp.stderr or cp.stdout or "")[-300:]
            chk = self.ssh_query(pod, job_poll_cmd(name, c.jobs_dir), timeout=c.ssh_timeout_s)
            if chk.returncode == 0 and (chk.stdout or "").split()[:1] in (["RUNNING"], ["RC"], ["GONE"]):
                started = True
                break
            c.sleep(5)
        if not started:
            return subprocess.CompletedProcess(argv, 255, "", f"detached job {name} not started: {err}")
        delays = list(JOB_POLL_DELAYS_S)
        rc, state, last_err = None, "", ""
        while True:
            c.sleep(delays.pop(0) if delays else c.job_poll_s)
            q = self.ssh_query(pod, job_poll_cmd(name, c.jobs_dir), timeout=c.ssh_timeout_s)
            words = (q.stdout or "").split() if q.returncode == 0 else []
            if not words:
                last_err = (q.stderr or "")[-300:]           # connection dropped: keep waiting until `timeout`
            elif words[0] == "RC":
                rc = int(words[1]) if len(words) > 1 and words[1].lstrip("-").isdigit() else 1
                break
            elif words[0] in ("GONE", "NOJOB"):
                state = words[0]
                break
            if c.now() - t0 > timeout:
                self.ssh_query(pod, job_kill_cmd(name, c.jobs_dir), timeout=c.ssh_timeout_s)
                rc, state = 124, "TIMEOUT"
                break
        out = self._job_file(pod, name, "out")
        errt = self._job_file(pod, name, "err")
        if rc is None:
            rc = 137 if state == "GONE" else 255
            errt = (errt or "") + f"\ndetached job {name}: {state or 'no exit code readable'} {last_err}".rstrip()
        elif state == "TIMEOUT":
            errt = (errt or "") + f"\ndetached job {name}: timeout after {timeout:.0f}s (process group killed)"
        return subprocess.CompletedProcess(argv, rc, out or "", errt or "")

    def _job_file(self, pod: PodInfo, name: str, ext: str) -> str:
        for _ in range(5):
            cp = self.ssh_query(pod, f"cat {shlex.quote(self.cfg.jobs_dir)}/{name}.{ext} 2>/dev/null; true",
                                timeout=self.cfg.ssh_timeout_s)
            if cp.returncode == 0:
                return cp.stdout or ""
            self.cfg.sleep(5)
        return ""

    def rsync(self, pod: PodInfo, remote: str, local: Path, single_file: bool = False) -> subprocess.CompletedProcess:
        local.parent.mkdir(parents=True, exist_ok=True)
        if not single_file:
            local.mkdir(parents=True, exist_ok=True)
        return self.run(rsync_argv(pod, remote, local, self.cfg, single_file), 600)

    # pods
    def create_pod(self, name: str, spec: Any) -> PodInfo | None:
        try:
            env = pod_env(spec, self.cfg, values=True)
        except KeyError as e:
            raise LaunchError(f"environment variable {e.args[0]} is not set on this host; nothing created")
        argv = create_argv(name, env, self.cfg)
        self.names.add(name)
        self.step("pod_create", "started", note=f"{name}: {redact(argv)}")
        t0 = self.cfg.now()
        cp = self.run(argv, self.cfg.create_deadline_s + 120)
        if cp.returncode != 0:
            err = f"runpodctl pod create {name} rc={cp.returncode}: {cp.stderr.strip()[-800:]}"
            # --wait timeout keeps the pod and names its id in the error: delete it at once (PLAN §10.7). Every
            # 14-character token is checked with `pod get` and deleted only if it is a pod carrying our name.
            for pid in sorted(set(POD_ID_RE.findall(cp.stderr or "") + POD_ID_RE.findall(cp.stdout or ""))):
                got = self.run(["runpodctl", "pod", "get", pid, "-o", "json"], 60)
                if got.returncode != 0:
                    continue
                try:
                    g = json.loads(got.stdout)
                except ValueError:
                    continue
                if not isinstance(g, dict) or g.get("name") != name:
                    continue
                stray = self.pod_from_json(g, name, spec, t0)
                with self.lock:
                    self.pods[stray.id] = stray
                self.pods_event("create", stray)
                self.save_diagnostics(stray, f"pod_create --wait timed out: {err[-300:]}")
                self.delete_pod(stray, note="created but not reachable within the wait timeout")
            self.step("pod_create", "failed", error=redact([err]))
            self.say(redact([err]))
            return None
        try:
            info = json.loads(cp.stdout)
        except ValueError:
            self.step("pod_create", "failed", error=f"{name}: unparseable runpodctl output: {cp.stdout[:300]}")
            return None
        if isinstance(info, list):
            info = info[0] if info else {}
        pod = self.pod_from_json(info, name, spec, t0)
        with self.lock:
            self.pods[pod.id] = pod
        self.pods_event("create", pod)
        self.step("pod_create", "done", note=f"{name} id {pod.id} {pod.ip}:{pod.port} ${pod.rate}/h "
                                             f"dc {pod.data_center} gpu {pod.gpu_type} in {self.cfg.now() - t0:.0f}s",
                  pod_id=pod.id)
        return pod

    def pod_from_json(self, info: dict, name: str, spec: Any, t0: float) -> PodInfo:
        ssh = info.get("ssh") or {}
        ip = ssh.get("ip") or info.get("publicIp") or info.get("ip") or ""
        port = ssh.get("port") or info.get("sshPort") or 22
        rate = info.get("costPerHr")
        created = parse_time(info.get("createdAt")) or t0
        machine = info.get("machine") or {}
        dc = info.get("dataCenterId") or machine.get("dataCenterId") or info.get("dataCenter")
        gpu = (info.get("gpu") or {}).get("displayName") if isinstance(info.get("gpu"), dict) else None
        gpu = gpu or machine.get("gpuDisplayName") or info.get("gpuDisplayName") or info.get("gpuId") or self.cfg.gpu_id
        if (not dc or not ip) and info.get("id"):
            got = self.run(["runpodctl", "pod", "get", str(info["id"]), "--include-machine", "-o", "json"], 60)
            if got.returncode == 0:
                try:
                    g = json.loads(got.stdout)
                    m = g.get("machine") or {}
                    dc = dc or g.get("dataCenterId") or m.get("dataCenterId")
                    gs = g.get("ssh") or {}
                    ip, port = ip or gs.get("ip") or "", port or gs.get("port") or 22
                    rate = rate if rate is not None else g.get("costPerHr")
                except ValueError:
                    pass
        return PodInfo(id=str(info.get("id")), name=name, ip=str(ip), port=int(port),
                       rate=float(rate) if rate is not None else self.cfg.rate_usd_per_h, created_at=created,
                       data_center=dc, gpu_type=gpu, episode_id=spec.cluster_id, create_called_at=t0)

    def delete_pod(self, pod: PodInfo, note: str | None = None) -> bool:
        with self.lock:
            if pod.deleted:
                return True
        self.step("pod_delete", "started", note=f"runpodctl pod delete {pod.id}", pod_id=pod.id)
        err = ""
        for attempt in range(self.cfg.delete_retries):
            cp = self.run(["runpodctl", "pod", "delete", pod.id], 120)
            if cp.returncode == 0 or "not found" in (cp.stderr or "").lower():
                seconds = max(0.0, self.cfg.now() - pod.created_at)
                usd = seconds / 3600.0 * pod.rate
                with self.lock:
                    pod.deleted = True
                self.pods_event("delete", pod, seconds, usd)
                self.step("pod_delete", "done", cost=usd, pod_id=pod.id,
                          note=f"{pod.name} {pod.id}: {int(seconds)} s at ${pod.rate}/h" + (f"; {note}" if note else ""))
                return True
            err = cp.stderr.strip()[-400:]
            self.cfg.sleep(10)
        self.step("pod_delete", "failed", error=f"{pod.id}: {err}", pod_id=pod.id)
        self.say(f"COULD NOT DELETE POD {pod.id} ({pod.name}): {err}; run `runpodctl pod delete {pod.id}` by hand")
        return False

    def reconcile_by_name(self) -> None:
        """Delete any live pod carrying one of this launch's names that is not already deleted (a create whose
        output was lost, or a --wait timeout whose id was not parsed)."""
        cp = self.run(["runpodctl", "pod", "list", "-o", "json"], 120)
        if cp.returncode != 0:
            self.step("pod_delete", "failed", error=f"runpodctl pod list rc={cp.returncode}: {cp.stderr[-300:]}")
            return
        try:
            pods = json.loads(cp.stdout) or []
        except ValueError:
            return
        for p in pods:
            name = str(p.get("name", ""))
            if name not in self.names or not name.startswith(NAME_PREFIX):
                continue
            pid = str(p.get("id"))
            with self.lock:
                known = self.pods.get(pid)
            if known is not None and known.deleted:
                continue
            if known is None:
                known = PodInfo(id=pid, name=name, ip="", port=0, rate=float(p.get("costPerHr") or self.cfg.rate_usd_per_h),
                                created_at=parse_time(p.get("createdAt")) or self.cfg.now())
                with self.lock:
                    self.pods[pid] = known
                self.pods_event("create", known)
            self.delete_pod(known, note="reconciled from pod list")

    def cleanup(self) -> None:
        if self.dry_run:
            return
        with self.lock:
            live = [p for p in self.pods.values() if not p.deleted]
        for p in live:
            self.delete_pod(p, note="cleanup")
        self.reconcile_by_name()

    # per pod
    def container_ready(self, pod: PodInfo) -> float:
        """PLAN Amendment 2026-10-23 (7) (smoke6b: `pod create --wait` returned ip:port while the image was still being
        pulled; uptimeSeconds -3 and ssh.error 'port 22 is declared but the host has not published a mapping for it yet'
        when the 180 s ssh window had run out). Poll `runpodctl pod get <id> -o json` every container_ready_interval_s
        until uptimeSeconds > 0 and the ssh field has ip and port and no error key; pod.ip/port are refreshed from it.
        Bounded by create_deadline_s counted from the create call. run.jsonl `container_ready` started/done/failed; a
        failure raises RuntimeError (setup failure). The pod get output is never logged (it carries env values)."""
        c = self.cfg
        origin = pod.create_called_at if pod.create_called_at is not None else pod.created_at
        deadline = origin + c.create_deadline_s
        t0 = c.now()
        self.step("container_ready", "started", pod_id=pod.id,
                  note=f"{pod.id}: `runpodctl pod get` every {c.container_ready_interval_s:.0f} s until uptimeSeconds > 0 "
                       f"and the ssh port is published; {max(0.0, deadline - t0):.0f} s left of the {c.create_deadline_s} s "
                       "from the create call")
        max_polls = int(max(0.0, deadline - t0) // max(c.container_ready_interval_s, 1e-9)) + 1   # bound when faked
        polls = 0
        last = ""
        while True:
            got = self.run(["runpodctl", "pod", "get", pod.id, "-o", "json"], 60)
            polls += 1
            if got.returncode != 0:
                last = f"runpodctl pod get rc={got.returncode}: {(got.stderr or '').strip()[-200:]}"
            else:
                try:
                    g = json.loads(got.stdout)
                except ValueError:
                    g, last = None, "runpodctl pod get output not JSON"
                if isinstance(g, list):
                    g = g[0] if g else None
                if isinstance(g, dict):
                    up = g.get("uptimeSeconds")
                    ssh = g.get("ssh") if isinstance(g.get("ssh"), dict) else {}
                    ip, port = ssh.get("ip"), ssh.get("port")
                    try:
                        upn = float(up)
                    except (TypeError, ValueError):
                        upn = None
                    if upn is not None and upn > 0 and ip and port and "error" not in ssh:
                        old = f"{pod.ip}:{pod.port}"
                        pod.ip, pod.port = str(ip), int(port)
                        waited = c.now() - t0
                        moved = f"{pod.ip}:{pod.port}" != old
                        self.step("container_ready", "done", pod_id=pod.id, seconds=round(waited, 1), polls=polls,
                                  uptime_s=upn, ssh_address=f"{pod.ip}:{pod.port}",
                                  note=f"{pod.name} id {pod.id} {pod.ip}:{pod.port} up {upn:.0f} s; ready after {waited:.0f} s, "
                                       f"{polls} poll(s)" + (f"; ssh address changed from {old}" if moved else ""))
                        return waited
                    last = (f"uptimeSeconds={up!r}, ssh " + (f"error: {str(ssh['error'])[:200]}" if "error" in ssh
                                                             else f"ip={ip!r} port={port!r}"))
                elif g is not None:
                    last = "runpodctl pod get returned no pod object"
            now = c.now()
            if now >= deadline or polls >= max_polls:
                err = (f"container not ready on pod {pod.id} {now - origin:.0f} s after the create call ({polls} poll(s) "
                       f"over {now - t0:.0f} s; limit {c.create_deadline_s} s); last: {redact([last])}")
                self.step("container_ready", "failed", pod_id=pod.id, seconds=round(now - t0, 1), polls=polls, error=err)
                raise RuntimeError(err)
            c.sleep(c.container_ready_interval_s)

    def driver_check(self, pod: PodInfo) -> dict:
        """PLAN Amendment 2026-10-23 (7): after ssh_ready and before the code push / pod_setup.sh, `nvidia-smi
        --query-gpu=name,driver_version` and `nvidia-smi` (its 'CUDA Version: X.Y', the highest CUDA the driver supports)
        over one ssh; raw output -> out_root/pods/<id>/nvidia_smi.txt; run.jsonl `driver_check` with gpu, driver_version,
        max_cuda. Max CUDA below cfg.min_cuda (numeric: 12.10 > 12.9) or unparseable -> DriverTooOld (not counted as an
        attempt, owner 2026-10-23); an ssh transport failure (rc 255/124) -> RuntimeError (an ordinary setup failure)."""
        c = self.cfg
        self.step("driver_check", "started", pod_id=pod.id,
                  note=f"{pod.id}: `{DRIVER_QUERY_CMD}` and `nvidia-smi`; max CUDA must be >= {c.min_cuda}")
        cp = self.ssh(pod, DRIVER_CHECK_CMD, timeout=c.ssh_timeout_s)
        path = self.out_root / "pods" / pod.id / "nvidia_smi.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rel_text(f"# {DRIVER_CHECK_CMD}\n# pod {pod.id} ({pod.name}) at {_utc(c.now())}, ssh rc={cp.returncode}\n"
                                 + (cp.stdout or "") + (f"\n--- stderr ---\n{cp.stderr}" if cp.stderr else "")), encoding="utf-8")
        if cp.returncode in (255, 124):
            err = f"driver check on pod {pod.id}: ssh failed rc={cp.returncode}: {(cp.stderr or '').strip()[-300:]}"
            self.step("driver_check", "failed", pod_id=pod.id, paths=[path], error=err)
            raise RuntimeError(err)
        q, _, smi = (cp.stdout or "").partition(DRIVER_SEP)
        info = parse_nvidia_smi(q, smi)
        extra = dict(gpu=info["gpu"], driver_version=info["driver"], max_cuda=info["cuda"])
        have, need = cuda_tuple(info["cuda"] or ""), cuda_tuple(c.min_cuda)
        if have is None or need is None or have < need:
            why = (f"max CUDA {info['cuda']}" if have is not None
                   else f"no 'CUDA Version' in the nvidia-smi output (ssh rc={cp.returncode})")
            err = (f"driver below {c.min_cuda}: {DRIVER_NOT_COUNTED}; pod {pod.id}: {why}, driver {info['driver']}, "
                   f"gpu {info['gpu']}; raw output {rel(path)}")
            self.step("driver_check", "failed", pod_id=pod.id, paths=[path], error=err, **extra)
            raise DriverTooOld(err)
        self.step("driver_check", "done", pod_id=pod.id, paths=[path], **extra,
                  note=f"{pod.id}: gpu {info['gpu']}, driver {info['driver']}, max CUDA {info['cuda']} (>= {c.min_cuda})")
        return info

    def ssh_ready(self, pod: PodInfo, why: str = "after pod_create") -> float:
        """PLAN Amendment 2026-10-23 (6) item 3: poll `ssh ... true` (ConnectTimeout 15) every ssh_ready_interval_s for
        up to ssh_ready_timeout_s; ready after ssh_ready_needed consecutive successes. run.jsonl `ssh_ready`
        started/done (seconds waited) or failed (last ssh stderr tail); a failure raises RuntimeError (setup failure)."""
        c = self.cfg
        self.step("ssh_ready", "started", pod_id=pod.id,
                  note=f"{pod.id} {pod.ip}:{pod.port} ({why}): `ssh ... true` every {c.ssh_ready_interval_s:.0f} s, "
                       f"{c.ssh_ready_needed} in a row, up to {c.ssh_ready_timeout_s:.0f} s")
        t0 = c.now()
        max_polls = int(c.ssh_ready_timeout_s // max(c.ssh_ready_interval_s, 1e-9)) + 1   # bound when the clock is faked
        polls = streak = 0
        last_err = ""
        while True:
            cp = self.run(probe_argv(pod, c), c.ssh_ready_connect_timeout_s + 15)
            polls += 1
            if cp.returncode == 0:
                streak += 1
            else:
                streak = 0
                last_err = f"rc={cp.returncode}: {((cp.stderr or '') + (cp.stdout or '')).strip()[-300:]}"
            waited = c.now() - t0
            if streak >= c.ssh_ready_needed:
                self.step("ssh_ready", "done", pod_id=pod.id, seconds=round(waited, 1), polls=polls,
                          note=f"{pod.id}: ready after {waited:.0f} s, {polls} probe(s)")
                return waited
            if waited >= c.ssh_ready_timeout_s or polls >= max_polls:
                err = (f"ssh not ready on pod {pod.id} ({pod.ip}:{pod.port}) after {waited:.0f} s, {polls} probe(s); "
                       f"last: {last_err or 'no failure, too few consecutive successes'}")
                self.step("ssh_ready", "failed", pod_id=pod.id, seconds=round(waited, 1), polls=polls, error=err)
                raise RuntimeError(err)
            c.sleep(c.ssh_ready_interval_s)

    def save_diagnostics(self, pod: PodInfo, reason: str) -> Path | None:
        """Before a pod that failed setup is deleted (Amendment 2026-10-23 (6) item 3): `runpodctl pod get <id> -o
        json` (env values dropped) and, if ssh answers, container diagnostics (DIAG_ON_FAILURE_CMD) into
        out_root/pods/<id>/diagnostics.txt. Never raises."""
        try:
            path = self.out_root / "pods" / pod.id / "diagnostics.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            parts = [f"# diagnostics for pod {pod.id} ({pod.name}) at {_utc(self.cfg.now())}", f"# reason: {reason}", ""]
            try:
                got = self.run(["runpodctl", "pod", "get", pod.id, "-o", "json"], 60)
                parts.append(f"== runpodctl pod get {pod.id} -o json (rc={got.returncode}; env values dropped)")
                try:
                    parts.append(json.dumps(redact_pod_json(json.loads(got.stdout)), indent=2, sort_keys=True))
                except ValueError:
                    parts.append("(output not JSON; not saved)")
                if got.stderr:
                    parts.append("stderr: " + got.stderr.strip()[-500:])
            except Exception as e:   # noqa: BLE001
                parts.append(f"== runpodctl pod get failed: {type(e).__name__}: {e}")
            parts.append("")
            try:
                if not pod.ip:
                    parts.append("== ssh diagnostics skipped: no ssh address")
                else:
                    probe = self.run(probe_argv(pod, self.cfg), self.cfg.ssh_ready_connect_timeout_s + 15)
                    if probe.returncode != 0:
                        parts.append(f"== ssh diagnostics skipped: ssh probe rc={probe.returncode}: "
                                     f"{(probe.stderr or '').strip()[-300:]}")
                    else:
                        cp = self.run(probe_argv(pod, self.cfg, DIAG_ON_FAILURE_CMD), 90)
                        parts.append(f"== ssh diagnostics (rc={cp.returncode})")
                        parts.append(cp.stdout or "")
                        if cp.stderr:
                            parts.append("--- stderr ---\n" + cp.stderr[-2000:])
            except Exception as e:   # noqa: BLE001
                parts.append(f"== ssh diagnostics failed: {type(e).__name__}: {e}")
            path.write_text(rel_text(redact(["\n".join(parts) + "\n"])), encoding="utf-8")
            self.step("diagnostics", "done", pod_id=pod.id, paths=[path], note=f"{pod.id}: saved before deletion ({reason[:200]})")
            return path
        except Exception as e:   # noqa: BLE001  never fail the cleanup
            try:
                self.say(f"diagnostics for pod {pod.id} could not be saved: {type(e).__name__}: {e}")
            except Exception:   # noqa: BLE001
                pass
            return None

    def setup(self, pod: PodInfo) -> None:
        """Container readiness (Amendment 2026-10-23 (7)), SSH readiness, the driver check (Amendment (7)), then
        pod_setup.sh (with the code push); on any failure the pod's diagnostics are saved before the exception reaches
        the caller that deletes the pod."""
        if pod.setup_done:
            return
        try:
            self.container_ready(pod)
            self.ssh_ready(pod)
            self.driver_check(pod)
            self._setup(pod)
        except Exception as e:
            if not getattr(e, "p6_setup_logged", False):
                self.step("setup", "failed", error=f"{pod.id}: {type(e).__name__}: {e}", pod_id=pod.id)
            self.save_diagnostics(pod, f"setup failed: {type(e).__name__}: {e}")
            raise

    def _setup(self, pod: PodInfo) -> None:
        if self.cfg.baked_template:
            self.step("setup", "skipped", note=f"{pod.id}: baked template {self.cfg.baked_template}", pod_id=pod.id)
            pod.setup_done = True
            return
        self.step("setup", "started", pod_id=pod.id, note=f"{pod.id}: pod_setup.sh over ssh"
                  + (f" (template {self.cfg.template_id}: steps 1-6 skipped on the prebuilt image)" if self.cfg.template_id else ""))
        t0 = self.cfg.now()
        if self.cfg.control_loop_commit == "local":
            self.push_repo(pod)
        cp = self.ssh(pod, f"export {setup_env_prefix(self.cfg)}; bash -s", timeout=self.cfg.setup_timeout_s,
                      stdin=Path(self.cfg.setup_script).read_text(encoding="utf-8"))
        logp = self.out_root / "pods" / pod.id / "setup.log"
        logp.parent.mkdir(parents=True, exist_ok=True)
        logp.write_text(rel_text((cp.stdout or "") + ("\n--- stderr ---\n" + cp.stderr if cp.stderr else "")), encoding="utf-8")
        got, missing = self.collect_files(pod)
        files_note = f"; pod files collected {len(got)}" + (f", not on the pod: {', '.join(missing)}" if missing else "")
        if cp.returncode != 0:
            self.step("setup", "failed", error=f"{pod.id}: rc={cp.returncode}: {(cp.stderr or cp.stdout)[-500:]}",
                      paths=[logp, *got], pod_id=pod.id, note=f"{pod.id}{files_note}")
            err = RuntimeError(f"setup failed on pod {pod.id} (rc={cp.returncode}); see {rel(logp)}")
            err.p6_setup_logged = True   # type: ignore[attr-defined]
            raise err
        pod.setup_done = True
        self.step("setup", "done", note=f"{pod.id}: {self.cfg.now() - t0:.0f}s{files_note}", paths=[logp, *got], pod_id=pod.id)

    def collect_files(self, pod: PodInfo) -> tuple[list[Path], list[str]]:
        """rsync each of cfg.remote_collect that exists on the pod into out_root/pods/<pod id>/ (the full compile
        logs, the FUSE mode, the toolchain env file). Returns (collected local paths, remote paths not found); the
        caller logs them (no `collect` step here: sweep.delete_latency reads the last collect per pod); never raises."""
        dest = self.out_root / "pods" / pod.id
        got, missing = [], []
        for remote in self.cfg.remote_collect:
            local = dest / os.path.basename(remote)
            try:
                cp = self.rsync(pod, remote, local, single_file=True)
            except Exception as e:   # never let a log copy fail the run
                cp = subprocess.CompletedProcess([], 1, "", str(e))
            if cp.returncode == 0 and local.exists():
                got.append(local)
            else:
                missing.append(remote)
        return got, missing

    def push_repo(self, pod: PodInfo) -> None:
        """Copy this host's `control_loop/` package (and pyproject.toml) to the pod's /workspace/src/control-loop
        through a tar stream over ssh (no git clone of an unpushed tree; no results, no .venv, no .git)."""
        dst = f"{self.cfg.volume_mount}/src/control-loop"
        tar = subprocess.run(["tar", "czf", "-", "--exclude=__pycache__", "-C", str(REPO), "control_loop", "pyproject.toml"],
                             capture_output=True, timeout=120)
        if tar.returncode != 0:
            raise RuntimeError(f"tar of the local control_loop tree failed: {tar.stderr.decode(errors='replace')[-300:]}")
        cmd = f"mkdir -p {shlex.quote(dst)} && tar xzf - -C {shlex.quote(dst)}"
        # Amendment 2026-10-23 (6) item 3: on an ssh transport failure (rc 255, or the ssh timed out) wait
        # push_retry_wait_s, re-run the readiness probe once and retry the push once; both attempts logged.
        for attempt in (1, 2):
            self.step("push_repo", "started", pod_id=pod.id, attempt=attempt,
                      note=f"{pod.id}: attempt {attempt}: control_loop/ tar stream ({len(tar.stdout)} bytes) -> {dst}")
            try:
                cp = subprocess.run(ssh_base(pod, self.cfg) + [cmd], input=tar.stdout, capture_output=True, timeout=self.cfg.ssh_timeout_s)
                rc, err = cp.returncode, cp.stderr.decode(errors="replace")[-300:]
            except subprocess.TimeoutExpired:
                rc, err = 124, f"ssh timed out after {self.cfg.ssh_timeout_s} s"
            except FileNotFoundError as e:
                rc, err = 127, str(e)
            if rc == 0:
                self.step("push_repo", "done", pod_id=pod.id, attempt=attempt, note=f"{pod.id}: attempt {attempt} ok")
                return
            transport = rc in (255, 124)
            self.step("push_repo", "failed", pod_id=pod.id, attempt=attempt,
                      error=f"{pod.id}: attempt {attempt} rc={rc}: {err}",
                      note="ssh transport failure; one retry follows" if transport and attempt == 1 else None)
            if attempt == 2 or not transport:
                raise RuntimeError(f"pushing the control_loop tree to pod {pod.id} failed rc={rc}"
                                   + (" (attempt 2 of 2)" if attempt == 2 else "") + f": {err}")
            self.cfg.sleep(self.cfg.push_retry_wait_s)
            self.ssh_ready(pod, why="before the push retry")

    def run_episode(self, pod: PodInfo, i: int, spec: Any, attempt: int) -> tuple[bool, str | None]:
        """One episode on a set-up pod. Returns (ok, error)."""
        dest = self.dests[i]
        cid = spec.cluster_id
        pod.episode_id = cid
        self.step("episode", "started", note=f"{cid} attempt {attempt} on pod {pod.id}", pod_id=pod.id, episode_id=cid)
        pre = run_prelude(spec, self.cfg)
        inst = payload_install_cmd(spec, self.cfg)
        cmd = pre + ("; " + inst if inst else "") + "; " + start_cmd(spec, self.cfg)
        # the payload travels on stdin (Amendment (25) item 5); start_cmd itself detaches run_redteam.sh under nohup,
        # with stdin from /dev/null, and returns its pid
        cp = self.ssh_query(pod, cmd, stdin=payload_b64(spec) if inst else None)
        if cp.returncode != 0:
            return False, f"start failed rc={cp.returncode}: {(cp.stderr or cp.stdout)[-400:]}"
        pid = (cp.stdout.strip().splitlines() or ["?"])[-1].strip()
        deadline = self.cfg.now() + float(spec.redruntime) * 3600 + self.cfg.episode_margin_s
        remote_dir, misses = "", 0
        while True:
            self.cfg.sleep(self.cfg.poll_s)
            found = self.ssh_query(pod, find_cmd(spec, self.cfg))
            if found.returncode != 0 and not found.stdout.strip():
                misses += 1
                if misses >= self.cfg.unreachable_polls:
                    return False, f"pod {pod.id} unreachable for {misses} polls: {found.stderr[-200:]}"
                continue
            misses = 0
            remote_dir = found.stdout.strip() or remote_dir
            if remote_dir:
                self.rsync(pod, remote_dir, dest)
                if (dest / "eval" / "metrics.json").exists():
                    break
            alive = self.ssh_query(pod, f"kill -0 {shlex.quote(pid)} 2>/dev/null").returncode == 0
            if not alive:
                if remote_dir:
                    self.rsync(pod, remote_dir, dest)
                if (dest / "eval" / "metrics.json").exists():
                    break
                return False, f"run_redteam.sh (pid {pid}) exited without eval/metrics.json"
            if self.cfg.now() > deadline:
                budget = int(float(spec.redruntime) * 3600 + self.cfg.episode_margin_s)
                return False, f"timeout: no eval/metrics.json {budget} s after the start"
        self.step("episode", "done", note=f"{cid} on pod {pod.id}", pod_id=pod.id, episode_id=cid)
        # collect: final rsync of the eval dir and the runner output beside it
        self.step("collect", "started", note=f"{cid} <- {pod.id}:{remote_dir}", pod_id=pod.id, episode_id=cid)
        self.rsync(pod, remote_dir, dest)
        self.rsync(pod, f"{episode_remote_out(spec, self.cfg)}/{cid}.out", dest.parent / f"{dest.name}.out", single_file=True)
        (dest / "p6_episode.json").write_text(json.dumps(dict(
            cluster_id=cid, experiment=spec.experiment, pod_id=pod.id, pod_name=pod.name, data_center=pod.data_center,
            gpu_type=pod.gpu_type, hourly_rate=pod.rate, attempt=attempt, remote_eval_dir=remote_dir,
            collected_at=_utc(self.cfg.now()), run_id=self.run_id), indent=2, sort_keys=True), encoding="utf-8")
        self.step("collect", "done", paths=[dest], note=f"{cid} -> {rel(dest)}", pod_id=pod.id, episode_id=cid)
        return True, None

    def fail_episode(self, i: int, spec: Any, pod: PodInfo | None, attempt: int, err: str) -> None:
        dest = self.dests[i]
        failed_dir = dest.parent / "_failed" / (spec.cluster_id if attempt == 1 else f"{spec.cluster_id}_attempt{attempt}")
        if dest.exists():
            failed_dir.parent.mkdir(parents=True, exist_ok=True)
            if failed_dir.exists():
                shutil.rmtree(failed_dir)
            shutil.move(str(dest), str(failed_dir))
        self.step("episode", "failed", error=f"{spec.cluster_id} attempt {attempt}: {err}",
                  paths=[failed_dir] if failed_dir.exists() else [], pod_id=pod.id if pod else None, episode_id=spec.cluster_id,
                  note="partial logs in _failed/ (never counted)")
        self.say(f"episode {spec.cluster_id} attempt {attempt} failed: {err}")

    def worker(self, pod: PodInfo | None, queue: deque[int]) -> None:
        """Run the queued episodes on `pod` serially; a failure deletes the pod, moves the logs aside and re-runs the
        episode once on a fresh pod (the project's one retry); the remaining queue follows on that pod."""
        attempts: dict[int, int] = {}
        driver_skips: set[int] = set()     # episodes whose one pod with a driver below min_cuda was not counted
        while queue:
            i = queue[0]
            spec = self.specs[i]
            attempts[i] = attempts.get(i, 0) + 1
            if pod is None:
                pod = self.create_pod(f"{self.names_for[i]}{'-retry' if attempts[i] > 1 else '-again'}", spec)
                if pod is None:
                    for j in list(queue):
                        self.results[j] = dict(status="lost", dest=rel(self.dests[j]), attempts=attempts.get(j, 0),
                                               error="no pod could be created")
                        self.step("episode", "failed", error=f"{self.specs[j].cluster_id}: no pod could be created",
                                  episode_id=self.specs[j].cluster_id)
                    queue.clear()
                    return
            driver_old = False
            try:
                self.setup(pod)
                ok, err = self.run_episode(pod, i, spec, attempts[i])
            except Exception as e:   # setup or ssh failure on this pod
                ok, err = False, f"{type(e).__name__}: {e}"
                driver_old = isinstance(e, DriverTooOld)
            if ok:
                queue.popleft()
                self.results[i] = dict(status="collected", dest=rel(self.dests[i]), attempts=attempts[i], pod_id=pod.id)
                if not queue:
                    self.delete_pod(pod, note="last episode collected")
                continue
            self.fail_episode(i, spec, pod, attempts[i], err or "unknown error")
            self.delete_pod(pod, note="episode failed")
            pod = None
            if driver_old and i not in driver_skips:
                # Amendment 2026-10-23 (7): a driver below min_cuda is not counted as an attempt (once per episode, so a
                # run of old-driver hosts still ends)
                driver_skips.add(i)
                attempts[i] -= 1
                self.say(f"episode {spec.cluster_id}: pod driver below {self.cfg.min_cuda}, {DRIVER_NOT_COUNTED}; fresh pod")
                continue
            if attempts[i] >= 2:
                queue.popleft()
                self.results[i] = dict(status="lost", dest=rel(self.dests[i]), attempts=attempts[i], error=err)
                self.say(f"episode {spec.cluster_id} lost after {attempts[i]} attempts (round at n-1, invalid under V1)")

    # orchestration
    def go(self) -> list[Path]:
        k = len(self.specs)
        if k == 0:
            return []
        if k > MAX_PODS:
            raise LaunchError(f"{k} episodes in one launch; at most {MAX_PODS} (PLAN §1.6(d))")
        if not self.dry_run:
            for name in SECRET_ENV[:1]:
                if name in DEFAULT_ENV_NAMES and name not in os.environ:
                    raise LaunchError(f"{name} is not set on this host; nothing created")
        self.names_for = {i: f"{NAME_PREFIX}{self.run_id}-e{i + 1}" for i in range(k)}
        if self.dry_run:
            return self.dry()
        # 1. create up to k pods in parallel (each create blocks with --wait up to cfg.wait_timeout)
        with ThreadPoolExecutor(max_workers=k) as ex:
            created = list(ex.map(lambda i: self.create_pod(self.names_for[i], self.specs[i]), range(k)))
        pods = [p for p in created if p is not None]
        if not pods:
            raise LaunchError("no pod could be created within the deadline (stock LOW?); nothing to run")
        if len(pods) < k:
            self.serial_note = f"serial fallback: {k} episodes on {len(pods)} pods (PLAN §7.7(2))"
            self.say(self.serial_note)
            self.step("pod_create", "done", note=self.serial_note)
        # 2.-4. assign episodes round-robin and run each pod's queue in its own thread
        queues: list[deque[int]] = [deque() for _ in pods]
        for i in range(k):
            queues[i % len(pods)].append(i)
        with ThreadPoolExecutor(max_workers=len(pods)) as ex:
            list(ex.map(lambda pq: self.worker(pq[0], pq[1]), zip(pods, queues)))
        return self.collected()

    def collected(self) -> list[Path]:
        return [self.dests[i] for i in range(len(self.specs)) if self.results.get(i, {}).get("status") == "collected"]

    def write_summary(self, error: str | None = None) -> None:
        with self.lock:
            pods = [dict(id=p.id, name=p.name, episode_id=p.episode_id, rate=p.rate, data_center=p.data_center,
                         gpu_type=p.gpu_type, deleted=p.deleted) for p in self.pods.values()]
        rec = dict(run_id=self.run_id, dry_run=self.dry_run, episodes={self.specs[i].cluster_id: self.results.get(i, dict(status="not run"))
                                                                     for i in range(len(self.specs))},
                   pods=pods, serial_fallback=self.serial_note, error=error, written=_utc())
        self.out_root.mkdir(parents=True, exist_ok=True)
        (self.out_root / "launch.json").write_text(rel_text(json.dumps(rec, indent=2, sort_keys=True)), encoding="utf-8")

    def dry(self) -> list[Path]:
        self.say(f"DRY RUN: {len(self.specs)} episode(s), nothing is created")
        for i, spec in enumerate(self.specs):
            name = self.names_for[i]
            ph = PodInfo(id="<pod-id>", name=name, ip="<pod-ip>", port=0, rate=self.cfg.rate_usd_per_h, created_at=0.0)
            env = pod_env(spec, self.cfg, values=False)
            lines = [
                ("pod_create", redact(create_argv(name, env, self.cfg))),
                ("container_ready", container_ready_text(self.cfg)),
                ("ssh_ready", ssh_ready_text(ph, self.cfg)),
                ("driver_check", driver_check_text(ph, self.cfg)),
                ("setup", ("skipped: baked template " + self.cfg.baked_template) if self.cfg.baked_template else
                 shlex.join(ssh_base(ph, self.cfg) + [f"export {setup_env_prefix(self.cfg)}; bash -s"]) + f" < {rel(self.cfg.setup_script)}"),
                ("episode", shlex.join(ssh_base(ph, self.cfg) + [run_prelude(spec, self.cfg)
                                                                 + ("; " + payload_install_cmd(spec, self.cfg, None) if getattr(spec, "payload_file", None) else "")
                                                                 + "; " + start_cmd(spec, self.cfg)])),
                ("collect", f"every {int(self.cfg.poll_s)} s until eval/metrics.json: "
                            + shlex.join(rsync_argv(ph, f"{episode_remote_out(spec, self.cfg)}/*_c{spec.cluster_id}", self.dests[i], self.cfg))),
                ("pod_delete", f"runpodctl pod delete <pod-id>   (within 2 min of collection; watchdog deletes {NAME_PREFIX}* older than 60 min)"),
            ]
            for step, text in lines:
                text = text.replace("-p 0 ", "-p <pod-port> ")
                self.say(f"would run [{step}] {text}")
                self.step(step, "skipped", note=f"dry run {spec.cluster_id}: {text}", episode_id=spec.cluster_id)
            self.results[i] = dict(status="dry_run", dest=rel(self.dests[i]), attempts=0)
        return list(self.dests)


def launch(specs: Sequence[Any], out_root: Path | str, log: Callable = runlog.log_step, dry_run: bool = False, *,
           dests: Sequence[Path | str] | None = None, pods_log: Path | str | None = None, run_id: str | None = None,
           cfg: PodConfig | None = None) -> list[Path]:
    """PLAN §7.7 for one launch (module docstring). Returns the collected eval dirs in spec order (fewer than
    `specs` if an episode was lost twice; `out_root/launch.json` says which). Raises LaunchError after cleanup."""
    out_root = Path(out_root)
    cfg = cfg or PodConfig()
    specs = list(specs)
    dests_p = [Path(d) for d in dests] if dests is not None else [out_root / f"e{i + 1}" for i in range(len(specs))]
    if len(dests_p) != len(specs):
        raise LaunchError(f"{len(dests_p)} dests for {len(specs)} specs")
    rid = run_id or (specs[0].experiment if specs else out_root.name)
    L = _Launch(specs, out_root, log, cfg, dests_p, rid, Path(pods_log) if pods_log else out_root / "pods.jsonl", dry_run)
    try:
        out = L.go()
    except LaunchError as e:
        L.cleanup()
        L.write_summary(error=str(e))
        if not e.partial:
            e.partial = L.collected()
        raise
    except BaseException as e:
        L.cleanup()
        L.write_summary(error=f"{type(e).__name__}: {e}")
        raise LaunchError(f"launch {rid} failed: {type(e).__name__}: {e}", L.collected()) from e
    else:
        L.cleanup()                       # idempotent: deletes nothing when every pod is already gone
        L.write_summary()
        with L.lock:
            alive = [p.id for p in L.pods.values() if not p.deleted]
        if alive:
            raise LaunchError(f"pods still alive after cleanup: {alive}; delete them by hand", out)
        return out


# --- spend from pods.jsonl ----------------------------------------------------------------------------------------

def read_pods_log(path: Path | str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def gpu_spend(path: Path | str, now: float | None = None, run_id: str | None = None,
              episode_prefix: str | None = None) -> dict:
    """GPU dollars and seconds from a pods.jsonl: every delete line's usd, plus a running estimate for any pod with
    a create line and no delete line (counted until it is deleted). `run_id` restricts to one launch;
    `episode_prefix` to pods whose (last) episode id starts with it, e.g. "<replicate>-r0a-" for one round."""
    now = time.time() if now is None else now
    recs = [r for r in read_pods_log(path) if (run_id is None or r.get("run_id") == run_id)
            and (episode_prefix is None or str(r.get("episode_id") or "").startswith(episode_prefix))]
    deleted = {r["pod_id"] for r in recs if r["event"] == "delete"}
    usd = sum(float(r.get("usd") or 0.0) for r in recs if r["event"] == "delete")
    secs = sum(int(r.get("seconds_billed") or 0) for r in recs if r["event"] == "delete")
    live = []
    for r in recs:
        if r["event"] == "create" and r["pod_id"] not in deleted:
            t = parse_time(r["time"]) or now
            s = max(0.0, now - t)
            usd += s / 3600.0 * float(r.get("hourly_rate") or H100_RATE_USD)
            secs += int(s)
            live.append(r["pod_id"])
    return dict(usd=round(usd, 4), seconds=secs, creates=sum(1 for r in recs if r["event"] == "create"),
                deletes=len(deleted), live=live)


# --- smoke test (PLAN §6.1) ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class _SmokeSpec:
    arena_root: str
    side_task: str = "payload"
    redruntime: float = 0.0
    seed: int = 733
    experiment: str = "phase6_smoke"
    cluster_id: str = "smoke"
    env_names: tuple = DEFAULT_ENV_NAMES
    payload_file: str | None = None


# the whole smoke_test.sh over ssh: compile, the stock-kernel benchmark (bench timeout 1200 s) and, after a crash, one
# CUDA_LAUNCH_BLOCKING prompt (Amendment 2026-10-22 (5)); was 1800 s
SMOKE_TIMEOUT_S = 3600


def smoke(out_root: Path | str, cfg: PodConfig | None = None, allow_paid: bool = False, dry_run: bool = False,
          log: Callable = runlog.log_step) -> int:
    """One pod, pod_setup.sh to the end, then smoke_test.sh (nvcc, torch cuda, fuse-overlayfs, opencode, starter
    kernels, run_redteam.sh --dry_run, arena_root verify; the single <= $0.05 opencode call only with
    `allow_paid`), output collected to out_root/smoke.log, pod deleted. Returns the smoke script's rc."""
    out_root, cfg = Path(out_root), cfg or PodConfig()
    # Amendment 2026-10-22 (5): the smoke test's stock_kernels_bench writes the diagnostic's logs; collect them too
    cfg = replace(cfg, remote_collect=tuple(cfg.remote_collect) + tuple(x for x in DIAG_COLLECT if x not in cfg.remote_collect))
    spec = _SmokeSpec(arena_root=cfg.remote_arena_root)
    rid = "smoke-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    L = _Launch([spec], out_root, log, cfg, [out_root / "smoke"], rid, out_root / "pods.jsonl", dry_run)
    name = f"{NAME_PREFIX}smoke"
    flags = ("--allow-paid " if allow_paid else "") + f"--arena-root {shlex.quote(cfg.remote_arena_root)}"
    if dry_run:
        ph = PodInfo(id="<pod-id>", name=name, ip="<pod-ip>", port=0, rate=cfg.rate_usd_per_h, created_at=0.0)
        L.say("DRY RUN smoke test: nothing is created")
        for step, text in [("pod_create", redact(create_argv(name, pod_env(spec, cfg, values=False), cfg))),
                           ("container_ready", container_ready_text(cfg)),
                           ("ssh_ready", ssh_ready_text(ph, cfg)),
                           ("driver_check", driver_check_text(ph, cfg)),
                           ("setup", shlex.join(ssh_base(ph, cfg) + [f"export {setup_env_prefix(cfg)}; bash -s"]) + f" < {rel(cfg.setup_script)}"),
                           ("episode", shlex.join(ssh_base(ph, cfg) + [f"bash -s -- {flags}"]) + f" < {rel(cfg.smoke_script)}"),
                           ("collect", f"stdout -> {rel(out_root / 'smoke.log')}; "
                                       + ", ".join(cfg.remote_collect) + f" -> {rel(out_root / 'pods' / '<pod-id>')}/"),
                           ("pod_delete", "runpodctl pod delete <pod-id>")]:
            L.say(f"would run [{step}] {text.replace('-p 0 ', '-p <pod-port> ')}")
            L.step(step, "skipped", note=f"dry run smoke: {text}")
        return 0
    rc = 1
    try:
        L.names_for = {0: name}
        pod = L.create_pod(name, spec)
        if pod is None:
            raise LaunchError("smoke: no pod could be created")
        L.setup(pod)
        L.step("episode", "started", note="smoke_test.sh" + (" --allow-paid" if allow_paid else ""), pod_id=pod.id)
        cp = L.ssh(pod, f"export {setup_env_prefix(cfg)}; bash -s -- {flags}", timeout=SMOKE_TIMEOUT_S,
                   stdin=Path(cfg.smoke_script).read_text(encoding="utf-8"))
        out_root.mkdir(parents=True, exist_ok=True)
        logp = out_root / "smoke.log"
        logp.write_text(rel_text(redact([cp.stdout or ""]) + "\n--- stderr ---\n" + redact([cp.stderr or ""])), encoding="utf-8")
        rc = cp.returncode
        L.step("episode", "done" if rc == 0 else "failed", error=None if rc == 0 else f"smoke_test.sh rc={rc}",
               paths=[logp], pod_id=pod.id, cost=0.05 if allow_paid else 0.0,
               note="paid opencode call included (<= $0.05, upper counted)" if allow_paid else "no paid call")
        got, missing = L.collect_files(pod)   # the smoke test's p6_compile.log (and the setup files again)
        L.step("collect", "done", paths=[logp, *got], pod_id=pod.id,
               note=f"pod files collected {len(got)}" + (f", not on the pod: {', '.join(missing)}" if missing else ""))
        L.delete_pod(pod, note="smoke test finished")
    finally:
        L.cleanup()
        L.write_summary()
    return rc


# --- stock-kernel diagnostic (PLAN Amendment 2026-10-22 (3), item 2) ------------------------------------------------

# Files the diagnostic leaves on the pod (collected into <out>/pods/<pod id>/ with REMOTE_COLLECT).
DIAG_COLLECT = ("/workspace/p6_diag_bench.log", "/workspace/p6_diag_info.txt", "/workspace/p6_diag_last_bench.json",
                "/workspace/p6_diag_sdpa_probe.log", "/workspace/p6_diag_bench_starter.log",
                "/workspace/p6_diag_starter_last_bench.json", "/workspace/p6_diag_bench_blocking.log")
DIAG_ENV_NAMES = tuple(n for n in DEFAULT_ENV_NAMES if n != "OPENROUTER_API_KEY")   # no agent: no key on the pod
DIAG_SEED = 733                                 # ARENA_SEED as an episode of replicate qwen3_733 exports it

# Streamed over ssh (`bash -s`) after pod_setup.sh steps 1-7. No agent and no model API call. What an episode's
# evaluator does when the agent left no results file (settings/cuda_kernel/evaluate.py 55-62): bench.run_benchmark(
# ArenaConfig()) in the task snapshot, i.e. compile the snapshot's kernels/, baseline (bench.py 196-203: starter_kernels
# looked up at $ARENA_ROOT/starter_kernels, absent in the composed root -> vanilla PyTorch), then the injected
# kernels' benchmark. `bash bench.sh` with no flag runs the same function with the same defaults (bench.py 292-303)
# and also prints the SUMMARY block and writes workspace/last_bench.json. The kernels are the unmodified
# task_context/kernels/ an agent starts from (copied as pipeline_redteam.sh:145-146 does), so "stock kernels" here
# means "an episode in which the agent made no edit".
DIAG_SCRIPT = r"""#!/usr/bin/env bash
# Phase 6 stock-kernel diagnostic (PLAN Amendment 2026-10-22 (3), item 2), streamed by `pods.py diag`.
set -uo pipefail
: "${WORKSPACE:=/workspace}"
: "${ARENA_ROOT:=$WORKSPACE/arena_root}"
: "${HF_HOME:=$WORKSPACE/hf}"
: "${P6_DIAG_SEED:=733}"
: "${P6_DIAG_BENCH_TIMEOUT:=1200}"
[ -f /etc/rp_environment ] && . /etc/rp_environment
unset RUNPOD_API_KEY
[ -f "$WORKSPACE/p6_env.sh" ] && . "$WORKSPACE/p6_env.sh"
export HF_HOME ARENA_ROOT TOKENIZERS_PARALLELISM=false ARENA_SEED="$P6_DIAG_SEED"
TC="$ARENA_ROOT/settings/cuda_kernel/task_context"
RA="$WORKSPACE/src/ResearchArena"
LOG="$WORKSPACE/p6_diag_bench.log"
INFO="$WORKSPACE/p6_diag_info.txt"
W="$WORKSPACE/p6_diag"
echo "# p6 stock-kernel diagnostic started $(date -u +%FT%TZ)" > "$LOG"
rm -rf "$W"; mkdir -p "$W"

fresh_copy() {   # fresh_copy <dir>: the task dir an episode's agent gets (pipeline_redteam.sh:145-146: cp -r task_context/*)
  rm -rf "$1"; mkdir -p "$1"; cp -r "$TC/"* "$1/"
  rm -rf "$1/workspace"; find "$1" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
}

verdict() {   # verdict <name> <log> <bench rc>
  python3 - "$1" "$2" "$3" <<'PY'
import re, sys
name, log, rc = sys.argv[1:4]
text = open(log, errors="replace").read()
lines = text.splitlines()
def grab(k):
    m = re.findall(r"^\s*%s\s*=\s*([0-9.]+)" % k, text, re.M)
    return m[-1] if m else None
agent, base, sp = grab("AGENT_TPS"), grab("BASELINE_TPS"), grab("SPEEDUP")
if rc == "0" and agent is not None:
    print("DIAG %s: RUN ok tps=%s baseline_tps=%s speedup=%s" % (name, agent, base, sp))
elif rc == "0" and "INJECT_STATUS=NONE" in text:
    print("DIAG %s: RUN ok tps=%s (no kernel injected; agent_tps = baseline)" % (name, base))
else:
    err = None
    for pat in (r"CUDA error", r"^[\w.]+(Error|Exception)\b", r"^COMPILE_STATUS=FAIL", r"\berror\b", r"^ninja: build stopped"):
        hit = [l.strip() for l in lines if re.search(pat, l.strip())]
        if hit:
            err = hit[0]; break
    if err is None:
        err = (lines[-1].strip() if lines else "no output")
    print("DIAG %s: CRASH %s (bench rc=%s)" % (name, err[:300], rc))
PY
}

bench_run() {   # bench_run <dir> <log> [bench args...]; returns bench.sh's rc
  local d="$1" log="$2"; shift 2
  local rc=0
  ( cd "$d" && timeout --signal=TERM --kill-after=30s "$P6_DIAG_BENCH_TIMEOUT" bash bench.sh "$@" ) >> "$log" 2>&1 || rc=$?
  echo "--- bench.sh $* rc=$rc $(date -u +%FT%TZ) ---" >> "$log"
  return $rc
}

# 0. the task dir and what the bench will load
fresh_copy "$W/stock"
{
  echo "# no agent; ResearchArena task_context from $TC (pinned 58776e0), copied as pipeline_redteam.sh:145-146 does"
  echo "# ARENA_ROOT=$ARENA_ROOT ARENA_SEED=$ARENA_SEED HF_HOME=$HF_HOME CUDA_HOME=${CUDA_HOME:-unset} TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST:-unset} python3=$(readlink -f "$(command -v python3)")"
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
  echo "--- pip show transformers torch ---"
  python3 -m pip show transformers torch 2>&1 || uv pip show --python python3 transformers torch 2>&1
  python3 -c "import torch, transformers; print('import: torch', torch.__version__, 'cuda', torch.version.cuda, 'transformers', transformers.__version__)"
  echo "--- model config as bench.py loads it (config.ArenaConfig, AutoConfig.from_pretrained) ---"
  ( cd "$W/stock" && python3 - <<'PY'
from config import ArenaConfig
from transformers import AutoConfig
c = ArenaConfig()
cfg = AutoConfig.from_pretrained(c.model_id, cache_dir=c.hf_cache_dir, trust_remote_code=True)
hd = getattr(cfg, "head_dim", None)
derived = hd is None
hd = hd if hd is not None else cfg.hidden_size // cfg.num_attention_heads
print("MODEL_CONFIG model_id=%s num_attention_heads=%s num_key_value_heads=%s head_dim=%s%s hidden_size=%s "
      "num_hidden_layers=%s dtype=%s max_new_tokens=%s seed=%s"
      % (c.model_id, cfg.num_attention_heads, getattr(cfg, "num_key_value_heads", None), hd,
         " (hidden_size/num_attention_heads)" if derived else "", cfg.hidden_size, cfg.num_hidden_layers,
         c.dtype, c.max_new_tokens, c.seed))
PY
  )
  echo "--- the copied kernels against the pinned checkout ---"
  diff -r "$W/stock/kernels" "$RA/settings/cuda_kernel/task_context/kernels" && echo "kernels/ identical to the checkout's task_context/kernels/"
  if [ -d "$ARENA_ROOT/starter_kernels" ]; then echo "starter_kernels at $ARENA_ROOT/starter_kernels: present (baseline = starter kernels)";
  else echo "starter_kernels at $ARENA_ROOT/starter_kernels: absent (bench.py 201-204: baseline = vanilla PyTorch, as in every run2 episode)"; fi
} > "$INFO" 2>&1
cat "$INFO" >> "$LOG"
grep '^MODEL_CONFIG' "$INFO" | sed 's/^MODEL_CONFIG/DIAG model_config:/' || echo "DIAG model_config: not read (see p6_diag_info.txt)"
grep -E '^(Name|Version): ' "$INFO" | paste -sd' ' | sed 's/^/DIAG versions: /'
sed -n 's/^import: torch .* transformers \(.*\)$/DIAG transformers: \1/p' "$INFO" | head -1
echo "--- 1. stock kernels: cd <task copy> && bash bench.sh (full benchmark) ---" >> "$LOG"

# 1. the stock kernels, full benchmark (the verdict)
rc=0; bench_run "$W/stock" "$LOG" || rc=$?
cp "$W/stock/workspace/last_bench.json" "$WORKSPACE/p6_diag_last_bench.json" 2>/dev/null || true
V1=$(verdict stock_kernels "$LOG" "$rc"); echo "$V1"; echo "$V1" >> "$LOG"

# 2. which tensors reach ops.attention (no CUDA kernel: a PyTorch stand-in records the shapes and computes SDPA)
( cd "$W/stock" && timeout 600 python3 - <<'PY'
import torch
import torch.nn.functional as F
from config import ArenaConfig
from bench import load_model_and_tokenizer
from inject import inject_agent_kernels
_sdpa = F.scaled_dot_product_attention          # the real function, taken before inject.py swaps it per forward
calls = []
class ShapeOps:
    def attention(self, q, k, v, causal):
        calls.append((tuple(q.shape), tuple(k.shape), tuple(v.shape), bool(causal)))
        if k.size(1) != q.size(1):
            r = q.size(1) // k.size(1)
            k, v = k.repeat_interleave(r, 1), v.repeat_interleave(r, 1)
        return _sdpa(q, k, v, is_causal=causal)
c = ArenaConfig()
model, tok = load_model_and_tokenizer(c)
print("attn_implementation", getattr(model.config, "_attn_implementation", None), flush=True)
print("injected", inject_agent_kernels(model, ShapeOps()), flush=True)
with torch.no_grad():
    x = tok("Hello", return_tensors="pt").to(c.device)
    model.generate(**x, max_new_tokens=4, do_sample=False, max_length=None)
for q, k, v, cz in calls[:3]:
    print("SDPA_CALL q=%s k=%s v=%s causal=%s" % (q, k, v, cz))
qh = sorted({q[1] for q, k, v, cz in calls}); kh = sorted({k[1] for q, k, v, cz in calls})
print("SDPA_SUMMARY calls=%d q_heads=%s kv_heads=%s" % (len(calls), qh, kh))
PY
) > "$WORKSPACE/p6_diag_sdpa_probe.log" 2>&1
python3 - "$WORKSPACE/p6_diag_sdpa_probe.log" <<'PY'
import re, sys
t = open(sys.argv[1], errors="replace").read()
m = re.search(r"SDPA_SUMMARY calls=(\d+) q_heads=(\[[^\]]*\]) kv_heads=(\[[^\]]*\])", t)
a = re.search(r"attn_implementation (\S+)", t)
if not m:
    print("DIAG sdpa_shapes: probe failed (see p6_diag_sdpa_probe.log): %s" % (t.strip().splitlines() or ["no output"])[-1][:200])
else:
    n, qh, kh = m.groups()
    same = qh == kh
    print("DIAG sdpa_shapes: ops.attention called %s times; query heads %s, key/value heads %s (%s); attn_implementation %s"
          % (n, qh, kh, "K/V expanded to the query head count" if same else "GQA K/V reach the kernel unexpanded",
             a.group(1) if a else "?"))
PY

# 3. the starter kernels (task_context/starter_kernels/*.cu in place of kernels/), full benchmark
#    (skipped when smoke_test.sh's stock_kernels_bench runs this script: P6_DIAG_SKIP_STARTER=1)
if [ "${P6_DIAG_SKIP_STARTER:-0}" != 1 ]; then
  fresh_copy "$W/starter"
  cp "$W/starter/starter_kernels/"*.cu "$W/starter/kernels/"
  echo "# starter_kernels/*.cu copied over kernels/ $(date -u +%FT%TZ)" > "$WORKSPACE/p6_diag_bench_starter.log"
  rc2=0; bench_run "$W/starter" "$WORKSPACE/p6_diag_bench_starter.log" || rc2=$?
  cp "$W/starter/workspace/last_bench.json" "$WORKSPACE/p6_diag_starter_last_bench.json" 2>/dev/null || true
  verdict starter_kernels "$WORKSPACE/p6_diag_bench_starter.log" "$rc2"
fi

# 4. only if the stock kernels crashed: one prompt with CUDA_LAUNCH_BLOCKING=1, so the error is raised at the
#    faulting launch and the Python frames name it
case "$V1" in
  *": CRASH "*)
    fresh_copy "$W/blocking"
    echo "# CUDA_LAUNCH_BLOCKING=1 bash bench.sh --prompts 1 $(date -u +%FT%TZ)" > "$WORKSPACE/p6_diag_bench_blocking.log"
    rc3=0; ( export CUDA_LAUNCH_BLOCKING=1; bench_run "$W/blocking" "$WORKSPACE/p6_diag_bench_blocking.log" --prompts 1 ) || rc3=$?
    verdict stock_kernels_blocking "$WORKSPACE/p6_diag_bench_blocking.log" "$rc3"
    grep -E 'File ".*(inject|bench|modeling_llama|sdpa_attention)\.py", line' "$WORKSPACE/p6_diag_bench_blocking.log" | tail -4 | sed 's/^ */DIAG blocking_frame: /'
    # the agent_ops function whose launch raised (inject.py calls ops.rmsnorm / ops.fused_mlp / ops.attention /
    # ops.rotary_embedding; the traceback's last such source line is the faulting launch under CUDA_LAUNCH_BLOCKING)
    fk=$(grep -oE '\bops\.(rmsnorm|fused_mlp|attention|rotary_embedding)\(' "$WORKSPACE/p6_diag_bench_blocking.log" | tail -1 | sed 's/^ops\.//; s/($//')
    echo "DIAG faulting_kernel: ${fk:-not named in the traceback (see p6_diag_bench_blocking.log)}"
    ;;
esac
rm -rf "$W"
echo "DIAG_DONE"
"""


@dataclass(frozen=True)
class _DiagSpec:
    arena_root: str
    side_task: str = "none"
    redruntime: float = 0.0
    seed: int = DIAG_SEED
    experiment: str = "phase6_diag"
    cluster_id: str = "diag"
    env_names: tuple = DIAG_ENV_NAMES
    payload_file: str | None = None


def diag_ssh_cmd(cfg: PodConfig) -> str:
    return f"export {setup_env_prefix(cfg)} P6_DIAG_SEED={DIAG_SEED}; bash -s -- diag"


def diag(out_root: Path | str, cfg: PodConfig | None = None, allow_paid: bool = False, dry_run: bool = False,
         log: Callable = runlog.log_step) -> int:
    """PLAN Amendment 2026-10-22 (3) item 2: ONE pod (`p6-diag`, current image), pod_setup.sh steps 1-7, then with no
    agent the stock kernels through bench.sh's full benchmark (DIAG_SCRIPT: also the model config, `pip show
    transformers torch`, the tensor shapes that reach ops.attention, the starter kernels' benchmark, and a
    CUDA_LAUNCH_BLOCKING re-run only after a crash), every log collected into <out>/pods/<pod id>/, the pod deleted at
    once. run.jsonl: pod_create, setup, diag_start (the canary's start marker), diag, collect, pod_delete (GPU $).
    Prints `DIAG stock_kernels: RUN ok tps=<...>` or `DIAG stock_kernels: CRASH <first error line>`. A real run needs
    `allow_paid` (it creates a GPU pod). Returns 0 when a stock_kernels verdict was obtained, else 1."""
    out_root, cfg = Path(out_root), cfg or PodConfig()
    cfg = replace(cfg, remote_collect=tuple(cfg.remote_collect) + tuple(x for x in DIAG_COLLECT if x not in cfg.remote_collect))
    spec = _DiagSpec(arena_root=cfg.remote_arena_root)
    rid = "diag-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    L = _Launch([spec], out_root, log, cfg, [out_root / "diag"], rid, out_root / "pods.jsonl", dry_run)
    name = f"{NAME_PREFIX}diag"
    script = Path(cfg.diag_script).read_text(encoding="utf-8") if cfg.diag_script else DIAG_SCRIPT
    if dry_run:
        ph = PodInfo(id="<pod-id>", name=name, ip="<pod-ip>", port=0, rate=cfg.rate_usd_per_h, created_at=0.0)
        L.say("DRY RUN stock-kernel diagnostic: nothing is created")
        steps = [("pod_create", redact(create_argv(name, pod_env(spec, cfg, values=False), cfg))),
                 ("container_ready", container_ready_text(cfg)),
                 ("ssh_ready", ssh_ready_text(ph, cfg)),
                 ("driver_check", driver_check_text(ph, cfg)),
                 ("setup", shlex.join(ssh_base(ph, cfg) + [f"export {setup_env_prefix(cfg)}; bash -s"]) + f" < {rel(cfg.setup_script)}"),
                 ("diag_start", "run.jsonl step diag_start (canary start marker); the bench log /workspace/p6_diag_bench.log starts growing"),
                 ("diag", shlex.join(ssh_base(ph, cfg) + [diag_ssh_cmd(cfg)]) + " < <pods.DIAG_SCRIPT, printed below>"),
                 ("collect", f"stdout -> {rel(out_root / 'diag.log')}; " + ", ".join(cfg.remote_collect)
                             + f" -> {rel(out_root / 'pods' / '<pod-id>')}/"),
                 ("pod_delete", "runpodctl pod delete <pod-id>   (at once; watchdog deletes p6-* older than 60 min)")]
        for step, text in steps:
            L.say(f"would run [{step}] {text.replace('-p 0 ', '-p <pod-port> ')}")
            L.step(step, "skipped", note=f"dry run diag: {text}")
        cfg.echo("----- DIAG_SCRIPT (streamed on stdin of the [diag] ssh) -----\n" + script + "----- end DIAG_SCRIPT -----")
        if not allow_paid:
            L.say("a real run needs --allow-paid (it creates one H100 pod: about 15-20 min, about $1.00-1.35 at $3.99/h)")
        return 0
    if not allow_paid:
        raise SystemExit("pods diag creates one H100 pod (paid GPU time): pass --allow-paid, or --dry-run to see the commands")
    rc, verdict_lines = 1, []
    try:
        L.names_for = {0: name}
        pod = L.create_pod(name, spec)
        if pod is None:
            raise LaunchError("diag: no pod could be created")
        L.setup(pod)
        L.step("diag_start", "started", pod_id=pod.id,
               note=f"stock-kernel bench on {pod.id} {pod.ip}:{pod.port}: log /workspace/p6_diag_bench.log (canary: must grow within 5 min)")
        L.say(f"diag_start on pod {pod.id} ({pod.ip}:{pod.port}); bench log /workspace/p6_diag_bench.log")
        t0 = cfg.now()
        cp = L.ssh(pod, diag_ssh_cmd(cfg), timeout=cfg.diag_timeout_s, stdin=script)
        out_root.mkdir(parents=True, exist_ok=True)
        logp = out_root / "diag.log"
        logp.write_text(rel_text(redact([cp.stdout or ""]) + "\n--- stderr ---\n" + redact([cp.stderr or ""])), encoding="utf-8")
        (out_root / "diag_script.sh").write_text(script, encoding="utf-8")
        verdict_lines = [ln.strip() for ln in (cp.stdout or "").splitlines() if ln.startswith("DIAG ")]
        stock = next((ln for ln in verdict_lines if ln.startswith("DIAG stock_kernels:")), None)
        done = "DIAG_DONE" in (cp.stdout or "")
        rc = 0 if stock else 1
        L.step("diag", "done" if stock else "failed", pod_id=pod.id, paths=[logp], cost=0.0,
               error=None if stock else f"no stock_kernels verdict (ssh rc={cp.returncode}, finished={done}): {(cp.stderr or '')[-300:]}",
               note=(stock or "no verdict") + f"; {int(cfg.now() - t0)} s; script finished {done}; no API call", verdict=verdict_lines)
        got, missing = L.collect_files(pod)
        L.step("collect", "done", paths=[logp, *got], pod_id=pod.id,
               note=f"pod files collected {len(got)}" + (f", not on the pod: {', '.join(missing)}" if missing else ""))
        L.delete_pod(pod, note="diagnostic finished")
    finally:
        L.cleanup()
        L.write_summary()
    for ln in verdict_lines:
        cfg.echo(ln)
    spent = gpu_spend(out_root / "pods.jsonl", cfg.now(), run_id=rid)
    cfg.echo(f"DIAG pod cost: {spent['seconds']} s, ${spent['usd']:.4f} GPU, $0 API; pods live from this run: {spent['live'] or 'none'}")
    (out_root / "diag_verdict.json").write_text(json.dumps(dict(run_id=rid, verdict=verdict_lines, gpu=spent, rc=rc), indent=2),
                                                encoding="utf-8")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 6 GPU pods: smoke test (PLAN §6.1) and the stock-kernel diagnostic "
                                             "(Amendment 2026-10-22 (3)). Launches are driven by sweep.py.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("smoke", help="one pod, setup, smoke_test.sh, delete")
    s.add_argument("--out", type=Path, default=Path("results") / PHASE / "smoke")
    s.add_argument("--allow-paid", action="store_true", help="include the single <= $0.05 opencode call to Qwen3")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--baked-template", default=None)
    s.add_argument("--template-id", default=os.environ.get(TEMPLATE_ENV) or None,
                   help=f"prebuilt-image template (default ${TEMPLATE_ENV}); setup still runs and skips steps 1-6")
    s.add_argument("--data-centers", default=DATA_CENTERS)
    s.add_argument("--gpu-id", default=GPU_ID)
    s.add_argument("--control-loop-commit", default="local", help="'local' pushes this host's control_loop/ tree; else a sha to clone")
    d = sub.add_parser("diag", help="one pod, setup, stock-kernel bench.sh (no agent), collect, delete")
    d.add_argument("--out", type=Path, default=Path("results") / PHASE / "diag1")
    d.add_argument("--allow-paid", action="store_true", help="required for a real run: it creates one H100 pod")
    d.add_argument("--dry-run", action="store_true")
    d.add_argument("--data-centers", default=DATA_CENTERS)
    d.add_argument("--gpu-id", default=GPU_ID)
    d.add_argument("--control-loop-commit", default="local", help="'local' pushes this host's control_loop/ tree; else a sha to clone")
    d.add_argument("--template-id", default=os.environ.get(TEMPLATE_ENV) or None,
                   help=f"prebuilt-image template (default ${TEMPLATE_ENV}); setup still runs and skips steps 1-6")
    a = ap.parse_args(argv)
    cfg = PodConfig(baked_template=getattr(a, "baked_template", None), template_id=a.template_id, data_centers=a.data_centers,
                    gpu_id=a.gpu_id, control_loop_commit=a.control_loop_commit)
    if a.cmd == "diag":
        return diag(a.out, cfg, allow_paid=a.allow_paid, dry_run=a.dry_run)
    return smoke(a.out, cfg, allow_paid=a.allow_paid, dry_run=a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
