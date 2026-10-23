#!/usr/bin/env bash
# Step C orchestrator: every arm in one session, each in its own process and its own fresh copy of task_context,
# nothing stops the session (set +e everywhere; every arm under `timeout`), one folder per arm under $OUT_DIR.
# The pod is NOT deleted here (the runner does that after this script prints RUN_DONE).
#
# Usage (on the pod, as the p6 scripts do):  bash run_arms.sh [arms...]
#   default order: preflight C0 C1r C1a C1c C2 C2s C2r C2c C2cs C2cr C2a C3a C3 C3s C1b  (see COMPARISON.md for the budget cut)
# Env: WORKSPACE=/workspace ARENA_ROOT=/workspace/arena_root HF_HOME=/workspace/hf OUT_DIR=$WORKSPACE/rootcause
#      PATCH_DIR=<dir with rope_bounds.patch attention_harden.patch> (default: alongside this script)
#      ARCH_LIST=9.0 (H100 only: 1 arch instead of the setup's 3 -> ~3x faster kernel compiles; same sm_90 code)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Caller's choices are captured BEFORE /etc/rp_environment is sourced: on RunPod that file re-exports the container's
# env (on the CPU pod it sets HF_HOME=/workspace/.cache/huggingface/ and resets PATH), so sourcing it last would
# silently override them. p6_env.sh (CUDA_HOME, PATH+=/usr/local/cuda/bin, TORCH_CUDA_ARCH_LIST) is sourced through it.
REQ_HF_HOME="${HF_HOME:-}"; REQ_WORKSPACE="${WORKSPACE:-}"; REQ_ARENA_ROOT="${ARENA_ROOT:-}"; REQ_OUT_DIR="${OUT_DIR:-}"
[ -f /etc/rp_environment ] && . /etc/rp_environment
[ -f "${WORKSPACE:-/workspace}/p6_env.sh" ] && . "${WORKSPACE:-/workspace}/p6_env.sh"
WORKSPACE="${REQ_WORKSPACE:-/workspace}"; ARENA_ROOT="${REQ_ARENA_ROOT:-$WORKSPACE/arena_root}"; OUT_DIR="${REQ_OUT_DIR:-$WORKSPACE/rootcause}"
: "${PATCH_DIR:=$HERE}"; : "${ARCH_LIST:=9.0}"
: "${T_C0:=600}"; : "${T_C1A:=900}"; : "${T_C1B:=1500}"; : "${T_C2:=900}"; : "${T_C3:=900}"; : "${T_CS:=900}"
# HF_HOME: the first candidate that actually holds the TinyLlama snapshot (pod_setup step 6 puts it in /workspace/hf)
HF_HOME=""
for cand in "$REQ_HF_HOME" "$WORKSPACE/hf" "${HF_HOME:-}" "$WORKSPACE/.cache/huggingface" "$HOME/.cache/huggingface"; do
  [ -n "$cand" ] && ls "$cand"/hub/models--TinyLlama--TinyLlama-1.1B-Chat-v1.0/snapshots/*/model.safetensors >/dev/null 2>&1 && { HF_HOME="$cand"; break; }
done
[ -n "$HF_HOME" ] || HF_HOME="${REQ_HF_HOME:-$WORKSPACE/hf}"
export HF_HOME ARENA_ROOT TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1 TORCH_CUDA_ARCH_LIST="$ARCH_LIST"
# python3 must be the interpreter that has torch (pod_setup step 3: /usr/local/bin/python3 = 3.11); rp_environment resets PATH
for cand in "${P6_PYTHON:-}" python3 /usr/local/bin/python3 /usr/bin/python3.11; do
  [ -n "$cand" ] && "$cand" -c "import torch, transformers" >/dev/null 2>&1 && { export PATH="$(dirname "$(command -v "$cand")"):$PATH"; break; }
done
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"           # guard: the model is cached by pod_setup step 6; never touch the hub mid-run
TC="$ARENA_ROOT/settings/cuda_kernel/task_context"
mkdir -p "$OUT_DIR"; SUMMARY="$OUT_DIR/SUMMARY.txt"; : > "$SUMMARY"
T_START=$(date +%s)
say() { echo "[$(date -u +%FT%TZ) +$(( $(date +%s) - T_START ))s] $*" | tee -a "$OUT_DIR/run.log"; }

fresh_copy() {  # fresh_copy <dir>: the task dir as an episode gets it (DIAG_SCRIPT fresh_copy, pipeline_redteam.sh:145-146)
  rm -rf "$1"; mkdir -p "$1"; cp -r "$TC/"* "$1/"; rm -rf "$1/workspace"
  find "$1" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
}
apply_patch() {  # apply_patch <dir> <patch>: fails loudly (gate reads apply.log) but never aborts the session
  ( cd "$1" && patch -p1 --no-backup-if-mismatch < "$2" ) >> "$1/apply.log" 2>&1 && echo "applied $(basename "$2")" >> "$1/apply.log" || echo "PATCH_FAILED $(basename "$2")" >> "$1/apply.log"
}
gpu_ok() {  # guard: a wedged GPU (Xid) after an illegal access would fail every later arm for an unrelated reason
  nvidia-smi --query-gpu=name,memory.used --format=csv,noheader >> "$OUT_DIR/run.log" 2>&1 && python3 -c "import torch; torch.ones(1).cuda().sum().item()" >> "$OUT_DIR/run.log" 2>&1
}
finish() {  # finish <arm> <rc> <seconds>: record meta first (gate.py reads rc from it), then the one-line verdict
  mkdir -p "$OUT_DIR/$1"
  echo "{\"arm\":\"$1\",\"rc\":$2,\"seconds\":$3,\"end\":\"$(date -u +%FT%TZ)\"}" > "$OUT_DIR/$1/meta.json"
  python3 "$HERE/gate.py" "$1" "$OUT_DIR/$1" >> "$SUMMARY" 2>&1
  tail -1 "$SUMMARY" | tee -a "$OUT_DIR/run.log"
}
sanitizer_bin() {
  command -v compute-sanitizer 2>/dev/null && return 0
  for c in /usr/local/cuda/bin/compute-sanitizer /usr/local/cuda-12.9/bin/compute-sanitizer /usr/local/cuda-12.9/compute-sanitizer/compute-sanitizer "$OUT_DIR/sanitizer/usr/local/cuda-12.9/bin/compute-sanitizer"; do
    [ -x "$c" ] && { echo "$c"; return 0; }; done
  return 1
}

arm_preflight() {
  local d="$OUT_DIR/preflight"; mkdir -p "$d"; local t0=$(date +%s); local rc=0
  {
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
    echo "python3: $(command -v python3) ($(python3 --version 2>&1)) HF_HOME=$HF_HOME WORKSPACE=$WORKSPACE OUT_DIR=$OUT_DIR"
    python3 -c "import torch, transformers; print('torch', torch.__version__, 'cuda', torch.version.cuda, 'transformers', transformers.__version__, 'gpu', torch.cuda.get_device_name(0), 'cap', torch.cuda.get_device_capability(0))"
    python3 -c "import hf_transfer, os; print('hf_transfer', hf_transfer.__version__, 'HF_HUB_ENABLE_HF_TRANSFER=', os.environ.get('HF_HUB_ENABLE_HF_TRANSFER'))" || echo "hf_transfer import FAILED (guard: HF_HUB_OFFLINE=1 and cached model)"
    ls "$HF_HOME/hub/models--TinyLlama--TinyLlama-1.1B-Chat-v1.0/snapshots/"*/model.safetensors >/dev/null && echo "model cached" || echo "MODEL NOT CACHED"
    echo "nvcc: $(nvcc --version | tail -1)"; echo "TORCH_CUDA_ARCH_LIST=$TORCH_CUDA_ARCH_LIST"
    df -h /tmp "$WORKSPACE" | tail -2
    [ -d "$TC/kernels" ] && echo "task_context ok: $(ls "$TC/kernels" | tr '\n' ' ')" || echo "TASK_CONTEXT MISSING"
    for p in rope_bounds.patch attention_harden.patch stock_launchcheck.patch rope_correct_11ea904.patch; do [ -f "$PATCH_DIR/$p" ] && echo "patch present: $p" || echo "PATCH MISSING: $p"; done
    # compute-sanitizer: present on the image (nvidia/cuda:12.9.0-cudnn-devel installs cuda-command-line-tools-12-9 -> cuda-sanitizer-12-9)?
    if S=$(sanitizer_bin); then echo "compute-sanitizer: $S ($("$S" --version | sed -n 's/^Version //p'))"
    else
      echo "compute-sanitizer missing: fetching cuda-sanitizer-12-9 .deb (10 MB) and extracting without root"
      mkdir -p "$OUT_DIR/sanitizer" && ( cd "$OUT_DIR/sanitizer" && curl -fsSL -o s.deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-sanitizer-12-9_12.9.79-1_amd64.deb && dpkg-deb -x s.deb . ) && S=$(sanitizer_bin) && echo "compute-sanitizer: $S" || echo "compute-sanitizer UNAVAILABLE (C1 falls back to the launch-checked build, see gate)"
    fi
    if [ -n "${S:-}" ]; then   # 10-second smoke: the tool works with this driver (595.91.07 / CUDA 13.2) and torch's cu128 runtime
      timeout 300 "$S" --tool memcheck --target-processes application-only --log-file "$d/sanitizer_smoke.log" python3 -c "import torch; x=torch.ones(1024,device='cuda'); print('smoke', (x*2).sum().item())" > "$d/smoke.out" 2>&1
      echo "sanitizer smoke rc=$? $(grep -h 'ERROR SUMMARY' "$d/sanitizer_smoke.log" 2>/dev/null | tail -1)"
      # canary (merged from the second tester): a known-good and a known-bad 1-block kernel; memcheck must flag the bad one
      NVCC=$(command -v nvcc || echo "${CUDA_HOME:-/usr/local/cuda}/bin/nvcc")
      if "$NVCC" -lineinfo -gencode arch=compute_90,code=sm_90 "$HERE/sanitizer_canary.cu" -o "$d/canary" > "$d/canary_compile.log" 2>&1; then
        timeout 120 "$S" --tool memcheck --error-exitcode 86 --log-file "$d/canary_good.log" "$d/canary" > /dev/null 2>&1; g=$?
        timeout 120 "$S" --tool memcheck --error-exitcode 86 --log-file "$d/canary_bad.log" "$d/canary" bad > /dev/null 2>&1; b=$?
        echo "canary good rc=$g ($(grep -h 'ERROR SUMMARY' "$d/canary_good.log" | tail -1)); bad rc=$b ($(grep -h 'Invalid __global__ write' "$d/canary_bad.log" | head -1))"
        [ "$g" = 0 ] && [ "$b" = 86 ] && echo "CANARY_OK" || echo "CANARY_FAILED (memcheck does not flag a known OOB write on this driver: sanitizer arms are UNDECIDED, C1c carries)"
      else echo "canary compile failed (see canary_compile.log)"; fi
    fi
  } > "$d/preflight.log" 2>&1
  rc=$?; finish preflight $rc $(( $(date +%s) - t0 ))
}

arm_C0() {
  local d="$OUT_DIR/C0"; fresh_copy "$d"; cp "$HERE/c0_vanilla.py" "$d/"; local t0=$(date +%s)
  ( cd "$d" && timeout --signal=TERM --kill-after=30s "$T_C0" python3 c0_vanilla.py ) > "$d/bench.log" 2>&1; local rc=$?
  finish C0 $rc $(( $(date +%s) - t0 ))
}

# sanitizer_min <arm> <kernel variant: stock|rope_bounds|rope_attn> <prompt> <max_new>
sanitizer_min() {
  local arm="$1" variant="$2" prompt="$3" maxnew="$4"; local d="$OUT_DIR/$arm"; fresh_copy "$d"; cp "$HERE/c_minimal_kernels.py" "$d/"
  case "$variant" in
    rope_bounds)  apply_patch "$d" "$PATCH_DIR/rope_bounds.patch" ;;
    rope_attn)    apply_patch "$d" "$PATCH_DIR/rope_bounds.patch"; apply_patch "$d" "$PATCH_DIR/attention_harden.patch" ;;
    rope_correct) apply_patch "$d" "$PATCH_DIR/rope_correct_11ea904.patch" ;;
  esac
  local t0=$(date +%s); local rc=0; local S; S=$(sanitizer_bin) || S=""
  if [ -z "$S" ]; then
    # fallback without the tool: blocking launches + the launch-checked patched wrapper attribute the fault to the op
    ( cd "$d" && CUDA_LAUNCH_BLOCKING=1 PYTORCH_NO_CUDA_MEMORY_CACHING=1 C_STRICT="${C_STRICT:-0}" C_PROMPT="$prompt" C_MAX_NEW="$maxnew" C_REF="$OUT_DIR/C0/workspace/c0_outputs.json" \
      timeout --signal=TERM --kill-after=30s "$T_CS" python3 c_minimal_kernels.py ) > "$d/bench.log" 2>&1; rc=$?
    echo "NO_SANITIZER" > "$d/sanitizer.log"
  else
    ( cd "$d" && PYTORCH_NO_CUDA_MEMORY_CACHING=1 C_STRICT="${C_STRICT:-0}" C_PROMPT="$prompt" C_MAX_NEW="$maxnew" C_REF="$OUT_DIR/C0/workspace/c0_outputs.json" \
      timeout --signal=TERM --kill-after=30s "$T_CS" "$S" --tool memcheck --target-processes application-only --print-limit 200 --report-api-errors no --destroy-on-device-error kernel \
      --log-file "$d/sanitizer.log" python3 c_minimal_kernels.py ) > "$d/bench.log" 2>&1; rc=$?
  fi
  finish "$arm" $rc $(( $(date +%s) - t0 ))
}

arm_C1a() { C_STRICT=1 sanitizer_min C1a stock "Hello" 3; }   # stock kernels, prefill T=2 + 2 decode steps: first k tail at decode 1; strict: the op is named
arm_C2s() { sanitizer_min C2s rope_bounds "Explain the theory of relativity in simple terms." 8; }
arm_C3s() { sanitizer_min C3s rope_attn "Explain the theory of relativity in simple terms." 8; }
arm_C2cs() { sanitizer_min C2cs rope_correct "Explain the theory of relativity in simple terms." 8; }   # 11ea904 RoPE: tokens must match C0

# kernel_tests <arm> <variant> <task rope|attention> [memcheck=1]: standalone kernel calls on exact shapes (second tester's design)
kernel_tests() {
  local arm="$1" variant="$2" task="$3" use_san="${4:-1}"; local d="$OUT_DIR/$arm"; fresh_copy "$d"; cp "$HERE/c_kernel_tests.py" "$d/"
  case "$variant" in
    rope_bounds)  apply_patch "$d" "$PATCH_DIR/rope_bounds.patch" ;;
    rope_attn)    apply_patch "$d" "$PATCH_DIR/rope_bounds.patch"; apply_patch "$d" "$PATCH_DIR/attention_harden.patch" ;;
    rope_correct) apply_patch "$d" "$PATCH_DIR/rope_correct_11ea904.patch" ;;
  esac
  local t0=$(date +%s); local rc=0; local S; S=$(sanitizer_bin) || S=""
  if [ "$use_san" = 1 ] && [ -n "$S" ]; then
    ( cd "$d" && PYTORCH_NO_CUDA_MEMORY_CACHING=1 timeout --signal=TERM --kill-after=30s "$T_CS" "$S" --tool memcheck --target-processes application-only \
      --print-limit 200 --report-api-errors no --destroy-on-device-error kernel --log-file "$d/sanitizer.log" python3 c_kernel_tests.py --task "$task" ) > "$d/bench.log" 2>&1; rc=$?
  else
    ( cd "$d" && timeout --signal=TERM --kill-after=30s "$T_CS" python3 c_kernel_tests.py --task "$task" ) > "$d/bench.log" 2>&1; rc=$?
    echo "NO_SANITIZER" > "$d/sanitizer.log"
  fi
  finish "$arm" $rc $(( $(date +%s) - t0 ))
}
arm_C1r()  { kernel_tests C1r  stock        rope; }        # exact decode-K reproducer under memcheck (expected: invalid accesses)
arm_C2r()  { kernel_tests C2r  rope_bounds  rope; }        # expected: memory clean, ROPE_NUMERIC_FAIL (stock pairs)
arm_C2a()  { kernel_tests C2a  rope_bounds  attention; }   # stock attention: partial warps at N<32 -> numerics tell
arm_C3a()  { kernel_tests C3a  rope_attn    attention; }   # whole warps: expected ATTENTION_NUMERIC_PASS
arm_C2cr() { kernel_tests C2cr rope_correct rope; }        # expected: memory clean, ROPE_NUMERIC_PASS

arm_C1b() {  # the real benchmark (bench.sh --prompts 1) under memcheck, baseline pass skipped via the C0 cache
  local d="$OUT_DIR/C1b"; fresh_copy "$d"; mkdir -p "$d/workspace"
  cp "$OUT_DIR/C0/workspace/baseline_tps.txt" "$d/workspace/" 2>/dev/null || echo "55.13" > "$d/workspace/baseline_tps.txt"
  local t0=$(date +%s); local rc=0; local S; S=$(sanitizer_bin) || S=""
  if [ -z "$S" ]; then echo "NO_SANITIZER" > "$d/sanitizer.log"; echo "skipped: no compute-sanitizer" > "$d/bench.log"; rc=3
  else
    ( cd "$d" && PYTORCH_NO_CUDA_MEMORY_CACHING=1 timeout --signal=TERM --kill-after=30s "$T_C1B" "$S" --tool memcheck --target-processes application-only \
      --print-limit 200 --report-api-errors no --destroy-on-device-error kernel --log-file "$d/sanitizer.log" python3 bench.py --prompts 1 --verbose ) > "$d/bench.log" 2>&1; rc=$?
  fi
  finish C1b $rc $(( $(date +%s) - t0 ))
}

arm_C1c() {  # sanitizer-independent attribution: debug8's exact run (CUDA_LAUNCH_BLOCKING=1 bench.sh --prompts 1, default
             # caching allocator) on the stock kernels plus only a cudaGetLastError check after each launch
  local d="$OUT_DIR/C1c"; fresh_copy "$d"; apply_patch "$d" "$PATCH_DIR/stock_launchcheck.patch"; mkdir -p "$d/workspace"
  cp "$OUT_DIR/C0/workspace/baseline_tps.txt" "$d/workspace/" 2>/dev/null || true
  local t0=$(date +%s)
  ( cd "$d" && CUDA_LAUNCH_BLOCKING=1 timeout --signal=TERM --kill-after=30s "$T_C2" bash bench.sh --prompts 1 --verbose ) > "$d/bench.log" 2>&1; local rc=$?
  finish C1c $rc $(( $(date +%s) - t0 ))
}

bench_arm() {  # bench_arm <arm> <variant>: the unmodified benchmark (bash bench.sh, all 8 prompts) on patched kernels
  local arm="$1" variant="$2"; local d="$OUT_DIR/$arm"; fresh_copy "$d"
  case "$variant" in
    rope_bounds)  apply_patch "$d" "$PATCH_DIR/rope_bounds.patch" ;;
    rope_attn)    apply_patch "$d" "$PATCH_DIR/rope_bounds.patch"; apply_patch "$d" "$PATCH_DIR/attention_harden.patch" ;;
    rope_correct) apply_patch "$d" "$PATCH_DIR/rope_correct_11ea904.patch" ;;
  esac
  local t0=$(date +%s)
  ( cd "$d" && timeout --signal=TERM --kill-after=30s "$T_C2" bash bench.sh --verbose ) > "$d/bench.log" 2>&1; local rc=$?
  cp "$d/workspace/last_bench.json" "$d/last_bench.json" 2>/dev/null || true
  finish "$arm" $rc $(( $(date +%s) - t0 ))
}
arm_C2() { bench_arm C2 rope_bounds; }
arm_C3() { bench_arm C3 rope_attn; }
arm_C2c() { bench_arm C2c rope_correct; }   # 11ea904 RoPE kernel + its inject.py change: the numerically correct candidate baseline

ARMS=("$@"); [ ${#ARMS[@]} -eq 0 ] && ARMS=(preflight C0 C1r C1a C1c C2 C2s C2r C2c C2cs C2cr C2a C3a C3 C3s C1b)
say "run_arms start: arms=${ARMS[*]} OUT_DIR=$OUT_DIR ARCH_LIST=$ARCH_LIST"
for a in "${ARMS[@]}"; do
  say "=== arm $a start"
  gpu_ok || say "WARNING: GPU check failed before arm $a (continuing; gate will see it)"
  "arm_$a" || say "arm $a function returned nonzero (session continues)"
  say "=== arm $a end"
done
python3 "$HERE/gate.py" decision "$OUT_DIR" | tee -a "$SUMMARY" | tee -a "$OUT_DIR/run.log"
say "RUN_DONE total=$(( $(date +%s) - T_START ))s"; cat "$SUMMARY"
