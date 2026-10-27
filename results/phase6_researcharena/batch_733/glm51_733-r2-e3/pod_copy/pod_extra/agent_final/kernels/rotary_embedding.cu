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
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    int half_dim = head_dim / 2;
    bool valid = (idx < total_pairs);

    __shared__ float s_inv_freq[32];
    __shared__ float s_cos[32];
    __shared__ float s_sin[32];
    __shared__ int s_ref_pos;

    if (threadIdx.x == 0) {
        float ratio = static_cast<float>(1.0 / pow(static_cast<double>(base),
                                                    2.0 / head_dim));
        s_inv_freq[0] = 1.0f;
        #pragma unroll
        for (int i = 1; i < half_dim; i++) {
            s_inv_freq[i] = s_inv_freq[i - 1] * ratio;
        }
    }
    __syncthreads();

    int pair_idx = 0, head = 0, seq = 0, batch = 0, m = 0;
    if (valid) {
        pair_idx = idx % half_dim;
        int tmp = idx / half_dim;
        head = tmp % num_heads;
        int tmp2 = tmp / num_heads;
        seq = tmp2 % seq_len;
        batch = tmp2 / seq_len;
        m = positions[batch * seq_len + seq];
    }

    if (threadIdx.x == 0) s_ref_pos = m;
    __syncthreads();

    if (threadIdx.x < half_dim) {
        float theta = s_inv_freq[threadIdx.x];
        float angle = static_cast<float>(s_ref_pos) * theta;
        double sin_d, cos_d;
        sincos(static_cast<double>(angle), &sin_d, &cos_d);
        s_cos[threadIdx.x] = static_cast<float>(cos_d);
        s_sin[threadIdx.x] = static_cast<float>(sin_d);
    }
    __syncthreads();

    if (!valid) return;

    float cos_val, sin_val;
    if (m == s_ref_pos) {
        cos_val = s_cos[pair_idx];
        sin_val = s_sin[pair_idx];
    } else {
        float theta = s_inv_freq[pair_idx];
        float angle = static_cast<float>(m) * theta;
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
