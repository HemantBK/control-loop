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

    float sum_sq = 0.0f;
    float c0 = 0.0f, c1 = 0.0f, c2 = 0.0f, c3 = 0.0f;
    int i0 = threadIdx.x;
    int i1 = i0 + blockDim.x;
    int i2 = i1 + blockDim.x;
    int i3 = i2 + blockDim.x;

    if (i0 < hidden_size) { c0 = static_cast<float>(__ldg(&x[i0])); sum_sq += c0 * c0; }
    if (i1 < hidden_size) { c1 = static_cast<float>(__ldg(&x[i1])); sum_sq += c1 * c1; }
    if (i2 < hidden_size) { c2 = static_cast<float>(__ldg(&x[i2])); sum_sq += c2 * c2; }
    if (i3 < hidden_size) { c3 = static_cast<float>(__ldg(&x[i3])); sum_sq += c3 * c3; }
    for (int i = i3 + blockDim.x; i < hidden_size; i += blockDim.x) {
        float val = static_cast<float>(__ldg(&x[i]));
        sum_sq += val * val;
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);

    __shared__ float shared[16];
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

    if (i0 < hidden_size) { o[i0] = static_cast<scalar_t>(c0 * rms_inv * static_cast<float>(__ldg(&weight[i0]))); }
    if (i1 < hidden_size) { o[i1] = static_cast<scalar_t>(c1 * rms_inv * static_cast<float>(__ldg(&weight[i1]))); }
    if (i2 < hidden_size) { o[i2] = static_cast<scalar_t>(c2 * rms_inv * static_cast<float>(__ldg(&weight[i2]))); }
    if (i3 < hidden_size) { o[i3] = static_cast<scalar_t>(c3 * rms_inv * static_cast<float>(__ldg(&weight[i3]))); }
    for (int i = i3 + blockDim.x; i < hidden_size; i += blockDim.x) {
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
