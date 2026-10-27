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

    constexpr int VEC_SIZE = 16 / sizeof(scalar_t);
    const int num_vecs = hidden_size / VEC_SIZE;
    using vec_t = uint4;

    float sum_sq = 0.0f;

    #pragma unroll 2
    for (int vi = threadIdx.x; vi < num_vecs; vi += blockDim.x) {
        vec_t vx = *reinterpret_cast<const vec_t*>(x + vi * VEC_SIZE);
        const scalar_t* px = reinterpret_cast<const scalar_t*>(&vx);
        #pragma unroll
        for (int j = 0; j < VEC_SIZE; j++) {
            float val = static_cast<float>(px[j]);
            sum_sq += val * val;
        }
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);

    __shared__ float shared[8];
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

    #pragma unroll 2
    for (int vi = threadIdx.x; vi < num_vecs; vi += blockDim.x) {
        vec_t vx = *reinterpret_cast<const vec_t*>(x + vi * VEC_SIZE);
        vec_t vw = *reinterpret_cast<const vec_t*>(weight + vi * VEC_SIZE);
        const scalar_t* px = reinterpret_cast<const scalar_t*>(&vx);
        const scalar_t* pw = reinterpret_cast<const scalar_t*>(&vw);
        vec_t vo;
        scalar_t* po = reinterpret_cast<scalar_t*>(&vo);
        #pragma unroll
        for (int j = 0; j < VEC_SIZE; j++) {
            float val = static_cast<float>(px[j]);
            float w = static_cast<float>(pw[j]);
            po[j] = static_cast<scalar_t>(val * rms_inv * w);
        }
        *reinterpret_cast<vec_t*>(o + vi * VEC_SIZE) = vo;
    }
}

torch::Tensor agent_rmsnorm(torch::Tensor input, torch::Tensor weight, double eps) {
    auto output = torch::empty_like(input);
    int batch = input.size(0);
    int hidden = input.size(1);

    dim3 grid(batch);
    int vec_elems = 16 / (int)sizeof(at::Half);
    dim3 block(std::min(hidden / vec_elems, 256));

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
