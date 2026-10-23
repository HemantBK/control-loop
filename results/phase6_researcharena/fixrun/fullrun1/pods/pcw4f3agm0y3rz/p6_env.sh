# written by pod_setup.sh (Phase 6, PLAN Amendment 2026-10-22 (2)); sourced through /etc/rp_environment by every ssh session
export CUDA_HOME=/usr/local/cuda
case ":$PATH:" in *":/usr/local/cuda/bin:"*) ;; *) export PATH="/usr/local/cuda/bin:$PATH" ;; esac
export TORCH_CUDA_ARCH_LIST="8.0;8.9;9.0"
