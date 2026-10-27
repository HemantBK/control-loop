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

    extern __shared__ float smem[];
    float* s_val = smem;
    float* warp_buf = smem + hidden_size;

    float sum_sq = 0.0f;

    if constexpr (sizeof(scalar_t) == 2) {
        const uint32_t* x_vec = reinterpret_cast<const uint32_t*>(x);
        int vec_len = hidden_size >> 1;
        for (int i = threadIdx.x; i < vec_len; i += blockDim.x) {
            uint32_t vx = __ldg(&x_vec[i]);
            const scalar_t* hx = reinterpret_cast<const scalar_t*>(&vx);
            float v0 = static_cast<float>(hx[0]);
            float v1 = static_cast<float>(hx[1]);
            s_val[i * 2] = v0;
            s_val[i * 2 + 1] = v1;
            sum_sq += v0 * v0 + v1 * v1;
        }
    } else {
        for (int i = threadIdx.x; i < hidden_size; i += blockDim.x) {
            float val = static_cast<float>(__ldg(&x[i]));
            s_val[i] = val;
            sum_sq += val * val;
        }
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);

    int lane = threadIdx.x & 31;
    int warp_id = threadIdx.x >> 5;

    if (lane == 0) warp_buf[warp_id] = sum_sq;
    __syncthreads();

    if (warp_id == 0) {
        int num_warps = (blockDim.x + 31) >> 5;
        sum_sq = (lane < num_warps) ? warp_buf[lane] : 0.0f;
        for (int offset = warpSize / 2; offset > 0; offset >>= 1)
            sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);
    }

    if (threadIdx.x == 0) {
        warp_buf[0] = rsqrtf(sum_sq / hidden_size + eps);
    }
    __syncthreads();

    float rms_inv = warp_buf[0];

    if constexpr (sizeof(scalar_t) == 2) {
        const uint32_t* w_vec = reinterpret_cast<const uint32_t*>(weight);
        uint32_t* o_vec = reinterpret_cast<uint32_t*>(o);
        int vec_len = hidden_size >> 1;
        for (int i = threadIdx.x; i < vec_len; i += blockDim.x) {
            uint32_t vw = __ldg(&w_vec[i]);
            const scalar_t* hw = reinterpret_cast<const scalar_t*>(&vw);
            union { scalar_t h[2]; uint32_t u; } ho;
            ho.h[0] = static_cast<scalar_t>(s_val[i * 2] * rms_inv * static_cast<float>(hw[0]));
            ho.h[1] = static_cast<scalar_t>(s_val[i * 2 + 1] * rms_inv * static_cast<float>(hw[1]));
            o_vec[i] = ho.u;
        }
    } else {
        for (int i = threadIdx.x; i < hidden_size; i += blockDim.x) {
            float w = static_cast<float>(__ldg(&weight[i]));
            o[i] = static_cast<scalar_t>(s_val[i] * rms_inv * w);
        }
    }
}

// ─── Host wrapper ────────────────────────────────────────────────────────────

torch::Tensor agent_rmsnorm(torch::Tensor input, torch::Tensor weight, double eps) {
    auto output = torch::empty_like(input);
    int batch = input.size(0);
    int hidden = input.size(1);

    dim3 grid(batch);
    dim3 block(min(max(hidden / 4, 32), 512));
    size_t smem_size = (hidden + 32) * sizeof(float);

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        input.scalar_type(), "rmsnorm", [&] {
            rmsnorm_kernel<scalar_t><<<grid, block, smem_size>>>(
                input.data_ptr<scalar_t>(),
                weight.data_ptr<scalar_t>(),
                output.data_ptr<scalar_t>(),
                hidden, static_cast<float>(eps)
            );
        }
    );

    return output;
}
