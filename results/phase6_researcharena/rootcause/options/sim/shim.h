// Minimal "CUDA on CPU" shim (Amendment (14) option checks): lets the rotary kernel's template body compile with g++ and be
// driven thread by thread. Covers what the stock and 11ea904 rotary kernels use.
#pragma once
#include <cmath>
#include <cstdint>
struct dim3s { unsigned x, y, z; };
static dim3s blockIdx{0,0,0}, blockDim{256,1,1}, threadIdx{0,0,0}, gridDim{1,1,1};
#define __global__
#define __device__
static inline float cuda_expf(float a) { return expf(a); }
static inline float cuda_logf(float a) { return logf(a); }
static inline float cuda_fdividef(float a, float b) { return a / b; }
static inline void cuda_sincosf(float a, float* s, float* c) { *s = sinf(a); *c = cosf(a); }
#define __expf cuda_expf
#define __logf cuda_logf
#define __sincosf cuda_sincosf
#define __fdividef cuda_fdividef
