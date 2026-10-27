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
    int vec_size = N / 8;
    int tid = threadIdx.x;
    int bdim = blockDim.x;

    for (int i = tid; i < vec_size; i += bdim) {
        uint4 gv = reinterpret_cast<uint4*>(gate)[i];
        const uint4 uv = reinterpret_cast<const uint4*>(up)[i];

        scalar_t* gh = reinterpret_cast<scalar_t*>(&gv);
        const scalar_t* uh = reinterpret_cast<const scalar_t*>(&uv);

        uint4 ov;
        scalar_t* oh = reinterpret_cast<scalar_t*>(&ov);

        #pragma unroll
        for (int j = 0; j < 8; j++) {
            float g = static_cast<float>(gh[j]);
            float u = static_cast<float>(uh[j]);
            float silu_g = g / (1.0f + expf(-g));
            oh[j] = static_cast<scalar_t>(silu_g * u);
        }
        reinterpret_cast<uint4*>(gate)[i] = ov;
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
    int vec_size = N / 8;
    int blocks = (vec_size + threads - 1) / threads;

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
