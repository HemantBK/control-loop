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
    float base
) {
    int half_dim = head_dim / 2;
    int bs_idx = blockIdx.x;

    extern __shared__ float smem[];
    float* s_cos = smem;
    float* s_sin = smem + half_dim;

    int m = positions[bs_idx];
    if (threadIdx.x < half_dim) {
        float theta = static_cast<float>(1.0 / pow(static_cast<double>(base),
                                                    (2.0 * threadIdx.x) / head_dim));
        float angle = static_cast<float>(m) * theta;
        double sin_d, cos_d;
        sincos(static_cast<double>(angle), &sin_d, &cos_d);
        s_cos[threadIdx.x] = static_cast<float>(cos_d);
        s_sin[threadIdx.x] = static_cast<float>(sin_d);
    }
    __syncthreads();

    int total_per_pos = num_heads * half_dim;
    for (int i = threadIdx.x; i < total_per_pos; i += blockDim.x) {
        int pair_idx = i % half_dim;
        int head = i / half_dim;

        int base_idx = (bs_idx * num_heads + head) * head_dim;
        int i0 = base_idx + pair_idx;
        int i1 = base_idx + pair_idx + half_dim;

        float x0 = static_cast<float>(x[i0]);
        float x1 = static_cast<float>(x[i1]);

        x[i0] = static_cast<scalar_t>(x0 * s_cos[pair_idx] - x1 * s_sin[pair_idx]);
        x[i1] = static_cast<scalar_t>(x1 * s_cos[pair_idx] + x0 * s_sin[pair_idx]);
    }
}

torch::Tensor agent_rotary_embedding(
    torch::Tensor x,          // [batch, seq_len, num_heads, head_dim]
    torch::Tensor positions,   // [batch, seq_len] int32
    double base
) {
    auto output = x;
    int batch = x.size(0);
    int seq_len = x.size(1);
    int num_heads = x.size(2);
    int head_dim = x.size(3);
    int half_dim = head_dim / 2;

    int num_positions = batch * seq_len;
    int total_per_pos = num_heads * half_dim;
    int threads = min(total_per_pos, 256);
    threads = max(((threads + 31) / 32) * 32, 32);
    size_t smem_size = 2 * half_dim * sizeof(float);

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        x.scalar_type(), "rotary_embedding", [&] {
            rotary_embedding_kernel<scalar_t><<<num_positions, threads, smem_size>>>(
                output.data_ptr<scalar_t>(),
                positions.data_ptr<int>(),
                seq_len, num_heads, head_dim,
                static_cast<float>(base)
            );
        }
    );

    return output;
}
