#!/bin/bash
# Phase 6 agent run (Amendment (17) item 1, kept): the last_bench.json event log. Started just before the episode; waits
# for the pipeline's new agent job dir (/tmp/arena_agent_*), then logs every inotify event whose path contains
# last_bench.json until the agent's time budget plus 30 minutes has passed. Output: $O/last_bench_events.log.
O=${P6_OUT:-/workspace/fullrun3}; mkdir -p $O; L=$O/last_bench_events.log; : > $L
LIMIT=${P6_WATCH_S:-5400}
cat > $O/watch.sh <<W
#!/bin/bash
t0=\$(date +%s); before=\$(ls -d /tmp/arena_agent_* 2>/dev/null)
while :; do d=\$(ls -dt /tmp/arena_agent_* 2>/dev/null | head -1); [ -n "\$d" ] && ! echo "\$before" | grep -qx "\$d" && break
  [ \$(( \$(date +%s) - t0 )) -gt 900 ] && { echo "\$(date -u +%FT%TZ) no agent job dir appeared" >> $L; exit 0; }; sleep 1; done
echo "\$(date -u +%FT%TZ) WATCHING \$d" >> $L
timeout $LIMIT inotifywait -m -r -q -e access,modify,open,close_write,close_nowrite,create,delete,moved_to,moved_from --timefmt '%FT%TZ' --format '%T %e %w%f' "\$d" 2>>$L | grep --line-buffered last_bench >> $L
echo "\$(date -u +%FT%TZ) WATCH_END" >> $L
W
chmod +x $O/watch.sh
setsid nohup $O/watch.sh > $O/watch.out 2>&1 < /dev/null &
echo "watcher started pid $!"
