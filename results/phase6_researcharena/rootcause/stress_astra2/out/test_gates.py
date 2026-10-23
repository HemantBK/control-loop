from pathlib import Path
import tempfile,subprocess,sys,json
script=Path(__file__).with_name('gate.py')
with tempfile.TemporaryDirectory() as d:
 r=Path(d)
 def put(n,t,rc=0):
  (r/(n+'.log')).write_text(t);(r/(n+'.rc')).write_text(str(rc))
 def get():
  subprocess.run([sys.executable,str(script),str(r)],check=True,stdout=subprocess.DEVNULL)
  return json.loads((r/'gates.json').read_text())
 assert get()['C0']=='FAIL' and get()['C4'].startswith('SKIP')
 put('versions','versions checked')
 put('compile','COMPILE_PASS C1\nCOMPILE_PASS C2\nCOMPILE_PASS C3')
 put('canary-good','ERROR SUMMARY: 0 errors')
 put('canary-bad','Invalid __global__ write',86)
 put('C0-model','C0_PASS')
 put('C1-rope','Invalid __global__ read\nrotary_embedding_kernel\nrotary_embedding.cu:34',86)
 for arm in ['C2','C3']:
  put(arm+'-model',arm+'_MEMORY_PASS steps=3\n'+arm+'_NUMERIC_PASS\nERROR SUMMARY: 0 errors')
  for task in ['rope','attention']:
   put(arm+'-'+task,arm+'_'+task.upper()+'_MEMORY_COMPLETE\n'+arm+'_'+task.upper()+'_NUMERIC_PASS\nERROR SUMMARY: 0 errors')
  put(arm+'-synccheck','ERROR SUMMARY: 0 errors')
 v=get();assert v['C1']=='PASS_EXPECTED_ROPE_FAULT' and v['C2']=='PASS' and v['C3']=='PASS'
 put('C2-model','C2_MEMORY_PASS steps=3\nC2_NUMERIC_FAIL\nERROR SUMMARY: 0 errors',3)
 assert get()['C2']=='FAIL' and get()['C2_memory']=='PASS'
 put('C3-model','C3_MEMORY_PASS steps=3\nC3_NUMERIC_PASS\nERROR SUMMARY: 0 errors',124)
 assert get()['C3']=='FAIL' and get()['C4'].startswith('SKIP')
print('GATE_TEST_PASS missing logs, positive fixtures, numeric fail, timeout rejected; synthetic only')
