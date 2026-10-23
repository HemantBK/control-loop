#!/bin/bash
# AddressSanitizer battery (Amendment (14)): every case prints ASAN_CLEAN or the first ASan report line.
cd "$(dirname "$0")"
run() { local k=$1 lbl=$2; shift 2; local o; o=$(./asan_$k "$@" 2>&1); if echo "$o" | grep -q ASAN_CLEAN; then echo "CLEAN    [$k] $lbl ($*): $(echo "$o" | head -1)"; else echo "OVERFLOW [$k] $lbl ($*): $(echo "$o" | grep -m1 -E 'ERROR: AddressSanitizer|SUMMARY')"; fi; }
echo "## control: stock kernel, TinyLlama shapes"
run stock "TinyLlama k decode" 1 1 4 64
run stock "TinyLlama k prefill odd T=13" 1 13 4 64
run stock "TinyLlama q decode" 1 1 32 64
echo "## option 2: 11ea904 kernel, TinyLlama shapes"
for T in 1 2 11 12 13 14; do run up "TinyLlama k T=$T" 1 $T 4 64; run up "TinyLlama q T=$T" 1 $T 32 64; done
run up "embedded3 probe shape" 2 16 4 64
echo "## option 3: STOCK kernel, no patch, Sheared-LLaMA-1.3B shapes (16 heads x 128, MHA: q and k identical)"
for T in $(seq 1 40); do run stock "Sheared q/k T=$T" 1 $T 16 128; done | sort | uniq -c -w 8 | sed 's/^/  /'
for T in 1 12 13 129 2049; do run stock "Sheared q/k T=$T" 1 $T 16 128; done
