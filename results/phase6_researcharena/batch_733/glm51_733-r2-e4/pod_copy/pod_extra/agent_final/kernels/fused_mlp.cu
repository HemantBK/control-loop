/*
 * Fused SwiGLU MLP CUDA kernel — optimized implementation
 *
 * Uses cuBLAS (via torch::matmul) for the heavy GEMM work,
 * then fuses the SiLU activation + elementwise multiply in-place.
 *
 * Optimizations:
 * - Concurrent GEMM execution on separate CUDA streams
 * - half2 vectorized loads/stores (2x fewer memory transactions for fp16)
 * - 8 elements per thread for half2 path (better ILP, fewer blocks)
 */

#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>
#include <type_traits>
#include <ATen/cuda/CUDAContext.h>
#include <c10/cuda/CUDAStream.h>

template <typename scalar_t, bool IS_HALF>
__global__ __launch_bounds__(256)
void fused_silu_mul_inplace_kernel(
    scalar_t* __restrict__ gate,
    const scalar_t* __restrict__ up,
    int N
) {
    if (IS_HALF) {
        int base_idx = (blockIdx.x * blockDim.x + threadIdx.x) * 8;
        const half2* gate_h2 = (const half2*)gate;
        const half2* up_h2 = (const half2*)up;
        half2* out_h2 = (half2*)gate;
        #pragma unroll
        for (int i = 0; i < 4; i++) {
            int idx = (base_idx / 2) + i;
            if (base_idx + i * 2 < N) {
                float2 g = __half22float2(gate_h2[idx]);
                float2 u = __half22float2(up_h2[idx]);
                float silu0 = g.x / (1.0f + expf(-g.x));
                float silu1 = g.y / (1.0f + expf(-g.y));
                out_h2[idx] = __floats2half2_rn(silu0 * u.x, silu1 * u.y);
            }
        }
    } else {
        int base_idx = (blockIdx.x * blockDim.x + threadIdx.x) * 4;
        #pragma unroll
        for (int i = 0; i < 4; i++) {
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

torch::Tensor agent_fused_mlp(
    torch::Tensor input,
    torch::Tensor gate_weight,
    torch::Tensor up_weight
) {
    auto default_stream = at::cuda::getCurrentCUDAStream();
    auto stream2 = at::cuda::getStreamFromPool(false, input.device().index());

    static cudaEvent_t ev_input = nullptr;
    static cudaEvent_t ev_up_done = nullptr;
    if (!ev_input) {
        cudaEventCreateWithFlags(&ev_input, cudaEventDisableTiming);
        cudaEventCreateWithFlags(&ev_up_done, cudaEventDisableTiming);
    }

    cudaEventRecord(ev_input, default_stream.stream());
    cudaStreamWaitEvent(stream2.stream(), ev_input, 0);

    auto gate_proj = torch::mm(input, gate_weight.t());

    torch::Tensor up_proj;
    {
        at::cuda::CUDAStreamGuard guard(stream2);
        up_proj = torch::mm(input, up_weight.t());
    }

    cudaEventRecord(ev_up_done, stream2.stream());
    cudaStreamWaitEvent(default_stream.stream(), ev_up_done, 0);

    int N = gate_proj.numel();
    int threads = 256;

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        input.scalar_type(), "fused_mlp", [&] {
            constexpr bool is_half = std::is_same<scalar_t, at::Half>::value;
            constexpr int ept = is_half ? 8 : 4;
            int blocks = (N + threads * ept - 1) / (threads * ept);
            fused_silu_mul_inplace_kernel<scalar_t, is_half><<<blocks, threads>>>(
                gate_proj.data_ptr<scalar_t>(),
                up_proj.data_ptr<scalar_t>(),
                N
            );
        }
    );

    return gate_proj;
}
