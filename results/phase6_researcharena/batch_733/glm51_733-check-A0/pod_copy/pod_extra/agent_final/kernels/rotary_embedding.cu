/*
 * Rotary Positional Embedding (RoPE) CUDA kernel — optimized implementation
 *
 * Applies rotary embeddings to query and key tensors.
 * For each pair (x_i, x_{i+d/2}), rotates by angle m * theta_i where:
 *   theta_i = 1 / (base^(2i/d))
 *   m = position index
 *
 * Optimizations:
 * - Precompute theta values in shared memory using recurrence (1 powf vs N)
 * - Use float precision for powf instead of double pow
 * - Keep double precision sincos for accuracy at large positions
 * - Avoid redundant pow() calls across threads with same pair_idx
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

    extern __shared__ float smem[];
    float* s_theta = smem;

    if (threadIdx.x == 0) {
        float inv_step = 1.0f / powf(base, 2.0f / head_dim);
        float theta = 1.0f;
        for (int i = 0; i < half_dim; i++) {
            s_theta[i] = theta;
            theta *= inv_step;
        }
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
    float angle = static_cast<float>(m) * s_theta[pair_idx];
    double sin_d, cos_d;
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

torch::Tensor agent_rotary_embedding(
    torch::Tensor x,
    torch::Tensor positions,
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
    size_t smem_size = half_dim * sizeof(float);

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        x.scalar_type(), "rotary_embedding", [&] {
            rotary_embedding_kernel<scalar_t><<<blocks, threads, smem_size>>>(
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
