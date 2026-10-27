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
    scalar_t* __restrict__ gate,
    const scalar_t* __restrict__ up,
    int N
) {
    if constexpr (sizeof(scalar_t) == 2) {
        const uint32_t* gate_vec = reinterpret_cast<const uint32_t*>(gate);
        const uint32_t* up_vec = reinterpret_cast<const uint32_t*>(up);
        uint32_t* out_vec = reinterpret_cast<uint32_t*>(gate);
        int half_N = N >> 1;
        int stride = blockDim.x * gridDim.x;

        for (int i = blockIdx.x * blockDim.x + threadIdx.x; i < half_N; i += stride) {
            uint32_t vg = gate_vec[i];
            uint32_t vu = up_vec[i];
            const scalar_t* hg = reinterpret_cast<const scalar_t*>(&vg);
            const scalar_t* hu = reinterpret_cast<const scalar_t*>(&vu);
            float g0 = static_cast<float>(hg[0]);
            float g1 = static_cast<float>(hg[1]);
            float u0 = static_cast<float>(hu[0]);
            float u1 = static_cast<float>(hu[1]);
            float s0 = g0 / (1.0f + __expf(-g0));
            float s1 = g1 / (1.0f + __expf(-g1));
            union { scalar_t h[2]; uint32_t u; } ho;
            ho.h[0] = static_cast<scalar_t>(s0 * u0);
            ho.h[1] = static_cast<scalar_t>(s1 * u1);
            out_vec[i] = ho.u;
        }
        if ((N & 1) && blockIdx.x == 0 && threadIdx.x == 0) {
            int idx = N - 1;
            float g = static_cast<float>(gate[idx]);
            float u = static_cast<float>(up[idx]);
            float silu_g = g / (1.0f + __expf(-g));
            gate[idx] = static_cast<scalar_t>(silu_g * u);
        }
    } else {
        int base_idx = (blockIdx.x * blockDim.x + threadIdx.x) * 4;
        #pragma unroll
        for (int i = 0; i < 4; i++) {
            int idx = base_idx + i;
            if (idx < N) {
                float g = static_cast<float>(gate[idx]);
                float u = static_cast<float>(up[idx]);
                float silu_g = g / (1.0f + __expf(-g));
                gate[idx] = static_cast<scalar_t>(silu_g * u);
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

    int threads = 256;
    int blocks = (N / 2 + threads - 1) / threads;
    if (blocks < 1) blocks = 1;

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
