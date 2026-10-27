/*
 * Fused SwiGLU MLP CUDA kernel — optimized implementation
 *
 * Uses cuBLAS (via torch::matmul) for the heavy GEMM work,
 * then fuses the SiLU activation + elementwise multiply in-place.
 *
 * Optimizations over baseline:
 *   - float4 vectorized loads/stores (8 half or 4 float per load)
 *   - Process vec_elems * UNROLL elements per thread
 *   - __launch_bounds__ for better register allocation
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
    constexpr int VEC_ELEMS = sizeof(float4) / sizeof(scalar_t);
    const int num_vecs = N / VEC_ELEMS;
    const int remainder_start = num_vecs * VEC_ELEMS;

    float4* vec_gate = reinterpret_cast<float4*>(gate);
    const float4* vec_up = reinterpret_cast<const float4*>(up);

    int idx = blockIdx.x * blockDim.x + threadIdx.x;

    if (idx < num_vecs) {
        float4 vg = vec_gate[idx];
        float4 vu = vec_up[idx];
        scalar_t* sg = reinterpret_cast<scalar_t*>(&vg);
        const scalar_t* su = reinterpret_cast<const scalar_t*>(&vu);
        float4 vo;
        scalar_t* so = reinterpret_cast<scalar_t*>(&vo);
        #pragma unroll
        for (int j = 0; j < VEC_ELEMS; j++) {
            float g = static_cast<float>(sg[j]);
            float u = static_cast<float>(su[j]);
            float silu_g = g / (1.0f + expf(-g));
            so[j] = static_cast<scalar_t>(silu_g * u);
        }
        vec_gate[idx] = vo;
    }

    int rem_idx = remainder_start + idx;
    if (rem_idx < N) {
        float g = static_cast<float>(gate[rem_idx]);
        float u = static_cast<float>(up[rem_idx]);
        float silu_g = g / (1.0f + expf(-g));
        gate[rem_idx] = static_cast<scalar_t>(silu_g * u);
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

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        input.scalar_type(), "fused_mlp", [&] {
            constexpr int VEC_ELEMS = sizeof(float4) / sizeof(scalar_t);
            int num_vecs = N / VEC_ELEMS;
            int threads = 256;
            int blocks = (num_vecs + threads - 1) / threads;
            if (blocks == 0) blocks = 1;

            fused_silu_mul_inplace_kernel<scalar_t><<<blocks, threads>>>(
                gate_proj.data_ptr<scalar_t>(),
                up_proj.data_ptr<scalar_t>(),
                N
            );
        }
    );

    return gate_proj;
}
