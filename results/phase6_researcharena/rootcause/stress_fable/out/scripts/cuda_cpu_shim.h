// Minimal "CUDA on CPU" shim so a kernel template body can be compiled by g++ (with AddressSanitizer) and driven
// thread-by-thread. Only what rotary_embedding.cu's kernel uses.
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
// glibc declares __expf/__logf/__sincosf itself; redirect the CUDA intrinsic names used by the kernel text
#define __expf cuda_expf
#define __logf cuda_logf
#define __sincosf cuda_sincosf
#define __fdividef cuda_fdividef
