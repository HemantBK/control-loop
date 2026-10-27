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
    int num_vec,
    float eps
) {
    int row = blockIdx.x;
    const scalar_t* x = input + row * hidden_size;
    scalar_t* o = output + row * hidden_size;
    const scalar_t* w = weight;

    constexpr int VEC = sizeof(float4) / sizeof(scalar_t);

    float sum_sq = 0.0f;
    for (int vi = threadIdx.x; vi < num_vec; vi += blockDim.x) {
        float4 vx = reinterpret_cast<const float4*>(x)[vi];
        const scalar_t* px = reinterpret_cast<const scalar_t*>(&vx);
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            float val = static_cast<float>(px[j]);
            sum_sq += val * val;
        }
    }
    int remainder_start = num_vec * VEC;
    for (int i = remainder_start + threadIdx.x; i < hidden_size; i += blockDim.x) {
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

    for (int vi = threadIdx.x; vi < num_vec; vi += blockDim.x) {
        float4 vx = reinterpret_cast<const float4*>(x)[vi];
        float4 vw = reinterpret_cast<const float4*>(w)[vi];
        const scalar_t* px = reinterpret_cast<const scalar_t*>(&vx);
        const scalar_t* pw = reinterpret_cast<const scalar_t*>(&vw);
        float4 vo;
        scalar_t* po = reinterpret_cast<scalar_t*>(&vo);
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            po[j] = static_cast<scalar_t>(static_cast<float>(px[j]) * rms_inv * static_cast<float>(pw[j]));
        }
        reinterpret_cast<float4*>(o)[vi] = vo;
    }
    for (int i = remainder_start + threadIdx.x; i < hidden_size; i += blockDim.x) {
        float val = static_cast<float>(__ldg(&x[i]));
        float wv = static_cast<float>(__ldg(&w[i]));
        o[i] = static_cast<scalar_t>(val * rms_inv * wv);
    }
}

// ─── Host wrapper ────────────────────────────────────────────────────────────

torch::Tensor agent_rmsnorm(torch::Tensor input, torch::Tensor weight, double eps) {
    auto output = torch::empty_like(input);
    int batch = input.size(0);
    int hidden = input.size(1);

    int elem_size = input.element_size();
    int vec_size = 16 / elem_size;
    int num_vec = hidden / vec_size;

    dim3 grid(batch);
    dim3 block(min(max(num_vec, 32), 512));

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        input.scalar_type(), "rmsnorm", [&] {
            rmsnorm_kernel<scalar_t><<<grid, block>>>(
                input.data_ptr<scalar_t>(),
                weight.data_ptr<scalar_t>(),
                output.data_ptr<scalar_t>(),
                hidden, num_vec, static_cast<float>(eps)
            );
        }
    );

    return output;
}
