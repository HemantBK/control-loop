/*
 * Fused SwiGLU MLP CUDA kernel — optimized with vectorized loads/stores
 *
 * Uses cuBLAS (via torch::matmul) for the heavy GEMM work,
 * then fuses the SiLU activation + elementwise multiply in-place.
 *
 * Optimizations:
 * - float4 vectorized loads/stores (8 half/bf16 values per transaction)
 * - 8 elements per thread for better ILP and reduced memory instructions
 * - Single bounds check per thread instead of per-element
 */

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
    constexpr int VEC = 8;
    int n_vec = N / VEC;
    int tid = blockIdx.x * blockDim.x + threadIdx.x;

    if (tid < n_vec) {
        float4 vg = *reinterpret_cast<const float4*>(gate + tid * VEC);
        float4 vu = *reinterpret_cast<const float4*>(up + tid * VEC);
        const scalar_t* sg = reinterpret_cast<const scalar_t*>(&vg);
        const scalar_t* su = reinterpret_cast<const scalar_t*>(&vu);
        float4 vo;
        scalar_t* so = reinterpret_cast<scalar_t*>(&vo);
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            float g = static_cast<float>(sg[j]);
            float u = static_cast<float>(su[j]);
            float silu_g = g / (1.0f + expf(-g));
            so[j] = static_cast<scalar_t>(silu_g * u);
        }
        *reinterpret_cast<float4*>(gate + tid * VEC) = vo;
    }
    for (int i = n_vec * VEC + tid; i < N; i += gridDim.x * blockDim.x) {
        float g = static_cast<float>(gate[i]);
        float u = static_cast<float>(up[i]);
        float silu_g = g / (1.0f + expf(-g));
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
    constexpr int VEC = 8;
    int n_vec = N / VEC;
    int threads = 256;
    int blocks = max((n_vec + threads - 1) / threads, 1);

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
