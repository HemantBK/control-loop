/*
 * Fused Attention CUDA kernel — optimized implementation
 *
 * Computes: output = softmax(Q @ K^T / sqrt(d)) @ V
 * with causal masking support.
 *
 * Optimizations:
 * - Template on HEAD_DIM for compile-time loop unrolling
 * - Vectorized uint4 loads for K rows
 * - ILP (2 rows per iteration) for K dot products
 * - Parallel V weighted sum across all threads (grouped approach)
 * - ILP for V weighted sum
 * - Fused normalization into V weighted sum
 * - Warp+block reductions for softmax
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>
#include <float.h>

template <typename scalar_t, int HEAD_DIM>
__global__ __launch_bounds__(512, 2)
void attention_kernel(
    const scalar_t* __restrict__ Q,
    const scalar_t* __restrict__ K,
    const scalar_t* __restrict__ V,
    scalar_t* __restrict__ output,
    int q_len,
    int kv_len,
    int num_kv_heads,
    float scale,
    bool causal
) {
    constexpr int VEC_ITERS = HEAD_DIM / 8;

    int b = blockIdx.x;
    int h = blockIdx.y;
    int q_pos = blockIdx.z;

    int num_heads = gridDim.y;
    int q_BH_stride = q_len * HEAD_DIM;
    int kv_BH_stride = kv_len * HEAD_DIM;
    int base_q = (b * num_heads + h) * q_BH_stride + q_pos * HEAD_DIM;
    int kv_h = h / (num_heads / num_kv_heads);
    int base_kv = (b * num_kv_heads + kv_h) * kv_BH_stride;
    int full_q_pos = kv_len - q_len + q_pos;

    int tid = threadIdx.x;
    int bdim = blockDim.x;

    extern __shared__ float smem[];
    float* scores = smem;
    float* s_q = smem + kv_len;
    float* v_partial = smem + kv_len + HEAD_DIM;
    float* warp_reduce = smem + kv_len + HEAD_DIM + bdim;

    for (int d = tid; d < HEAD_DIM; d += bdim) {
        s_q[d] = static_cast<float>(Q[base_q + d]);
    }
    __syncthreads();

    float local_max = -FLT_MAX;
    int j = tid;
    for (; j + bdim < kv_len; j += bdim * 2) {
        int j2 = j + bdim;
        float dot1 = 0.0f, dot2 = 0.0f;
        const uint4* K_vec1 = reinterpret_cast<const uint4*>(K + base_kv + j * HEAD_DIM);
        const uint4* K_vec2 = reinterpret_cast<const uint4*>(K + base_kv + j2 * HEAD_DIM);
        #pragma unroll
        for (int v = 0; v < VEC_ITERS; v++) {
            uint4 kv1 = __ldg(K_vec1 + v);
            uint4 kv2 = __ldg(K_vec2 + v);
            const scalar_t* kh1 = reinterpret_cast<const scalar_t*>(&kv1);
            const scalar_t* kh2 = reinterpret_cast<const scalar_t*>(&kv2);
            #pragma unroll
            for (int e = 0; e < 8; e++) {
                dot1 += s_q[v * 8 + e] * static_cast<float>(kh1[e]);
                dot2 += s_q[v * 8 + e] * static_cast<float>(kh2[e]);
            }
        }
        float score1 = (causal && j > full_q_pos) ? -FLT_MAX : dot1 * scale;
        float score2 = (causal && j2 > full_q_pos) ? -FLT_MAX : dot2 * scale;
        scores[j] = score1;
        scores[j2] = score2;
        local_max = fmaxf(local_max, fmaxf(score1, score2));
    }
    for (; j < kv_len; j += bdim) {
        if (causal && j > full_q_pos) {
            scores[j] = -FLT_MAX;
        } else {
            float dot = 0.0f;
            int base_k = base_kv + j * HEAD_DIM;
            const uint4* K_vec = reinterpret_cast<const uint4*>(K + base_k);
            #pragma unroll
            for (int v = 0; v < VEC_ITERS; v++) {
                uint4 kv = __ldg(K_vec + v);
                const scalar_t* kh = reinterpret_cast<const scalar_t*>(&kv);
                #pragma unroll
                for (int e = 0; e < 8; e++) {
                    dot += s_q[v * 8 + e] * static_cast<float>(kh[e]);
                }
            }
            scores[j] = dot * scale;
        }
        local_max = fmaxf(local_max, scores[j]);
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        local_max = fmaxf(local_max, __shfl_down_sync(0xffffffff, local_max, offset));

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
    {
        int j = tid;
        for (; j + bdim < kv_len; j += bdim * 2) {
            float e1 = expf(scores[j] - global_max);
            float e2 = expf(scores[j + bdim] - global_max);
            scores[j] = e1;
            scores[j + bdim] = e2;
            local_sum += e1 + e2;
        }
        for (; j < kv_len; j += bdim) {
            float e = expf(scores[j] - global_max);
            scores[j] = e;
            local_sum += e;
        }
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

    int num_groups = bdim / HEAD_DIM;

    if (num_groups >= 1) {
        int my_d = tid % HEAD_DIM;
        int my_group = tid / HEAD_DIM;

        float my_acc = 0.0f;
        int j = my_group;
        for (; j + num_groups < kv_len; j += num_groups * 2) {
            int j2 = j + num_groups;
            int base_v1 = base_kv + j * HEAD_DIM;
            int base_v2 = base_kv + j2 * HEAD_DIM;
            float s1 = scores[j] * inv_sum;
            float s2 = scores[j2] * inv_sum;
            my_acc += s1 * static_cast<float>(__ldg(&V[base_v1 + my_d]))
                    + s2 * static_cast<float>(__ldg(&V[base_v2 + my_d]));
        }
        for (; j < kv_len; j += num_groups) {
            int base_v = base_kv + j * HEAD_DIM;
            my_acc += scores[j] * inv_sum * static_cast<float>(__ldg(&V[base_v + my_d]));
        }

        v_partial[tid] = my_acc;
        __syncthreads();

        if (my_group == 0) {
            float total = v_partial[my_d];
            for (int g = 1; g < num_groups; g++) {
                total += v_partial[my_d + g * HEAD_DIM];
            }
            output[base_q + my_d] = static_cast<scalar_t>(total);
        }
    } else {
        for (int d = tid; d < HEAD_DIM; d += bdim) {
            float acc = 0.0f;
            for (int j = 0; j < kv_len; j++) {
                int base_v = base_kv + j * HEAD_DIM;
                acc += scores[j] * inv_sum * static_cast<float>(__ldg(&V[base_v + d]));
            }
            output[base_q + d] = static_cast<scalar_t>(acc);
        }
    }
}

// ─── Host wrapper ────────────────────────────────────────────────────────────

torch::Tensor agent_attention(
    torch::Tensor Q,      // [batch, heads, q_len, head_dim]
    torch::Tensor K,      // [batch, heads, kv_len, head_dim]
    torch::Tensor V,      // [batch, heads, kv_len, head_dim]
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
    int threads = min(max(((kv_len + 31) / 32) * 32, head_dim * 4), 512);
    size_t smem_size = (static_cast<size_t>(kv_len) + head_dim + threads + 32) * sizeof(float);
    TORCH_CHECK(smem_size <= 48 * 1024, "attention: kv_len ", kv_len, " needs ", smem_size,
                " bytes of dynamic shared memory, above the 48 KB default");

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        Q.scalar_type(), "attention", [&] {
            if (head_dim == 64) {
                attention_kernel<scalar_t, 64><<<grid, threads, smem_size>>>(
                    Q.data_ptr<scalar_t>(),
                    K.data_ptr<scalar_t>(),
                    V.data_ptr<scalar_t>(),
                    output.data_ptr<scalar_t>(),
                    q_len, kv_len, kv_heads, scale, causal
                );
            } else if (head_dim == 128) {
                attention_kernel<scalar_t, 128><<<grid, threads, smem_size>>>(
                    Q.data_ptr<scalar_t>(),
                    K.data_ptr<scalar_t>(),
                    V.data_ptr<scalar_t>(),
                    output.data_ptr<scalar_t>(),
                    q_len, kv_len, kv_heads, scale, causal
                );
            } else {
                TORCH_CHECK(false, "attention: unsupported head_dim ", head_dim);
            }
        }
    );
    cudaError_t err = cudaGetLastError();
    TORCH_CHECK(err == cudaSuccess, "attention kernel launch failed: ", cudaGetErrorString(err));

    return output;
}
