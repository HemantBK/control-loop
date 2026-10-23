// Drives the extracted rotary kernel with the stock launcher's grid (rotary_embedding.cu:66-70) on CPU under ASan.
// Usage: sim <B> <T> <H> <D>   (prints the launch config; ASan reports any out-of-bounds access)
#include "cuda_cpu_shim.h"
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <cstring>
typedef _Float16 half_t;   // 2-byte element like c10::Half
#ifdef PATCHED
#include "kernel_rope_bounds.inc"
#else
#include "kernel_stock.inc"
#endif
int main(int argc, char** argv) {
    int B = atoi(argv[1]), T = atoi(argv[2]), H = atoi(argv[3]), D = atoi(argv[4]);
    int half_dim = D / 2;
    int total_pairs = B * T * H * half_dim;
    int threads = 256;
    int blocks = (total_pairs + threads - 1) / threads;
    // exact-size heap buffers: ASan flags any byte past the end
    half_t* x = (half_t*)malloc((size_t)B * T * H * D * sizeof(half_t));
    int* positions = (int*)malloc((size_t)B * T * sizeof(int));
    for (int i = 0; i < B * T * H * D; i++) x[i] = (half_t)(0.01f * (i % 97));
    for (int i = 0; i < B * T; i++) positions[i] = i % T;
    printf("launch: B=%d T=%d H=%d D=%d total_pairs=%d blocks=%d threads=%d launched=%d tail=%d x_bytes=%zu\n",
           B, T, H, D, total_pairs, blocks, threads, blocks * threads, blocks * threads - total_pairs,
           (size_t)B * T * H * D * sizeof(half_t));
    gridDim.x = blocks; blockDim.x = threads;
    for (unsigned b = 0; b < (unsigned)blocks; b++) for (unsigned t = 0; t < (unsigned)threads; t++) {
        blockIdx.x = b; threadIdx.x = t;
#ifdef PATCHED
        rotary_embedding_kernel<half_t>(x, positions, T, H, D, 10000.0f, total_pairs);
#else
        rotary_embedding_kernel<half_t>(x, positions, T, H, D, 10000.0f);
#endif
    }
    printf("done: no out-of-bounds access detected by ASan\n");
    free(x); free(positions);
    return 0;
}
