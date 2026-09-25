"""Run root's read-only acquisition audit on Windows CPU1 under tmux timeout."""
from pathlib import Path
import ctypes,json,os,runpy,time
from ctypes import wintypes

root=Path(__file__).resolve().parent
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.GetCurrentProcess.restype=wintypes.HANDLE
kernel.SetProcessAffinityMask.argtypes=(wintypes.HANDLE,ctypes.c_size_t)
kernel.SetProcessAffinityMask.restype=wintypes.BOOL
assert kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(),2)
started=time.monotonic()
print(json.dumps(dict(cpu_affinity_mask=2,started_monotonic=started)),flush=True)
runpy.run_path(str(root/'verify_provider_chain.py'),run_name='__main__')
print(json.dumps(dict(elapsed_seconds=time.monotonic()-started,complete=True)),flush=True)
