#!/bin/bash
# Re-measure step 3b: the final initial kernels (change 03's attention, change 06's RoPE) under memcheck with launch counts.
bash "$(dirname "$0")/rm_memcheck.sh" initial
