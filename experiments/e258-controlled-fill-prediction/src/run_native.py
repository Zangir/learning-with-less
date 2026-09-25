"""Execute the frozen native worlds once and retain every raw capture."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import time
from engine_capture import ROOT, run_episode, serial


def main():
    protocol=json.loads((ROOT/'protocol.json').read_text())
    freeze=json.loads((ROOT/'freeze.json').read_text())
    for rel,expected in freeze['sha256'].items():
        assert sha256((ROOT/rel).read_bytes()).hexdigest()==expected,rel
    source=json.loads((ROOT/'source-provenance.json').read_text())
    for row in source['patched_files']:
        assert sha256((ROOT/'source/patched'/row['path']).read_bytes()).hexdigest()==row['sha256']
    directory=ROOT/'episodes'
    directory.mkdir(exist_ok=True)
    assert not list(directory.glob('*.json')), 'No silent continuation or overwrite of native outcomes.'
    started=time.perf_counter()
    with (ROOT/'native-executions.jsonl').open('x',encoding='utf-8') as receipts:
        for index,spec in enumerate(protocol['episodes']):
            assert index<protocol['resources']['max_native_episodes']
            before=time.perf_counter()
            capture=run_episode(spec,'study',prefix=spec.get('prefix',False))
            raw=(json.dumps(serial(capture),separators=(',',':'))+'\n').encode()
            (directory/(spec['name']+'.json')).write_bytes(raw)
            receipt=dict(name=spec['name'],ordinal=index+1,sha256=sha256(raw).hexdigest(),bytes=len(raw),
                         seconds=time.perf_counter()-before,finished_at=datetime.now(timezone.utc).isoformat())
            receipts.write(json.dumps(receipt)+'\n');receipts.flush()
            if (index+1)%128==0:print(f'Native captures {index+1}/{len(protocol["episodes"])}',flush=True)
    assert len(protocol['episodes'])==3212
    (ROOT/'native-summary.json').write_text(json.dumps(dict(completed=True,engine_runs=len(protocol['episodes']),
        seconds=time.perf_counter()-started,protocol_sha256=sha256((ROOT/'protocol.json').read_bytes()).hexdigest(),
        single_execution=True,no_learning_performed=True),indent=2)+'\n')
    print('Completed all 3212 native runs.',flush=True)


if __name__=='__main__':main()
