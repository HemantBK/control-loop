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
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    int half_dim = head_dim / 2;
    int tid = threadIdx.x;
    int bdim = blockDim.x;

    __shared__ float s_inv_freq[64];
    __shared__ float s_cos[64];
    __shared__ float s_sin[64];
    __shared__ int s_block_pos;

    float log_base = logf(base);
    for (int i = tid; i < half_dim; i += bdim) {
        s_inv_freq[i] = expf(-2.0f * i / head_dim * log_base);
    }
    __syncthreads();

    if (tid == 0) {
        int first_idx = blockIdx.x * bdim;
        int fi_p = first_idx % half_dim;
        int fi_t = first_idx / half_dim;
        int fi_s = (fi_t / num_heads) % seq_len;
        int fi_b = (fi_t / num_heads) / seq_len;
        s_block_pos = positions[fi_b * seq_len + fi_s];
    }
    __syncthreads();

    for (int i = tid; i < half_dim; i += bdim) {
        float a = static_cast<float>(s_block_pos) * s_inv_freq[i];
        double sd, cd;
        sincos(static_cast<double>(a), &sd, &cd);
        s_sin[i] = static_cast<float>(sd);
        s_cos[i] = static_cast<float>(cd);
    }
    __syncthreads();

    if (idx >= total_pairs) return;

    int pair_idx = idx % half_dim;
    int tmp = idx / half_dim;
    int head = tmp % num_heads;
    int tmp2 = tmp / num_heads;
    int seq = tmp2 % seq_len;
    int batch = tmp2 / seq_len;

    int m = positions[batch * seq_len + seq];
    float cos_val, sin_val;
    if (m == s_block_pos) {
        cos_val = s_cos[pair_idx];
        sin_val = s_sin[pair_idx];
    } else {
        float theta = s_inv_freq[pair_idx];
        float angle = static_cast<float>(m) * theta;
        double sd, cd;
        sincos(static_cast<double>(angle), &sd, &cd);
        cos_val = static_cast<float>(cd);
        sin_val = static_cast<float>(sd);
    }

    int base_idx = ((batch * seq_len + seq) * num_heads + head) * head_dim;
    int i0 = base_idx + pair_idx;
    int i1 = base_idx + pair_idx + half_dim;

    float x0 = static_cast<float>(x[i0]);
    float x1 = static_cast<float>(x[i1]);

    x[i0] = static_cast<scalar_t>(x0 * cos_val - x1 * sin_val);
    x[i1] = static_cast<scalar_t>(x1 * cos_val + x0 * sin_val);
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
    int threads = 256;
    int blocks = (total_pairs + threads - 1) / threads;

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        x.scalar_type(), "rotary_embedding", [&] {
            rotary_embedding_kernel<scalar_t><<<blocks, threads>>>(
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
