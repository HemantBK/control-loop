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
    int num_bs = total_pairs / (num_heads * half_dim);
    int bs_idx = blockIdx.x;
    if (bs_idx >= num_bs) return;

    int batch = bs_idx / seq_len;
    int seq = bs_idx % seq_len;
    int m = positions[batch * seq_len + seq];

    extern __shared__ float smem[];
    float* s_cos = smem;
    float* s_sin = smem + half_dim;

    float neg_log_base = -__logf(base);
    for (int pi = threadIdx.x; pi < half_dim; pi += blockDim.x) {
        float theta = __expf(neg_log_base * (2.0f * pi) / (float)head_dim);
        float angle = static_cast<float>(m) * theta;
        float sin_val, cos_val;
        sincosf(angle, &sin_val, &cos_val);
        s_cos[pi] = cos_val;
        s_sin[pi] = sin_val;
    }
    __syncthreads();

    int total_elements = num_heads * half_dim;
    for (int idx = threadIdx.x; idx < total_elements; idx += blockDim.x) {
        int pair_idx = idx % half_dim;
        int head = idx / half_dim;

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
    int num_bs = batch * seq_len;
    if (num_bs == 0) return output;

    int total_per_bs = num_heads * half_dim;
    int threads = min(max(total_per_bs, half_dim), 256);
    threads = ((threads + 31) / 32) * 32;
    int blocks = num_bs;
    size_t smem_size = 2 * half_dim * sizeof(float);

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
