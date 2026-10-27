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
    int total_pairs,
    int precompute_sincos,
    int num_positions
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    int half_dim = head_dim / 2;

    extern __shared__ float smem[];
    float* s_theta = smem;
    float* s_sincos = s_theta + half_dim;

    for (int i = threadIdx.x; i < half_dim; i += blockDim.x) {
        s_theta[i] = static_cast<float>(1.0 / pow(static_cast<double>(base),
                                                    (2.0 * i) / head_dim));
    }

    if (precompute_sincos) {
        int num_sc = num_positions * half_dim;
        for (int i = threadIdx.x; i < num_sc; i += blockDim.x) {
            int pos_idx = i / half_dim;
            int pair = i % half_dim;
            int m = __ldg(&positions[pos_idx]);
            float angle = static_cast<float>(m) * s_theta[pair];
            double sin_d, cos_d;
            sincos(static_cast<double>(angle), &sin_d, &cos_d);
            s_sincos[i * 2] = static_cast<float>(cos_d);
            s_sincos[i * 2 + 1] = static_cast<float>(sin_d);
        }
    }
    __syncthreads();

    if (idx >= total_pairs) return;

    int pair_idx = idx % half_dim;
    int tmp = idx / half_dim;
    int head = tmp % num_heads;
    int tmp2 = tmp / num_heads;
    int seq = tmp2 % seq_len;
    int batch = tmp2 / seq_len;

    float cos_val, sin_val;
    if (precompute_sincos) {
        int sc_idx = (batch * seq_len + seq) * half_dim + pair_idx;
        cos_val = s_sincos[sc_idx * 2];
        sin_val = s_sincos[sc_idx * 2 + 1];
    } else {
        int m = __ldg(&positions[batch * seq_len + seq]);
        float angle = static_cast<float>(m) * s_theta[pair_idx];
        double sin_d, cos_d;
        sincos(static_cast<double>(angle), &sin_d, &cos_d);
        cos_val = static_cast<float>(cos_d);
        sin_val = static_cast<float>(sin_d);
    }

    int base_idx = ((batch * seq_len + seq) * num_heads + head) * head_dim;
    int i0 = base_idx + pair_idx;
    int i1 = base_idx + pair_idx + half_dim;

    float x0 = static_cast<float>(__ldg(&x[i0]));
    float x1 = static_cast<float>(__ldg(&x[i1]));

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

    int num_positions = batch * seq_len;
    int precompute_sincos = 0;
    size_t smem_size = half_dim * sizeof(float);
    size_t sincos_smem = (size_t)num_positions * half_dim * 2 * sizeof(float);
    if (smem_size + sincos_smem <= 46 * 1024) {
        precompute_sincos = 1;
        smem_size += sincos_smem;
    }

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        x.scalar_type(), "rotary_embedding", [&] {
            rotary_embedding_kernel<scalar_t><<<blocks, threads, smem_size>>>(
                output.data_ptr<scalar_t>(),
                positions.data_ptr<int>(),
                seq_len, num_heads, head_dim,
                static_cast<float>(base),
                total_pairs,
                precompute_sincos,
                num_positions
            );
        }
    );

    return output;
}
