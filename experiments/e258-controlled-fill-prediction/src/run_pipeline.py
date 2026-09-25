"""Bound all native generation, validation and learned fits in one Windows job."""
import json
import subprocess
import sys
import time
from resource_guard import ROOT,record


def main():
    stages=[]
    status='failed'
    try:
        for name,script in [('native','run_native.py'),('validation','validate_study.py'),('study','evaluate_study.py')]:
            start=time.perf_counter()
            with (ROOT/f'{name}.log').open('x',encoding='utf-8') as log:
                result=subprocess.run([sys.executable,str(ROOT/'code'/script)],cwd=ROOT,
                    stdout=log,stderr=subprocess.STDOUT,timeout=3400)
            stages.append(dict(stage=name,exit=result.returncode,seconds=time.perf_counter()-start))
            print(json.dumps(stages[-1]),flush=True)
            assert result.returncode==0, f'{name} failed; no later stage may execute.'
        status='completed'
    finally:
        record('runtime-resource.json',dict(status=status,stages=stages,
            native_episode_limit=4096,learned_fit_limit=24,planned_native_episodes=3212,planned_learned_fits=24))


if __name__=='__main__':main()
