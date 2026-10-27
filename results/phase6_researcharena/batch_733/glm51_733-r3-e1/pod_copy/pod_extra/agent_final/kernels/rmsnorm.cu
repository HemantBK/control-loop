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
    int tid = threadIdx.x;
    int stride = blockDim.x;

    int i0 = tid;
    int i1 = tid + stride;
    int i2 = tid + 2 * stride;
    int i3 = tid + 3 * stride;

    float v0 = 0.0f, v1 = 0.0f, v2 = 0.0f, v3 = 0.0f;

    if (i0 < hidden_size) { v0 = static_cast<float>(__ldg(&x[i0])); sum_sq += v0 * v0; }
    if (i1 < hidden_size) { v1 = static_cast<float>(__ldg(&x[i1])); sum_sq += v1 * v1; }
    if (i2 < hidden_size) { v2 = static_cast<float>(__ldg(&x[i2])); sum_sq += v2 * v2; }
    if (i3 < hidden_size) { v3 = static_cast<float>(__ldg(&x[i3])); sum_sq += v3 * v3; }

    for (int i = i3 + stride; i < hidden_size; i += stride) {
        float val = static_cast<float>(__ldg(&x[i]));
        sum_sq += val * val;
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);

    __shared__ float shared[16];
    int lane = tid & 31;
    int warp_id = tid >> 5;

    if (lane == 0) shared[warp_id] = sum_sq;
    __syncthreads();

    if (warp_id == 0) {
        int num_warps = (stride + 31) >> 5;
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

    if (i0 < hidden_size) { o[i0] = static_cast<scalar_t>(v0 * rms_inv * static_cast<float>(__ldg(&weight[i0]))); }
    if (i1 < hidden_size) { o[i1] = static_cast<scalar_t>(v1 * rms_inv * static_cast<float>(__ldg(&weight[i1]))); }
    if (i2 < hidden_size) { o[i2] = static_cast<scalar_t>(v2 * rms_inv * static_cast<float>(__ldg(&weight[i2]))); }
    if (i3 < hidden_size) { o[i3] = static_cast<scalar_t>(v3 * rms_inv * static_cast<float>(__ldg(&weight[i3]))); }

    for (int i = i3 + stride; i < hidden_size; i += stride) {
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
