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
    int n_vec = N / VEC;
    int base_vec = blockIdx.x * blockDim.x + threadIdx.x;
    if (base_vec < n_vec) {
        float4 gv = reinterpret_cast<const float4*>(gate)[base_vec];
        float4 uv = reinterpret_cast<const float4*>(up)[base_vec];
        scalar_t* g_vals = reinterpret_cast<scalar_t*>(&gv);
        const scalar_t* u_vals = reinterpret_cast<const scalar_t*>(&uv);
        float4 ov;
        scalar_t* o_vals = reinterpret_cast<scalar_t*>(&ov);
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            float g = static_cast<float>(g_vals[j]);
            float u = static_cast<float>(u_vals[j]);
            float silu_g = g / (1.0f + expf(-g));
            o_vals[j] = static_cast<scalar_t>(silu_g * u);
        }
        reinterpret_cast<float4*>(gate)[base_vec] = ov;
    }
    int tail_start = n_vec * VEC;
    int base_scalar = tail_start + (blockIdx.x * blockDim.x + threadIdx.x);
    if (base_scalar < N) {
        float g = static_cast<float>(gate[base_scalar]);
        float u = static_cast<float>(up[base_scalar]);
        float silu_g = g / (1.0f + expf(-g));
        gate[base_scalar] = static_cast<scalar_t>(silu_g * u);
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
    int n_vec = N / 8;
    int blocks = (n_vec + threads - 1) / threads;
    if (N % 8 != 0) blocks = max(blocks, (N + threads - 1) / threads);

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
