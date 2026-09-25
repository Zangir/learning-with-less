"""Fetch three predeclared BTC historical snapshot members with bounded range reads."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request
import lz4.frame
ROOT=Path(__file__).resolve().parent
LEDGER=ROOT/'acquisition_probe_ledger.json'
plan=json.loads(LEDGER.read_text())
TARGETS={'data/20251208/0/l2Book/BTC.lz4':'train','data/20251216/0/l2Book/BTC.lz4':'validation','data/20251223/0/l2Book/BTC.lz4':'test'}
plan['fixed_date_authorization']={'utc':dt.datetime.now(dt.timezone.utc).isoformat(),'header_ceiling_bytes':1048576,'each_member_ceiling_bytes':4194304,'total_ceiling_bytes':16777216,'targets':TARGETS,'policy':'Dates fixed in r1 plan before observed outcomes; BTC-only exploratory historical pilot; no inferential acceptance','free_disk_before':shutil.disk_usage(Path.cwd()).free}
assert plan['fixed_date_authorization']['free_disk_before']>=50*2**30
found=[]
header_bytes=0
acquisition_bytes=0

def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def save():LEDGER.write_text(json.dumps(plan,indent=2))
def fetch(start,size,kind):
    global acquisition_bytes
    assert acquisition_bytes+size<=16777216
    rec={'kind':kind,'range_start':start,'expected_response_bytes':size,'requested_range':f'bytes={start}-{start+size-1}','started_at':now(),'body_bytes_consumed':0}
    plan['transfers'].append(rec);save()
    try:
        req=urllib.request.Request(plan['url'],headers={'Range':rec['requested_range'],'Accept-Encoding':'identity'})
        with urllib.request.urlopen(req,timeout=20) as response:
            rec.update(status=response.status,content_range=response.headers.get('Content-Range'),content_length=response.headers.get('Content-Length'))
            if response.status!=206 or rec['content_range']!=f'bytes {start}-{start+size-1}/933171200':raise RuntimeError('Range not honored; body refused')
            body=response.read(size);rec['body_bytes_consumed']=len(body);acquisition_bytes+=len(body)
        if len(body)!=size:raise RuntimeError('Truncated range')
        rec['sha256']=hashlib.sha256(body).hexdigest();rec['finished_at']=now();save();return body
    except Exception as error:
        rec['error']=str(error);rec['finished_at']=now();save();raise

save()
index=json.loads((ROOT/'december_tar_index_partial.json').read_text())
last=index[-1]
position=last['data_offset']+((last['size']+511)//512)*512
while header_bytes+1536<=1048576 and len(found)<3:
    block=fetch(position,1536,'fixed_dates_tar_header_index');header_bytes+=len(block)
    consumed=0
    saw_file=False
    while consumed+512<=len(block):
        raw=block[consumed:consumed+512]
        if not raw.strip(b'\0'):raise RuntimeError('Endarchive before targets')
        info=tarfile.TarInfo.frombuf(raw,'utf-8','surrogateescape')
        member={'path':info.name,'size':info.size,'header_offset':position+consumed,'data_offset':position+consumed+512,'type':info.type.decode()}
        index.append(member)
        consumed+=512
        if info.isfile():
            saw_file=True
            print(member['path'],member['size'],flush=True)
            if info.name in TARGETS:
                assert info.size<=4194304
                body=fetch(member['data_offset'],info.size,'fixed_date_l2Book_member')
                day=info.name.split('/')[1];stem=f'btc_{day}_00'
                (ROOT/(stem+'.lz4')).write_bytes(body)
                decoder=lz4.frame.LZ4FrameDecompressor();raw_data=decoder.decompress(body,max_length=128*2**20)
                assert decoder.eof
                (ROOT/(stem+'.jsonl')).write_bytes(raw_data)
                lines=raw_data.splitlines();first=json.loads(lines[0]);lastrow=json.loads(lines[-1])
                result={'date':day,'predeclared_role':TARGETS[info.name],'member':member,'compressed_path':str(ROOT/(stem+'.lz4')),'jsonl_path':str(ROOT/(stem+'.jsonl')),'compressed_bytes':len(body),'compressed_sha256':hashlib.sha256(body).hexdigest(),'decompressed_bytes':len(raw_data),'decompressed_sha256':hashlib.sha256(raw_data).hexdigest(),'records':len(lines),'first_exchange_ms':first['raw']['data']['time'],'last_exchange_ms':lastrow['raw']['data']['time'],'first_outer_time':first['time'],'last_outer_time':lastrow['time'],'origin':'exploratory_real_data'}
                found.append(result)
                (ROOT/'historical_holdout_acquisition_result.json').write_text(json.dumps(found,indent=2))
                print('TARGET_ACQUIRED',json.dumps(result),flush=True)
            position=member['data_offset']+((info.size+511)//512)*512
            break
        elif info.size:
            raise RuntimeError('Unexpected nonregular payload')
    if not saw_file:
        position+=consumed
    (ROOT/'december_tar_index_partial.json').write_text(json.dumps(index,indent=2))
plan['fixed_date_result']={'found_dates':[x['date'] for x in found],'header_bytes':header_bytes,'acquisition_bytes':acquisition_bytes,'finished_at':now()};save()
assert len(found)==3,'Headerbudget exhausted before all targets'
print(json.dumps(plan['fixed_date_result']),flush=True)
