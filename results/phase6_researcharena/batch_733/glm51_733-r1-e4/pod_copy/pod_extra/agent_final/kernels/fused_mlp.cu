/*
 * Fused SwiGLU MLP CUDA kernel — optimized implementation
 *
 * Uses cuBLAS (via torch::matmul) for the heavy GEMM work,
 * then fuses the SiLU activation + elementwise multiply in-place.
 *
 * Optimizations:
 * - Gate and up projections on separate CUDA streams for GEMM overlap
 * - Vectorized 128-bit loads/stores (8 elements per iteration) for SiLU+multiply
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>
#include <ATen/cuda/CUDAContext.h>
#include <ATen/cuda/CUDAEvent.h>
#include <c10/cuda/CUDAStream.h>
#include <c10/cuda/CUDAGuard.h>
#include <type_traits>

template <typename scalar_t>
__global__ void fused_silu_mul_inplace_kernel(
    scalar_t* __restrict__ gate,
    const scalar_t* __restrict__ up,
    int N
) {
    constexpr bool is_half = std::is_same<scalar_t, at::Half>::value;

    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    int stride = gridDim.x * blockDim.x;

    int num_vec = N / 8;

    for (int vi = tid; vi < num_vec; vi += stride) {
        uint4 g_vec = reinterpret_cast<const uint4*>(gate)[vi];
        uint4 u_vec = reinterpret_cast<const uint4*>(up)[vi];

        if constexpr (is_half) {
            half2* g_h2 = reinterpret_cast<half2*>(&g_vec);
            half2* u_h2 = reinterpret_cast<half2*>(&u_vec);
            #pragma unroll
            for (int j = 0; j < 4; j++) {
                float2 gf = __half22float2(g_h2[j]);
                float2 uf = __half22float2(u_h2[j]);
                gf.x = (gf.x / (1.0f + expf(-gf.x))) * uf.x;
                gf.y = (gf.y / (1.0f + expf(-gf.y))) * uf.y;
                g_h2[j] = __float22half2_rn(gf);
            }
        } else {
            __nv_bfloat162* g_bf2 = reinterpret_cast<__nv_bfloat162*>(&g_vec);
            __nv_bfloat162* u_bf2 = reinterpret_cast<__nv_bfloat162*>(&u_vec);
            #pragma unroll
            for (int j = 0; j < 4; j++) {
                float2 gf = __bfloat1622float2(g_bf2[j]);
                float2 uf = __bfloat1622float2(u_bf2[j]);
                gf.x = (gf.x / (1.0f + expf(-gf.x))) * uf.x;
                gf.y = (gf.y / (1.0f + expf(-gf.y))) * uf.y;
                g_bf2[j] = __float22bfloat162_rn(gf);
            }
        }

        reinterpret_cast<uint4*>(gate)[vi] = g_vec;
    }

    int scalar_start = num_vec * 8;
    for (int idx = scalar_start + tid; idx < N; idx += stride) {
        float g = static_cast<float>(gate[idx]);
        float u = static_cast<float>(up[idx]);
        float silu_g = g / (1.0f + expf(-g));
        gate[idx] = static_cast<scalar_t>(silu_g * u);
    }
}

torch::Tensor agent_fused_mlp(
    torch::Tensor input,
    torch::Tensor gate_weight,
    torch::Tensor up_weight
) {
    auto stream = at::cuda::getCurrentCUDAStream();
    auto stream2 = c10::cuda::getStreamFromPool();

    at::cuda::CUDAEvent input_ready;
    input_ready.record(stream);
    input_ready.block(stream2);

    auto gate_proj = torch::mm(input, gate_weight.t());

    torch::Tensor up_proj;
    {
        c10::cuda::CUDAStreamGuard guard(stream2);
        up_proj = torch::mm(input, up_weight.t());
    }

    at::cuda::CUDAEvent up_done;
    up_done.record(stream2);
    up_done.block(stream);

    int N = gate_proj.numel();
    int num_vec = N / 8;
    int threads = 256;
    int blocks = (num_vec + threads - 1) / threads;
    blocks = max(blocks, 1);

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        input.scalar_type(), "fused_mlp", [&] {
            fused_silu_mul_inplace_kernel<scalar_t><<<blocks, threads, 0, stream>>>(
                gate_proj.data_ptr<scalar_t>(),
                up_proj.data_ptr<scalar_t>(),
                N
            );
        }
    );

    return gate_proj;
}
