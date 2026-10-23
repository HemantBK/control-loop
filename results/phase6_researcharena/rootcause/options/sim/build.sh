#!/bin/bash
# Builds the ASan drivers and the numerics libraries for the stock (58776e0) and upstream (11ea904) rotary kernels.
set -euo pipefail
cd "$(dirname "$0")"; RA=/root/src/ResearchArena; F=settings/cuda_kernel/task_context/kernels/rotary_embedding.cu
git -C $RA show 58776e09339c1714d0524130590abaf6eac7879d:$F > stock.cu; git -C $RA show 11ea904:$F > up.cu
python3 extract.py stock.cu kernel_stock.inc; python3 extract.py up.cu kernel_up.inc
sha256sum stock.cu up.cu kernel_stock.inc kernel_up.inc
for k in stock up; do t=0; [ $k = up ] && t=1
  g++ -O1 -g -fsanitize=address -fno-omit-frame-pointer -DASAN_MAIN -DKERNEL_INC="\"kernel_$k.inc\"" -DHAS_TOTAL=$t rope_sim.cpp -o asan_$k
  g++ -O2 -fPIC -shared -DKERNEL_INC="\"kernel_$k.inc\"" -DHAS_TOTAL=$t rope_sim.cpp -o librope_${k}_f16.so
  g++ -O2 -fPIC -shared -DSCALAR=__bf16 -DKERNEL_INC="\"kernel_$k.inc\"" -DHAS_TOTAL=$t rope_sim.cpp -o librope_${k}_bf16.so 2> bf16_$k.log && echo "bf16 $k ok" || echo "bf16 $k FAILED (see bf16_$k.log)"
done
ls -la asan_* librope_*
