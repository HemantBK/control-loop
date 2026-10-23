#!/bin/bash
# Amendment (15) cache-path test on the CPU pod: cache TinyLlama as pod_setup step 6 does (snapshot_download, default
# revision, HF_HOME/hub), then load it offline with bench.py's own load_model_and_tokenizer (device switched to cpu):
# (1) without the mirror: expected to fail as in the void run; (2) after run_arms.sh's mirror_hf_cache: expected to load.
set -u
H=$(mktemp -d /root/scratch/rootcause/cachetest.XXXX); TC=$(mktemp -d); K=/root/control-loop/results/phase6_researcharena/rootcause/gpu_kit/gpu_run
git -C /root/src/ResearchArena archive 58776e09339c1714d0524130590abaf6eac7879d settings/cuda_kernel/task_context | tar -x -C $TC
T=$TC/settings/cuda_kernel/task_context
UV="uv run --no-project --python 3.11 --with torch==2.10.0 --with transformers==4.53.3 --with accelerate --with hf_transfer==0.1.9"
HF_HOME=$H HF_HUB_ENABLE_HF_TRANSFER=0 $UV python -c "from huggingface_hub import snapshot_download; print('cached at', snapshot_download('TinyLlama/TinyLlama-1.1B-Chat-v1.0'))" 2>&1 | tail -1
ls $H; ls $H/hub
LOAD="import sys; sys.path.insert(0, '.'); from config import ArenaConfig; from bench import load_model_and_tokenizer; c = ArenaConfig(); c.device = 'cpu'; m, t = load_model_and_tokenizer(c); print('MODEL_LOAD_OK', type(m).__name__, t.vocab_size)"
echo "### (1) without the mirror"; ( cd $T && HF_HOME=$H HF_HUB_OFFLINE=1 $UV python -c "$LOAD" 2>&1 | grep -E "MODEL_LOAD_OK|couldn't connect|LocalEntryNotFound|OSError" | head -2 )
echo "### (2) with run_arms.sh's mirror_hf_cache"
HF_HOME=$H bash -c "$(sed -n '/^mirror_hf_cache() {/,/^}/p' $K/run_arms.sh); mirror_hf_cache"; ls -la $H | grep models--
( cd $T && HF_HOME=$H HF_HUB_OFFLINE=1 $UV python -c "$LOAD" 2>&1 | grep -E "MODEL_LOAD_OK|couldn't connect|LocalEntryNotFound|OSError|\[bench\]" | head -5 )
rm -rf $H $TC
