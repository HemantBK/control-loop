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
__global__ __launch_bounds__(256, 4)
void fused_silu_mul_inplace_kernel(
    scalar_t* __restrict__ gate,
    const scalar_t* __restrict__ up,
    int N
) {
    constexpr int VEC_SIZE = sizeof(float4) / sizeof(scalar_t);
    int num_vecs = N / VEC_SIZE;
    float4* gate_vec = reinterpret_cast<float4*>(gate);
    const float4* up_vec = reinterpret_cast<const float4*>(up);

    for (int i = blockIdx.x * blockDim.x + threadIdx.x; i < num_vecs; i += blockDim.x * gridDim.x) {
        float4 gv = gate_vec[i];
        float4 uv = up_vec[i];
        float4 ov;
        const scalar_t* g_vals = reinterpret_cast<const scalar_t*>(&gv);
        const scalar_t* u_vals = reinterpret_cast<const scalar_t*>(&uv);
        scalar_t* o_vals = reinterpret_cast<scalar_t*>(&ov);
        #pragma unroll
        for (int j = 0; j < VEC_SIZE; j++) {
            float g = static_cast<float>(g_vals[j]);
            float u = static_cast<float>(u_vals[j]);
            float silu_g = g / (1.0f + expf(-g));
            o_vals[j] = static_cast<scalar_t>(silu_g * u);
        }
        gate_vec[i] = ov;
    }

    int rem_start = num_vecs * VEC_SIZE;
    for (int i = rem_start + blockIdx.x * blockDim.x + threadIdx.x; i < N; i += blockDim.x * gridDim.x) {
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

    int elem_size = gate_proj.element_size();
    int vec_size = sizeof(float4) / elem_size;
    int num_vecs = N / vec_size;

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

    return gate_proj;  // modified in-place, no extra allocation
}
