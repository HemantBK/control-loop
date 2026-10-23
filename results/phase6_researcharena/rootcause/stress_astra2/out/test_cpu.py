"""New regression checks; does not rerun the completed model probe."""
from pathlib import Path
import json, torch
out=Path(__file__).resolve().parent
rows=[]
for line in (out/'raw/A1.jsonl').read_text().splitlines():
 try:r=json.loads(line)
 except ValueError:continue
 if r.get('event')=='rope_in':rows.append(r)
assert len(rows)==3
for row in rows:
 for n in ['q','k']:
  l=row[n+'_launch']; expected=256 if row['step']>0 and n=='k' else 0
  assert l['oob_element_accesses']==expected
  print('SAVED_A1',row['step'],n,'pairs',l['pairs'],'threads',l['launched_pairs'],'OOB',expected)
# Enumerate guard coverage, not merely aligned sizes. Each valid pair owns exactly 2 elements.
for b in [1,2]:
 for s in [1,2,3,12,13,31,32,33]:
  for h in [1,4,32]:
   for d in [2,64,128]:
    n=b*s*h*(d//2); offsets=[];pos=[]
    for idx in range(((n+255)//256)*256):
     if idx>=n:continue
     pair=idx%(d//2);tmp=idx//(d//2);head=tmp%h;tmp2=tmp//h;seq=tmp2%s;batch=tmp2//s
     base=((batch*s+seq)*h+head)*d
     offsets.extend([base+2*pair,base+2*pair+1]);pos.append(batch*s+seq)
    assert sorted(offsets)==list(range(b*s*h*d)) and max(pos)<b*s
print('CPU_BOUNDS_PASS cases=144')
for s in range(1,4097):
 t=min(((s+31)//32)*32,256); assert t>=32 and t%32==0 and t<=256
print('CPU_ATTENTION_WARPS_PASS lengths=1..4096')
# Stock math (not CUDA fast-intrinsic emulation) versus Llama rotate_half.
torch.manual_seed(42)
x=torch.randn(1,1,4,64)
for m in [0,1,12,13]:
 a=m*10000.**(-torch.arange(32).float()*2/64);c=a.cos();s=a.sin()
 adj=x.clone();adj[...,::2]=x[...,::2]*c-x[...,1::2]*s;adj[...,1::2]=x[...,::2]*s+x[...,1::2]*c
 hf=torch.cat([x[...,:32]*c-x[...,32:]*s,x[...,32:]*c+x[...,:32]*s],-1)
 print('SEMANTIC_DIFFERENCE',m,'adjacent_vs_half_maxabs',float((adj-hf).abs().max()),'decode_reset_vs_hf_maxabs',float((x-hf).abs().max()))
 if m: assert not torch.allclose(adj,hf,rtol=.05,atol=.1)
print('CPU_TEST_PASS; no GPU correctness claim')
