#!/bin/bash
# Re-measure monitor (owner, 2026-10-24): every 2 s, GPU clocks, utilisation, temperature and power
# (monitor_gpu.csv: epoch, SM MHz, mem MHz, util %, mem util %, temp C, power W), and the 1-minute load average, the
# GPU's compute processes and the top CPU processes (monitor_cpu.log). Runs until stopped (procs.py kill-tree).
O=${P6_RM:-/workspace/remeasure}; mkdir -p $O
while :; do
  t=$(date +%s.%N)
  echo "$t,$(nvidia-smi --query-gpu=clocks.sm,clocks.mem,utilization.gpu,utilization.memory,temperature.gpu,power.draw --format=csv,noheader,nounits 2>&1 | head -1)" >> $O/monitor_gpu.csv
  { echo "== $t load $(cut -d' ' -f1-3 /proc/loadavg)"; nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>&1
    ps -eo pid,pcpu,etimes,comm --sort=-pcpu | head -6; } >> $O/monitor_cpu.log
  sleep 2
done
