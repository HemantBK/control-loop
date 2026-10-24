/*
 * RMSNorm CUDA kernel — optimized implementation
 *
 * Computes: output = (x / rms(x)) * weight
 * where rms(x) = sqrt(mean(x^2) + eps)
 *
 * Optimizations:
 * - 256 threads (8 warps) for faster reduction vs 1024 threads (32 warps)
 * - Input cached in registers during first pass, reused in second pass
 * - Eliminates second global memory read of input
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

    int tid = threadIdx.x;
    int bdim = blockDim.x;

    // Load input into registers and compute sum of squares
    // Each thread handles up to 8 elements (supports hidden_size <= 2048 with 256 threads)
    constexpr int MAX_VEC = 8;
    float vals[MAX_VEC];
    float sum_sq = 0.0f;

    #pragma unroll
    for (int i = 0; i < MAX_VEC; i++) {
        int idx = tid + i * bdim;
        vals[i] = (idx < hidden_size) ? static_cast<float>(__ldg(&x[idx])) : 0.0f;
        sum_sq += vals[i] * vals[i];
    }

    // Warp-level reduction
    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);

    __shared__ float shared[32];
    int lane = tid & 31;
    int warp_id = tid >> 5;

    if (lane == 0) shared[warp_id] = sum_sq;
    __syncthreads();

    if (warp_id == 0) {
        int num_warps = (bdim + 31) >> 5;
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

    // Normalize and scale using cached register values (no second global read of input)
    #pragma unroll
    for (int i = 0; i < MAX_VEC; i++) {
        int idx = tid + i * bdim;
        if (idx < hidden_size) {
            float w = static_cast<float>(__ldg(&weight[idx]));
            o[idx] = static_cast<scalar_t>(vals[i] * rms_inv * w);
        }
    }
}

// ─── Host wrapper ────────────────────────────────────────────────────────────

torch::Tensor agent_rmsnorm(torch::Tensor input, torch::Tensor weight, double eps) {
    auto output = torch::empty_like(input);
    int batch = input.size(0);
    int hidden = input.size(1);

    dim3 grid(batch);
    // Use 256 threads for hidden_size=2048 (8 elements per thread)
    // Scales up to 1024 threads for larger hidden sizes
    dim3 block(min((hidden + 7) / 8, 1024));

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
