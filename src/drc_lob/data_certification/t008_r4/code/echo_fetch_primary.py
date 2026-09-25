"""Fetch only predeclared, bounded public documentation; never market payloads."""
from datetime import datetime, timezone
from pathlib import Path
import ctypes
import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "authoritative-sources"
CAP = 16 * 1024**2
WEB_RESERVE = 2 * 1024**2
HEADER_RESERVE = 65536
PER_BODY_CAP = 512 * 1024
SEED = 20260919


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_once(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    kernel.SetProcessAffinityMask.restype = ctypes.c_int
    kernel.GetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
    handle = kernel.GetCurrentProcess()
    assert kernel.SetProcessAffinityMask(handle, 1), ctypes.get_last_error()
    process_mask, system_mask = ctypes.c_size_t(), ctypes.c_size_t()
    assert kernel.GetProcessAffinityMask(handle, ctypes.byref(process_mask), ctypes.byref(system_mask))
    assert process_mask.value == 1
    started = time.monotonic()
    opener = urllib.request.build_opener(NoRedirect())
    for plan_path in sorted(OUT.glob("requests_batch*.json")):
        plan = json.loads(plan_path.read_text())
        for entry in plan["requests"]:
            receipt_path = OUT / (entry["id"] + ".receipt.json")
            if receipt_path.exists():
                continue
            old = [json.loads(p.read_text()) for p in OUT.glob("*.receipt.json")]
            charged = WEB_RESERVE + sum(r["body_bytes"] + r["transport_reserve_bytes"] for r in old)
            assert charged + PER_BODY_CAP + HEADER_RESERVE <= CAP
            free = shutil.disk_usage(ROOT).free
            retained = sum(p.stat().st_size for d in (ROOT.parent / "r2", ROOT.parent / "r3", ROOT) for p in d.rglob("*") if p.is_file())
            assert free >= 50 * 1024**3 + PER_BODY_CAP
            assert retained + PER_BODY_CAP + HEADER_RESERVE < 12 * 1024**3
            assert time.monotonic() - started < 3500
            rec = dict(entry, started_at=stamp(), seed=SEED, pid=os.getpid(), affinity_mask=process_mask.value,
                       plan_sha256=sha(plan_path.read_bytes()), code_sha256=sha(Path(__file__).read_bytes()),
                       body_cap=PER_BODY_CAP, body_bytes=0, transport_reserve_bytes=HEADER_RESERVE,
                       physical_free_bytes_before=free, physical_retained_bytes_before=retained,
                       charged_before=charged, completed=False)
            write_once(OUT / (entry["id"] + ".started.json"), rec)
            body = bytearray()
            try:
                request = urllib.request.Request(entry["url"], headers={"User-Agent": "research-source-audit/1.0", "Accept-Encoding": "identity"})
                try:
                    response = opener.open(request, timeout=30)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    rec.update(status=response.status, response_url=response.url, response_headers=dict(response.headers.items()))
                    while len(body) < PER_BODY_CAP:
                        block = response.read(min(65536, PER_BODY_CAP - len(body)))
                        if not block:
                            rec["eof"] = True
                            break
                        body.extend(block)
                    rec["completed"] = response.status == 200 and rec.get("eof", False)
                    if not rec.get("eof", False):
                        rec["error"] = "body cap reached; no further byte consumed"
            except Exception as error:
                rec["error"] = repr(error)
            rec.update(body_bytes=len(body), body_sha256=sha(body), finished_at=stamp(),
                       body_path=str(OUT / entry["filename"]))
            with (OUT / entry["filename"]).open("xb") as stream:
                stream.write(body)
            write_once(receipt_path, rec)
            print(json.dumps({k: rec.get(k) for k in ("id", "status", "body_bytes", "completed", "error")}), flush=True)
    print(json.dumps({"elapsed_seconds": time.monotonic() - started, "affinity_mask": process_mask.value}), flush=True)


if __name__ == "__main__":
    main()
