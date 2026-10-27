#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

namespace {

template <typename scalar_t>
struct VecOps;

template <>
struct VecOps<at::Half> {
    using vec_t = half2;
    static __device__ __forceinline__ float2 to_float(vec_t v) { return __half22float2(v); }
    static __device__ __forceinline__ vec_t from_float(float2 v) { return __float22half2_rn(v); }
};

template <>
struct VecOps<at::BFloat16> {
    using vec_t = __nv_bfloat162;
    static __device__ __forceinline__ float2 to_float(vec_t v) { return __bfloat162float2(v); }
    static __device__ __forceinline__ vec_t from_float(float2 v) { return __float22bfloat162_rn(v); }
};

}

template <typename scalar_t>
__global__ __launch_bounds__(1024)
void rmsnorm_kernel(
    const scalar_t* __restrict__ input,
    const scalar_t* __restrict__ weight,
    scalar_t* __restrict__ output,
    int hidden_size,
    float eps
) {
    using Ops = VecOps<scalar_t>;
    using vec_t = typename Ops::vec_t;

    int row = blockIdx.x;
    const vec_t* x_v = reinterpret_cast<const vec_t*>(input + row * hidden_size);
    const vec_t* w_v = reinterpret_cast<const vec_t*>(weight);
    vec_t* o_v = reinterpret_cast<vec_t*>(output + row * hidden_size);
    int vec_len = hidden_size / 2;

    float sum_sq = 0.0f;
    for (int i = threadIdx.x; i < vec_len; i += blockDim.x) {
        float2 vf = Ops::to_float(__ldg(&x_v[i]));
        sum_sq += vf.x * vf.x + vf.y * vf.y;
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

    for (int i = threadIdx.x; i < vec_len; i += blockDim.x) {
        float2 vf = Ops::to_float(__ldg(&x_v[i]));
        float2 wf = Ops::to_float(__ldg(&w_v[i]));
        vf.x = vf.x * rms_inv * wf.x;
        vf.y = vf.y * rms_inv * wf.y;
        o_v[i] = Ops::from_float(vf);
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
