template <typename scalar_t>
__global__ void rotary_embedding_kernel(
    scalar_t* __restrict__ x,          // [batch, seq_len, num_heads, head_dim]
    const int* __restrict__ positions,  // [batch, seq_len]
    int seq_len,
    int num_heads,
    int head_dim,
    float base
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    int half_dim = head_dim / 2;

    int pair_idx = idx % half_dim;
    int tmp = idx / half_dim;
    int head = tmp % num_heads;
    int tmp2 = tmp / num_heads;
    int seq = tmp2 % seq_len;
    int batch = tmp2 / seq_len;

    int m = positions[batch * seq_len + seq];
    // Fast pow: base^(2*pair_idx/head_dim) = exp(log(base) * 2*pair_idx/head_dim)
    float exp_val = __expf(__logf(base) * __fdividef(2.0f * pair_idx, (float)head_dim));
    float theta = __fdividef(1.0f, exp_val);
    float angle = m * theta;

    float cos_val, sin_val;
    __sincosf(angle, &sin_val, &cos_val);

    int base_idx = ((batch * seq_len + seq) * num_heads + head) * head_dim;
    int i0 = base_idx + 2 * pair_idx;
    int i1 = i0 + 1;

    float x0 = static_cast<float>(x[i0]);
    float x1 = static_cast<float>(x[i1]);

    x[i0] = static_cast<scalar_t>(x0 * cos_val - x1 * sin_val);
    x[i1] = static_cast<scalar_t>(x0 * sin_val + x1 * cos_val);
}

