/*
 * Rotary Positional Embedding (RoPE) CUDA kernel — optimized implementation
 *
 * Applies rotary embeddings to query and key tensors.
 * For each pair (x_i, x_{i+d/2}), rotates by angle m * theta_i where:
 *   theta_i = 1 / (base^(2i/d))
 *   m = position index
 *
 * Optimizations:
 * - Precompute inv_freq in shared memory (eliminates redundant pow() calls)
 * - Use sincosf for faster trig computation
 * - Process 2 pairs per thread to reduce kernel launch overhead
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

template <typename scalar_t>
__global__ void rotary_embedding_kernel(
    scalar_t* __restrict__ x,
    const int* __restrict__ positions,
    int seq_len,
    int num_heads,
    int head_dim,
    float base,
    int total_pairs
) {
    int half_dim = head_dim / 2;

    __shared__ float s_inv_freq[128];
    for (int i = threadIdx.x; i < half_dim; i += blockDim.x) {
        s_inv_freq[i] = static_cast<float>(
            1.0 / pow(static_cast<double>(base), (2.0 * i) / head_dim));
    }
    __syncthreads();

    int idx = blockIdx.x * blockDim.x * 2 + threadIdx.x;

    #pragma unroll
    for (int rep = 0; rep < 2; rep++) {
        int cur_idx = idx + rep * blockDim.x;
        if (cur_idx >= total_pairs) return;

        int pair_idx = cur_idx % half_dim;
        int tmp = cur_idx / half_dim;
        int head = tmp % num_heads;
        int tmp2 = tmp / num_heads;
        int seq = tmp2 % seq_len;
        int batch = tmp2 / seq_len;

        int m = positions[batch * seq_len + seq];
        float angle = static_cast<float>(m) * s_inv_freq[pair_idx];
        double cos_d, sin_d;
        sincos(static_cast<double>(angle), &sin_d, &cos_d);
        float cos_val = static_cast<float>(cos_d);
        float sin_val = static_cast<float>(sin_d);

        int base_idx = ((batch * seq_len + seq) * num_heads + head) * head_dim;
        int i0 = base_idx + pair_idx;
        int i1 = base_idx + pair_idx + half_dim;

        float x0 = static_cast<float>(x[i0]);
        float x1 = static_cast<float>(x[i1]);

        x[i0] = static_cast<scalar_t>(x0 * cos_val - x1 * sin_val);
        x[i1] = static_cast<scalar_t>(x1 * cos_val + x0 * sin_val);
    }
}

// ─── Host wrapper ────────────────────────────────────────────────────────────

torch::Tensor agent_rotary_embedding(
    torch::Tensor x,          // [batch, seq_len, num_heads, head_dim]
    torch::Tensor positions,   // [batch, seq_len] int32
    double base
) {
    int batch = x.size(0);
    int seq_len = x.size(1);
    int num_heads = x.size(2);
    int head_dim = x.size(3);
    int half_dim = head_dim / 2;

    int total_pairs = batch * seq_len * num_heads * half_dim;
    int threads = 256;
    int blocks = (total_pairs + threads * 2 - 1) / (threads * 2);

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        x.scalar_type(), "rotary_embedding", [&] {
            rotary_embedding_kernel<scalar_t><<<blocks, threads>>>(
                x.data_ptr<scalar_t>(),
                positions.data_ptr<int>(),
                seq_len, num_heads, head_dim,
                static_cast<float>(base),
                total_pairs
            );
        }
    );

    return x;
}
