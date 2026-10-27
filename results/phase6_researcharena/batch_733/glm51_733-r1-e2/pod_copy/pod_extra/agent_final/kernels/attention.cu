#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>
#include <float.h>

template <typename scalar_t>
__global__ void attention_kernel(
    const scalar_t* __restrict__ Q,
    const scalar_t* __restrict__ K,
    const scalar_t* __restrict__ V,
    scalar_t* __restrict__ output,
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
    int lane = tid & 31;
    int warp_id = tid >> 5;
    int num_warps = (bdim + 31) >> 5;

    for (int d = tid; d < head_dim; d += bdim) {
        s_q[d] = static_cast<float>(Q[base_q + d]);
    }
    __syncthreads();

    // Warp-cooperative dot product: each warp computes one score per iteration
    float local_max = -FLT_MAX;

    for (int j_base = 0; j_base < kv_len; j_base += num_warps) {
        int j = j_base + warp_id;
        if (j < kv_len) {
            if (causal && j > full_q_pos) {
                if (lane == 0) scores[j] = -FLT_MAX;
            } else {
                float dot = 0.0f;
                int base_k = base_kv + j * head_dim;
                #pragma unroll
                for (int d = lane; d < head_dim; d += 32) {
                    dot += s_q[d] * static_cast<float>(__ldg(&K[base_k + d]));
                }
                for (int offset = 16; offset > 0; offset >>= 1)
                    dot += __shfl_down_sync(0xffffffff, dot, offset);
                if (lane == 0) {
                    float s = dot * scale;
                    scores[j] = s;
                    local_max = fmaxf(local_max, s);
                }
            }
        }
    }

    // Inter-warp max reduction
    __shared__ float warp_reduce[32];

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

    // Exp and local sum
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

    // Weighted sum of V - already well-coalesced, just add unroll hint
    for (int d = tid; d < head_dim; d += bdim) {
        float acc = 0.0f;
        #pragma unroll 4
        for (int j = 0; j < kv_len; j++) {
            acc += scores[j] * static_cast<float>(__ldg(&V[base_kv + j * head_dim + d]));
        }
        output[base_q + d] = static_cast<scalar_t>(acc);
    }
}

torch::Tensor agent_attention(
    torch::Tensor Q,
    torch::Tensor K,
    torch::Tensor V,
    bool causal
) {
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
    cudaError_t err = cudaGetLastError();
    TORCH_CHECK(err == cudaSuccess, "attention kernel launch failed: ", cudaGetErrorString(err));

    return output;
}
