"""Fixed assignment paths and small transparent serialization helpers."""
from pathlib import Path
from t016_p2.common import sha, read, dump, now, verify_json_packet

WORK = Path(__file__).resolve().parents[1]
A = Path(__file__).resolve().parents[2] / 'runtime'
OUT = A / 'T-016/r5-later-period-evaluation'
FROZEN = A / 'cycle-20260922-0921/frozen-R-029'
FROZEN_SHA = '9b803d7598f20f8e3e17291de769731806175ec7c4088373090834a0020b8bb0'
REVIEW = A / 'cycle-20260922-1021/frozen-RV-027'
REVIEW_SHA = '4da8ad084333110cc494a6d327215ca98aa0ca0668cca7a4e587980b800616ce'
SOURCE = A / 'T-008/r3/interface/full_day_startup30'
INDEX = SOURCE / 'dataset_index.v2.3.0.json'
POLICY = A / 'T-008/r3/panel_protocol.v3.2.startup30.json'
DATES = ['2025-08-01', '2025-09-01', '2025-10-01', '2025-11-01']
FAMILIES = ('breakout', 'rebound')
ARMS = ('C', 'P', 'R')
SEED = 20260919
BASE = '30fb8a00c199a2e74a98851d4292cf3b8b6819e6'


def stage(name, detail):
    line = f'{now()} | {name} | {detail}'
    print(line, flush=True)
    with (OUT / 'timings.log').open('a', encoding='utf-8') as stream:
        stream.write(line + '\n')


def lines(path):
    import json
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]
