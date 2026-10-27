/*
 * Rotary Positional Embedding (RoPE) CUDA kernel — optimized implementation
 *
 * Applies rotary embeddings to query and key tensors.
 * For each pair (x_i, x_{i+d/2}), rotates by angle m * theta_i where:
 *   theta_i = 1 / (base^(2i/d))
 *   m = position index
 *
 * Optimization: sin/cos computed once per (batch, seq) position and shared
 * across all heads via shared memory, eliminating redundant pow+sincos calls.
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

template <typename scalar_t>
__global__ __launch_bounds__(512)
void rotary_embedding_kernel(
    scalar_t* __restrict__ x,
    const int* __restrict__ positions,
    int seq_len,
    int num_heads,
    int head_dim,
    float base,
    int half_dim
) {
    int bs_idx = blockIdx.x;
    int batch = bs_idx / seq_len;
    int seq = bs_idx % seq_len;
    int tid = threadIdx.x;
    int bdim = blockDim.x;

    extern __shared__ float smem[];
    float* s_cos = smem;
    float* s_sin = smem + half_dim;

    int m = positions[batch * seq_len + seq];

    for (int i = tid; i < half_dim; i += bdim) {
        float theta = static_cast<float>(1.0 / pow(static_cast<double>(base),
                                                    (2.0 * i) / head_dim));
        float angle = static_cast<float>(m) * theta;
        double sin_d, cos_d;
        sincos(static_cast<double>(angle), &sin_d, &cos_d);
        s_cos[i] = static_cast<float>(cos_d);
        s_sin[i] = static_cast<float>(sin_d);
    }
    __syncthreads();

    int total_pairs = num_heads * half_dim;
    for (int idx = tid; idx < total_pairs; idx += bdim) {
        int pair_idx = idx % half_dim;
        int head = idx / half_dim;

        int base_idx = ((batch * seq_len + seq) * num_heads + head) * head_dim;
        int i0 = base_idx + pair_idx;
        int i1 = base_idx + pair_idx + half_dim;

        float x0 = static_cast<float>(x[i0]);
        float x1 = static_cast<float>(x[i1]);
        float cos_val = s_cos[pair_idx];
        float sin_val = s_sin[pair_idx];

        x[i0] = static_cast<scalar_t>(x0 * cos_val - x1 * sin_val);
        x[i1] = static_cast<scalar_t>(x1 * cos_val + x0 * sin_val);
    }
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

    int total_pairs_per_bs = num_heads * half_dim;
    int threads = min(max(total_pairs_per_bs, half_dim), 512);
    threads = ((threads + 31) / 32) * 32;
    int blocks = batch * seq_len;
    size_t smem_size = 2 * half_dim * sizeof(float);

    if (blocks == 0) return output;

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        x.scalar_type(), "rotary_embedding", [&] {
            rotary_embedding_kernel<scalar_t><<<blocks, threads, smem_size>>>(
                output.data_ptr<scalar_t>(),
                positions.data_ptr<int>(),
                seq_len, num_heads, head_dim,
                static_cast<float>(base),
                half_dim
            );
        }
    );

    return output;
}
