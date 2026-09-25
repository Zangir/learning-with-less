"""Fixed E264 paths, populations and output helpers."""
from pathlib import Path
from t016_p2.common import sha, read, dump, now, verify_json_packet
WORK=Path(__file__).resolve().parents[1]
A=Path(__file__).resolve().parents[2] / 'runtime'
OUT=A/'T-016/r6-fixed-output-diagnosis'
R029=A/'cycle-20260922-0921/frozen-R-029'
R031=A/'cycle-20260922-1122/frozen-R-031'
RV027=A/'cycle-20260922-1021/frozen-RV-027'
RV029=A/'cycle-20260922-1222/frozen-RV-029'
PACKETS={R029:'9b803d7598f20f8e3e17291de769731806175ec7c4088373090834a0020b8bb0',
    R031:'5450d4411bbfc91451b4b60b330c23da0eec5f31fabe628dcf9c26d9083b72c0',
    RV027:'4da8ad084333110cc494a6d327215ca98aa0ca0668cca7a4e587980b800616ce',
    RV029:'f0e2cb0530e5e65fb563729b9399062c439d20e2105b6636618fdf66243bab9f'}
DATES=[f'2025-{m:02d}-01' for m in range(5,12)]
GROUPS={'May-Jul':DATES[:3],'Aug-Nov':DATES[3:]}
FAMILIES=('breakout','rebound')
METHODS=('C','P','R','onehot-F','onehot-A','onehot-N','uniform','train-frequency')
CONTRASTS={'P-C':('P','C'),'R-C':('R','C'),'R-P':('R','P'),
    'C-frequency':('C','train-frequency'),'P-frequency':('P','train-frequency'),
    'R-frequency':('R','train-frequency'),'frequency-uniform':('train-frequency','uniform')}
SEED=20260919
def stage(name,detail):
    line=f'{now()} | {name} | {detail}'
    print(line,flush=True)
    with (OUT/'timings.log').open('a',encoding='utf-8') as stream:stream.write(line+'\n')
