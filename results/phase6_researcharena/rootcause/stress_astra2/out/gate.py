"""Parse saved logs/exit codes; never infer PASS merely from process completion."""
import argparse,json,re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('results',type=Path);a=p.parse_args();r=a.results

def text(name):
 p=r/(name+'.log');return p.read_text(errors='replace') if p.exists() else ''
def rc(name):
 try:return int((r/(name+'.rc')).read_text())
 except (FileNotFoundError,ValueError):return -999

def clean(name):return 'ERROR SUMMARY: 0 errors' in text(name)
canary=(rc('canary-good')==0 and clean('canary-good') and rc('canary-bad')==86 and 'Invalid __global__ write' in text('canary-bad'))
versions=rc('versions')==0
c0=versions and rc('C0-model')==0 and 'C0_PASS' in text('C0-model')
c1=(versions and 'COMPILE_PASS C1' in text('compile') and canary and any(rc(n)==86 and re.search(r'Invalid __global__ (read|write)',text(n)) and re.search(r'rotary_embedding_kernel',text(n)) and re.search(r'rotary_embedding\.cu:\d+',text(n)) for n in ['C1-model','C1-rope']))
verdict={'C0':'PASS' if c0 else 'FAIL','C1':'PASS_EXPECTED_ROPE_FAULT' if c1 else 'FAIL_OR_INCONCLUSIVE'}
for arm in ['C2','C3']:
 memory=versions and ('COMPILE_PASS '+arm) in text('compile') and canary and clean(arm+'-model') and arm+'_MEMORY_PASS steps=3' in text(arm+'-model') and rc(arm+'-model') in [0,3,4]
 numerics=c0 and rc(arm+'-model')==0 and arm+'_NUMERIC_PASS' in text(arm+'-model')
 for task in ['rope','attention']:
  n=arm+'-'+task
  memory=memory and clean(n) and arm+'_'+task.upper()+'_MEMORY_COMPLETE' in text(n) and rc(n) in [0,3]
  numerics=numerics and rc(n)==0 and arm+'_'+task.upper()+'_NUMERIC_PASS' in text(n)
 sync=rc(arm+'-synccheck')==0 and clean(arm+'-synccheck')
 verdict[arm]='PASS' if memory and numerics and sync else 'FAIL'
 verdict[arm+'_memory']='PASS' if memory else 'FAIL_OR_UNKNOWN'
 verdict[arm+'_numeric']='PASS' if numerics else 'FAIL_OR_UNKNOWN'
 verdict[arm+'_synccheck']='PASS' if sync else 'FAIL_OR_UNKNOWN'
selected=next((arm for arm in ['C2','C3'] if verdict[arm]=='PASS'),None)
# The real episode is outside the supplied repository. Owner adapter must attest artifacts, not TPS only.
if selected is None:verdict['C4']='SKIP_NO_CORRECT_PATCHED_ARM'
else:
 try:
  d=json.loads((r/'C4/episode_result.json').read_text())
  ok=(rc('C4-episode')==0 and d['arm']==selected and d['compile_status']=='PASS' and d['runtime_error'] is None and d['episode_complete'] is True and d['evaluation_complete'] is True and d['correctness_pass'] is True and d['agent_tps']>0 and d['baseline_tps']>0 and all(d['injected'][n] for n in ['rotary_embedding','attention','rmsnorm','fused_mlp']) and len(d['artifacts'])>0 and all((r/'C4'/f).is_file() for f in d['artifacts']))
 except (OSError,ValueError,KeyError,TypeError):ok=False
 verdict['C4']='PASS' if ok else 'FAIL_OR_NOT_RUN'
(r/'gates.json').write_text(json.dumps(verdict,indent=2))
(r/'selected.txt').write_text(selected or '')
for k,v in verdict.items():print(k+'_'+v)
