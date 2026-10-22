#!/usr/bin/env bash
# Phase 6 step 0, the pod spec smoke test (phases/phase6_researcharena/PLAN.md §6.1). Streamed over ssh by
# `python -m control_loop.adapters.researcharena.pods smoke` after pod_setup.sh. Every check prints PASS/FAIL and
# the script exits with the number of failures. The single paid call (one opencode request to Qwen3 via OpenRouter,
# <= $0.05) runs ONLY with --allow-paid; without it the check prints SKIPPED. No secret is printed.
#
#   bash -s -- [--allow-paid] [--arena-root DIR]   (stdin = this file)
#
# Amendment 2026-10-22 (2) (PLAN): the starter-kernel compile is judged by the built agent_ops.so, not bench.sh's exit
# code (pod_setup.sh compile_check; full log /workspace/p6_compile.log, collected by pods.py); the versions check
# requires python 3.11, torch 2.10.x, torch.version.cuda 12.8 (PyPI wheel, ResearchArena's container runtime), nvcc 12.9 and a CUDA_HOME with cuda_runtime.h; the
# composed root's task_context is a real copy and must hold no generated files when verify runs.
# Amendment 2026-10-22 (5): `versions` also requires transformers 4.53.3; `stock_kernels_bench` runs the unmodified
# kernels/ through bench.sh's full benchmark on the TinyLlama config with the diagnostic's own script (pods.DIAG_SCRIPT,
# read from the pushed control-loop tree; the starter-kernel run is skipped) and passes only if the benchmark completes
# with an AGENT_TPS line and the kernels were injected; on a crash the script re-runs one prompt with
# CUDA_LAUNCH_BLOCKING=1 and names the faulting kernel. transformers.__version__ and the K/V head count reaching
# ops.attention are printed. Full logs /workspace/p6_diag_*.log (collected by pods.py).
# P6_SMOKE_ONLY=<check name> (tests) runs that one check.
set -uo pipefail
ALLOW_PAID=0
ARENA_ROOT="${ARENA_ROOT:-/workspace/arena_root}"
while [ $# -gt 0 ]; do
  case "$1" in
    --allow-paid) ALLOW_PAID=1 ;;
    --arena-root) ARENA_ROOT="$2"; shift ;;
    *) echo "unknown flag $1" >&2; exit 2 ;;
  esac
  shift
done
WORKSPACE="${WORKSPACE:-/workspace}"
RA_DIR="$WORKSPACE/src/ResearchArena"
CL_DIR="$WORKSPACE/src/control-loop"
SETUP_SH="${P6_SETUP_SH:-$CL_DIR/control_loop/adapters/researcharena/pod_setup.sh}"
P6_ENV_FILE="${P6_ENV_FILE:-$WORKSPACE/p6_env.sh}"
P6_RP_ENV="${P6_RP_ENV:-/etc/rp_environment}"
export P6_COMPILE_LOG="${P6_COMPILE_LOG:-$WORKSPACE/p6_compile.log}"
# the toolchain pod_setup.sh step 1 chose (CUDA_HOME, PATH, TORCH_CUDA_ARCH_LIST), as an episode's ssh session gets it
if [ -f "$P6_ENV_FILE" ]; then . "$P6_ENV_FILE"; fi
export PYTHONPATH="$CL_DIR${PYTHONPATH:+:$PYTHONPATH}" RESEARCHARENA_ROOT="$RA_DIR" HF_HOME="${HF_HOME:-$WORKSPACE/hf}" ARENA_ROOT WORKSPACE
FAIL=0
check() {   # check <name> <command...>
  local name="$1"; shift
  if [ -n "${P6_SMOKE_ONLY:-}" ] && [ "$P6_SMOKE_ONLY" != "$name" ]; then return 0; fi
  local t0; t0=$(date +%s)
  if out=$("$@" 2>&1); then
    printf 'PASS %-28s (%ss) %s\n' "$name" "$(( $(date +%s) - t0 ))" "$(echo "$out" | tail -1)"
  else
    printf 'FAIL %-28s (%ss)\n%s\n' "$name" "$(( $(date +%s) - t0 ))" "$(echo "$out" | tail -80)"
    FAIL=$((FAIL + 1))
  fi
}

overlay_test() {
  # the HF-cache overlay works, with the real fuse-overlayfs or the copy-based shim pod_setup.sh installs when
  # /dev/fuse is absent (FUSE_NOTES.md); the mode is printed and compared with what pod_setup.sh recorded
  local mode=real recorded d
  grep -q "copy-based" "$(command -v fuse-overlayfs)" 2>/dev/null && mode=shim
  recorded=$(cat "${P6_FUSE_MODE_FILE:-$WORKSPACE/p6_fuse_mode}" 2>/dev/null || echo unrecorded)
  d=$(mktemp -d)
  mkdir -p "$d/lower" "$d/upper" "$d/work" "$d/merged" && echo x > "$d/lower/x"
  fuse-overlayfs -o "lowerdir=$d/lower,upperdir=$d/upper,workdir=$d/work" "$d/merged" || return 1
  [ "$(cat "$d/merged/x")" = x ] || { echo "lower file not visible in merged"; return 1; }
  echo y > "$d/merged/y"; echo more >> "$d/merged/x"
  [ ! -e "$d/lower/y" ] && [ "$(cat "$d/lower/x")" = x ] || { echo "a write in merged reached lower"; return 1; }
  if mountpoint -q "$d/merged" 2>/dev/null; then fusermount -u "$d/merged" 2>/dev/null || umount "$d/merged"; fi
  rm -rf "$d"
  [ ! -e "$d" ] || { echo "overlay dir not removable"; return 1; }
  [ "$mode" = "$recorded" ] || { echo "overlay mode=$mode but pod_setup.sh recorded '$recorded'"; return 1; }
  echo "overlay ok: mode=$mode (p6_fuse_mode=$recorded)"
}
torch_test() { python3 -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0)); assert torch.cuda.is_available()"; }
compile_test() { P6_RUN_ONLY=compile_check bash "$SETUP_SH"; }        # artefact rule, full log in $P6_COMPILE_LOG
versions_test() { P6_RUN_ONLY=versions_check bash "$SETUP_SH"; }       # python 3.11, torch 2.10.x / cuda 12.8 (PyPI), nvcc 12.9
toolchain_env_test() {
  # episodes reach the toolchain only through /etc/rp_environment (pods.py run_prelude sources it)
  [ -f "$P6_ENV_FILE" ] || { echo "$P6_ENV_FILE missing (pod_setup.sh step 1)"; return 1; }
  grep -qF ". $P6_ENV_FILE" "$P6_RP_ENV" 2>/dev/null || { echo "$P6_RP_ENV does not source $P6_ENV_FILE"; return 1; }
  ( set +u; . "$P6_RP_ENV" >/dev/null 2>&1; echo "via $P6_RP_ENV: CUDA_HOME=${CUDA_HOME:-unset} nvcc=$(command -v nvcc || echo none) python3=$(readlink -f "$(command -v python3)") TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST:-unset}"
    [ -n "${CUDA_HOME:-}" ] && [ -n "${TORCH_CUDA_ARCH_LIST:-}" ] && command -v nvcc >/dev/null )
}
dryrun_test() {
  ( cd "$ARENA_ROOT" && bash run_redteam.sh --setting cuda_kernel --side_task payload --redruntime 0.01 \
      --redteammodel opencode_or:openrouter/qwen/qwen3-235b-a22b-2507 --seed 733 --experiment phase6_smoke \
      --cluster_id smoke --task_config tinyllama --dry_run )
}
verify_test() {
  # verify ignores (and lists) build artefacts in the task_context copy; the smoke test also requires none to be
  # left, because an episode's pipeline_redteam.sh:146 `cp -r task_context/*` would hand them to the agent
  local out; out=$( cd "$CL_DIR" && python3 -m control_loop.adapters.researcharena.arena_root verify "$ARENA_ROOT" --checkout "$RA_DIR" ) || { echo "$out"; return 1; }
  echo "$out"
  echo "$out" | tail -1 | python3 -c 'import json,sys; m=json.loads(sys.stdin.read()); n=m.get("generated_ignored", 0); sys.exit(0 if n == 0 else print(f"{n} generated file(s) left in the composed task_context (see composed_root_manifest.json generated_ignored)") or 1)'
}
stock_bench_test() {
  local script out rc=0 v tf sd fk
  script=$( cd "$CL_DIR" && python3 -c 'import sys; from control_loop.adapters.researcharena.pods import DIAG_SCRIPT; sys.stdout.write(DIAG_SCRIPT)' ) \
    || { echo "could not read pods.DIAG_SCRIPT from $CL_DIR"; return 1; }
  out=$(printf '%s' "$script" | P6_DIAG_SKIP_STARTER=1 ARENA_ROOT="$ARENA_ROOT" WORKSPACE="$WORKSPACE" bash -s -- smoke 2>&1) || rc=$?
  echo "$out" | grep '^DIAG ' || true
  v=$(echo "$out" | grep '^DIAG stock_kernels:' | tail -1)
  tf=$(echo "$out" | sed -n 's/^DIAG transformers: //p' | tail -1)
  sd=$(echo "$out" | sed -n 's/^DIAG sdpa_shapes: //p' | tail -1)
  fk=$(echo "$out" | sed -n 's/^DIAG faulting_kernel: //p' | tail -1)
  echo "$out" | grep -q '^DIAG_DONE' || { echo "diagnostic script did not finish (rc=$rc); full log $WORKSPACE/p6_diag_bench.log"; return 1; }
  case "$v" in
    *": RUN ok tps="*" (no kernel injected"*) echo "stock kernels were not injected (INJECT_STATUS=NONE): the benchmark did not exercise them"; return 1 ;;
    *": RUN ok tps="*) ;;
    *) echo "stock kernels did not complete: ${v:-no verdict}${fk:+; faulting kernel: $fk}; full log $WORKSPACE/p6_diag_bench.log"; return 1 ;;
  esac
  case "$sd" in
    *"GQA K/V reach the kernel unexpanded"*) echo "benchmark completed but K/V reach ops.attention unexpanded ($sd): the kernels index K/V by query head (Amendment (5))"; return 1 ;;
  esac
  echo "${v#DIAG stock_kernels: }; transformers ${tf:-?}; ${sd:-sdpa probe: no output}"
}
paid_test() {
  # one request through the same provider block the opencode_or overlay uses (PLAN §1.4(2)); the key comes from the
  # pod's environment ({env:OPENROUTER_API_KEY}) and is never echoed. opencode's non-interactive form is
  # `opencode run -m <provider/model> "<prompt>"` (unverified against the pinned CLI version; see PODS_NOTES.md).
  [ -f /etc/rp_environment ] && . /etc/rp_environment
  [ -n "${OPENROUTER_API_KEY:-}" ] || { echo "OPENROUTER_API_KEY not in the pod environment"; return 1; }
  local d; d=$(mktemp -d)
  cat > "$d/opencode.json" <<'JSON'
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "openrouter": {
      "npm": "@openrouter/ai-sdk-provider",
      "options": { "apiKey": "{env:OPENROUTER_API_KEY}" },
      "models": { "qwen/qwen3-235b-a22b-2507": { "name": "qwen3-235b-a22b-2507" } }
    }
  }
}
JSON
  ( cd "$d" && timeout 120 opencode run -m openrouter/qwen/qwen3-235b-a22b-2507 "reply with the single word ok" ) | tail -3
}

check nvcc nvcc --version
check nvidia-smi nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
check versions versions_test
check toolchain_env toolchain_env_test
check torch_cuda torch_test
check hf_overlay overlay_test
check opencode_version opencode --version
check researcharena_commit git -C "$RA_DIR" rev-parse HEAD
check starter_kernels_compile compile_test
check stock_kernels_bench stock_bench_test
check run_redteam_dry_run dryrun_test
check arena_root_verify verify_test
if [ "$ALLOW_PAID" = 1 ]; then
  check opencode_qwen3_call paid_test
elif [ -z "${P6_SMOKE_ONLY:-}" ]; then
  echo "SKIPPED opencode_qwen3_call (pass --allow-paid for the single <= \$0.05 call)"
fi
echo "smoke test: $FAIL failure(s)"
exit "$FAIL"
