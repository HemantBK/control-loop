/*
 * Fused Attention CUDA kernel — optimized implementation
 *
 * Computes: output = softmax(Q @ K^T / sqrt(d)) @ V
 * with causal masking support.
 *
 * Optimizations over baseline:
 * - Parallel warp+block reductions instead of serial thread-0 loops
 * - Vectorized dot products where possible
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>
#include <float.h>

template <typename scalar_t>
__global__ __launch_bounds__(256)
void attention_kernel(
    const scalar_t* __restrict__ Q,    // [B, H, N_q, D]
    const scalar_t* __restrict__ K,    // [B, H, N_kv, D]
    const scalar_t* __restrict__ V,    // [B, H, N_kv, D]
    scalar_t* __restrict__ output,     // [B, H, N_q, D]
    int q_len,
    int kv_len,
    int head_dim,
    int num_kv_heads,
    float scale,
    bool causal
) {
    int b = blockIdx.x;
    int h = blockIdx.y;
    int q_pos = blockIdx.z;

    int num_heads = gridDim.y;
    int q_BH_stride = q_len * head_dim;
    int kv_BH_stride = kv_len * head_dim;
    int base_q = (b * num_heads + h) * q_BH_stride + q_pos * head_dim;
    int kv_h = h / (num_heads / num_kv_heads);
    int base_kv = (b * num_kv_heads + kv_h) * kv_BH_stride;
    int full_q_pos = kv_len - q_len + q_pos;

    extern __shared__ float smem[];
    float* scores = smem;
    float* s_q = smem + kv_len;

    int tid = threadIdx.x;
    int bdim = blockDim.x;

    for (int d = tid; d < head_dim; d += bdim) {
        s_q[d] = static_cast<float>(Q[base_q + d]);
    }
    __syncthreads();

    float local_max = -FLT_MAX;
    for (int j = tid; j < kv_len; j += bdim) {
        if (causal && j > full_q_pos) {
            scores[j] = -FLT_MAX;
        } else {
            float dot = 0.0f;
            int base_k = base_kv + j * head_dim;
            const uint4* k4 = reinterpret_cast<const uint4*>(&K[base_k]);
            #pragma unroll
            for (int d8 = 0; d8 < head_dim / 8; d8++) {
                uint4 kv = __ldg(k4 + d8);
                const scalar_t* ks = reinterpret_cast<const scalar_t*>(&kv);
                dot += s_q[d8*8+0] * static_cast<float>(ks[0])
                     + s_q[d8*8+1] * static_cast<float>(ks[1])
                     + s_q[d8*8+2] * static_cast<float>(ks[2])
                     + s_q[d8*8+3] * static_cast<float>(ks[3])
                     + s_q[d8*8+4] * static_cast<float>(ks[4])
                     + s_q[d8*8+5] * static_cast<float>(ks[5])
                     + s_q[d8*8+6] * static_cast<float>(ks[6])
                     + s_q[d8*8+7] * static_cast<float>(ks[7]);
            }
            scores[j] = dot * scale;
        }
        local_max = fmaxf(local_max, scores[j]);
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        local_max = fmaxf(local_max, __shfl_down_sync(0xffffffff, local_max, offset));

    __shared__ float warp_reduce[32];
    int lane = tid & 31;
    int warp_id = tid >> 5;
    int num_warps = (bdim + 31) >> 5;

    if (lane == 0) warp_reduce[warp_id] = local_max;
    __syncthreads();

    float global_max;
    if (warp_id == 0) {
        float val = (lane < num_warps) ? warp_reduce[lane] : -FLT_MAX;
        for (int offset = warpSize / 2; offset > 0; offset >>= 1)
            val = fmaxf(val, __shfl_down_sync(0xffffffff, val, offset));
        if (lane == 0) warp_reduce[0] = val;
    }
    __syncthreads();
    global_max = warp_reduce[0];

    float local_sum = 0.0f;
    for (int j = tid; j < kv_len; j += bdim) {
        float e = expf(scores[j] - global_max);
        scores[j] = e;
        local_sum += e;
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        local_sum += __shfl_down_sync(0xffffffff, local_sum, offset);

    __syncthreads();
    if (lane == 0) warp_reduce[warp_id] = local_sum;
    __syncthreads();

    float global_sum;
    if (warp_id == 0) {
        float val = (lane < num_warps) ? warp_reduce[lane] : 0.0f;
        for (int offset = warpSize / 2; offset > 0; offset >>= 1)
            val += __shfl_down_sync(0xffffffff, val, offset);
        if (lane == 0) warp_reduce[0] = val;
    }
    __syncthreads();
    global_sum = warp_reduce[0];

    float inv_sum = 1.0f / global_sum;
    for (int j = tid; j < kv_len; j += bdim) {
        scores[j] *= inv_sum;
    }
    __syncthreads();

    for (int d = tid; d < head_dim; d += bdim) {
        float acc = 0.0f;
        for (int j = 0; j < kv_len; j++) {
            int base_v = base_kv + j * head_dim;
            acc += scores[j] * static_cast<float>(__ldg(&V[base_v + d]));
        }
        output[base_q + d] = static_cast<scalar_t>(acc);
    }
}

// ─── Host wrapper ────────────────────────────────────────────────────────────

torch::Tensor agent_attention(
    torch::Tensor Q,      // [batch, heads, q_len, head_dim]
    torch::Tensor K,      // [batch, heads, kv_len, head_dim]
    torch::Tensor V,      // [batch, heads, kv_len, head_dim]
    bool causal
) {
    // PATCH(attn_harden): the kernel indexes dense [B, H, N, D] buffers; refuse anything else instead of reading
    // past them. inject.py:120-122 already passes .contiguous() tensors; the checks cost nothing on the hot path.
    TORCH_CHECK(Q.dim() == 4 && K.dim() == 4 && V.dim() == 4, "attention: Q, K, V must be [batch, heads, len, head_dim]");
    TORCH_CHECK(Q.is_cuda() && K.is_cuda() && V.is_cuda(), "attention: Q, K, V must be CUDA tensors");
    TORCH_CHECK(Q.is_contiguous() && K.is_contiguous() && V.is_contiguous(), "attention: Q, K, V must be contiguous");
    TORCH_CHECK(Q.scalar_type() == K.scalar_type() && Q.scalar_type() == V.scalar_type(), "attention: dtype mismatch");
    int batch = Q.size(0);
    int heads = Q.size(1);
    int q_len = Q.size(2);
    int kv_len = K.size(2);
    int head_dim = Q.size(3);
    int kv_heads = K.size(1);
    TORCH_CHECK(K.size(0) == batch && V.size(0) == batch, "attention: batch mismatch");
    TORCH_CHECK(V.size(1) == kv_heads && V.size(2) == kv_len, "attention: K/V shape mismatch");
    TORCH_CHECK(K.size(3) == head_dim && V.size(3) == head_dim, "attention: head_dim mismatch");
    TORCH_CHECK(kv_heads > 0 && heads % kv_heads == 0, "attention: num heads must be a multiple of num kv heads");
    TORCH_CHECK(q_len <= kv_len, "attention: q_len must not exceed kv_len");

    float scale = 1.0f / sqrtf(static_cast<float>(head_dim));
    auto output = torch::empty_like(Q);
    if (batch == 0 || heads == 0 || q_len == 0) return output;

    dim3 grid(batch, heads, q_len);
    // PATCH(attn_harden): whole warps only: the reductions use full-mask __shfl_down_sync (lines 72, 87, 103, 112),
    // which is undefined for a partial warp (stock launched kv_len threads, e.g. 2 or 12 at prefill).
    int threads = min(((kv_len + 31) / 32) * 32, 256);
    size_t smem_size = (static_cast<size_t>(kv_len) + head_dim) * sizeof(float);
    TORCH_CHECK(smem_size <= 48 * 1024, "attention: kv_len ", kv_len, " needs ", smem_size,
                " bytes of dynamic shared memory, above the 48 KB default");

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        Q.scalar_type(), "attention", [&] {
            attention_kernel<scalar_t><<<grid, threads, smem_size>>>(
                Q.data_ptr<scalar_t>(),
                K.data_ptr<scalar_t>(),
                V.data_ptr<scalar_t>(),
                output.data_ptr<scalar_t>(),
                q_len, kv_len, head_dim, kv_heads, scale, causal
            );
        }
    );
    // PATCH(attn_harden): surface launch errors here (asynchronous; no sync added)
    cudaError_t err = cudaGetLastError();
    TORCH_CHECK(err == cudaSuccess, "attention kernel launch failed: ", cudaGetErrorString(err));

    return output;
}
