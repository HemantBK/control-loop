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
__global__ __launch_bounds__(512)
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

    constexpr int VEC = 8;
    int n_vec = hidden_size / VEC;

    float sum_sq = 0.0f;
    for (int i = threadIdx.x; i < n_vec; i += blockDim.x) {
        float4 xv = reinterpret_cast<const float4*>(x)[i];
        const scalar_t* vals = reinterpret_cast<const scalar_t*>(&xv);
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            float val = static_cast<float>(vals[j]);
            sum_sq += val * val;
        }
    }
    for (int i = n_vec * VEC + threadIdx.x; i < hidden_size; i += blockDim.x) {
        float val = static_cast<float>(__ldg(&x[i]));
        sum_sq += val * val;
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);

    __shared__ float shared[32];
    int lane = threadIdx.x & 31;
    int warp_id = threadIdx.x >> 5;

    if (lane == 0) shared[warp_id] = sum_sq;
    __syncthreads();

    if (warp_id == 0) {
        int num_warps = (blockDim.x + 31) >> 5;
        sum_sq = (lane < num_warps) ? shared[lane] : 0.0f;
        for (int offset = warpSize / 2; offset > 0; offset >>= 1)
            sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);
    }

    __shared__ float s_rms_inv;
    if (threadIdx.x == 0) {
        s_rms_inv = rsqrtf(sum_sq / hidden_size + eps);
    }
    __syncthreads();

    float rms_inv = s_rms_inv;

    for (int i = threadIdx.x; i < n_vec; i += blockDim.x) {
        float4 xv = reinterpret_cast<const float4*>(x)[i];
        float4 wv = reinterpret_cast<const float4*>(weight)[i];
        const scalar_t* x_vals = reinterpret_cast<const scalar_t*>(&xv);
        const scalar_t* w_vals = reinterpret_cast<const scalar_t*>(&wv);
        float4 ov;
        scalar_t* o_vals = reinterpret_cast<scalar_t*>(&ov);
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            float val = static_cast<float>(x_vals[j]);
            float w = static_cast<float>(w_vals[j]);
            o_vals[j] = static_cast<scalar_t>(val * rms_inv * w);
        }
        reinterpret_cast<float4*>(o)[i] = ov;
    }
    for (int i = n_vec * VEC + threadIdx.x; i < hidden_size; i += blockDim.x) {
        float val = static_cast<float>(__ldg(&x[i]));
        float w = static_cast<float>(__ldg(&weight[i]));
        o[i] = static_cast<scalar_t>(val * rms_inv * w);
    }
}

// ─── Host wrapper ────────────────────────────────────────────────────────────

torch::Tensor agent_rmsnorm(torch::Tensor input, torch::Tensor weight, double eps) {
    auto output = torch::empty_like(input);
    int batch = input.size(0);
    int hidden = input.size(1);

    dim3 grid(batch);
    int n_vec = hidden / 8;
    int threads = min(max(n_vec, 64), 512);
    threads = ((threads + 31) / 32) * 32;
    dim3 block(threads);

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
