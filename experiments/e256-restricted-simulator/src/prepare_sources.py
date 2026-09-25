"""Copy verified upstream software and apply a separately identified local repair."""
from pathlib import Path
from datetime import datetime, timezone
import difflib
import hashlib
import json
import shutil

ROOT=(Path(__file__).resolve().parents[1] / 'runtime')
PREVIOUS=ROOT.parent/'r5-simulator'
ACCEPTED=ROOT.parents[1]/'cycle-20260922-0515/frozen-R-024'
REVIEW=ROOT.parents[1]/'cycle-20260922-0616/frozen-RV-022'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(name,value):
    (ROOT/name).write_text(json.dumps(value,indent=2)+'\n')


def main():
    assert sha(REVIEW/'manifest.json')=='c422d9ada892b181c69f5f5ac653013e281b3fcebc170d8abb3147e510383e3c'
    assert sha(ACCEPTED/'manifest.json')=='0114f93fa6fb0a61c5e01b1cf21c2ca0f61c38b82f457188ce239e6b2d2b62fd'
    preserved=[dict(path=p.relative_to(ROOT.parent).as_posix(),bytes=p.stat().st_size,sha256=sha(p))
               for p in ROOT.parent.rglob('*') if p.is_file() and ROOT not in p.parents]
    write('preservation-before.json',preserved)
    source=json.loads((ACCEPTED/'source-slice.json').read_text())
    records=[]
    for row in source['files']:
        original=ACCEPTED/'source/abides'/row['path']
        assert sha(original)==row['sha256']
        for variant in ('upstream','patched'):
            target=ROOT/'source'/variant/row['path']
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(original,target)
        records.append(row)
    patched=ROOT/'source/patched/util/OrderBook.py'
    before=patched.read_text()
    replacements=[
      ("self.history[0][order.order_id]['transactions'].append((self.owner.currentTime, order.quantity))",
       "self.history[0][order.order_id]['transactions'].append((self.owner.currentTime, matched_order.quantity))"),
      ('book[i][0] = new_order','book[i][mi] = new_order')]
    after=before
    for old,new in replacements:
        assert after.count(old)==1
        after=after.replace(old,new)
    patched.write_bytes(after.encode())
    # Keep the old engine intact; the repair gets its own clearly labelled passport.
    (ROOT/'native-repair.diff').write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
                                        fromfile='upstream/util/OrderBook.py',tofile='patched/util/OrderBook.py')))
    write('source-provenance.json',dict(repository='https://github.com/abides-sim/abides',
       revision=source['revision'],license='BSD-3-Clause plus retained dependency notices',
       upstream_files=records,patched_files=[dict(path=r['path'],sha256=sha(ROOT/'source/patched'/r['path'])) for r in records],
       changed_files=['util/OrderBook.py'],native_changed_lines=2,downloaded_bytes=0,
       accepted_author_manifest=sha(ACCEPTED/'manifest.json'),accepted_review_manifest=sha(REVIEW/'manifest.json'),
       prepared_at=datetime.now(timezone.utc).isoformat()))
    write('software-transfer.json',dict(continuation_bytes=0,prior_r5_bytes=252122,dependency_downloads=0,
                                     market_data_bytes=0,limit_bytes=256*1024**2))
    assert shutil.disk_usage(ROOT).free>=50*1024**3
    print('Verified preserved input identities; copied14 upstream files; patched2 lines; downloaded0 bytes.')


if __name__=='__main__':
    main()
