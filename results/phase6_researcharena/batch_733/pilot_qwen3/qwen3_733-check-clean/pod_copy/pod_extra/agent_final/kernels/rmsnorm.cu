/*
 * RMSNorm CUDA kernel — optimized implementation
 *
 * Computes: output = (x / rms(x)) * weight
 * where rms(x) = sqrt(mean(x^2) + eps)
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

template <typename scalar_t>
__global__ __launch_bounds__(1024)
void rmsnorm_kernel(
    const scalar_t* __restrict__ input,
    const scalar_t* __restrict__ weight,
    scalar_t* __restrict__ output,
    int hidden_size,
    float eps
) {
    int row = blockIdx.x;
    const scalar_t* x = input + row * hidden_size;
    scalar_t* o = output + row * hidden_size;

    // Step 1: compute sum of squares
    float sum_sq = 0.0f;
    int tid = threadIdx.x;
    int bdim = blockDim.x;

    if (hidden_size % 4 == 0 && bdim % 32 == 0) {
        const float4* input_f4 = (const float4*)input;
        int num_float4 = hidden_size / 4;
        for (int i = tid; i < num_float4; i += bdim) {
            float4 val = __ldg(&input_f4[i]);
            sum_sq += val.x * val.x + val.y * val.y + val.z * val.z + val.w * val.w;
        }
    } else {
        for (int i = tid; i < hidden_size; i += bdim) {
            float val = static_cast<float>(__ldg(&x[i]));
            sum_sq += val * val;
        }
    }

    // Warp-level reduction
    if (blockDim.x >= 64) {
        for (int offset = warpSize / 2; offset > 0; offset >>= 1)
            sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);
    }

    __shared__ float shared[32];
    int lane = threadIdx.x & 31;
    int warp_id = threadIdx.x >> 5;

    if (lane == 0) shared[warp_id] = sum_sq;
    __syncthreads();

    if (warp_id == 0) {
        int num_warps = (blockDim.x + 31) >> 5;
        sum_sq = (lane < num_warps) ? shared[lane] : 0.0f;
        if (num_warps >= 2) {
            for (int offset = warpSize / 2; offset > 0; offset >>= 1)
                sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);
        }
    }

    __shared__ float s_rms_inv;
    if (threadIdx.x == 0) {
        s_rms_inv = rsqrtf(sum_sq / hidden_size + eps);
    }
    __syncthreads();

    float rms_inv = s_rms_inv;

    // Step 2: normalize and scale
    if (hidden_size % 4 == 0 && bdim % 32 == 0) {
        float4* o_f4 = (float4*)o;
        const float4* x_f4 = (const float4*)x;
        const float4* w_f4 = (const float4*)weight;
        int num_float4 = hidden_size / 4;
        for (int i = tid; i < num_float4; i += bdim) {
            float4 val = __ldg(&x_f4[i]);
            float4 w = __ldg(&w_f4[i]);
            o_f4[i] = make_float4(val.x * rms_inv * w.x, val.y * rms_inv * w.y, val.z * rms_inv * w.z, val.w * rms_inv * w.w);
        }
    } else {
        for (int i = threadIdx.x; i < hidden_size; i += blockDim.x) {
            float val = static_cast<float>(__ldg(&x[i]));
            float w = static_cast<float>(__ldg(&weight[i]));
            o[i] = static_cast<scalar_t>(val * rms_inv * w);
        }
    }
}

// ─── Host wrapper ────────────────────────────────────────────────────────────

torch::Tensor agent_rmsnorm(torch::Tensor input, torch::Tensor weight, double eps) {
    auto output = torch::empty_like(input);
    int batch = input.size(0);
    int hidden = input.size(1);

    dim3 grid(batch);
    dim3 block(min(hidden, 1024));

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
