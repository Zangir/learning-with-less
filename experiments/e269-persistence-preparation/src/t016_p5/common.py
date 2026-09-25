"""Exact E271 paths, accounting bounds and evidence helpers."""
from pathlib import Path
import shutil
from t016_p2.common import dump, read, sha, now

WORK = Path(__file__).resolve().parents[1]
A = Path(__file__).resolve().parents[2] / 'runtime'
OUT = A / 'T-016/r8-fixed-persistence'
PREPARATION = A / 'T-016/r7-prospective-preparation'
RELEASE = A / 'cycle-20260922-1845/E271-execution-release.json'
FROZEN = A / 'cycle-20260922-0921/frozen-R-029'
HISTORICAL = A / 'T-016/r6-fixed-output-diagnosis'
BASE = '2cca8b92d48058d26eb6388fd520869bfa8a10fd'
DATE = '2026-02-01'
SOURCE_ID = 'tardis-hyperliquid-2026-02-01-btc-e270'
SEED = 20260919
METHODS = ('C', 'P', 'R', 'onehot-F', 'onehot-A', 'onehot-N', 'uniform', 'train-frequency')
PAIRS = {'P-C': ('P','C'), 'R-C': ('R','C'), 'R-P': ('R','P'),
         'C-frequency': ('C','train-frequency'), 'P-frequency': ('P','train-frequency'),
         'R-frequency': ('R','train-frequency'), 'frequency-uniform': ('train-frequency','uniform')}

def stage(name, detail):
    line = f'{now()} | {name} | {detail}'
    print(line, flush=True)
    with (OUT/'timing.log').open('a', encoding='utf-8') as stream:
        stream.write(line+'\n')

def resources(extra=0):
    retained = sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file())
    total = 11982036334 + 8388608 + retained + extra
    reserved_total = total + 67108864 + 536870912
    free = shutil.disk_usage(Path.cwd()).free
    assert retained + extra <= 201326592, 'E271 output allocation exhausted'
    assert reserved_total <= 12884901888, 'Q16 or independent-review reserve exhausted'
    assert free > 53687091200, 'Physical free-space floor'
    return {'utc': now(), 'retained_bytes': retained, 'planned_extra_bytes': extra,
            'cumulative_upper_bound_bytes': total, 'review_reserve_bytes': 67108864,
            'Q16_minimum_reserve_bytes': 536870912, 'ceiling_bytes': 12884901888,
            'remaining_after_both_reserves_bytes': 12884901888-reserved_total,
            'physical_C_free_bytes': free, 'new_market_bytes': 0}

def lines(path):
    import json
    with Path(path).open(encoding='utf-8-sig') as stream:
        return [json.loads(line) for line in stream if line.strip()]
