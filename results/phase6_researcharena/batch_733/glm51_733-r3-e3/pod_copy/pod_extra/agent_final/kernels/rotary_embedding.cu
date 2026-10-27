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
__global__ __launch_bounds__(256)
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

    __shared__ float s_theta[64];
    __shared__ float s_sin[64];
    __shared__ float s_cos[64];
    __shared__ int s_pos;

    if (threadIdx.x < half_dim) {
        s_theta[threadIdx.x] = static_cast<float>(1.0 / pow(static_cast<double>(base),
                                                             (2.0 * threadIdx.x) / head_dim));
    }

    if (threadIdx.x == 0) {
        int fi = blockIdx.x * blockDim.x;
        int p = fi % half_dim;
        int t = fi / half_dim;
        int h = t % num_heads;
        int t2 = t / num_heads;
        int s = t2 % seq_len;
        int b = t2 / seq_len;
        s_pos = positions[b * seq_len + s];
    }
    __syncthreads();

    if (threadIdx.x < half_dim) {
        float angle = static_cast<float>(s_pos) * s_theta[threadIdx.x];
        double sin_d, cos_d;
        sincos(static_cast<double>(angle), &sin_d, &cos_d);
        s_sin[threadIdx.x] = static_cast<float>(sin_d);
        s_cos[threadIdx.x] = static_cast<float>(cos_d);
    }
    __syncthreads();

    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= total_pairs) return;

    int pair_idx = idx % half_dim;
    int tmp = idx / half_dim;
    int head = tmp % num_heads;
    int tmp2 = tmp / num_heads;
    int seq = tmp2 % seq_len;
    int batch = tmp2 / seq_len;

    int m = positions[batch * seq_len + seq];
    float cos_val, sin_val;

    if (m == s_pos) {
        cos_val = s_cos[pair_idx];
        sin_val = s_sin[pair_idx];
    } else {
        float angle = static_cast<float>(m) * s_theta[pair_idx];
        double sin_d, cos_d;
        sincos(static_cast<double>(angle), &sin_d, &cos_d);
        cos_val = static_cast<float>(cos_d);
        sin_val = static_cast<float>(sin_d);
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
    int batch = x.size(0);
    int seq_len = x.size(1);
    int num_heads = x.size(2);
    int head_dim = x.size(3);

    int total_pairs = batch * seq_len * num_heads * (head_dim / 2);
    int threads = 256;
    int blocks = (total_pairs + threads - 1) / threads;

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
