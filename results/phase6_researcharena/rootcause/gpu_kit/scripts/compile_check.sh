#!/usr/bin/env bash
# Compile-only check of a kernels directory with the same nvcc (12.9.86), the same flags torch.utils.cpp_extension.load
# uses in bench.py:139-146 (-O3 --use_fast_math -lineinfo, plus torch's COMMON_NVCC_FLAGS) and the same target
# (sm_90 = H100; the pod's TORCH_CUDA_ARCH_LIST is 8.0;8.9;9.0 so 8.0/8.9 are compiled too) against torch 2.10.0's
# headers. No GPU: objects only, then a -shared link to catch unresolved symbols between bindings.cpp and the .cu files.
set -euo pipefail
DIR="${1:?kernels dir}"; OUT="${2:-$DIR/_build}"
VENV="${VENV:-$HOME/work/venv/py311}"
CUDA="${CUDA_HOME:-$HOME/work/cuda_debs/root/usr/local/cuda-12.9}"
PY="$VENV/bin/python"
TORCH_INC=$("$PY" -c "import torch.utils.cpp_extension as c; print(' '.join('-I'+p for p in c.include_paths()))")
PY_INC=$("$PY" -c "import sysconfig; print(sysconfig.get_paths()['include'])")
TORCH_LIB=$("$PY" -c "import torch, os; print(os.path.join(os.path.dirname(torch.__file__), 'lib'))")
ABI=$("$PY" -c "import torch; print(int(torch._C._GLIBCXX_USE_CXX11_ABI))")
ARCHS="${ARCHS:-90}"
mkdir -p "$OUT"
export PATH="$CUDA/bin:$PATH"
DEFS="-DTORCH_API_INCLUDE_EXTENSION_H -DTORCH_EXTENSION_NAME=agent_ops -D_GLIBCXX_USE_CXX11_ABI=$ABI -DPYBIND11_COMPILER_TYPE=\"_gcc\" -DPYBIND11_STDLIB=\"_libstdcpp\" -DPYBIND11_BUILD_ABI=\"_cxxabi1011\""
NVCC_COMMON="-D__CUDA_NO_HALF_OPERATORS__ -D__CUDA_NO_HALF_CONVERSIONS__ -D__CUDA_NO_BFLOAT16_CONVERSIONS__ -D__CUDA_NO_HALF2_OPERATORS__ --expt-relaxed-constexpr"
GEN=""; for a in ${ARCHS//;/ }; do GEN="$GEN -gencode arch=compute_$a,code=sm_$a"; done
echo "nvcc: $(nvcc --version | tail -1)"; echo "archs: $ARCHS"; echo "dir: $DIR"
rc=0
for f in "$DIR"/*.cu; do
  b=$(basename "$f" .cu)
  echo "--- nvcc $b.cu"
  if nvcc -c "$f" -o "$OUT/$b.cuda.o" $DEFS $NVCC_COMMON $GEN -O3 --use_fast_math -lineinfo -std=c++17 \
       --compiler-options -fPIC $TORCH_INC -I"$PY_INC" -I"$CUDA/include" -Xcompiler -Wall 2> "$OUT/$b.nvcc.log"; then
    echo "OK   $b.cu ($(grep -c warning "$OUT/$b.nvcc.log" || true) warnings)"; grep -i "warning" "$OUT/$b.nvcc.log" | head -5 || true
  else echo "FAIL $b.cu"; cat "$OUT/$b.nvcc.log"; rc=1; fi
done
echo "--- g++ bindings.cpp"
if g++ -c "$DIR/bindings.cpp" -o "$OUT/bindings.o" $DEFS -O3 -std=c++17 -fPIC $TORCH_INC -I"$PY_INC" -I"$CUDA/include" 2> "$OUT/bindings.log"; then echo "OK   bindings.cpp"; else echo "FAIL bindings.cpp"; cat "$OUT/bindings.log"; rc=1; fi
echo "--- link agent_ops.so (shared; CUDA runtime from the extracted toolkit; torch libs from the CPU wheel)"
if g++ -shared -o "$OUT/agent_ops.so" "$OUT"/*.o -L"$TORCH_LIB" -lc10 -ltorch -ltorch_cpu -ltorch_python -L"$CUDA/lib64" -lcudart 2> "$OUT/link.log"; then
  echo "OK   link ($(stat -c %s "$OUT/agent_ops.so") bytes)"; nm -C "$OUT/agent_ops.so" | grep -E " T .*agent_(rmsnorm|rotary_embedding|fused_mlp|attention)" | sed 's/^/     /'
  und=$(nm -C -u "$OUT/agent_ops.so" | grep -E "agent_|_kernel" || true); if [ -n "$und" ]; then echo "FAIL unresolved kernel/wrapper symbols:"; echo "$und"; rc=1; else echo "OK   no unresolved agent_*/kernel symbols (Python/torch symbols resolve at import)"; fi
else echo "FAIL link"; head -20 "$OUT/link.log"; rc=1; fi
echo "RESULT: $([ $rc = 0 ] && echo COMPILE_OK || echo COMPILE_FAIL)"
exit $rc
