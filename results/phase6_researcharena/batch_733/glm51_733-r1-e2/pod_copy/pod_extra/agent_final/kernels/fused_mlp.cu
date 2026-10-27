#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

template <typename scalar_t>
__global__ void fused_silu_mul_inplace_kernel(
    scalar_t* __restrict__ gate,
    const scalar_t* __restrict__ up,
    int N
) {
    int base_idx = (blockIdx.x * blockDim.x + threadIdx.x) * 4;
    #pragma unroll
    for (int i = 0; i < 4; i++) {
        int idx = base_idx + i;
        if (idx < N) {
            float g = static_cast<float>(__ldg(&gate[idx]));
            float u = static_cast<float>(__ldg(&up[idx]));
            float silu_g = g / (1.0f + expf(-g));
            gate[idx] = static_cast<scalar_t>(silu_g * u);
        }
    }
}

__global__ void fused_silu_mul_inplace_kernel_half2(
    __half* __restrict__ gate,
    const __half* __restrict__ up,
    int N
) {
    int vec_N = N / 2;
    int base_idx = (blockIdx.x * blockDim.x + threadIdx.x) * 4;
    #pragma unroll
    for (int i = 0; i < 4; i++) {
        int idx = base_idx + i;
        if (idx < vec_N) {
            half2 gv = __ldg(reinterpret_cast<const half2*>(gate) + idx);
            half2 uv = __ldg(reinterpret_cast<const half2*>(up) + idx);
            float2 gf = __half22float2(gv);
            float2 uf = __half22float2(uv);
            float silu0 = gf.x / (1.0f + expf(-gf.x));
            float silu1 = gf.y / (1.0f + expf(-gf.y));
            half2 out;
            out.x = __float2half(silu0 * uf.x);
            out.y = __float2half(silu1 * uf.y);
            *(reinterpret_cast<half2*>(gate) + idx) = out;
        }
    }
    if (N % 2 != 0 && threadIdx.x == 0 && blockIdx.x == 0) {
        int last = N - 1;
        float g = __half2float(__ldg(&gate[last]));
        float u = __half2float(__ldg(&up[last]));
        float silu_g = g / (1.0f + expf(-g));
        gate[last] = __float2half(silu_g * u);
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
    int threads = 256;

    if (input.scalar_type() == at::ScalarType::Half && N % 2 == 0) {
        int vec_N = N / 2;
        int blocks = (vec_N + threads * 4 - 1) / (threads * 4);
        fused_silu_mul_inplace_kernel_half2<<<blocks, threads>>>(
            reinterpret_cast<__half*>(gate_proj.data_ptr<at::Half>()),
            reinterpret_cast<const __half*>(up_proj.data_ptr<at::Half>()),
            N
        );
    } else {
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
    }

    return gate_proj;
}
