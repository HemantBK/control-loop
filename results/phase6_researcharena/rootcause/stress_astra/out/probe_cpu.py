import json, inspect, os, sys, re
import torch, transformers
from transformers import AutoModelForCausalLM, AutoTokenizer
from transformers.models.llama import modeling_llama as lm
from transformers.cache_utils import DynamicCache
import torch.nn.functional as F
from pathlib import Path
root=Path(os.environ.get('STOCK',str(Path.home()/'ResearchArena/58776e0/settings/cuda_kernel/task_context')))
text=(root/'kernels/rotary_embedding.cu').read_text()
assert 'int total_pairs = batch * seq_len * num_heads * half_dim;' in text
threads=int(re.search(r'int threads = (\d+);',text).group(1))
def meta(t):
    if t is None:return None
    return dict(shape=list(t.shape),stride=list(t.stride()),contiguous=t.is_contiguous(),dtype=str(t.dtype))
def emit(event,**kw):print(json.dumps(dict(event=event,step=step,**kw)),flush=True)
def launch(t):
    # Exactly inject.py:162-165 and rotary_embedding.cu:62-70, then enumerate :24-51.
    x=t.permute(0,2,1,3).contiguous(); b,s,h,d=x.shape
    n=b*s*h*(d//2); blocks=(n+threads-1)//threads
    pos=[]; offs=[]
    for idx in range(blocks*threads):
        pair=idx%(d//2); tmp=idx//(d//2); head=tmp%h; tmp2=tmp//h; seq=tmp2%s; batch=tmp2//s
        pos.append(batch*s+seq); base=((batch*s+seq)*h+head)*d; offs.extend([base+2*pair,base+2*pair+1])
    return dict(input=meta(x),pairs=n,grid=[blocks,1,1],block=[threads,1,1],launched_pairs=blocks*threads,elements=x.numel(),accessed_elements=len(offs),max_element=max(offs),oob_element_accesses=sum(a>=x.numel() for a in offs),positions_numel=b*s,max_position_index=max(pos),oob_position_reads=sum(a>=b*s for a in pos))
step=-1; counts={}; last={}
orig_rope=lm.apply_rotary_pos_emb
orig_cache=DynamicCache.update
orig_sdpa=F.scaled_dot_product_attention
# one record of each event per step: all 22 layers run, counters checked below.
def rope(q,k,cos,sin,*args,**kw):
    counts['rope']=counts.get('rope',0)+1
    if counts['rope']==1:emit('rope_in',q=meta(q),k=meta(k),cos=meta(cos),sin=meta(sin),q_launch=launch(q),k_launch=launch(k))
    qo,ko=orig_rope(q,k,cos,sin,*args,**kw); last['q']=qo
    return qo,ko
def cache(self,key_states,value_states,layer_idx,cache_kwargs=None):
    counts['cache']=counts.get('cache',0)+1
    if layer_idx==0:emit('cache_in',q=meta(last['q']),k=meta(key_states),v=meta(value_states),**{n:meta(v) for n,v in (cache_kwargs or {}).items() if torch.is_tensor(v)})
    r=orig_cache(self,key_states,value_states,layer_idx,cache_kwargs)
    if layer_idx==0:emit('cache_out',q=meta(last['q']),k=meta(r[0]),v=meta(r[1]))
    return r
def sdpa(q,k,v,*args,**kw):
    counts['attention']=counts.get('attention',0)+1
    if counts['attention']==1:emit('attention',q=meta(q),k=meta(k),v=meta(v),is_causal=kw.get('is_causal'))
    return orig_sdpa(q,k,v,*args,**kw)
lm.apply_rotary_pos_emb=rope;DynamicCache.update=cache;F.scaled_dot_product_attention=sdpa
rot_orig=lm.LlamaRotaryEmbedding.forward
def rot(self,x,position_ids):
    emit('positions',position_ids=meta(position_ids),values=position_ids.tolist())
    return rot_orig(self,x,position_ids)
lm.LlamaRotaryEmbedding.forward=rot
torch.set_num_threads(8)
print(json.dumps(dict(torch=torch.__version__,transformers=transformers.__version__,cuda=torch.version.cuda,threads=torch.get_num_threads())),flush=True)
model_id=os.environ.get('MODEL','TinyLlama/TinyLlama-1.1B-Chat-v1.0')
tok=AutoTokenizer.from_pretrained(model_id)
m=AutoModelForCausalLM.from_pretrained(model_id,torch_dtype=torch.float16,attn_implementation='sdpa').eval()
print(json.dumps(dict(model=model_id,config=m.config.to_dict())),flush=True)
for module,name in [(lm,'modeling_llama.py'),(transformers.cache_utils,'cache_utils.py'),(transformers.integrations.sdpa_attention,'sdpa_attention.py')]:
    Path(__file__).with_name('raw').joinpath(name).write_text(inspect.getsource(module))
ids=tok('Explain the theory of relativity in simple terms.',return_tensors='pt').input_ids
past=None
with torch.inference_mode():
    for step in range(3):
        counts={};emit('input',ids=ids.tolist())
        out=m(input_ids=ids,past_key_values=past,use_cache=True)
        assert torch.isfinite(out.logits).all()
        emit('counts',counts=counts)
        assert all(counts[n]==22 for n in ['rope','cache','attention'])
        past=out.past_key_values;ids=out.logits[:,-1:].argmax(-1)
print('A1_PASS dtype=float16 prefill=1 decode=2 layers=22',flush=True)
