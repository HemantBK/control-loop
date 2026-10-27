/*
 * RMSNorm CUDA kernel — optimized implementation
 *
 * Computes: output = (x / rms(x)) * weight
 * where rms(x) = sqrt(mean(x^2) + eps)
 *
 * Optimizations:
 * - Vectorized loads/stores (uint4 = 8 half/bf16 elements at a time)
 * - Single-pass with shared memory caching to avoid re-reading input
 * - Warp shuffle reductions
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
    int num_vec = hidden_size / VEC;
    int tid = threadIdx.x;
    int bdim = blockDim.x;

    extern __shared__ float smem[];
    float* s_val = smem;
    float* s_w   = smem + hidden_size;
    float* s_red = smem + 2 * hidden_size;
    float* s_ri  = s_red + 32;

    float sum_sq = 0.0f;
    for (int vi = tid; vi < num_vec; vi += bdim) {
        uint4 xv = *reinterpret_cast<const uint4*>(&x[vi * VEC]);
        uint4 wv = *reinterpret_cast<const uint4*>(&weight[vi * VEC]);
        const scalar_t* xs = reinterpret_cast<const scalar_t*>(&xv);
        const scalar_t* ws = reinterpret_cast<const scalar_t*>(&wv);
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            float val = static_cast<float>(xs[j]);
            float w   = static_cast<float>(ws[j]);
            s_val[vi * VEC + j] = val;
            s_w[vi * VEC + j]   = w;
            sum_sq += val * val;
        }
    }
    for (int i = num_vec * VEC + tid; i < hidden_size; i += bdim) {
        float val = static_cast<float>(__ldg(&x[i]));
        float w   = static_cast<float>(__ldg(&weight[i]));
        s_val[i] = val;
        s_w[i]   = w;
        sum_sq += val * val;
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);

    int lane = tid & 31;
    int warp_id = tid >> 5;

    if (lane == 0) s_red[warp_id] = sum_sq;
    __syncthreads();

    if (warp_id == 0) {
        int num_warps = (bdim + 31) >> 5;
        sum_sq = (lane < num_warps) ? s_red[lane] : 0.0f;
        for (int offset = warpSize / 2; offset > 0; offset >>= 1)
            sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);
    }

    if (tid == 0) {
        *s_ri = rsqrtf(sum_sq / hidden_size + eps);
    }
    __syncthreads();

    float rms_inv = *s_ri;

    for (int vi = tid; vi < num_vec; vi += bdim) {
        uint4 ov;
        scalar_t* os = reinterpret_cast<scalar_t*>(&ov);
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            int idx = vi * VEC + j;
            os[j] = static_cast<scalar_t>(s_val[idx] * rms_inv * s_w[idx]);
        }
        *reinterpret_cast<uint4*>(&o[vi * VEC]) = ov;
    }
    for (int i = num_vec * VEC + tid; i < hidden_size; i += bdim) {
        o[i] = static_cast<scalar_t>(s_val[i] * rms_inv * s_w[i]);
    }
}

torch::Tensor agent_rmsnorm(torch::Tensor input, torch::Tensor weight, double eps) {
    auto output = torch::empty_like(input);
    int batch = input.size(0);
    int hidden = input.size(1);

    dim3 grid(batch);
    int num_vec = hidden / 8;
    dim3 block(max(64, min(num_vec, 512)));
    size_t smem = (2 * hidden + 32 + 1) * sizeof(float);

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        input.scalar_type(), "rmsnorm", [&] {
            rmsnorm_kernel<scalar_t><<<grid, block, smem>>>(
                input.data_ptr<scalar_t>(),
                weight.data_ptr<scalar_t>(),
                output.data_ptr<scalar_t>(),
                hidden, static_cast<float>(eps)
            );
        }
    );

    return output;
}
