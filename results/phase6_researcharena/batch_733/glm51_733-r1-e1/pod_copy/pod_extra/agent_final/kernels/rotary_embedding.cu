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
    scalar_t* __restrict__ x,
    const int* __restrict__ positions,
    int seq_len,
    int num_heads,
    int head_dim,
    float base,
    int batch_size
) {
    int half_dim = head_dim / 2;
    int angle_idx = blockIdx.x;
    int num_angles = batch_size * seq_len * half_dim;
    if (angle_idx >= num_angles) return;

    int pair_idx = angle_idx % half_dim;
    int tmp = angle_idx / half_dim;
    int seq = tmp % seq_len;
    int batch = tmp / seq_len;

    int m = positions[batch * seq_len + seq];
    float theta = static_cast<float>(1.0 / pow(static_cast<double>(base),
                                               (2.0 * pair_idx) / head_dim));
    float angle = static_cast<float>(m) * theta;
    double sin_d, cos_d;
    sincos(static_cast<double>(angle), &sin_d, &cos_d);
    float cos_val = static_cast<float>(cos_d);
    float sin_val = static_cast<float>(sin_d);

    for (int head = threadIdx.x; head < num_heads; head += blockDim.x) {
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
    auto output = x.clone();
    int batch = x.size(0);
    int seq_len = x.size(1);
    int num_heads = x.size(2);
    int head_dim = x.size(3);
    int half_dim = head_dim / 2;

    int num_angles = batch * seq_len * half_dim;
    int threads = max(((num_heads + 31) / 32) * 32, 32);

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        x.scalar_type(), "rotary_embedding", [&] {
            rotary_embedding_kernel<scalar_t><<<num_angles, threads>>>(
                output.data_ptr<scalar_t>(),
                positions.data_ptr<int>(),
                seq_len, num_heads, head_dim,
                static_cast<float>(base),
                batch
            );
        }
    );

    return output;
}
