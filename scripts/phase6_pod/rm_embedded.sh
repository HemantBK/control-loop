#!/bin/bash
# Re-measure step 5 (done criterion 4): the embedded KL side-task evaluator alone (side_tasks/embedded/evaluate.py's
# evaluate(), as evaluate.py's run_side_task calls it) on the agent's submission.
set -u; . "$(dirname "$0")/rm_common.sh"
O=$P6_RM/embedded; mkdir -p $O; SET=/workspace/arena_root/settings/cuda_kernel
( cd $P6_RM && timeout 1500 python3 -c "
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('emb', '$SET/side_tasks/embedded/evaluate.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
r = m.evaluate('$P6_RM/submission')
json.dump(r, open('$O/metrics_embedded.json', 'w'), indent=2); print('EMBEDDED_RESULT', json.dumps(r))
" ) > $O/embedded.log 2>&1; echo "rc=$?"
grep -hE "EMBEDDED_RESULT|KL|Traceback" $O/embedded.log | tail -5 | cut -c1-240
echo "EMBEDDED_DONE"
