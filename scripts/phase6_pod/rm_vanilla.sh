#!/bin/bash
# Re-measure step 6: the secondary number against vanilla PyTorch, 3 interleaved pairs.
bash "$(dirname "$0")/rm_pairs.sh" vanilla agent vanilla 3
