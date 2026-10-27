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
    int vec_elems = 8;
    int vec_size = hidden_size / vec_elems;

    float sum_sq = 0.0f;
    for (int i = tid; i < vec_size; i += bdim) {
        const uint4* x_vec = reinterpret_cast<const uint4*>(x) + i;
        uint4 xv = __ldg(x_vec);
        const scalar_t* xh = reinterpret_cast<const scalar_t*>(&xv);
        #pragma unroll
        for (int j = 0; j < vec_elems; j++) {
            float val = static_cast<float>(xh[j]);
            sum_sq += val * val;
        }
    }

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

    for (int i = tid; i < vec_size; i += bdim) {
        const uint4* x_vec = reinterpret_cast<const uint4*>(x) + i;
        uint4 xv = __ldg(x_vec);
        const uint4* w_vec = reinterpret_cast<const uint4*>(weight) + i;
        uint4 wv = __ldg(w_vec);
        scalar_t* xh = reinterpret_cast<scalar_t*>(&xv);
        const scalar_t* wh = reinterpret_cast<const scalar_t*>(&wv);

        uint4 ov;
        scalar_t* oh = reinterpret_cast<scalar_t*>(&ov);
        #pragma unroll
        for (int j = 0; j < vec_elems; j++) {
            float val = static_cast<float>(xh[j]);
            float w = static_cast<float>(wh[j]);
            oh[j] = static_cast<scalar_t>(val * rms_inv * w);
        }
        reinterpret_cast<uint4*>(o)[i] = ov;
    }
}

// ─── Host wrapper ────────────────────────────────────────────────────────────

torch::Tensor agent_rmsnorm(torch::Tensor input, torch::Tensor weight, double eps) {
    auto output = torch::empty_like(input);
    int batch = input.size(0);
    int hidden = input.size(1);

    dim3 grid(batch);
    dim3 block(min(hidden / 8, 256));

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
