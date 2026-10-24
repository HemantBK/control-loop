#!/bin/bash
# Real-tool rehearsal of the re-measure session against this CPU pod (owner, 2026-10-24): real ssh (127.0.0.1:22, a
# throwaway key accepted only from localhost, removed at the end) and real rsync; every step that does not need a GPU.
# /workspace on this pod is laid out as on a GPU pod: arena_root (the composed root), src/control-loop (the procs helper),
# hf; only directories this script creates are removed afterwards. Exit 0 only if every step passes.
set -u; cd /root/control-loop
O=results/phase6_researcharena/fixrun/remeasure_final/local_rehearsal; rm -rf $O; mkdir -p $O
K=/root/scratch/commitprep/p6_local_key; rm -f $K $K.pub; ssh-keygen -q -t ed25519 -N "" -C p6-local-rehearsal -f $K
AK=/root/.ssh/authorized_keys; cp $AK $O/authorized_keys.before.count 2>/dev/null; wc -l < $AK > $O/authorized_keys.lines_before
echo "from=\"127.0.0.1,::1\" $(cat $K.pub)" >> $AK
MADE=""
for d in arena_root src hf bench_changes pod_rm remeasure jobs; do [ -e /workspace/$d ] || MADE="$MADE $d"; done
echo "creating under /workspace:$MADE"
cp -a /root/phase6_arena_root /workspace/arena_root
mkdir -p /workspace/src/control-loop /workspace/hf/hub; cp -r control_loop /workspace/src/control-loop/
cleanup() {
  grep -v "p6-local-rehearsal" $AK > $AK.tmp && cat $AK.tmp > $AK && rm -f $AK.tmp
  echo "authorized_keys lines: before $(cat $O/authorized_keys.lines_before), after $(wc -l < $AK)"
  for d in $MADE; do rm -rf /workspace/$d; done; rm -f /workspace/rm_manifest.txt $K $K.pub
  git -C /root/src/ResearchArena diff --quiet HEAD -- && echo "ResearchArena checkout unchanged" || echo "CHECKOUT CHANGED"
}
trap cleanup EXIT
export P6_LOCAL_TARGET=1 P6_LOCAL_KEY=$K P6_RM_OUT=$O P6_RM_NAME=p6-local P6_RM_RUN_ID=p6-local
R="uv run --frozen python scripts/phase6/remeasure.py"
ok=1
for s in check create ready driver setup kit harness localcheck copy delete; do
  echo "=== $s $(date -u +%T)"; $R $s > $O/step_$s.out 2>&1; rc=$?; tail -4 $O/step_$s.out | cut -c1-220
  [ $rc = 0 ] || { echo "LOCAL_STEP_FAILED $s rc=$rc"; ok=0; }
done
python3 -c "import json; v=json.load(open('$O/copy_verify.json')); print('copy verify:', {k: v[k] for k in ('pass','remote_files','local_matching','n_missing','n_mismatched')})"
grep -q "monitor stopped for the copy" $O/pod_copy/remeasure/monitor.out 2>/dev/null && echo "the copy step stopped the monitor via procs.py" || { echo "MONITOR_NOT_STOPPED"; ok=0; }
[ $ok = 1 ] && echo "LOCAL_REHEARSAL PASS" || echo "LOCAL_REHEARSAL FAIL"
