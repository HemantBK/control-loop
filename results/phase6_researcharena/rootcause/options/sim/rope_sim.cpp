// Drives an extracted rotary_embedding_kernel with its launcher's grid (blocks = ceil(total_pairs/256), 256 threads), every
// (block, thread) in turn. Built two ways: -DASAN_MAIN as an executable on exact-size heap buffers under AddressSanitizer
// (args: B T H D), or as a shared library exposing rope_run() for numerics from Python (ctypes). KERNEL_INC names the
// extracted kernel text; HAS_TOTAL=1 when the kernel takes total_pairs (11ea904, guard-only patch).
#include "shim.h"
#include <cstdio>
#include <cstdlib>
#ifndef SCALAR
#define SCALAR _Float16
#endif
typedef SCALAR scalar_sim;
#include KERNEL_INC
extern "C" int rope_run(scalar_sim* x, const int* pos, int B, int T, int H, int D, float base) {
    int total = B * T * H * (D / 2), threads = 256, blocks = (total + threads - 1) / threads;
    gridDim.x = blocks; blockDim.x = threads;
    for (int b = 0; b < blocks; b++) for (int t = 0; t < threads; t++) {
        blockIdx.x = b; threadIdx.x = t;
#if HAS_TOTAL
        rotary_embedding_kernel<scalar_sim>(x, pos, T, H, D, base, total);
#else
        rotary_embedding_kernel<scalar_sim>(x, pos, T, H, D, base);
#endif
    }
    return blocks * threads - total;   // threads past the last pair (the tail)
}
#ifdef ASAN_MAIN
int main(int argc, char** argv) {
    int B = atoi(argv[1]), T = atoi(argv[2]), H = atoi(argv[3]), D = atoi(argv[4]);
    size_t n = (size_t)B * T * H * D;
    scalar_sim* x = (scalar_sim*)malloc(n * sizeof(scalar_sim)); int* pos = (int*)malloc((size_t)B * T * sizeof(int));
    for (size_t i = 0; i < n; i++) x[i] = (scalar_sim)(0.01f * (i % 97));
    for (int i = 0; i < B * T; i++) pos[i] = i % T;
    int total = B * T * H * (D / 2);
    printf("launch B=%d T=%d H=%d D=%d total_pairs=%d blocks=%d tail_threads=%d\n", B, T, H, D, total, (total + 255) / 256,
           ((total + 255) / 256) * 256 - total);
    int tail = rope_run(x, pos, B, T, H, D, 10000.0f);
    printf("ASAN_CLEAN (tail=%d)\n", tail);
    free(x); free(pos); return 0;
}
#endif
