#include <cuda_runtime.h>
#include <cstdio>
__global__ void canary(int *p, int bad) { if (threadIdx.x==0) p[bad ? 1024 : 0]=17; }
int main(int argc,char**) { int *p; if(cudaMalloc(&p,1024*sizeof(int))!=cudaSuccess)return 2;
canary<<<1,32>>>(p,argc>1);cudaError_t e=cudaDeviceSynchronize();
if(e!=cudaSuccess){fprintf(stderr,"CANARY_CUDA_ERROR %s\n",cudaGetErrorString(e));return 1;}
cudaFree(p);puts("CANARY_DONE");return 0; }
