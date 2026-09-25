import requests, tarfile, io, json
from pathlib import Path
out=(Path(__file__).resolve().parents[1] / 'runtime')
u='https://zenodo.org/api/records/18184441/files/book_diffs_202512.tar/content'
r=requests.get(u,headers={'Range':'bytes=0-511','Accept-Encoding':'identity'},stream=True,timeout=(15,30))
print(r.status_code,dict(r.headers),flush=True)
assert r.status_code==206
b=r.raw.read(512)
(out/'probe_header.bin').write_bytes(b)
t=tarfile.TarInfo.frombuf(b,'utf8','strict')
print(t.name,t.size,t.type,flush=True)
(out/'probe.json').write_text(json.dumps({'status':r.status_code,'headers':dict(r.headers),'bytes':len(b),'name':t.name,'size':t.size},indent=2))
