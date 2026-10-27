/*
 * Fused SwiGLU MLP CUDA kernel — optimized implementation
 *
 * Uses cuBLAS (via torch::matmul) for the heavy GEMM work,
 * then fuses the SiLU activation + elementwise multiply in-place.
 *
 * Optimization: vectorized 8-byte loads/stores (uint2) for 2-byte dtypes,
 * processing VEC=4 elements per transaction to reduce load/store count.
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
    constexpr int VEC = 4;
    int vec_N = (N / VEC) * VEC;
    int base_idx = (blockIdx.x * blockDim.x + threadIdx.x) * VEC;

    if (base_idx + VEC <= vec_N) {
        uint2 vg = *reinterpret_cast<const uint2*>(&gate[base_idx]);
        uint2 vu = *reinterpret_cast<const uint2*>(&up[base_idx]);
        const scalar_t* pg = reinterpret_cast<const scalar_t*>(&vg);
        const scalar_t* pu = reinterpret_cast<const scalar_t*>(&vu);
        union { uint2 u; scalar_t s[VEC]; } out;
        #pragma unroll
        for (int j = 0; j < VEC; j++) {
            float g = static_cast<float>(pg[j]);
            float u = static_cast<float>(pu[j]);
            float silu_g = g / (1.0f + expf(-g));
            out.s[j] = static_cast<scalar_t>(silu_g * u);
        }
        *reinterpret_cast<uint2*>(&gate[base_idx]) = out.u;
    } else {
        #pragma unroll
        for (int i = 0; i < VEC; i++) {
            int idx = base_idx + i;
            if (idx < N) {
                float g = static_cast<float>(gate[idx]);
                float u = static_cast<float>(up[idx]);
                float silu_g = g / (1.0f + expf(-g));
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
    auto gate_proj = torch::mm(input, gate_weight.t());
    auto up_proj = torch::mm(input, up_weight.t());

    int N = gate_proj.numel();

    constexpr int VEC = 4;
    int threads = 256;
    int blocks = (N + threads * VEC - 1) / (threads * VEC);

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
