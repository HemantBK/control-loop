/*
 * Rotary Positional Embedding (RoPE) CUDA kernel — optimized
 *
 * Optimizations:
 * - __sincosf for combined sin/cos (1 instruction vs 2)
 * - __fdividef for fast division
 * - __expf + __logf for fast pow replacement
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>
#include <limits>

template <typename scalar_t>
__global__ void rotary_embedding_kernel(
    scalar_t* __restrict__ x,          // [batch, seq_len, num_heads, head_dim]
    const int* __restrict__ positions,  // [batch, seq_len]
    int seq_len,
    int num_heads,
    int head_dim,
    float base,
    int total_pairs             // PATCH(rope_bounds): number of valid (batch, seq, head, pair) work items
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= total_pairs) return;   // PATCH(rope_bounds): the last block is partial whenever total_pairs % 256 != 0
    int half_dim = head_dim / 2;

    int pair_idx = idx % half_dim;
    int tmp = idx / half_dim;
    int head = tmp % num_heads;
    int tmp2 = tmp / num_heads;
    int seq = tmp2 % seq_len;
    int batch = tmp2 / seq_len;

    int m = positions[batch * seq_len + seq];
    // Fast pow: base^(2*pair_idx/head_dim) = exp(log(base) * 2*pair_idx/head_dim)
    float exp_val = __expf(__logf(base) * __fdividef(2.0f * pair_idx, (float)head_dim));
    float theta = __fdividef(1.0f, exp_val);
    float angle = m * theta;

    float cos_val, sin_val;
    __sincosf(angle, &sin_val, &cos_val);

    int base_idx = ((batch * seq_len + seq) * num_heads + head) * head_dim;
    int i0 = base_idx + 2 * pair_idx;
    int i1 = i0 + 1;

    float x0 = static_cast<float>(x[i0]);
    float x1 = static_cast<float>(x[i1]);

    x[i0] = static_cast<scalar_t>(x0 * cos_val - x1 * sin_val);
    x[i1] = static_cast<scalar_t>(x0 * sin_val + x1 * cos_val);
}

// ─── Host wrapper ────────────────────────────────────────────────────────────

torch::Tensor agent_rotary_embedding(
    torch::Tensor x,          // [batch, seq_len, num_heads, head_dim]
    torch::Tensor positions,   // [batch, seq_len] int32
    double base
) {
    // PATCH(rope_bounds): the kernel indexes a dense [batch, seq_len, num_heads, head_dim] buffer, so make the
    // copy it works on contiguous whatever the caller's strides are, and make the positions buffer dense int32.
    TORCH_CHECK(x.dim() == 4, "rotary_embedding: x must be [batch, seq_len, num_heads, head_dim], got dim ", x.dim());
    TORCH_CHECK(x.is_cuda(), "rotary_embedding: x must be a CUDA tensor");
    TORCH_CHECK(positions.scalar_type() == torch::kInt32, "rotary_embedding: positions must be int32, got ",
                positions.scalar_type());
    TORCH_CHECK(positions.device() == x.device(), "rotary_embedding: positions must be on x's device");
    auto output = x.clone(at::MemoryFormat::Contiguous);
    auto pos = positions.contiguous();
    int batch = x.size(0);
    int seq_len = x.size(1);
    int num_heads = x.size(2);
    int head_dim = x.size(3);
    int half_dim = head_dim / 2;
    TORCH_CHECK(head_dim % 2 == 0, "rotary_embedding: head_dim must be even, got ", head_dim);
    TORCH_CHECK(pos.numel() >= static_cast<int64_t>(batch) * seq_len,
                "rotary_embedding: positions has ", pos.numel(), " elements, need batch*seq_len = ",
                static_cast<int64_t>(batch) * seq_len);
    int64_t total_pairs_64 = static_cast<int64_t>(batch) * seq_len * num_heads * half_dim;
    TORCH_CHECK(total_pairs_64 <= std::numeric_limits<int>::max(), "rotary_embedding: tensor too large for int indexing");
    int total_pairs = static_cast<int>(total_pairs_64);
    if (total_pairs == 0) return output;
    int threads = 256;
    int blocks = (total_pairs + threads - 1) / threads;

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        x.scalar_type(), "rotary_embedding", [&] {
            rotary_embedding_kernel<scalar_t><<<blocks, threads>>>(
                output.data_ptr<scalar_t>(),
                pos.data_ptr<int>(),
                seq_len, num_heads, head_dim,
                static_cast<float>(base),
                total_pairs
            );
        }
    );
    // PATCH(rope_bounds): surface launch errors here instead of at the next PyTorch op (asynchronous; no sync added)
    cudaError_t err = cudaGetLastError();
    TORCH_CHECK(err == cudaSuccess, "rotary_embedding kernel launch failed: ", cudaGetErrorString(err));

    return output;
}
