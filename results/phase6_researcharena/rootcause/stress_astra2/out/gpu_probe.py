"""Run only after approval, on GPU. Fresh process for every invocation.
No model APIs. Uses downloaded TinyLlama weights, greedy/teacher-forced local inference.
"""
import argparse, importlib, json, os, sys
from pathlib import Path
import torch
import torch.nn.functional as F
p=argparse.ArgumentParser();p.add_argument('--arm',choices=['C0','C1','C2','C3'],required=True)
p.add_argument('--task',choices=['model','rope','attention'],default='model')
p.add_argument('--results',type=Path,required=True);a=p.parse_args()
root=Path(__file__).resolve().parent;a.results.mkdir(parents=True,exist_ok=True)
assert torch.cuda.is_available();assert torch.cuda.current_device()==0
assert torch.cuda.current_stream()==torch.cuda.default_stream()
torch.manual_seed(42);torch.cuda.manual_seed_all(42)
class KernelFailure(BaseException):pass
counts={n:0 for n in ['rotary_embedding','attention','rmsnorm','fused_mlp']}
ops=None
if a.arm!='C0':
 sys.path.insert(0,str(root/'build'/a.arm));raw=importlib.import_module('review_'+a.arm)
 class Strict:
  def __getattr__(self,name):
   fn=getattr(raw,name)
   def call(*args,**kw):
    try:
     r=fn(*args,**kw);torch.cuda.synchronize();counts[name]+=1;return r
    except Exception as e:
     print('KERNEL_FAIL',name,repr(e),flush=True);raise KernelFailure(name) from e
   return call
 ops=Strict()

def rope_test():
 # First case is the exact decode-K OOB reproducer. Real positions, standalone math test.
 for dtype in [torch.float16,torch.bfloat16,torch.float32]:
  for b,s,h in [(1,1,4),(1,1,32),(1,12,4),(1,13,4),(2,3,4)]:
   x=torch.randn(b,h,s,64,device='cuda',dtype=dtype).transpose(1,2)
   pos=torch.arange(12,12+s,device='cuda',dtype=torch.int32)[None].expand(b,-1)
   y=ops.rotary_embedding(x,pos,10000.)
   assert y.shape==x.shape and torch.isfinite(y).all()
   f=pos.float()[...,None]*10000.**(-torch.arange(32,device='cuda').float()*2/64)
   c=f.cos().to(dtype)[:,:,None];sn=f.sin().to(dtype)[:,:,None]
   hf=torch.cat([x[...,:32]*c-x[...,32:]*sn,x[...,32:]*c+x[...,:32]*sn],-1)
   # Do not abort early: log every comparison, then return a mechanical verdict.
   ok=torch.allclose(y,hf,atol=.02,rtol=.02)
   print('ROPE_CASE',str(dtype),[b,s,h,64],bool(ok),'maxabs',float((y-hf).abs().max()),flush=True)
   yield bool(ok)

def attention_test():
 for n in [1,2,12,13,14,31,32,33,255,256,257]:
  for causal in [False,True]:
   q,k,v=[torch.randn(1,32,n,64,device='cuda',dtype=torch.float16) for _ in range(3)]
   y=ops.attention(q,k,v,causal)
   ref=F.scaled_dot_product_attention(q.float(),k.float(),v.float(),is_causal=causal).half()
   ok=bool(torch.isfinite(y).all() and torch.allclose(y,ref,atol=.02,rtol=.02))
   print('ATTENTION_CASE',n,causal,ok,'maxabs',float((y-ref).abs().max()),flush=True)
   yield ok

if a.task!='model':
 assert ops is not None
 checks=list(rope_test() if a.task=='rope' else attention_test())
 print(a.arm+'_'+a.task.upper()+'_MEMORY_COMPLETE',flush=True)
 ok=all(checks);print(a.arm+'_'+a.task.upper()+'_NUMERIC_'+('PASS' if ok else 'FAIL'),flush=True)
 sys.exit(0 if ok else 3)

import transformers
from transformers import AutoModelForCausalLM,AutoTokenizer
assert transformers.__version__=='4.53.3';assert torch.__version__.startswith('2.10.')
model_id=os.environ.get('MODEL','TinyLlama/TinyLlama-1.1B-Chat-v1.0')
tok=AutoTokenizer.from_pretrained(model_id,local_files_only=True)
m=AutoModelForCausalLM.from_pretrained(model_id,torch_dtype=torch.float16,attn_implementation='sdpa',local_files_only=True).cuda().eval()
if ops:
 sys.path.insert(0,str(root/'arms'/a.arm));from inject import inject_agent_kernels
 flags=inject_agent_kernels(m,ops);assert all(flags.values());print('INJECT_FLAGS',json.dumps(flags),flush=True)
reference=a.results/'C0_reference.pt'
ref=torch.load(reference,weights_only=True) if a.arm!='C0' and reference.exists() else None
ids=tok('Explain the theory of relativity in simple terms.',return_tensors='pt').input_ids.cuda()
assert ids.shape==(1,12)
inputs=[];logits=[];cache=None
with torch.inference_mode():
 for step in range(3):
  if ref is not None:ids=ref['inputs'][step].cuda()
  inputs.append(ids.cpu());r=m(input_ids=ids,past_key_values=cache,use_cache=True);torch.cuda.synchronize()
  assert torch.isfinite(r.logits).all();cache=r.past_key_values
  assert cache.key_cache[0].shape==(1,4,12+step,64)
  logits.append(r.logits[:,-1].cpu());ids=r.logits[:,-1:].argmax(-1)
  print('STEP_COMPLETE',step,flush=True)
if ops:
 expected={'rotary_embedding':132,'attention':22,'rmsnorm':132,'fused_mlp':66}
 assert counts==expected,(counts,expected)
print('COUNTS',json.dumps(counts),flush=True)
print(a.arm+'_MEMORY_PASS steps=3',flush=True)
if a.arm=='C0':
 torch.save(dict(inputs=inputs,logits=logits),reference);print('C0_PASS',flush=True)
else:
 if ref is None:
  print(a.arm+'_NUMERIC_UNAVAILABLE C0_missing',flush=True);sys.exit(4)
 ok=all(torch.allclose(x,y,atol=.1,rtol=.05) for x,y in zip(logits,ref['logits']))
 print('LOGITS_MAXABS',[float((x-y).abs().max()) for x,y in zip(logits,ref['logits'])],flush=True)
 print(a.arm+'_NUMERIC_'+('PASS' if ok else 'FAIL'),flush=True)
 sys.exit(0 if ok else 3)
