"""Windows assignment bounds, inherited by children without third-party imports."""
import ctypes
from ctypes import wintypes
import os


class BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                ("active", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]


def enforce():
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "2"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
    handle = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.basic.flags = 0x200 | 0x10 | 0x2000
    limits.basic.affinity = (1 << 6) | (1 << 7)
    limits.job_memory = 8 * 1024**3
    checks = [kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(), limits.basic.affinity),
              kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)),
              kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess())]
    if not all(checks):
        raise OSError(ctypes.get_last_error(), "Cannot enforce T011 resource bounds")
    # Keep the handle alive: closing this job is the child's curtain call.
    return handle, {"pid": os.getpid(), "cpu_affinity": [6, 7],
                    "aggregate_memory_limit_bytes": limits.job_memory, "threads": 2}
