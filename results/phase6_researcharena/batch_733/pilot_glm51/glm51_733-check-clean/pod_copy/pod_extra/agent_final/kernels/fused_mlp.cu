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
__global__ void fused_silu_mul_inplace_kernel(
    scalar_t* __restrict__ gate,
    const scalar_t* __restrict__ up,
    int N
) {
    using Ops = VecOps<scalar_t>;
    using vec_t = typename Ops::vec_t;

    int vec_len = N / 2;
    vec_t* gate_v = reinterpret_cast<vec_t*>(gate);
    const vec_t* up_v = reinterpret_cast<const vec_t*>(up);

    int base_vec = (blockIdx.x * blockDim.x + threadIdx.x) * 2;

    #pragma unroll
    for (int v = 0; v < 2; v++) {
        int vi = base_vec + v;
        if (vi < vec_len) {
            float2 gf = Ops::to_float(gate_v[vi]);
            float2 uf = Ops::to_float(__ldg(&up_v[vi]));
            gf.x = (gf.x / (1.0f + expf(-gf.x))) * uf.x;
            gf.y = (gf.y / (1.0f + expf(-gf.y))) * uf.y;
            gate_v[vi] = Ops::from_float(gf);
        }
    }

    if ((N & 1) && blockIdx.x == 0 && threadIdx.x == 0) {
        int idx = N - 1;
        float g = static_cast<float>(gate[idx]);
        float u = static_cast<float>(up[idx]);
        gate[idx] = static_cast<scalar_t>((g / (1.0f + expf(-g))) * u);
    }
}

torch::Tensor agent_fused_mlp(
    torch::Tensor input,
    torch::Tensor gate_weight,
    torch::Tensor up_weight
) {
    auto gate_proj = torch::mm(input, gate_weight.t());
    auto up_proj = torch::mm(input, up_weight.t());

    int N = gate_proj.numel();

    int threads = 256;
    int blocks = max(1, (N / 2 + threads * 2 - 1) / (threads * 2));

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        input.scalar_type(), "fused_mlp", [&] {
            fused_silu_mul_inplace_kernel<scalar_t><<<blocks, threads>>>(
                gate_proj.data_ptr<scalar_t>(),
                up_proj.data_ptr<scalar_t>(),
                N
            );
        }
    );

    return gate_proj;
}
