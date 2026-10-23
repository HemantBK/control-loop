from pathlib import Path
import hashlib,json,sys,traceback
import torch
from torch.utils.cpp_extension import load
out=Path(__file__).resolve().parent
failed=False
for arm in ['C1','C2','C3']:
 try:
  root=out/'arms'/arm;build=out/'build'/arm;build.mkdir(parents=True,exist_ok=True)
  sources=[root/'bindings.cpp']+sorted((root/'kernels').glob('*.cu'))
  print('SOURCE_SHA256',arm,json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources+[root/'inject.py']}),flush=True)
  m=load(name='review_'+arm,sources=list(map(str,sources)),build_directory=str(build),extra_cuda_cflags=['-O3','--use_fast_math','-lineinfo'],extra_cflags=['-O3'],verbose=True)
  assert all(hasattr(m,n) for n in ['rotary_embedding','attention','rmsnorm','fused_mlp'])
  print('COMPILE_PASS '+arm,flush=True)
 except Exception:
  traceback.print_exc();print('COMPILE_FAIL '+arm,flush=True);failed=True
print('NO_GPU_KERNEL_EXECUTION performed by compile check; CUDA available='+str(torch.cuda.is_available()))
sys.exit(1 if failed else 0)
