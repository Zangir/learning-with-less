"""Day-local source joins and compact cut tables, preserving admitted source order."""
from hashlib import sha256
import json
import numpy as np
from t016_p0.engine import Observations, NS
from t016_p1.features import raw_book


def load_day(directory, segments, start, end, source_id):
    rows, segment_index = [], 0
    with (directory/'state_rows.jsonl').open('rb') as stream:
        for index, raw in enumerate(stream):
            row = json.loads(raw)
            if row['event_ns'] >= end:
                break
            if row['event_ns'] < start:
                continue
            while index >= segments[segment_index]['stop_row_index']:
                segment_index += 1
            segment = segments[segment_index]
            assert segment['first_row_index'] <= index < segment['stop_row_index']
            assert row['asset']=='BTC' and row['source_id']==source_id
            assert row['release_ns'] is None and row['admission_evidence_ns'] is None
            row.update(segment_id=segment['segment_id'], physical_line_1_based=index+1,
                       source_line_sha256=sha256(raw).hexdigest())
            rows.append(row)
    wanted = {r['source_ordinal']:r for r in rows}
    provenance = {}
    with (directory/'source_provenance.jsonl').open('rb') as stream:
        for line, raw in enumerate(stream,1):
            p = json.loads(raw)
            if p['source_ordinal'] in wanted:
                assert p['source_ordinal'] not in provenance
                row=wanted[p['source_ordinal']]
                assert row['event_ns']==p['event_ns']
                row['disconnect_epoch']=p['disconnect_epoch']
                provenance[p['source_ordinal']]={**p,'provenance_line_1_based':line,
                                               'provenance_line_sha256':sha256(raw).hexdigest()}
    assert set(provenance)==set(wanted)
    return rows, provenance, Observations(rows,segments,start,end)


def compact_cuts(obs, output):
    cuts=list(obs.grid)
    n=len(cuts)
    arrays={key:np.full(n,-1,dtype='<i8') for key in
            ('cut_ns','event_ns','source_ordinal','source_row_index','age_ns','segment_id')}
    arrays['book_units8_counts']=np.zeros((n,30),dtype='<i8')
    arrays['valid_bbo']=np.zeros(n,dtype=np.bool_)
    arrays['valid_depth']=np.zeros(n,dtype=np.bool_)
    reasons=['supported']+sorted({p['reason'] for p in obs.grid.values() if p['reason']})
    arrays['support_reason_code']=np.zeros(n,dtype='<i2')
    blocked={p['cut_ns']:p['reason'] for p in output['blocked_cuts']}
    block_reasons=['not_blocked']+sorted(set(blocked.values()))
    arrays['blocked_reason_code']=np.zeros(n,dtype='<i2')
    checks=0
    for i,cut in enumerate(cuts):
        p=obs.grid[cut];arrays['cut_ns'][i]=cut
        for key in ('event_ns','source_ordinal','age_ns','segment_id'):
            if key in p:arrays[key][i]=p[key]
        if 'row_index' in p:
            row=obs.rows[p['row_index']]
            arrays['source_row_index'][i]=row['physical_line_1_based']-1
            values=raw_book(row)
            assert len(values)==30
            arrays['book_units8_counts'][i]=values
        arrays['valid_bbo'][i]=p['valid']
        arrays['valid_depth'][i]=p['valid'] and p['depth_rejection'] is None
        arrays['support_reason_code'][i]=0 if p['valid'] else reasons.index(p['reason'])
        arrays['blocked_reason_code'][i]=block_reasons.index(blocked[cut]) if cut in blocked else 0
        if p['valid']:
            book=arrays['book_units8_counts'][i]
            expected=[int(book[j]) for j in (0,15,5,20,10,25)]+[int(arrays['age_ns'][i])]
            assert p['bbo']==expected
            checks+=1
    return arrays, {'support_reason_codes':reasons,'blocked_reason_codes':block_reasons,
                    'same_row_projection_checks':checks}


def dump_json(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def dump_lines(path,rows):
    with path.open('w',encoding='utf-8') as f:
        for row in rows:f.write(json.dumps(row,sort_keys=True,ensure_ascii=False)+'\n')
