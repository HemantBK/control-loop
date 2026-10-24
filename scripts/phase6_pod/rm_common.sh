# sourced by the re-measure step scripts (owner, 2026-10-24)
[ -f /etc/rp_environment ] && . /etc/rp_environment; [ -f /workspace/p6_env.sh ] && . /workspace/p6_env.sh
export HF_HOME=/workspace/hf HF_HUB_OFFLINE=1 P6_RM=${P6_RM:-/workspace/remeasure} P6_RM_BUILD=${P6_RM_BUILD:-/workspace/rm_build}
K=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); TCA=/workspace/arena_root/settings/cuda_kernel/task_context; TC=$P6_RM/tc
H=/workspace/src/control-loop/control_loop/adapters/researcharena/procs.py
mkdir -p $P6_RM
