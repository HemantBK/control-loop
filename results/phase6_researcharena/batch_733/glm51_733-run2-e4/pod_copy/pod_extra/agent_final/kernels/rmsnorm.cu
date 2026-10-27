/*
 * RMSNorm CUDA kernel — optimized implementation
 *
 * Computes: output = (x / rms(x)) * weight
 * where rms(x) = sqrt(mean(x^2) + eps)
 *
 * Optimization: vectorized 8-byte loads/stores (uint2) for 2-byte dtypes
 * (fp16/bf16). Each thread loads VEC=4 elements per transaction, halving
 * the number of load/store instructions vs scalar access.
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

    constexpr int VEC = 4;
    int vec_hidden = (hidden_size / VEC) * VEC;

    float sum_sq = 0.0f;
    float sq0 = 0.0f, sq1 = 0.0f, sq2 = 0.0f, sq3 = 0.0f;
    for (int i = threadIdx.x * VEC; i < vec_hidden; i += blockDim.x * VEC) {
        uint2 vx = *reinterpret_cast<const uint2*>(&x[i]);
        const scalar_t* px = reinterpret_cast<const scalar_t*>(&vx);
        float v0 = static_cast<float>(px[0]);
        float v1 = static_cast<float>(px[1]);
        float v2 = static_cast<float>(px[2]);
        float v3 = static_cast<float>(px[3]);
        sq0 += v0 * v0;
        sq1 += v1 * v1;
        sq2 += v2 * v2;
        sq3 += v3 * v3;
    }
    sum_sq = sq0 + sq1 + sq2 + sq3;
    for (int i = vec_hidden + threadIdx.x; i < hidden_size; i += blockDim.x) {
        float val = static_cast<float>(__ldg(&x[i]));
        sum_sq += val * val;
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);

    __shared__ float shared[16];
    int lane = threadIdx.x & 31;
    int warp_id = threadIdx.x >> 5;
    int num_warps = (blockDim.x + 31) >> 5;

    if (lane == 0) shared[warp_id] = sum_sq;
    __syncthreads();

    if (warp_id == 0) {
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

    for (int i = threadIdx.x * VEC; i < vec_hidden; i += blockDim.x * VEC) {
        uint2 vx = *reinterpret_cast<const uint2*>(&x[i]);
        uint2 vw = *reinterpret_cast<const uint2*>(&weight[i]);
        const scalar_t* px = reinterpret_cast<const scalar_t*>(&vx);
        const scalar_t* pw = reinterpret_cast<const scalar_t*>(&vw);
        union { uint2 u; scalar_t s[VEC]; } out_pack;
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            float val = static_cast<float>(px[j]);
            float w = static_cast<float>(pw[j]);
            out_pack.s[j] = static_cast<scalar_t>(val * rms_inv * w);
        }
        *reinterpret_cast<uint2*>(&o[i]) = out_pack.u;
    }
    for (int i = vec_hidden + threadIdx.x; i < hidden_size; i += blockDim.x) {
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
    constexpr int VEC = 4;
    int threads = min(hidden / VEC, 512);
    threads = max(((threads + 31) / 32) * 32, 32);

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        input.scalar_type(), "rmsnorm", [&] {
            rmsnorm_kernel<scalar_t><<<grid, threads>>>(
                input.data_ptr<scalar_t>(),
                weight.data_ptr<scalar_t>(),
                output.data_ptr<scalar_t>(),
                hidden, static_cast<float>(eps)
            );
        }
    );

    return output;
}
