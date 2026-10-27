/*
 * Fused SwiGLU MLP CUDA kernel — optimized implementation
 *
 * Uses cuBLAS (via torch::matmul) for the heavy GEMM work,
 * then fuses the SiLU activation + elementwise multiply in-place.
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

template <typename scalar_t>
__global__ __launch_bounds__(256)
void fused_silu_mul_inplace_kernel(
    scalar_t* __restrict__ gate,         // [N] - modified in place
    const scalar_t* __restrict__ up,     // [N]
    int N
) {
    constexpr int VEC = sizeof(float4) / sizeof(scalar_t);
    int num_vec = N / VEC;
    int vi = blockIdx.x * blockDim.x + threadIdx.x;
    if (vi < num_vec) {
        float4 g_vec = reinterpret_cast<const float4*>(gate)[vi];
        float4 u_vec = reinterpret_cast<const float4*>(up)[vi];
        scalar_t* pg = reinterpret_cast<scalar_t*>(&g_vec);
        const scalar_t* pu = reinterpret_cast<const scalar_t*>(&u_vec);
        float4 o_vec;
        scalar_t* po = reinterpret_cast<scalar_t*>(&o_vec);
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            float g = static_cast<float>(pg[j]);
            float u = static_cast<float>(pu[j]);
            float silu_g = g / (1.0f + expf(-g));
            po[j] = static_cast<scalar_t>(silu_g * u);
        }
        reinterpret_cast<float4*>(gate)[vi] = o_vec;
    }
    for (int i = threadIdx.x + blockIdx.x * blockDim.x + num_vec * VEC; i < N; i += blockDim.x * gridDim.x) {
        float g = static_cast<float>(gate[i]);
        float u = static_cast<float>(up[i]);
        float silu_g = g / (1.0f + expf(-g));
        gate[i] = static_cast<scalar_t>(silu_g * u);
    }
}

// ─── Host wrapper ────────────────────────────────────────────────────────────

torch::Tensor agent_fused_mlp(
    torch::Tensor input,        // [batch, hidden]
    torch::Tensor gate_weight,  // [intermediate, hidden]
    torch::Tensor up_weight     // [intermediate, hidden]
) {
    // Use torch matmul (cuBLAS) for the GEMMs
    auto gate_proj = torch::mm(input, gate_weight.t());
    auto up_proj = torch::mm(input, up_weight.t());

    int N = gate_proj.numel();

    constexpr int VEC = 8;
    int num_vec = N / VEC;
    int threads = 256;
    int blocks = (num_vec + threads - 1) / threads;
    if (blocks == 0) blocks = 1;

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

    return gate_proj;  // modified in-place, no extra allocation
}
