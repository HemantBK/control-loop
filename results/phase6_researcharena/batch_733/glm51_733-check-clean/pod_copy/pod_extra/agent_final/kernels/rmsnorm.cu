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
__global__ __launch_bounds__(256)
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
    int tid = threadIdx.x;
    int bdim = blockDim.x;

    constexpr int VEC = 8;
    int num_vecs = hidden_size / VEC;

    float sum_sq = 0.0f;

    for (int vi = tid; vi < num_vecs; vi += bdim) {
        float4 xv = reinterpret_cast<const float4*>(x)[vi];
        const scalar_t* vals = reinterpret_cast<const scalar_t*>(&xv);
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            float val = static_cast<float>(vals[j]);
            sum_sq += val * val;
        }
    }

    for (int i = tid + num_vecs * VEC; i < hidden_size; i += bdim) {
        float val = static_cast<float>(__ldg(&x[i]));
        sum_sq += val * val;
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);

    __shared__ float shared[32];
    int lane = tid & 31;
    int warp_id = tid >> 5;
    int num_warps = (bdim + 31) >> 5;

    if (lane == 0) shared[warp_id] = sum_sq;
    __syncthreads();

    if (warp_id == 0) {
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

    for (int vi = tid; vi < num_vecs; vi += bdim) {
        float4 xv = reinterpret_cast<const float4*>(x)[vi];
        float4 wv = reinterpret_cast<const float4*>(weight)[vi];
        const scalar_t* x_vals = reinterpret_cast<const scalar_t*>(&xv);
        const scalar_t* w_vals = reinterpret_cast<const scalar_t*>(&wv);
        float4 ov;
        scalar_t* o_vals = reinterpret_cast<scalar_t*>(&ov);
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            o_vals[j] = static_cast<scalar_t>(static_cast<float>(x_vals[j]) * rms_inv * static_cast<float>(w_vals[j]));
        }
        reinterpret_cast<float4*>(o)[vi] = ov;
    }

    for (int i = tid + num_vecs * VEC; i < hidden_size; i += bdim) {
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
    dim3 block(min((hidden + 7) / 8, 256));

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
