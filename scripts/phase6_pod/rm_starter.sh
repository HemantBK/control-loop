#!/bin/bash
# Re-measure step 7: the secondary number against the starter kernels, 3 interleaved pairs.
bash "$(dirname "$0")/rm_pairs.sh" starter agent starter 3
