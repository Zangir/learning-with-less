"""Bounded TAR header walk and one December first-hour L2 member acquisition."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request
import urllib.error
import lz4.frame

ROOT=Path(__file__).resolve().parent
LEDGER=ROOT/'acquisition_probe_ledger.json'
plan=json.loads(LEDGER.read_text())
plan['additional_authorization']={'utc':dt.datetime.now(dt.timezone.utc).isoformat(),'header_ceiling_bytes':1048576,'member_ceiling_bytes':4194304,'target':'data/20251201/0/l2Book/BTC.lz4','reason':'Paired snapshot comparison with existing participant-linked nominal00hour','free_disk_before':shutil.disk_usage(Path.cwd()).free}
assert plan['additional_authorization']['free_disk_before']>=50*2**30

def save():LEDGER.write_text(json.dumps(plan,indent=2))
def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def fetch(start,size,kind):
    rec={'kind':kind,'range_start':start,'expected_response_bytes':size,'requested_range':f'bytes={start}-{start+size-1}','started_at':now(),'body_bytes_consumed':0}
    plan['transfers'].append(rec);save()
    try:
        req=urllib.request.Request(plan['url'],headers={'Range':rec['requested_range'],'Accept-Encoding':'identity'})
        with urllib.request.urlopen(req,timeout=20) as response:
            rec.update(status=response.status,content_range=response.headers.get('Content-Range'),content_length=response.headers.get('Content-Length'))
            expected=f'bytes {start}-{start+size-1}/933171200'
            if response.status!=206 or rec['content_range']!=expected:raise RuntimeError('Range not honored; body refused')
            body=response.read(size);rec['body_bytes_consumed']=len(body)
        if len(body)!=size:raise RuntimeError('Truncated range')
        rec['sha256']=hashlib.sha256(body).hexdigest();rec['finished_at']=now();save();return body
    except Exception as error:
        rec['error']=str(error);rec['finished_at']=now();save();raise

save()
position=2048+((1487910+511)//512)*512
headers=0
found=False
members=[]
while headers<1048576:
    raw=fetch(position,512,'tar_header_index');headers+=len(raw)
    if not raw.strip(b'\0'):break
    info=tarfile.TarInfo.frombuf(raw,'utf-8','surrogateescape')
    member={'path':info.name,'size':info.size,'header_offset':position,'data_offset':position+512,'type':info.type.decode()}
    members.append(member)
    (ROOT/'december_tar_index_partial.json').write_text(json.dumps(members,indent=2))
    print(member,flush=True)
    if info.name=='data/20251201/0/l2Book/BTC.lz4':
        assert info.size<=4194304
        body=fetch(position+512,info.size,'paired_hour00_l2Book_member')
        (ROOT/'btc_20251201_00.lz4').write_bytes(body)
        dec=lz4.frame.LZ4FrameDecompressor();unpacked=dec.decompress(body,max_length=128*2**20)
        assert dec.eof
        (ROOT/'btc_20251201_00.jsonl').write_bytes(unpacked)
        first=json.loads(unpacked.splitlines()[0]);last=json.loads(unpacked.splitlines()[-1])
        result={'member':member,'compressed_bytes':len(body),'compressed_sha256':hashlib.sha256(body).hexdigest(),'decompressed_bytes':len(unpacked),'decompressed_sha256':hashlib.sha256(unpacked).hexdigest(),'records':len(unpacked.splitlines()),'first_exchange_ms':first['raw']['data']['time'],'last_exchange_ms':last['raw']['data']['time'],'first_outer_time':first['time'],'last_outer_time':last['time']}
        (ROOT/'paired_hour00_acquisition_result.json').write_text(json.dumps(result,indent=2));print(result,flush=True);found=True;break
    position+=512+((info.size+511)//512)*512
plan['additional_result']={'found':found,'header_bytes':headers,'finished_at':now()};save()
