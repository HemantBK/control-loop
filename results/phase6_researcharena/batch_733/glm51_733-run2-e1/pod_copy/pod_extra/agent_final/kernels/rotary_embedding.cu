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
    int total_positions
) {
    int pos_idx = blockIdx.x;
    if (pos_idx >= total_positions) return;

    int half_dim = head_dim / 2;
    int batch = pos_idx / seq_len;
    int seq = pos_idx % seq_len;

    __shared__ float s_cos[64];
    __shared__ float s_sin[64];

    int m = positions[pos_idx];

    for (int pi = threadIdx.x; pi < half_dim; pi += blockDim.x) {
        float theta = static_cast<float>(1.0 / pow(static_cast<double>(base),
                                                   (2.0 * pi) / head_dim));
        float angle = static_cast<float>(m) * theta;
        double sin_d, cos_d;
        sincos(static_cast<double>(angle), &sin_d, &cos_d);
        s_cos[pi] = static_cast<float>(cos_d);
        s_sin[pi] = static_cast<float>(sin_d);
    }
    __syncthreads();

    int total_pairs = num_heads * half_dim;
    for (int idx = threadIdx.x; idx < total_pairs; idx += blockDim.x) {
        int pair_idx = idx % half_dim;
        int head = idx / half_dim;

        int base_idx = ((batch * seq_len + seq) * num_heads + head) * head_dim;
        int i0 = base_idx + pair_idx;
        int i1 = base_idx + pair_idx + half_dim;

        float x0 = static_cast<float>(x[i0]);
        float x1 = static_cast<float>(x[i1]);

        x[i0] = static_cast<scalar_t>(x0 * s_cos[pair_idx] - x1 * s_sin[pair_idx]);
        x[i1] = static_cast<scalar_t>(x1 * s_cos[pair_idx] + x0 * s_sin[pair_idx]);
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

    int total_positions = batch * seq_len;
    if (total_positions == 0) return output;

    int threads = 256;

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        x.scalar_type(), "rotary_embedding", [&] {
            rotary_embedding_kernel<scalar_t><<<total_positions, threads>>>(
                output.data_ptr<scalar_t>(),
                positions.data_ptr<int>(),
                seq_len, num_heads, head_dim,
                static_cast<float>(base),
                total_positions
            );
        }
    );

    return output;
}
