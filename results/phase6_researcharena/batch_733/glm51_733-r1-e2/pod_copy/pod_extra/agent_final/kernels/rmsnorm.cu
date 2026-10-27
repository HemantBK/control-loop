#include <torch/extension.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <math.h>

template <typename scalar_t>
__global__ __launch_bounds__(1024)
void rmsnorm_kernel_scalar(
    const scalar_t* __restrict__ input,
    const scalar_t* __restrict__ weight,
    scalar_t* __restrict__ output,
    int hidden_size,
    float eps
) {
    int row = blockIdx.x;
    const scalar_t* x = input + row * hidden_size;
    scalar_t* o = output + row * hidden_size;

    extern __shared__ float smem[];
    float* s_weight = smem;
    float* s_shared = smem + hidden_size;

    float sum_sq = 0.0f;
    float cached[4];
    int n_cached = 0;

    for (int i = threadIdx.x; i < hidden_size; i += blockDim.x) {
        float val = static_cast<float>(__ldg(&x[i]));
        float w = static_cast<float>(__ldg(&weight[i]));
        s_weight[i] = w;
        cached[n_cached] = val;
        sum_sq += val * val;
        n_cached++;
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);

    int lane = threadIdx.x & 31;
    int warp_id = threadIdx.x >> 5;

    if (lane == 0) s_shared[warp_id] = sum_sq;
    __syncthreads();

    if (warp_id == 0) {
        int num_warps = (blockDim.x + 31) >> 5;
        sum_sq = (lane < num_warps) ? s_shared[lane] : 0.0f;
        for (int offset = warpSize / 2; offset > 0; offset >>= 1)
            sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);
    }

    if (threadIdx.x == 0) {
        s_shared[32] = rsqrtf(sum_sq / hidden_size + eps);
    }
    __syncthreads();

    float rms_inv = s_shared[32];

    int ci = 0;
    for (int i = threadIdx.x; i < hidden_size; i += blockDim.x) {
        float w = s_weight[i];
        o[i] = static_cast<scalar_t>(cached[ci] * rms_inv * w);
        ci++;
    }
}

__global__ __launch_bounds__(1024)
void rmsnorm_kernel_half2(
    const __half* __restrict__ input,
    const __half* __restrict__ weight,
    __half* __restrict__ output,
    int hidden_size,
    float eps
) {
    int row = blockIdx.x;
    int vec_size = hidden_size / 2;
    const half2* x_vec = reinterpret_cast<const half2*>(input + row * hidden_size);
    const half2* w_vec = reinterpret_cast<const half2*>(weight);
    half2* o_vec = reinterpret_cast<half2*>(output + row * hidden_size);

    extern __shared__ float smem[];
    float* s_weight = smem;
    float* s_shared = smem + hidden_size;

    float sum_sq = 0.0f;
    float c0a[4], c0b[4];
    int n_cached = 0;

    for (int i = threadIdx.x; i < vec_size; i += blockDim.x) {
        half2 xv = __ldg(&x_vec[i]);
        half2 wv = __ldg(&w_vec[i]);
        float2 xf = __half22float2(xv);
        float2 wf = __half22float2(wv);
        s_weight[i * 2] = wf.x;
        s_weight[i * 2 + 1] = wf.y;
        c0a[n_cached] = xf.x;
        c0b[n_cached] = xf.y;
        sum_sq += xf.x * xf.x + xf.y * xf.y;
        n_cached++;
    }

    for (int offset = warpSize / 2; offset > 0; offset >>= 1)
        sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);

    int lane = threadIdx.x & 31;
    int warp_id = threadIdx.x >> 5;

    if (lane == 0) s_shared[warp_id] = sum_sq;
    __syncthreads();

    if (warp_id == 0) {
        int num_warps = (blockDim.x + 31) >> 5;
        sum_sq = (lane < num_warps) ? s_shared[lane] : 0.0f;
        for (int offset = warpSize / 2; offset > 0; offset >>= 1)
            sum_sq += __shfl_down_sync(0xffffffff, sum_sq, offset);
    }

    if (threadIdx.x == 0) {
        s_shared[32] = rsqrtf(sum_sq / hidden_size + eps);
    }
    __syncthreads();

    float rms_inv = s_shared[32];

    int ci = 0;
    for (int i = threadIdx.x; i < vec_size; i += blockDim.x) {
        float w0 = s_weight[i * 2];
        float w1 = s_weight[i * 2 + 1];
        float2 out_f;
        out_f.x = c0a[ci] * rms_inv * w0;
        out_f.y = c0b[ci] * rms_inv * w1;
        o_vec[i] = __float22half2_rn(out_f);
        ci++;
    }
}

torch::Tensor agent_rmsnorm(torch::Tensor input, torch::Tensor weight, double eps) {
    auto output = torch::empty_like(input);
    int batch = input.size(0);
    int hidden = input.size(1);

    dim3 grid(batch);
    size_t smem_size = (hidden + 33) * sizeof(float);

    if (input.scalar_type() == at::ScalarType::Half && hidden % 2 == 0) {
        dim3 block(min(hidden / 2, 1024));
        rmsnorm_kernel_half2<<<grid, block, smem_size>>>(
            reinterpret_cast<__half*>(input.data_ptr<at::Half>()),
            reinterpret_cast<__half*>(weight.data_ptr<at::Half>()),
            reinterpret_cast<__half*>(output.data_ptr<at::Half>()),
            hidden, static_cast<float>(eps)
        );
    } else {
        dim3 block(min(hidden, 1024));
        AT_DISPATCH_FLOATING_TYPES_AND2(
            at::ScalarType::Half, at::ScalarType::BFloat16,
            input.scalar_type(), "rmsnorm", [&] {
                rmsnorm_kernel_scalar<scalar_t><<<grid, block, smem_size>>>(
                    input.data_ptr<scalar_t>(),
                    weight.data_ptr<scalar_t>(),
                    output.data_ptr<scalar_t>(),
                    hidden, static_cast<float>(eps)
                );
            }
        );
    }

    return output;
}
