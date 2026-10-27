// Benchmark change 06 (Baseline B): upstream 11ea904's RoPE. It pairs x_i with x_{i+d/2} (split halves, as HF Llama's
// rotate_half), where the stock kernel paired adjacent elements, and it rotates by the real positions inject.py
// passes, where the stock wrapper restarted them at 0 on every decode step.
/*
 * Rotary Positional Embedding (RoPE) CUDA kernel — baseline implementation
 *
 * Applies rotary embeddings to query and key tensors.
 * For each pair (x_i, x_{i+d/2}), rotates by angle m * theta_i where:
 *   theta_i = 1 / (base^(2i/d))
 *   m = position index
 *
 * Used in LLaMA, Mistral, and most modern transformer models.
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

// ─── Kernel ──────────────────────────────────────────────────────────────────

template <typename scalar_t>
__global__ __launch_bounds__(1024)
void rotary_embedding_kernel(
    scalar_t* __restrict__ x,
    const int* __restrict__ positions,
    const float* __restrict__ inv_freq,
    int seq_len,
    int num_heads,
    int head_dim,
    int total_pairs
) {
    int half_dim = head_dim / 2;
    int bs = blockIdx.x;
    int m = positions[bs];

    __shared__ float s_cos[64];
    __shared__ float s_sin[64];

    for (int i = threadIdx.x; i < half_dim; i += blockDim.x) {
        float theta = inv_freq[i];
        float angle = static_cast<float>(m) * theta;
        double sin_d, cos_d;
        sincos(static_cast<double>(angle), &sin_d, &cos_d);
        s_cos[i] = static_cast<float>(cos_d);
        s_sin[i] = static_cast<float>(sin_d);
    }
    __syncthreads();

    int total = num_heads * half_dim;
    for (int tid = threadIdx.x; tid < total; tid += blockDim.x) {
        int pair_idx = tid % half_dim;
        int head = tid / half_dim;

        int base_idx = (bs * num_heads + head) * head_dim;
        int i0 = base_idx + pair_idx;
        int i1 = base_idx + pair_idx + half_dim;

        float cos_val = s_cos[pair_idx];
        float sin_val = s_sin[pair_idx];

        float x0 = static_cast<float>(x[i0]);
        float x1 = static_cast<float>(x[i1]);

        x[i0] = static_cast<scalar_t>(x0 * cos_val - x1 * sin_val);
        x[i1] = static_cast<scalar_t>(x1 * cos_val + x0 * sin_val);
    }
}

// ─── Host wrapper ────────────────────────────────────────────────────────────

torch::Tensor agent_rotary_embedding(
    torch::Tensor x,          // [batch, seq_len, num_heads, head_dim]
    torch::Tensor positions,   // [batch, seq_len] int32
    double base
) {
    int batch = x.size(0);
    int seq_len = x.size(1);
    int num_heads = x.size(2);
    int head_dim = x.size(3);
    int half_dim = head_dim / 2;

    static torch::Tensor inv_freq;
    static int cached_half_dim = 0;
    static double cached_base = 0.0;
    static int cached_device = -1;

    int cur_device = x.device().index();
    if (half_dim != cached_half_dim || base != cached_base || cur_device != cached_device) {
        auto inv_freq_cpu = torch::empty({half_dim}, torch::kFloat32);
        for (int i = 0; i < half_dim; i++) {
            inv_freq_cpu[i] = static_cast<float>(1.0 / pow(base, 2.0 * i / head_dim));
        }
        inv_freq = inv_freq_cpu.to(x.device());
        cached_half_dim = half_dim;
        cached_base = base;
        cached_device = cur_device;
    }

    int total_pairs = batch * seq_len * num_heads * half_dim;
    int blocks = batch * seq_len;
    int threads = min(max(num_heads * half_dim, half_dim), 1024);
    threads = max(((threads + 31) / 32) * 32, half_dim);

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        x.scalar_type(), "rotary_embedding", [&] {
            rotary_embedding_kernel<scalar_t><<<blocks, threads>>>(
                x.data_ptr<scalar_t>(),
                positions.data_ptr<int>(),
                inv_freq.data_ptr<float>(),
                seq_len, num_heads, head_dim,
                total_pairs
            );
        }
    );

    return x;
}
