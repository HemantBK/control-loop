#!/usr/bin/env bash
# Step C orchestrator: every arm in one session, each in its own process and its own fresh copy of task_context,
# nothing stops the session (set +e everywhere; every arm under `timeout`), one folder per arm under $OUT_DIR.
# The pod is NOT deleted here (the runner does that after this script prints RUN_DONE).
#
# Usage (on the pod):  bash run_arms.sh <ARM>        one arm, appends its GATE line to $OUT_DIR/SUMMARY.txt (R7: driven one
#                                                   ssh call at a time by gpu_run/drive_session.sh from the CPU machine)
#                      bash run_arms.sh decision     the DECISION block from SUMMARY.txt
#                      bash run_arms.sh              all arms in the default order, then the decision (no deadline: not for the pod)
#   default order (Amendment (15) session): preflight C0 C1s C2 C2s C2c C2cs C2cm C2cr C2ce
#                      bash run_arms.sh limits <ARM>  prints the arm's inner timeout and outer limit (self-test)
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
: "${T_C0:=600}"; : "${T_C1B:=1500}"; : "${T_C2:=900}"; : "${T_CS:=300}"   # R7: T_CS 900 -> 300 (sanitizer/kernel-test arms)
: "${T_C2S:=900}"; : "${T_PRE:=600}"   # Amendment (15): preflight also loads the model offline   # Amendment (13), manager: C2s (a rule-A arm) keeps 900 s; preflight's overall limit
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
mirror_hf_cache() {  # Amendment (15): pod_setup caches models with snapshot_download under $HF_HOME/hub/, while bench.py
                     # loads with cache_dir=$HF_HOME (config.py hf_cache_dir) and so looks in $HF_HOME/models--*. Mirror each
                     # cached model there (symlink, idempotent) so the offline lookup finds it; the void run of 2026-10-23
                     # failed on exactly this mismatch.
  local m; for m in "$HF_HOME"/hub/models--*; do [ -d "$m" ] || continue; [ -e "$HF_HOME/$(basename "$m")" ] || ln -s "$m" "$HF_HOME/$(basename "$m")"; done
}
mirror_hf_cache
TC="$ARENA_ROOT/settings/cuda_kernel/task_context"
mkdir -p "$OUT_DIR"; SUMMARY="$OUT_DIR/SUMMARY.txt"; touch "$SUMMARY"   # appended, never truncated (one arm per call)
T_START=$(date +%s)
say() { echo "[$(date -u +%FT%TZ) +$(( $(date +%s) - T_START ))s] $*" | tee -a "$OUT_DIR/run.log"; }

fresh_copy() {  # fresh_copy <dir>: the task dir as an episode gets it (DIAG_SCRIPT fresh_copy, pipeline_redteam.sh:145-146)
  rm -rf "$1"; mkdir -p "$1"; cp -r "$TC/"* "$1/"; rm -rf "$1/workspace"
  find "$1" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
}
apply_variant() {  # apply_variant <dir> <stock|rope_guard|rope_bounds|rope_attn|rope_correct>
  case "$2" in
    rope_guard)   apply_patch "$1" "$PATCH_DIR/rope_guard_only.patch"; apply_patch "$1" "$PATCH_DIR/starter_rope_guard_only.patch" ;;  # Amendment 12: ONLY the guard
    rope_bounds)  apply_patch "$1" "$PATCH_DIR/rope_bounds.patch" ;;
    rope_attn)    apply_patch "$1" "$PATCH_DIR/rope_bounds.patch"; apply_patch "$1" "$PATCH_DIR/attention_harden.patch" ;;
    rope_correct) apply_patch "$1" "$PATCH_DIR/opt2_task_context.patch" ;;   # Amendment (15): option 2's minimal set (RoPE kernel, starter RoPE, inject.py RoPE hunks)
    stock)        echo "stock: no patch" >> "$1/apply.log" ;;
  esac
}
apply_patch() {  # apply_patch <dir> <patch>: fails loudly (gate reads apply.log) but never aborts the session
  ( cd "$1" && patch -p1 --no-backup-if-mismatch < "$2" ) >> "$1/apply.log" 2>&1 && echo "applied $(basename "$2")" >> "$1/apply.log" || echo "PATCH_FAILED $(basename "$2")" >> "$1/apply.log"
}
gpu_ok() {  # guard: a wedged GPU (Xid) after an illegal access would fail every later arm for an unrelated reason
  # Amendment (13), manager: each probe has its own timeout, so a hung driver cannot stall the session here
  timeout --kill-after=10s 60 nvidia-smi --query-gpu=name,memory.used --format=csv,noheader >> "$OUT_DIR/run.log" 2>&1 \
    && timeout --kill-after=10s 120 python3 -c "import torch; torch.ones(1).cuda().sum().item()" >> "$OUT_DIR/run.log" 2>&1
}
arm_limit() {  # the overall limit of one arm on the pod (Amendment (13); same table as drive_session.sh's arm_timeout)
  case "$1" in
    preflight) echo "$T_PRE" ;; C0) echo "$T_C0" ;; C1b) echo "$T_C1B" ;; C2s|C2cm) echo "$T_C2S" ;;
    C1s|C1c|C2|C2c|C3|C2ce) echo "$T_C2" ;;
    C2cs) echo $(( 2 * T_CS )) ;;
    C1a|C1r|C2r|C2a|C2cr|C3a|C3s) echo "$T_CS" ;;
    *) echo "$T_C2" ;;
  esac
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
    # Amendment (15): load the model offline exactly as bench.py does (its own load_model_and_tokenizer, ArenaConfig, from a
    # fresh copy of task_context, HF_HUB_OFFLINE=1); the arms' model loads depend on this, so gate.py requires MODEL_LOAD_OK
    ls -d "$HF_HOME"/models--* 2>/dev/null | sed 's/^/hf cache mirror: /'
    LD=$(mktemp -d); cp -r "$TC/"* "$LD/"; rm -rf "$LD/workspace"
    ( cd "$LD" && HF_HUB_OFFLINE=1 timeout --kill-after=10s 240 python3 -c "import sys; sys.path.insert(0, '.'); from config import ArenaConfig; from bench import load_model_and_tokenizer; m, t = load_model_and_tokenizer(ArenaConfig()); print('MODEL_LOAD_OK', type(m).__name__, t.vocab_size)" ) 2>&1 | tail -4
    rm -rf "$LD"
    [ -d "$TC/kernels" ] && echo "task_context ok: $(ls "$TC/kernels" | tr '\n' ' ')" || echo "TASK_CONTEXT MISSING"
    for p in rope_guard_only.patch starter_rope_guard_only.patch rope_bounds.patch attention_harden.patch stock_launchcheck.patch opt2_task_context.patch c_embedded_check.py embedded_evaluate.py opt2_embedded3_evaluate.py c_minimal_kernels.py c0_vanilla.py c_kernel_tests.py; do [ -f "$PATCH_DIR/$p" ] && echo "patch present: $p" || echo "PATCH MISSING: $p"; done
    # compute-sanitizer: present on the image (nvidia/cuda:12.9.0-cudnn-devel installs cuda-command-line-tools-12-9 -> cuda-sanitizer-12-9)?
    if S=$(sanitizer_bin); then echo "compute-sanitizer: $S ($("$S" --version | sed -n 's/^Version //p'))"
    else
      echo "compute-sanitizer missing: fetching cuda-sanitizer-12-9 .deb (10 MB) and extracting without root"
      mkdir -p "$OUT_DIR/sanitizer" && ( cd "$OUT_DIR/sanitizer" && curl -fsSL --max-time 90 -o s.deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-sanitizer-12-9_12.9.79-1_amd64.deb && dpkg-deb -x s.deb . ) && S=$(sanitizer_bin) && echo "compute-sanitizer: $S" || echo "compute-sanitizer UNAVAILABLE (C1 falls back to the launch-checked build, see gate)"
    fi
    if [ -n "${S:-}" ]; then   # 10-second smoke: the tool works with this driver (595.91.07 / CUDA 13.2) and torch's cu128 runtime
      timeout 120 "$S" --tool memcheck --target-processes application-only --log-file "$d/sanitizer_smoke.log" python3 -c "import torch; x=torch.ones(1024,device='cuda'); print('smoke', (x*2).sum().item())" > "$d/smoke.out" 2>&1
      echo "sanitizer smoke rc=$? $(grep -h 'ERROR SUMMARY' "$d/sanitizer_smoke.log" 2>/dev/null | tail -1)"
      # canary (merged from the second tester): a known-good and a known-bad 1-block kernel; memcheck must flag the bad one
      NVCC=$(command -v nvcc || echo "${CUDA_HOME:-/usr/local/cuda}/bin/nvcc")
      if timeout 120 "$NVCC" -lineinfo -gencode arch=compute_90,code=sm_90 "$HERE/sanitizer_canary.cu" -o "$d/canary" > "$d/canary_compile.log" 2>&1; then
        timeout 120 "$S" --tool memcheck --error-exitcode 86 --log-file "$d/canary_good.log" "$d/canary" > /dev/null 2>&1; g=$?
        timeout 120 "$S" --tool memcheck --error-exitcode 86 --log-file "$d/canary_bad.log" "$d/canary" bad > /dev/null 2>&1; b=$?
        echo "canary good rc=$g ($(grep -h 'ERROR SUMMARY' "$d/canary_good.log" | tail -1)); bad rc=$b ($(grep -h 'Invalid __global__ write' "$d/canary_bad.log" | head -1))"
        python3 "$HERE/gate.py" parse "$d/canary_bad.log" | grep -q '"what": "Invalid __global__ write' && echo "PARSER_OK (gate.py parse_sanitizer on the real canary_bad.log)" || echo "PARSER_FAILED on canary_bad.log"
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
  apply_variant "$d" "$variant"
  local T_CS="${SAN_TIMEOUT:-$T_CS}"   # Amendment (13), manager: C2s passes SAN_TIMEOUT=$T_C2S (900 s); the information arms keep T_CS
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
arm_C2s() { SAN_TIMEOUT="$T_C2S" sanitizer_min C2s rope_guard "Explain the theory of relativity in simple terms." 8; }   # rule-A companion: guard-only kernels under memcheck (900 s, Amendment (13))
arm_C3s() { sanitizer_min C3s rope_attn "Explain the theory of relativity in simple terms." 8; }
arm_C2cm() { SAN_TIMEOUT="$T_C2S" sanitizer_min C2cm rope_correct "Explain the theory of relativity in simple terms." 8; }   # Amendment (15): option 2 under memcheck on the full model path
arm_C2ce() {  # Amendment (15): the side-task evaluators (embedded KL with call/fallback counts; embedded3 probe) on option 2
  local d="$OUT_DIR/C2ce"; fresh_copy "$d"; apply_variant "$d" rope_correct
  cp "$HERE/c_embedded_check.py" "$HERE/embedded_evaluate.py" "$HERE/opt2_embedded3_evaluate.py" "$d/"
  local t0=$(date +%s)
  ( cd "$d" && timeout --signal=TERM --kill-after=30s "$T_C2" python3 c_embedded_check.py ) > "$d/bench.log" 2>&1; local rc=$?
  finish C2ce $rc $(( $(date +%s) - t0 ))
}
arm_C2cs() {  # R4: 11ea904 RoPE numerics vs C0 on the 8 eval prompts x 32 tokens, NO memcheck, twice: RoPE-only injected
              # (bench_rope.log) and all four ops injected (bench.log); the gate wants MIN_TEXT_MATCH_C0=yes in both
  local d="$OUT_DIR/C2cs"; fresh_copy "$d"; cp "$HERE/c_minimal_kernels.py" "$d/"; apply_variant "$d" rope_correct
  local t0=$(date +%s); local rc=0 rc2=0
  ( cd "$d" && C_OPS=rope C_PROMPT=all C_MAX_NEW=32 C_REF="$OUT_DIR/C0/workspace/c0_outputs.json" timeout --signal=TERM --kill-after=30s "$T_CS" python3 c_minimal_kernels.py ) > "$d/bench_rope.log" 2>&1; rc=$?
  ( cd "$d" && C_OPS=all  C_PROMPT=all C_MAX_NEW=32 C_REF="$OUT_DIR/C0/workspace/c0_outputs.json" timeout --signal=TERM --kill-after=30s "$T_CS" python3 c_minimal_kernels.py ) > "$d/bench.log" 2>&1; rc2=$?
  echo "NO_SANITIZER" > "$d/sanitizer.log"
  finish C2cs $(( rc != 0 ? rc : rc2 )) $(( $(date +%s) - t0 ))
}

# kernel_tests <arm> <variant> <task rope|attention> [memcheck=1]: standalone kernel calls on exact shapes (second tester's design)
kernel_tests() {
  local arm="$1" variant="$2" task="$3" use_san="${4:-1}"; local d="$OUT_DIR/$arm"; fresh_copy "$d"; cp "$HERE/c_kernel_tests.py" "$d/"
  apply_variant "$d" "$variant"
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
arm_C2r()  { kernel_tests C2r  rope_guard   rope; }        # guard-only kernel: expected memory clean, ROPE_NUMERIC_FAIL (stock interleaved pairs)
arm_C2a()  { kernel_tests C2a  rope_guard   attention; }   # stock attention: partial warps at N<32 -> numerics tell
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
  local d="$OUT_DIR/C1c"; fresh_copy "$d"; apply_patch "$d" "$PATCH_DIR/stock_launchcheck.patch"   # R2: no cached baseline -> bench.sh loads the vanilla model first, as debug8 did
  local t0=$(date +%s)
  ( cd "$d" && CUDA_LAUNCH_BLOCKING=1 timeout --signal=TERM --kill-after=30s "$T_C2" bash bench.sh --prompts 1 --verbose ) > "$d/bench.log" 2>&1; local rc=$?
  finish C1c $rc $(( $(date +%s) - t0 ))
}

bench_arm() {  # bench_arm <arm> <variant>: the unmodified benchmark (bash bench.sh, all 8 prompts) on patched kernels
  local arm="$1" variant="$2"; local d="$OUT_DIR/$arm"; fresh_copy "$d"
  apply_variant "$d" "$variant"
  local t0=$(date +%s)
  ( cd "$d" && timeout --signal=TERM --kill-after=30s "$T_C2" bash bench.sh --verbose ) > "$d/bench.log" 2>&1; local rc=$?
  cp "$d/workspace/last_bench.json" "$d/last_bench.json" 2>/dev/null || true
  finish "$arm" $rc $(( $(date +%s) - t0 ))
}
arm_C1s() { bench_arm C1s stock; }        # R2: stock kernels, `bash bench.sh --verbose`, identical conditions to C2; rule A needs it to END IN A CUDA ERROR
arm_C2() { bench_arm C2 rope_guard; }     # rule A: ONLY the `idx < total_pairs` guard (kernels/ and starter_kernels/)
arm_C3() { bench_arm C3 rope_attn; }
arm_C2c() { bench_arm C2c rope_correct; }   # 11ea904 RoPE kernel + its inject.py change: the numerically correct candidate baseline

# Inner mode (Amendment (13), manager): `run_arms.sh __inner <ARM>` runs the arm function itself. The outer call below starts
# it in its own session (setsid) and kills the whole session when the arm's overall limit passes, so an overrunning arm
# (including nested `timeout`s, which each take their own process group) cannot keep running into the next arm.
if [ "${1:-}" = __inner ]; then
  a="$2"; gpu_ok || say "WARNING: GPU check failed before arm $a (continuing; gate will see it)"
  "arm_$a" || say "arm $a function returned nonzero (session continues)"
  exit 0
fi
kill_session() {  # kill_session <sid>: TERM then KILL every process left in that session
  pkill -TERM -s "$1" 2>/dev/null; sleep 5; pkill -KILL -s "$1" 2>/dev/null; true
}
: "${OUTER_MARGIN:=60}"   # Amendment (13), manager: the outer limit is the arm's inner timeout + 60 s, so the inner `timeout`
                         # (started after the arm's own startup, gpu_ok, fresh copy and patching) always governs first
outer_limit() { echo $(( $(arm_limit "$1") + OUTER_MARGIN )); }
if [ "${1:-}" = limits ]; then echo "ARM_LIMITS $2 inner=$(arm_limit "$2") outer=$(outer_limit "$2")"; exit 0; fi
run_one() {  # run_one <arm>: the arm in its own session, under its overall limit; leftovers of an earlier arm are killed first
  local a="$1" lim; lim=$(outer_limit "$a")
  if [ -f "$OUT_DIR/.arm_sid" ]; then
    local old; old=$(cat "$OUT_DIR/.arm_sid")
    if pgrep -s "$old" >/dev/null 2>&1; then say "killing leftovers of session $old before arm $a"; kill_session "$old"; fi
  fi
  local t0; t0=$(date +%s)
  setsid bash "$HERE/run_arms.sh" __inner "$a" < /dev/null & local pid=$!
  echo "$pid" > "$OUT_DIR/.arm_sid"   # setsid execs bash in a new session whose id is this pid
  while kill -0 "$pid" 2>/dev/null; do
    if [ $(( $(date +%s) - t0 )) -ge "$lim" ]; then
      say "arm $a exceeded its overall limit ${lim}s: killing session $pid"
      kill_session "$pid"; wait "$pid" 2>/dev/null
      grep -q "^GATE $a " <(tail -1 "$SUMMARY") || finish "$a" 124 $(( $(date +%s) - t0 ))   # gate the partial logs as a timeout
      return
    fi
    sleep 2
  done
  wait "$pid" 2>/dev/null
}
ARMS=("$@"); WANT_DECISION=0
# Amendment (13): C1b dropped (it could never start before its deadline in this order)
[ ${#ARMS[@]} -eq 0 ] && { ARMS=(preflight C0 C1s C2 C2s C2c C2cs C2cm C2cr C2ce); WANT_DECISION=1; }   # Amendment (15) session order
say "run_arms start: arms=${ARMS[*]} OUT_DIR=$OUT_DIR ARCH_LIST=$ARCH_LIST T_C0=$T_C0 T_C2=$T_C2 T_CS=$T_CS T_C2S=$T_C2S T_PRE=$T_PRE"
for a in "${ARMS[@]}"; do
  [ "$a" = decision ] && { WANT_DECISION=1; continue; }
  declare -F "arm_$a" >/dev/null || { say "unknown arm $a"; echo "GATE $a NOT_RUN: unknown arm" >> "$SUMMARY"; continue; }
  say "=== arm $a start (inner timeout $(arm_limit "$a")s, outer limit $(outer_limit "$a")s)"
  run_one "$a"
  say "=== arm $a end"
done
[ "$WANT_DECISION" = 1 ] && python3 "$HERE/gate.py" decision "$OUT_DIR" | tee -a "$SUMMARY" | tee -a "$OUT_DIR/run.log"
say "RUN_DONE total=$(( $(date +%s) - T_START ))s"
