// Benchmark change 06 (Baseline B): upstream 11ea904's RoPE. It pairs x_i with x_{i+d/2} (split halves, as HF Llama's
// rotate_half), where the stock kernel paired adjacent elements, and it rotates by the real positions inject.py
// passes, where the stock wrapper restarted them at 0 on every decode step.
/*
 * Rotary Positional Embedding (RoPE) CUDA kernel — optimized implementation
 *
 * Applies rotary embeddings to query and key tensors.
 * For each pair (x_i, x_{i+d/2}), rotates by angle m * theta_i where:
 *   theta_i = 1 / (base^(2i/d))
 *   m = position index
 *
 * Optimization: 1 block per (batch, seq) position. sin/cos for all pair_idx
 * values are precomputed once into shared memory by the first half_dim threads,
 * then all (head, pair_idx) threads read from shared memory. This eliminates
 * redundant pow() + sincos() calls across heads (32x fewer for Q, 4x for K).
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

// ─── Kernel ──────────────────────────────────────────────────────────────────

template <typename scalar_t>
__global__ __launch_bounds__(1024)
void rotary_embedding_kernel(
    scalar_t* __restrict__ x,
    const int* __restrict__ positions,
    int seq_len,
    int num_heads,
    int head_dim,
    float base,
    int total_pairs
) {
    int half_dim = head_dim / 2;
    int bs_idx = blockIdx.x;
    int batch = bs_idx / seq_len;
    int seq = bs_idx % seq_len;

    int m = positions[bs_idx];

    __shared__ float smem_cos[64];
    __shared__ float smem_sin[64];

    if (threadIdx.x < half_dim) {
        float theta = static_cast<float>(1.0 / pow(static_cast<double>(base),
                                                    (2.0 * threadIdx.x) / head_dim));
        float angle = static_cast<float>(m) * theta;
        double sin_d, cos_d;
        sincos(static_cast<double>(angle), &sin_d, &cos_d);
        smem_cos[threadIdx.x] = static_cast<float>(cos_d);
        smem_sin[threadIdx.x] = static_cast<float>(sin_d);
    }
    __syncthreads();

    int total_vec_pairs = num_heads * (half_dim / 2);

    for (int idx = threadIdx.x; idx < total_vec_pairs; idx += blockDim.x) {
        int local_pair = idx % (half_dim / 2);
        int head = idx / (half_dim / 2);
        int pair0 = local_pair * 2;
        int pair1 = pair0 + 1;

        float cos0 = smem_cos[pair0];
        float sin0 = smem_sin[pair0];
        float cos1 = smem_cos[pair1];
        float sin1 = smem_sin[pair1];

        int base_idx = (bs_idx * num_heads + head) * head_dim;

        uint32_t vx_lo = *reinterpret_cast<const uint32_t*>(&x[base_idx + pair0]);
        const scalar_t* px_lo = reinterpret_cast<const scalar_t*>(&vx_lo);
        float a0 = static_cast<float>(px_lo[0]);
        float a1 = static_cast<float>(px_lo[1]);

        uint32_t vx_hi = *reinterpret_cast<const uint32_t*>(&x[base_idx + pair0 + half_dim]);
        const scalar_t* px_hi = reinterpret_cast<const scalar_t*>(&vx_hi);
        float b0 = static_cast<float>(px_hi[0]);
        float b1 = static_cast<float>(px_hi[1]);

        union { uint32_t u; scalar_t s[2]; } out_lo;
        out_lo.s[0] = static_cast<scalar_t>(a0 * cos0 - b0 * sin0);
        out_lo.s[1] = static_cast<scalar_t>(a1 * cos1 - b1 * sin1);
        *reinterpret_cast<uint32_t*>(&x[base_idx + pair0]) = out_lo.u;

        union { uint32_t u; scalar_t s[2]; } out_hi;
        out_hi.s[0] = static_cast<scalar_t>(b0 * cos0 + a0 * sin0);
        out_hi.s[1] = static_cast<scalar_t>(b1 * cos1 + a1 * sin1);
        *reinterpret_cast<uint32_t*>(&x[base_idx + pair0 + half_dim]) = out_hi.u;
    }

    if (half_dim % 2 != 0) {
        int odd_pair = half_dim - 1;
        for (int idx = total_vec_pairs + threadIdx.x; idx < num_heads * half_dim; idx += blockDim.x) {
            int head = idx / half_dim;
            float cos_val = smem_cos[odd_pair];
            float sin_val = smem_sin[odd_pair];
            int base_idx = (bs_idx * num_heads + head) * head_dim;
            int i0 = base_idx + odd_pair;
            int i1 = base_idx + odd_pair + half_dim;
            float x0 = static_cast<float>(x[i0]);
            float x1 = static_cast<float>(x[i1]);
            x[i0] = static_cast<scalar_t>(x0 * cos_val - x1 * sin_val);
            x[i1] = static_cast<scalar_t>(x1 * cos_val + x0 * sin_val);
        }
    }
}

// ─── Host wrapper ────────────────────────────────────────────────────────────

torch::Tensor agent_rotary_embedding(
    torch::Tensor x,          // [batch, seq_len, num_heads, head_dim]
    torch::Tensor positions,   // [batch, seq_len] int32
    double base
) {
    auto output = x.clone();
    int batch = x.size(0);
    int seq_len = x.size(1);
    int num_heads = x.size(2);
    int head_dim = x.size(3);
    int half_dim = head_dim / 2;

    int blocks = batch * seq_len;
    int total_vec_pairs = num_heads * (half_dim / 2);
    int threads = min(total_vec_pairs, 1024);
    threads = max(((threads + 31) / 32) * 32, 32);

    if (blocks > 0) {
        AT_DISPATCH_FLOATING_TYPES_AND2(
            at::ScalarType::Half, at::ScalarType::BFloat16,
            x.scalar_type(), "rotary_embedding", [&] {
                rotary_embedding_kernel<scalar_t><<<blocks, threads>>>(
                    output.data_ptr<scalar_t>(),
                    positions.data_ptr<int>(),
                    seq_len, num_heads, head_dim,
                    static_cast<float>(base),
                    batch * seq_len * num_heads * half_dim
                );
            }
        );
    }

    return output;
}
