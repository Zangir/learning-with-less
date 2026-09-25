from pathlib import Path
import ctypes
from ctypes import wintypes as w
import json, os, subprocess, sys, time

ROOT = (Path(__file__).resolve().parents[1] / 'runtime')
START = time.perf_counter()
os.environ.update(OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2', PYTHONIOENCODING='utf-8')
k = ctypes.WinDLL('kernel32', use_last_error=True)
k.GetCurrentProcess.restype = w.HANDLE
k.SetProcessAffinityMask.argtypes = [w.HANDLE, ctypes.c_size_t]
assert k.SetProcessAffinityMask(k.GetCurrentProcess(), (1 << 8) | (1 << 9))
class Basic(ctypes.Structure):
    _fields_ = [('ProcessTime', ctypes.c_int64), ('JobTime', ctypes.c_int64), ('Flags', w.DWORD), ('MinWS', ctypes.c_size_t), ('MaxWS', ctypes.c_size_t), ('Active', w.DWORD), ('Affinity', ctypes.c_size_t), ('Priority', w.DWORD), ('Scheduling', w.DWORD)]
class IO(ctypes.Structure):
    _fields_ = [(x, ctypes.c_uint64) for x in ('readops','writeops','otherops','readbytes','writebytes','otherbytes')]
class Extended(ctypes.Structure):
    _fields_ = [('Basic', Basic), ('IO', IO), ('ProcessMemory', ctypes.c_size_t), ('JobMemory', ctypes.c_size_t), ('PeakProcess', ctypes.c_size_t), ('PeakJob', ctypes.c_size_t)]
k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
k.CreateJobObjectW.restype = w.HANDLE
k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
k.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
job = k.CreateJobObjectW(None, None)
limits = Extended()
limits.Basic.Flags = 0x200 | 0x2000
limits.JobMemory = 8 * 1024**3
assert k.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
assert k.AssignProcessToJobObject(job, k.GetCurrentProcess())

def record(name, extra=None):
    assert k.QueryInformationJobObject(job,9,ctypes.byref(limits),ctypes.sizeof(limits),None)
    metadata={'runtime_seconds':time.perf_counter()-START,'cpu_affinity':[8,9],'job_memory_limit_bytes':limits.JobMemory,'peak_job_memory_bytes':limits.PeakJob,'python':sys.version}
    if extra: metadata.update(extra)
    (ROOT/name).write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps(metadata),flush=True)
