#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>
#include <type_traits>

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

    float sum_sq = 0.0f;

    if constexpr (std::is_same_v<scalar_t, at::Half>) {
        const half2* x_h2 = reinterpret_cast<const half2*>(x);
        int h2_count = hidden_size >> 1;
        for (int i = threadIdx.x; i < h2_count; i += blockDim.x) {
            float2 f = __half22float2(__ldg(&x_h2[i]));
            sum_sq += f.x * f.x + f.y * f.y;
        }
    } else {
        for (int i = threadIdx.x; i < hidden_size; i += blockDim.x) {
            float val = static_cast<float>(__ldg(&x[i]));
            sum_sq += val * val;
        }
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

    if constexpr (std::is_same_v<scalar_t, at::Half>) {
        const half2* x_h2 = reinterpret_cast<const half2*>(x);
        const half2* w_h2 = reinterpret_cast<const half2*>(weight);
        half2* o_h2 = reinterpret_cast<half2*>(o);
        int h2_count = hidden_size >> 1;
        for (int i = threadIdx.x; i < h2_count; i += blockDim.x) {
            float2 f_val = __half22float2(__ldg(&x_h2[i]));
            float2 f_w = __half22float2(__ldg(&w_h2[i]));
            float2 f_out;
            f_out.x = f_val.x * rms_inv * f_w.x;
            f_out.y = f_val.y * rms_inv * f_w.y;
            o_h2[i] = __float22half2_rn(f_out);
        }
    } else {
        for (int i = threadIdx.x; i < hidden_size; i += blockDim.x) {
            float val = static_cast<float>(__ldg(&x[i]));
            float w = static_cast<float>(__ldg(&weight[i]));
            o[i] = static_cast<scalar_t>(val * rms_inv * w);
        }
    }
}

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
