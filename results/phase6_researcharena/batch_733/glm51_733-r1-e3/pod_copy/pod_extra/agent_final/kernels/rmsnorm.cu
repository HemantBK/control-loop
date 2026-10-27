#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

template <typename scalar_t>
__global__ __launch_bounds__(256)
void rmsnorm_kernel(
    const scalar_t* __restrict__ input,
    const scalar_t* __restrict__ weight,
    scalar_t* __restrict__ output,
    int hidden_size,
    float eps
) {
    int row = blockIdx.x;
    const scalar_t* x = input + row * hidden_size;
    scalar_t* o = output + row * hidden_size;

    const int VEC_ELEMS = 16 / (int)sizeof(scalar_t);
    const int num_vecs = hidden_size / VEC_ELEMS;

    extern __shared__ float smem[];
    float* s_input = smem;
    float* shared = smem + hidden_size;

    float sum_sq = 0.0f;
    for (int vi = threadIdx.x; vi < num_vecs; vi += blockDim.x) {
        const float4 xv = __ldg(reinterpret_cast<const float4*>(x) + vi);
        const scalar_t* xe = reinterpret_cast<const scalar_t*>(&xv);
        #pragma unroll
        for (int j = 0; j < VEC_ELEMS; j++) {
            float val = static_cast<float>(xe[j]);
            s_input[vi * VEC_ELEMS + j] = val;
            sum_sq += val * val;
        }
    }
    for (int i = num_vecs * VEC_ELEMS + threadIdx.x; i < hidden_size; i += blockDim.x) {
        float val = static_cast<float>(__ldg(&x[i]));
        s_input[i] = val;
        sum_sq += val * val;
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);

    int lane = threadIdx.x & 31;
    int warp_id = threadIdx.x >> 5;
    int num_warps = (blockDim.x + 31) >> 5;

    if (lane == 0) shared[warp_id] = sum_sq;
    __syncthreads();

    float sum_sq_final = 0.0f;
    for (int i = lane; i < num_warps; i += 32) {
        sum_sq_final += shared[i];
    }
    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        sum_sq_final += __shfl_down_sync(0xffffffff, sum_sq_final, offset);

    float rms_inv;
    if (lane == 0) {
        rms_inv = rsqrtf(sum_sq_final / hidden_size + eps);
    }
    rms_inv = __shfl_sync(0xffffffff, rms_inv, 0);

    for (int i = threadIdx.x; i < hidden_size; i += blockDim.x) {
        float val = s_input[i];
        float w = static_cast<float>(__ldg(&weight[i]));
        o[i] = static_cast<scalar_t>(val * rms_inv * w);
    }
}

torch::Tensor agent_rmsnorm(torch::Tensor input, torch::Tensor weight, double eps) {
    auto output = torch::empty_like(input);
    int batch = input.size(0);
    int hidden = input.size(1);

    int block_size = min(max(hidden, 64), 512);
    block_size = ((block_size + 31) / 32) * 32;

    dim3 grid(batch);
    dim3 block(block_size);
    size_t smem_size = (hidden + 32) * sizeof(float);

    AT_DISPATCH_FLOATING_TYPES_AND2(
        at::ScalarType::Half, at::ScalarType::BFloat16,
        input.scalar_type(), "rmsnorm", [&] {
            rmsnorm_kernel<scalar_t><<<grid, block, smem_size>>>(
                input.data_ptr<scalar_t>(),
                weight.data_ptr<scalar_t>(),
                output.data_ptr<scalar_t>(),
                hidden, static_cast<float>(eps)
            );
        }
    );

    return output;
}
