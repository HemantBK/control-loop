#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

template <typename scalar_t>
__global__ __launch_bounds__(256)
void fused_silu_mul_inplace_kernel(
    scalar_t* __restrict__ gate,
    const scalar_t* __restrict__ up,
    int N
) {
    const int VEC_ELEMS = 16 / (int)sizeof(scalar_t);
    const int num_vecs = N / VEC_ELEMS;

    for (int vi = blockIdx.x * blockDim.x + threadIdx.x; vi < num_vecs; vi += blockDim.x * gridDim.x) {
        float4 gv = __ldg(reinterpret_cast<const float4*>(gate) + vi);
        const float4 uv = __ldg(reinterpret_cast<const float4*>(up) + vi);
        scalar_t* ge = reinterpret_cast<scalar_t*>(&gv);
        const scalar_t* ue = reinterpret_cast<const scalar_t*>(&uv);
        #pragma unroll
        for (int j = 0; j < VEC_ELEMS; j++) {
            float g = static_cast<float>(ge[j]);
            float u = static_cast<float>(ue[j]);
            float silu_g = g * __frcp_rn(1.0f + __expf(-g));
            ge[j] = static_cast<scalar_t>(silu_g * u);
        }
        reinterpret_cast<float4*>(gate)[vi] = gv;
    }
    int tail_start = num_vecs * VEC_ELEMS;
    for (int i = tail_start + blockIdx.x * blockDim.x + threadIdx.x; i < N; i += blockDim.x * gridDim.x) {
        float g = static_cast<float>(__ldg(&gate[i]));
        float u = static_cast<float>(__ldg(&up[i]));
        float silu_g = g * __frcp_rn(1.0f + __expf(-g));
        gate[i] = static_cast<scalar_t>(silu_g * u);
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
    int vec_elems = 16 / gate_proj.element_size();
    int num_vecs = N / vec_elems;
    int threads = 256;
    int blocks = max((num_vecs + threads - 1) / threads, 1);

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
