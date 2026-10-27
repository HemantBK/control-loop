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
__global__ __launch_bounds__(256)
void fused_silu_mul_inplace_kernel(
    scalar_t* __restrict__ gate,
    const scalar_t* __restrict__ up,
    int N
) {
    constexpr int VEC = 8;
    int vec_idx = blockIdx.x * blockDim.x + threadIdx.x;
    int base = vec_idx * VEC;

    if (base >= N) return;

    if (base + VEC <= N) {
        uint4 gv = *reinterpret_cast<const uint4*>(&gate[base]);
        uint4 uv = *reinterpret_cast<const uint4*>(&up[base]);
        const scalar_t* gs = reinterpret_cast<const scalar_t*>(&gv);
        const scalar_t* us = reinterpret_cast<const scalar_t*>(&uv);
        uint4 ov;
        scalar_t* os = reinterpret_cast<scalar_t*>(&ov);
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            float g = static_cast<float>(gs[j]);
            float u = static_cast<float>(us[j]);
            os[j] = static_cast<scalar_t>(g / (1.0f + expf(-g)) * u);
        }
        *reinterpret_cast<uint4*>(&gate[base]) = ov;
    } else {
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            int idx = base + j;
            if (idx < N) {
                float g = static_cast<float>(gate[idx]);
                float u = static_cast<float>(up[idx]);
                gate[idx] = static_cast<scalar_t>(g / (1.0f + expf(-g)) * u);
            }
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

    constexpr int VEC = 8;
    int threads = 256;
    int total_vec = (N + VEC - 1) / VEC;
    int blocks = (total_vec + threads - 1) / threads;

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
