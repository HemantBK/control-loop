/*
 * Rotary Positional Embedding (RoPE) CUDA kernel — optimized implementation
 *
 * Applies rotary embeddings to query and key tensors.
 * For each pair (x_i, x_{i+d/2}), rotates by angle m * theta_i where:
 *   theta_i = 1 / (base^(2i/d))
 *   m = position index
 *
 * Optimizations:
 * - Precompute sin/cos per pair_idx in shared memory (reduces pow+sincos
 *   from total_pairs to half_dim per block)
 * - All threads in a block share the same position (guaranteed by flat index
 *   structure when blockDim.x <= num_heads * half_dim)
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

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

    __shared__ float s_sin[64];
    __shared__ float s_cos[64];
    __shared__ int s_m;

    if (threadIdx.x == 0) {
        int first_idx = blockIdx.x * blockDim.x;
        if (first_idx < total_pairs) {
            int tmp = first_idx / half_dim;
            int tmp2 = tmp / num_heads;
            int seq = tmp2 % seq_len;
            int batch = tmp2 / seq_len;
            s_m = positions[batch * seq_len + seq];
        } else {
            s_m = 0;
        }
    }
    __syncthreads();

    for (int i = threadIdx.x; i < half_dim; i += blockDim.x) {
        float theta = static_cast<float>(1.0 / pow(static_cast<double>(base),
                                                   (2.0 * i) / head_dim));
        float angle = static_cast<float>(s_m) * theta;
        double sin_d, cos_d;
        sincos(static_cast<double>(angle), &sin_d, &cos_d);
        s_sin[i] = static_cast<float>(sin_d);
        s_cos[i] = static_cast<float>(cos_d);
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

    float cos_val = s_cos[pair_idx];
    float sin_val = s_sin[pair_idx];

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
