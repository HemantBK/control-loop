#!/usr/bin/env bash
# Run within the one already-approved pod; this script provisions nothing and calls no model API.
# Outer controller MUST enforce spend, delete pod, and retrieve logs even on SSH loss.
set -uo pipefail
cd "$(dirname "$0")"
: "${GPU_RUN_APPROVED:?Set YES only after owner approval}"
[[ "$GPU_RUN_APPROVED" == YES ]] || exit 2
: "${GPU_REMAINING_SECONDS:?Controller must reserve >=1800 s at approved hourly rate within $5}"
(( GPU_REMAINING_SECONDS >= 1800 )) || { echo BUDGET_PREFLIGHT_FAIL; exit 2; }
: "${TORCH_CUDA_ARCH_LIST:?Set from target GPU before compiling}"
: "${CUDA_HOME:?}"
R="${RESULTS:-$PWD/results/phase6_researcharena/rootcause}"
mkdir -p "$R";export RESULTS="$R" PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_ENABLE_HF_TRANSFER=0 MAX_JOBS=4 PYTORCH_NO_CUDA_MEMORY_CACHING=1
export LD_LIBRARY_PATH="$CUDA_HOME/lib:$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
PY="${PYTHON:-python3}";CS="${COMPUTE_SANITIZER:-$CUDA_HOME/bin/compute-sanitizer}"
# Individual subprocess groups are bounded; failures never short-circuit subsequent arms.
run() { local n="$1" sec="$2";shift 2
 timeout --signal=TERM --kill-after=5s "${sec}s" "$@" > "$R/$n.log" 2>&1
 local rc=$?;echo "$rc" > "$R/$n.rc";printf '%s EXIT=%s\n' "$n" "$rc"
}
run versions 15 bash -c 'nvidia-smi; "$CUDA_HOME/bin/nvcc" --version; "'"$CS"'" --version; "'"$PY"'" -c "import torch,transformers; print(torch.__version__,transformers.__version__,torch.version.cuda); assert torch.cuda.is_available()"'
# Always rebuild on GPU: CPU compile objects are not certified for this architecture/ABI.
run compile 300 "$PY" compile_check.py
run canary-compile 30 "$CUDA_HOME/bin/nvcc" -lineinfo --cudart shared --cudadevrt none -L"$CUDA_HOME/lib" -L"$CUDA_HOME/lib64" sanitizer_canary.cu -o "$R/canary"
run canary-good 20 "$CS" --tool memcheck --error-exitcode 86 "$R/canary"
run canary-bad 20 "$CS" --tool memcheck --error-exitcode 86 "$R/canary" bad
run C0-model 90 "$PY" gpu_probe.py --arm C0 --results "$R"
run C1-model 150 "$CS" --tool memcheck --error-exitcode 86 "$PY" gpu_probe.py --arm C1 --results "$R"
# Mandatory exact-shape repro, even if full-model memcheck hangs or fails earlier in attention.
run C1-rope 30 "$CS" --tool memcheck --error-exitcode 86 "$PY" gpu_probe.py --arm C1 --task rope --results "$R"
for arm in C2 C3;do
 run "$arm-model" 150 "$CS" --tool memcheck --error-exitcode 86 "$PY" gpu_probe.py --arm "$arm" --results "$R"
 run "$arm-rope" 30 "$CS" --tool memcheck --error-exitcode 86 "$PY" gpu_probe.py --arm "$arm" --task rope --results "$R"
 run "$arm-attention" 45 "$CS" --tool memcheck --error-exitcode 86 "$PY" gpu_probe.py --arm "$arm" --task attention --results "$R"
 run "$arm-synccheck" 45 "$CS" --tool synccheck --error-exitcode 86 "$PY" gpu_probe.py --arm "$arm" --task attention --results "$R"
done
"$PY" gate.py "$R" | tee "$R/gates-before-C4.txt"
selected=$(cat "$R/selected.txt")
if [[ -n "$selected" ]]; then
 mkdir -p "$R/C4"
 if [[ -n "${EPISODE_RUNNER:-}" && -x "$EPISODE_RUNNER" ]];then
  # Owner-supplied, pre-reviewed offline episode replay adapter. NOT bench.py masquerading as an episode.
  # Arguments: selected patched task_context, results dir. Must emit episode_result.json and raw artifacts.
  export SELECTED_ARM="$selected"
  run C4-episode 420 env -u PYTORCH_NO_CUDA_MEMORY_CACHING "$EPISODE_RUNNER" "$PWD/arms/$selected" "$R/C4"
 else
  echo C4_BLOCKED_EPISODE_RUNNER_MISSING > "$R/C4-episode.log";echo 125 > "$R/C4-episode.rc"
 fi
else
 echo C4_SKIP_NO_CORRECT_PATCHED_ARM > "$R/C4-episode.log";echo 125 > "$R/C4-episode.rc"
fi
"$PY" gate.py "$R" | tee "$R/gates-final.txt"
echo GPU_SESSION_COMPLETE_DELETE_POD_NOW
# Deletion is mandatory in the OUTER controller's finally/watchdog, not dependent on this shell surviving.
