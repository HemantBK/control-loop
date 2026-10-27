/*
 * Rotary Positional Embedding (RoPE) CUDA kernel — optimized implementation
 *
 * Applies rotary embeddings to query and key tensors.
 * For each pair (x_i, x_{i+d/2}), rotates by angle m * theta_i where:
 *   theta_i = 1 / (base^(2i/d))
 *   m = position index
 *
 * Optimizations over baseline:
 * - Precomputed freqs cached on GPU (eliminates per-thread pow())
 * - Out-of-place kernel with empty_like (eliminates clone/memcpy overhead)
 * - Shared memory for freqs (reduces global memory reads)
 * - __launch_bounds__ for better register allocation
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>
#include <utility>

template <typename scalar_t>
__global__ __launch_bounds__(256)
void rotary_embedding_kernel(
    const scalar_t* __restrict__ x,
    scalar_t* __restrict__ out,
    const int* __restrict__ positions,
    const float* __restrict__ freqs,
    int seq_len,
    int num_heads,
    int head_dim,
    int total_pairs
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= total_pairs) return;
    int half_dim = head_dim / 2;

    __shared__ float sm_freq[64];
    if (threadIdx.x < half_dim) {
        sm_freq[threadIdx.x] = freqs[threadIdx.x];
    }
    __syncthreads();

    int pair_idx = idx % half_dim;
    int tmp = idx / half_dim;
    int head = tmp % num_heads;
    int tmp2 = tmp / num_heads;
    int seq = tmp2 % seq_len;
    int batch = tmp2 / seq_len;

    float theta = sm_freq[pair_idx];
    int m = positions[batch * seq_len + seq];
    float angle = static_cast<float>(m) * theta;
    double sin_d, cos_d;
    sincos(static_cast<double>(angle), &sin_d, &cos_d);
    float cos_val = static_cast<float>(cos_d);
    float sin_val = static_cast<float>(sin_d);

    int base_idx = ((batch * seq_len + seq) * num_heads + head) * head_dim;
    int i0 = base_idx + pair_idx;
    int i1 = base_idx + pair_idx + half_dim;

    float x0 = static_cast<float>(x[i0]);
    float x1 = static_cast<float>(x[i1]);

    out[i0] = static_cast<scalar_t>(x0 * cos_val - x1 * sin_val);
    out[i1] = static_cast<scalar_t>(x1 * cos_val + x0 * sin_val);
}

torch::Tensor agent_rotary_embedding(
    torch::Tensor x,
    torch::Tensor positions,
    double base
) {
    int batch = x.size(0);
    int seq_len = x.size(1);
    int num_heads = x.size(2);
    int head_dim = x.size(3);
    int half_dim = head_dim / 2;

    static std::pair<int, double> cache_key{-1, 0.0};
    static torch::Tensor cached_freqs;

    if (cache_key.first != head_dim || cache_key.second != base ||
        !cached_freqs.defined() || cached_freqs.device() != x.device()) {
        auto freqs_cpu = torch::empty({half_dim}, torch::kFloat32);
        auto acc = freqs_cpu.accessor<float, 1>();
        for (int i = 0; i < half_dim; i++) {
            acc[i] = static_cast<float>(1.0 / pow(base, 2.0 * i / head_dim));
        }
        cached_freqs = freqs_cpu.to(x.device());
        cache_key = {head_dim, base};
    }

    auto output = torch::empty_like(x);
    if (x.numel() == 0) return output;

    int total_pairs = batch * seq_len * num_heads * half_dim;
    int threads = 256;
    int blocks = (total_pairs + threads - 1) / threads;

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        x.scalar_type(), "rotary_embedding", [&] {
            rotary_embedding_kernel<scalar_t><<<blocks, threads>>>(
                x.data_ptr<scalar_t>(),
                output.data_ptr<scalar_t>(),
                positions.data_ptr<int>(),
                cached_freqs.data_ptr<float>(),
                seq_len, num_heads, head_dim,
                total_pairs
            );
        }
    );

    return output;
}
