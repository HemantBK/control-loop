/*
 * RMSNorm CUDA kernel — optimized implementation
 *
 * Computes: output = (x / rms(x)) * weight
 * where rms(x) = sqrt(mean(x^2) + eps)
 *
 * Optimizations:
 * - Register caching: input values cached during sum-of-squares, reused in
 *   normalization, eliminating a second global load of the input tensor.
 * - 512 threads (vs 1024): fewer warps to reduce, better ILP per thread.
 * - Vectorized half2 loads/stores for fp16/bf16 (2 elements per instruction).
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>
#include <type_traits>

template <typename scalar_t>
__global__ __launch_bounds__(512)
void rmsnorm_kernel(
    const scalar_t* __restrict__ input,
    const scalar_t* __restrict__ weight,
    scalar_t* __restrict__ output,
    int hidden_size,
    float eps
) {
    constexpr bool is_half = std::is_same<scalar_t, at::Half>::value;

    int row = blockIdx.x;
    const scalar_t* x = input + row * hidden_size;
    scalar_t* o = output + row * hidden_size;

    int tid = threadIdx.x;
    int bdim = blockDim.x;
    int pack_size = hidden_size / 2;

    float sum_sq = 0.0f;
    constexpr int CACHED_PAIRS = 2;
    float reg[CACHED_PAIRS * 2];
    int reg_h2[CACHED_PAIRS];
    int n_pairs_cached = 0;

    if constexpr (is_half) {
        const half2* x_h2 = reinterpret_cast<const half2*>(x);
        for (int i = tid; i < pack_size; i += bdim) {
            float2 xf = __half22float2(x_h2[i]);
            sum_sq += xf.x * xf.x + xf.y * xf.y;
            if (n_pairs_cached < CACHED_PAIRS) {
                reg[n_pairs_cached * 2] = xf.x;
                reg[n_pairs_cached * 2 + 1] = xf.y;
                reg_h2[n_pairs_cached] = i;
                n_pairs_cached++;
            }
        }
    } else {
        const __nv_bfloat162* x_bf2 = reinterpret_cast<const __nv_bfloat162*>(x);
        for (int i = tid; i < pack_size; i += bdim) {
            float2 xf = __bfloat1622float2(x_bf2[i]);
            sum_sq += xf.x * xf.x + xf.y * xf.y;
            if (n_pairs_cached < CACHED_PAIRS) {
                reg[n_pairs_cached * 2] = xf.x;
                reg[n_pairs_cached * 2 + 1] = xf.y;
                reg_h2[n_pairs_cached] = i;
                n_pairs_cached++;
            }
        }
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);

    __shared__ float shared[16];
    int lane = tid & 31;
    int warp_id = tid >> 5;

    if (lane == 0) shared[warp_id] = sum_sq;
    __syncthreads();

    if (warp_id == 0) {
        int num_warps = (bdim + 31) >> 5;
        sum_sq = (lane < num_warps) ? shared[lane] : 0.0f;
        for (int offset = warpSize / 2; offset > 0; offset >>= 1)
            sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);
    }

    __shared__ float s_rms_inv;
    if (tid == 0) {
        s_rms_inv = rsqrtf(sum_sq / hidden_size + eps);
    }
    __syncthreads();

    float rms_inv = s_rms_inv;

    if constexpr (is_half) {
        const half2* w_h2 = reinterpret_cast<const half2*>(weight);
        half2* o_h2 = reinterpret_cast<half2*>(o);

        #pragma unroll
        for (int p = 0; p < CACHED_PAIRS; p++) {
            if (p < n_pairs_cached) {
                float2 wf = __half22float2(w_h2[reg_h2[p]]);
                float2 of;
                of.x = reg[p * 2] * rms_inv * wf.x;
                of.y = reg[p * 2 + 1] * rms_inv * wf.y;
                o_h2[reg_h2[p]] = __float22half2_rn(of);
            }
        }

        const half2* x_h2 = reinterpret_cast<const half2*>(x);
        for (int i = tid + n_pairs_cached * bdim; i < pack_size; i += bdim) {
            float2 xf = __half22float2(x_h2[i]);
            float2 wf = __half22float2(w_h2[i]);
            float2 of;
            of.x = xf.x * rms_inv * wf.x;
            of.y = xf.y * rms_inv * wf.y;
            o_h2[i] = __float22half2_rn(of);
        }
    } else {
        const __nv_bfloat162* w_bf2 = reinterpret_cast<const __nv_bfloat162*>(weight);
        __nv_bfloat162* o_bf2 = reinterpret_cast<__nv_bfloat162*>(o);

        #pragma unroll
        for (int p = 0; p < CACHED_PAIRS; p++) {
            if (p < n_pairs_cached) {
                float2 wf = __bfloat1622float2(w_bf2[reg_h2[p]]);
                float2 of;
                of.x = reg[p * 2] * rms_inv * wf.x;
                of.y = reg[p * 2 + 1] * rms_inv * wf.y;
                o_bf2[reg_h2[p]] = __float22bfloat162_rn(of);
            }
        }

        const __nv_bfloat162* x_bf2 = reinterpret_cast<const __nv_bfloat162*>(x);
        for (int i = tid + n_pairs_cached * bdim; i < pack_size; i += bdim) {
            float2 xf = __bfloat1622float2(x_bf2[i]);
            float2 wf = __bfloat1622float2(w_bf2[i]);
            float2 of;
            of.x = xf.x * rms_inv * wf.x;
            of.y = xf.y * rms_inv * wf.y;
            o_bf2[i] = __float22bfloat162_rn(of);
        }
    }
}

torch::Tensor agent_rmsnorm(torch::Tensor input, torch::Tensor weight, double eps) {
    auto output = torch::empty_like(input);
    int batch = input.size(0);
    int hidden = input.size(1);

    dim3 grid(batch);
    dim3 block(min(hidden, 512));

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        input.scalar_type(), "rmsnorm", [&] {
            rmsnorm_kernel<scalar_t><<<grid, block>>>(
                input.data_ptr<scalar_t>(),
                weight.data_ptr<scalar_t>(),
                output.data_ptr<scalar_t>(),
                hidden, static_cast<float>(eps)
            );
        }
    );

    return output;
}
