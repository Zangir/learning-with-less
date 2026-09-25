"""Complete the aligned trade member within the approved 384 MiB total cap."""
import json
import acquire_sample as acquisition

previous = json.loads((acquisition.ROOT / "sample_manifest.json").read_text())
acquisition.LIMIT = 384 * 1024**2
# The old cap was enforced after a <=1 MiB read; include that entire overhang.
acquisition.transferred = 257 * 1024**2
acquisition.manifest = previous["files"]
archive = "trades_2025_12.tar"
member = "20251201/0.gz"
offset, size = acquisition.uncompressed_member(archive, member)
payload = acquisition.request_range(archive, offset, offset + size - 1)
assert len(payload) == size
acquisition.persist("trades_20251201_00.gz", payload,
                    dict(archive=archive, member=member, range_start=offset, range_bytes=size))
path = acquisition.ROOT / "sample_manifest.json"
manifest = json.loads(path.read_text())
manifest["transferred_bytes_is_conservative_upper_bound"] = True
manifest["approved_cap_bytes"] = acquisition.LIMIT
manifest["initial_attempt_seconds"] = previous["seconds"]
manifest["initial_attempt"] = "256 MiB cap correctly stopped during trade transfer; 384 MiB cap approved before this completion. Existing two verified members retained."
path.write_text(json.dumps(manifest, indent=2))
print("complete", acquisition.transferred, flush=True)
