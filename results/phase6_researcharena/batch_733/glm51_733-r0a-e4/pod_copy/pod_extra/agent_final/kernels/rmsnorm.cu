/*
 * RMSNorm CUDA kernel — optimized implementation
 *
 * Computes: output = (x / rms(x)) * weight
 * where rms(x) = sqrt(mean(x^2) + eps)
 *
 * Optimizations over baseline:
 *   - float4 vectorized loads/stores (8 half or 4 float per load)
 *   - Reduced thread count with more work per thread
 *   - __launch_bounds__ for better register allocation
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

    constexpr int VEC_ELEMS = sizeof(float4) / sizeof(scalar_t);
    const int num_vecs = hidden_size / VEC_ELEMS;
    const int remainder_start = num_vecs * VEC_ELEMS;

    const float4* vec_x = reinterpret_cast<const float4*>(x);
    const float4* vec_w = reinterpret_cast<const float4*>(weight);
    float4* vec_o = reinterpret_cast<float4*>(o);

    float sum_sq = 0.0f;
    for (int i = threadIdx.x; i < num_vecs; i += blockDim.x) {
        float4 vx = vec_x[i];
        const scalar_t* sx = reinterpret_cast<const scalar_t*>(&vx);
        #pragma unroll
        for (int j = 0; j < VEC_ELEMS; j++) {
            float val = static_cast<float>(sx[j]);
            sum_sq += val * val;
        }
    }
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

    for (int i = threadIdx.x; i < num_vecs; i += blockDim.x) {
        float4 vx = vec_x[i];
        float4 vw = vec_w[i];
        const scalar_t* sx = reinterpret_cast<const scalar_t*>(&vx);
        const scalar_t* sw = reinterpret_cast<const scalar_t*>(&vw);
        float4 vo;
        scalar_t* so = reinterpret_cast<scalar_t*>(&vo);
        #pragma unroll
        for (int j = 0; j < VEC_ELEMS; j++) {
            so[j] = static_cast<scalar_t>(static_cast<float>(sx[j]) * rms_inv * static_cast<float>(sw[j]));
        }
        vec_o[i] = vo;
    }
    for (int i = remainder_start + threadIdx.x; i < hidden_size; i += blockDim.x) {
        float val = static_cast<float>(__ldg(&x[i]));
        float w = static_cast<float>(__ldg(&weight[i]));
        o[i] = static_cast<scalar_t>(val * rms_inv * w);
    }
}

torch::Tensor agent_rmsnorm(torch::Tensor input, torch::Tensor weight, double eps) {
    auto output = torch::empty_like(input);
    int batch = input.size(0);
    int hidden = input.size(1);

    dim3 grid(batch);

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        input.scalar_type(), "rmsnorm", [&] {
            constexpr int VEC_ELEMS = sizeof(float4) / sizeof(scalar_t);
            int num_vecs = hidden / VEC_ELEMS;
            dim3 block(min(max(num_vecs, 64), 512));

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
