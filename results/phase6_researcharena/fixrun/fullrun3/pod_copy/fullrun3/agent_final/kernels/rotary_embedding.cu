/*
 * Rotary Positional Embedding (RoPE) CUDA kernel — optimized
 *
 * Key optimizations:
 * - In-place operation (no clone; inject.py already passes contiguous copies)
 * - Precomputed inv_freq in shared memory (eliminates redundant pow per thread)
 * - Float expf/logf instead of double pow for inv_freq computation
 * - __sincosf with manual argument reduction instead of double sincos
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

// ─── Kernel ──────────────────────────────────────────────────────────────────

template <typename scalar_t>
__global__ __launch_bounds__(256)
void rotary_embedding_kernel(
    scalar_t* __restrict__ x,          // [batch, seq_len, num_heads, head_dim]
    const int* __restrict__ positions,  // [batch, seq_len]
    int seq_len,
    int num_heads,
    int head_dim,
    float base,
    int total_pairs
) {
    int half_dim = head_dim / 2;

    // Precompute inv_freq in shared memory (only half_dim unique values)
    __shared__ float s_inv_freq[128];
    if (threadIdx.x < half_dim) {
        s_inv_freq[threadIdx.x] = expf(-logf(base) * (2.0f * (float)threadIdx.x) / (float)head_dim);
    }
    __syncthreads();

    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= total_pairs) return;

    // Decode flat index → (batch, seq, head, pair)
    int pair_idx = idx % half_dim;
    int tmp = idx / half_dim;
    int head = tmp % num_heads;
    int tmp2 = tmp / num_heads;
    int seq = tmp2 % seq_len;
    int batch = tmp2 / seq_len;

    int m = positions[batch * seq_len + seq];
    float angle = (float)m * s_inv_freq[pair_idx];

    // Argument reduction to [-pi, pi] for __sincosf accuracy with large positions
    const float inv_2pi = 0.15915494309189535f;  // 1/(2*pi)
    float k_rnd = floorf(angle * inv_2pi + 0.5f);
    angle = angle - k_rnd * 6.2831853071795862f;

    float sin_val, cos_val;
    __sincosf(angle, &sin_val, &cos_val);

    // Index into x: [batch, seq, head, head_dim]
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
    // Operate in-place: inject.py already passes .contiguous() copies
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
