#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

template <typename scalar_t>
__global__ void fused_silu_mul_inplace_kernel(
    scalar_t* __restrict__ gate,
    const scalar_t* __restrict__ up,
    int N
) {
    constexpr int VEC_SIZE = 16 / sizeof(scalar_t);
    using vec_t = uint4;
    int vec_idx = blockIdx.x * blockDim.x + threadIdx.x;
    int base_idx = vec_idx * VEC_SIZE;
    if (base_idx >= N) return;

    vec_t vg = *reinterpret_cast<const vec_t*>(gate + base_idx);
    vec_t vu = *reinterpret_cast<const vec_t*>(up + base_idx);
    const scalar_t* pg = reinterpret_cast<const scalar_t*>(&vg);
    const scalar_t* pu = reinterpret_cast<const scalar_t*>(&vu);
    vec_t vo;
    scalar_t* po = reinterpret_cast<scalar_t*>(&vo);

    #pragma unroll
    for (int i = 0; i < VEC_SIZE; i++) {
        float g = static_cast<float>(pg[i]);
        float u = static_cast<float>(pu[i]);
        float silu_g = g / (1.0f + expf(-g));
        po[i] = static_cast<scalar_t>(silu_g * u);
    }
    *reinterpret_cast<vec_t*>(gate + base_idx) = vo;
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
    constexpr int VEC_SIZE = 16 / sizeof(at::Half);
    int blocks = (N + threads * VEC_SIZE - 1) / (threads * VEC_SIZE);

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
