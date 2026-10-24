/*
 * Fused SwiGLU MLP CUDA kernel — optimized implementation
 *
 * Uses cuBLAS (via torch::matmul) for the heavy GEMM work,
 * then fuses the SiLU activation + elementwise multiply in-place.
 *
 * Optimization: for batch=1 (decode), combines gate+up weights into a single
 * GEMM to save one kernel launch per layer. Cached across calls.
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

// In-place fused SiLU-multiply: gate[i] = silu(gate[i]) * up[i]
// 4 elements per thread with strided access for coalesced memory loads
template <typename scalar_t>
__global__ void fused_silu_mul_inplace_kernel(
    scalar_t* __restrict__ gate,         // [N] - modified in place
    const scalar_t* __restrict__ up,     // [N]
    int N
) {
    int tid = threadIdx.x;
    int bdim = blockDim.x;
    int block_start = blockIdx.x * bdim * 4;

    #pragma unroll
    for (int i = 0; i < 4; i++) {
        int idx = block_start + tid + i * bdim;
        if (idx < N) {
            float g = static_cast<float>(gate[idx]);
            float u = static_cast<float>(up[idx]);
            float silu_g = g / (1.0f + expf(-g));
            gate[idx] = static_cast<scalar_t>(silu_g * u);
        }
    }
}

// ─── Host wrapper ────────────────────────────────────────────────────────────

torch::Tensor agent_fused_mlp(
    torch::Tensor input,        // [batch, hidden]
    torch::Tensor gate_weight,  // [intermediate, hidden]
    torch::Tensor up_weight     // [intermediate, hidden]
) {
    int batch = input.size(0);
    int intermediate = gate_weight.size(0);

    torch::Tensor gate_proj, up_proj;

    if (batch == 1) {
        // Combined GEMM for decode (batch=1): concatenate weights once, single launch
        static torch::Tensor cached_combined;
        static void* last_gate_ptr = nullptr;
        static void* last_up_ptr = nullptr;
        void* gp = gate_weight.data_ptr();
        void* up = up_weight.data_ptr();

        if (last_gate_ptr != gp || last_up_ptr != up || cached_combined.numel() == 0) {
            cached_combined = torch::cat({gate_weight, up_weight}, 0);
            last_gate_ptr = gp;
            last_up_ptr = up;
        }

        auto combined_proj = torch::mm(input, cached_combined.t());
        gate_proj = combined_proj.narrow(1, 0, intermediate);
        up_proj = combined_proj.narrow(1, intermediate, intermediate);
    } else {
        // Separate GEMMs for prefill (batch > 1)
        gate_proj = torch::mm(input, gate_weight.t());
        up_proj = torch::mm(input, up_weight.t());
    }

    int N = gate_proj.numel();
    int threads = 256;
    int blocks = (N + threads * 4 - 1) / (threads * 4);

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
