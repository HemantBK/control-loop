import json, pathlib, urllib.request, tarfile, hashlib
r=json.load(open(pathlib.Path.home()/'out/raw/cuda_redistrib.json')); dst=pathlib.Path.home()/'work/cuda'; dst.mkdir(exist_ok=True)
for key in ['cuda_nvcc','cuda_cudart','cuda_cccl','cuda_sanitizer_api']:
    a=r[key]['linux-x86_64']; p=pathlib.Path.home()/'work'/pathlib.Path(a['relative_path']).name
    if not p.exists(): urllib.request.urlretrieve('https://developer.download.nvidia.com/compute/cuda/redist/'+a['relative_path'],p)
    assert hashlib.sha256(p.read_bytes()).hexdigest()==a['sha256']
    with tarfile.open(p) as t:
        for m in t.getmembers():
            m.name='/'.join(m.name.split('/')[1:])
            if m.name:t.extract(m,dst,filter='data')
    print(key,a['sha256'],flush=True)
