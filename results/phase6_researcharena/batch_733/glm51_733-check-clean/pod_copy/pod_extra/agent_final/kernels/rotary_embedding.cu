// Benchmark change 06 (Baseline B): upstream 11ea904's RoPE. It pairs x_i with x_{i+d/2} (split halves, as HF Llama's
// rotate_half), where the stock kernel paired adjacent elements, and it rotates by the real positions inject.py
// passes, where the stock wrapper restarted them at 0 on every decode step.
/*
 * Rotary Positional Embedding (RoPE) CUDA kernel — baseline implementation
 *
 * Applies rotary embeddings to query and key tensors.
 * For each pair (x_i, x_{i+d/2}), rotates by angle m * theta_i where:
 *   theta_i = 1 / (base^(2i/d))
 *   m = position index
 *
 * Used in LLaMA, Mistral, and most modern transformer models.
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

// ─── Kernel ──────────────────────────────────────────────────────────────────

template <typename scalar_t>
__global__ void rotary_embedding_kernel(
    scalar_t* __restrict__ x,          // [batch, seq_len, num_heads, head_dim]
    const int* __restrict__ positions,  // [batch, seq_len]
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

    __shared__ float s_cos[64];
    __shared__ float s_sin[64];
    __shared__ float s_ratio;

    if (threadIdx.x == 0) {
        s_ratio = static_cast<float>(1.0 / pow(static_cast<double>(base), 2.0 / head_dim));
    }
    __syncthreads();

    float ratio = s_ratio;
    for (int i = threadIdx.x; i < half_dim; i += blockDim.x) {
        float inv_freq_i = 1.0f;
        float r = ratio;
        int p = i;
        while (p > 0) {
            if (p & 1) inv_freq_i *= r;
            r *= r;
            p >>= 1;
        }
        float angle = static_cast<float>(m) * inv_freq_i;
        double sin_d, cos_d;
        sincos(static_cast<double>(angle), &sin_d, &cos_d);
        s_cos[i] = static_cast<float>(cos_d);
        s_sin[i] = static_cast<float>(sin_d);
    }
    __syncthreads();

    int total_for_pos = num_heads * half_dim;
    for (int idx = threadIdx.x; idx < total_for_pos; idx += blockDim.x) {
        int pair_idx = idx % half_dim;
        int head = idx / half_dim;

        float cos_val = s_cos[pair_idx];
        float sin_val = s_sin[pair_idx];

        int base_idx = (bs_idx * num_heads + head) * head_dim;
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
    auto output = x.clone();
    int batch = x.size(0);
    int seq_len = x.size(1);
    int num_heads = x.size(2);
    int head_dim = x.size(3);
    int half_dim = head_dim / 2;

    int total_pairs = batch * seq_len * num_heads * half_dim;
    int num_positions = batch * seq_len;

    if (num_positions == 0) return output;

    int threads = 256;
    dim3 grid(num_positions);

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        x.scalar_type(), "rotary_embedding", [&] {
            rotary_embedding_kernel<scalar_t><<<grid, threads>>>(
                output.data_ptr<scalar_t>(),
                positions.data_ptr<int>(),
                seq_len, num_heads, head_dim,
                static_cast<float>(base),
                total_pairs
            );
        }
    );

    return output;
}
