"""Acquire three aligned first-hour members, bounded to 256 MiB transferred."""
from pathlib import Path
import gzip
import hashlib
import io
import json
import tarfile
import time

import requests

ROOT = Path(__file__).resolve().parents[1] / "runtime"
DATA = ROOT / "data"
BASE = "https://zenodo.org/records/18184441/files/"
LIMIT = 256 * 1024**2
STARTED = time.monotonic()
SESSION = requests.Session()
transferred = 0
manifest = []


def request_range(archive, start, end):
    global transferred
    response = SESSION.get(BASE + archive + "?download=1", headers={"Range": f"bytes={start}-{end}"}, stream=True, timeout=(20, 30))
    response.raise_for_status()
    if response.status_code != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {start}-"):
        response.close()
        raise RuntimeError("Source did not honor bounded range request")
    chunks = []
    for block in response.iter_content(1024**2):
        transferred += len(block)
        if transferred > LIMIT or time.monotonic() - STARTED > 1800:
            response.close()
            raise RuntimeError("Declared acquisition budget exceeded")
        chunks.append(block)
    response.close()
    return b"".join(chunks)


def uncompressed_member(archive, desired):
    offset = 0
    for _ in range(1000):
        header = request_range(archive, offset, offset + 511)
        info = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
        print("header", archive, info.name, info.size, flush=True)
        if info.name == desired:
            return offset + 512, info.size
        offset += 512 + ((info.size + 511) // 512) * 512
    raise RuntimeError("Member not found within 1000 headers")


def persist(name, data, provenance):
    path = DATA / name
    path.write_bytes(data)
    # Read the whole member so gzip gets a chance to object to damaged luggage.
    raw_bytes = 0
    with gzip.open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            raw_bytes += len(block)
    row = dict(file=name, bytes=len(data), uncompressed_bytes=raw_bytes,
               sha256=hashlib.sha256(data).hexdigest(), gzip_crc_verified=True, **provenance)
    manifest.append(row)
    (ROOT / "sample_manifest.json").write_text(json.dumps(dict(record="https://zenodo.org/records/18184441", license="CC-BY-4.0", subset="2025-12-01 00:00-01:00 UTC", archive_md5_verified=False, transferred_bytes=transferred, seconds=time.monotonic()-STARTED, files=manifest), indent=2))
    print("persisted", name, len(data), raw_bytes, flush=True)


def main():
    DATA.mkdir(exist_ok=True)
    archive = "btc_orders_202512.tar.xz"
    # The first member was inspected before acquisition: 71,745,554 compressed bytes.
    prefix = request_range(archive, 0, 76 * 1024**2 - 1)
    with tarfile.open(fileobj=io.BytesIO(prefix), mode="r|xz") as tar:
        member = next(iter(tar))
        assert member.name == "20251201/btc_00.data.gz"
        payload = tar.extractfile(member).read()
        assert len(payload) == member.size
    persist("btc_20251201_00.data.gz", payload, dict(archive=archive, member=member.name, range_start=0, range_bytes=len(prefix)))
    for archive, member, filename in [
        ("book_diffs_202512.tar", "20251201/ex0.gz", "book_diffs_20251201_00.gz"),
        ("trades_2025_12.tar", "20251201/0.gz", "trades_20251201_00.gz"),
    ]:
        offset, size = uncompressed_member(archive, member)
        payload = request_range(archive, offset, offset + size - 1)
        assert len(payload) == size
        persist(filename, payload, dict(archive=archive, member=member, range_start=offset, range_bytes=size))
    print("complete", transferred, time.monotonic()-STARTED, flush=True)


if __name__ == "__main__":
    main()
