from pathlib import Path
import shutil,difflib
out=Path(__file__).resolve().parent
stock=Path.home()/'ResearchArena/58776e0/settings/cuda_kernel/task_context'
for arm in ['C1','C2','C3']:
 dst=out/'arms'/arm
 shutil.copytree(stock,dst,dirs_exist_ok=True)
 if arm=='C1':continue
 p=dst/'kernels/rotary_embedding.cu';s=p.read_text()
 s=s.replace('#include <math.h>','#include <math.h>\n#include <climits>')
 s=s.replace('    float base\n','    float base,\n    int total_pairs\n')
 s=s.replace('    int half_dim = head_dim / 2;','    if (idx >= total_pairs) return;\n    int half_dim = head_dim / 2;',1)
 s=s.replace('    auto output = x.clone();','''    TORCH_CHECK(x.is_cuda() && positions.is_cuda(), "RoPE requires CUDA tensors");
    TORCH_CHECK(x.device() == positions.device(), "RoPE device mismatch");
    TORCH_CHECK(x.dim() == 4 && positions.dim() == 2, "RoPE rank mismatch");
    TORCH_CHECK(positions.scalar_type() == at::kInt, "RoPE positions must be int32");
    TORCH_CHECK(x.size(3) > 0 && x.size(3) % 2 == 0, "RoPE requires even head_dim");
    TORCH_CHECK(positions.size(0) == x.size(0) && positions.size(1) == x.size(1),
                "RoPE positions shape mismatch");
    TORCH_CHECK(x.numel() <= INT_MAX - 512, "RoPE indexing exceeds int32 range");
    x = x.contiguous();
    positions = positions.contiguous();
    auto output = x.clone();
    if (x.numel() == 0) return output;''')
 s=s.replace('                static_cast<float>(base)','                static_cast<float>(base), total_pairs')
 p.write_text(s)
 if arm=='C3':
  p=dst/'kernels/attention.cu';s=p.read_text().replace('    int threads = min(kv_len, 256);','''    // Full-mask shuffles require full warps, including the first reduction warp.
    int threads = min(((kv_len + 31) / 32) * 32, 256);''');p.write_text(s)
for label,files,a,b in [('rope-safety',['kernels/rotary_embedding.cu'],'C1','C2'),('attention-warps',['kernels/attention.cu'],'C2','C3')]:
 diff=''
 for f in files:
  diff+=''.join(difflib.unified_diff((out/'arms'/a/f).read_text().splitlines(True),(out/'arms'/b/f).read_text().splitlines(True),fromfile='a/'+f,tofile='b/'+f))
 (out/(label+'.patch')).write_text(diff)
print('PATCHES_READY stock preserved; C2 safety only; C3 adds attention full-warps')
