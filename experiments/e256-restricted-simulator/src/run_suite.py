"""Run the predeclared upstream controls, patched captures, and independent audit."""
import importlib.metadata
import json
import os
import subprocess
import sys
import time
from resource_guard import ROOT,record


def main():
    steps=[]
    status='failed'
    try:
        for variant in ('upstream','patched'):
            started=time.perf_counter()
            env=dict(os.environ,T012_ENGINE_VARIANT=variant)
            with (ROOT/f'{variant}.log').open('w',encoding='utf-8') as log:
                result=subprocess.run([sys.executable,str(ROOT/'code/engine_capture.py')],env=env,cwd=ROOT,
                                      stdout=log,stderr=subprocess.STDOUT,timeout=1200)
            steps.append(dict(step=variant,exit=result.returncode,seconds=time.perf_counter()-started))
            if result.returncode: raise RuntimeError(f'{variant} execution failed; preserve logs before any repair')
        started=time.perf_counter()
        with (ROOT/'validation.log').open('w',encoding='utf-8') as log:
            result=subprocess.run([sys.executable,str(ROOT/'code/validate_captured.py')],cwd=ROOT,
                                  stdout=log,stderr=subprocess.STDOUT,timeout=300)
        steps.append(dict(step='independent_validation',exit=result.returncode,seconds=time.perf_counter()-started))
        if result.returncode: raise RuntimeError('Independent validation failed; inspect saved comparisons')
        status='completed'
    finally:
        record('runtime-resource.json',dict(status=status,steps=steps,
            packages={p:importlib.metadata.version(p) for p in ('numpy','pandas','scipy','tqdm')},
            configured_engine_run_limit=32,upstream_source_modified=False,patched_source_modified=True))


if __name__=='__main__':
    main()
