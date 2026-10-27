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

// In-place fused SiLU-multiply: gate[i] = silu(gate[i]) * up[i]
// 4 elements per thread for better ILP
template <typename scalar_t>
__global__ void fused_silu_mul_inplace_kernel(
    scalar_t* __restrict__ gate,         // [N] - modified in place
    const scalar_t* __restrict__ up,     // [N]
    int N
) {
    constexpr int VEC = 8;
    int base_idx = (blockIdx.x * blockDim.x + threadIdx.x) * VEC;
    if (base_idx + VEC <= N) {
        uint4 gv = *reinterpret_cast<const uint4*>(gate + base_idx);
        uint4 uv = *reinterpret_cast<const uint4*>(up + base_idx);
        const scalar_t* g = reinterpret_cast<const scalar_t*>(&gv);
        const scalar_t* u = reinterpret_cast<const scalar_t*>(&uv);
        uint4 out_vec;
        scalar_t* out = reinterpret_cast<scalar_t*>(&out_vec);
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            float gf = static_cast<float>(g[j]);
            float uf = static_cast<float>(u[j]);
            out[j] = static_cast<scalar_t>(gf / (1.0f + expf(-gf)) * uf);
        }
        *reinterpret_cast<uint4*>(gate + base_idx) = out_vec;
    } else {
        for (int i = base_idx; i < N && i < base_idx + VEC; i++) {
            float g = static_cast<float>(gate[i]);
            float u = static_cast<float>(up[i]);
            gate[i] = static_cast<scalar_t>(g / (1.0f + expf(-g)) * u);
        }
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

    int threads = 256;
    int blocks = (N + threads * 8 - 1) / (threads * 8);

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
