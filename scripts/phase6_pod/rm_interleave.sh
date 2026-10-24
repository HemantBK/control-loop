#!/bin/bash
# Re-measure step 2: the main number, initial kernels against the agent's kernels, 3 interleaved pairs.
bash "$(dirname "$0")/rm_pairs.sh" initial agent interleave 3
