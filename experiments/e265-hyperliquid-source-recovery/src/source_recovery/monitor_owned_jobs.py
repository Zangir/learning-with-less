"""Record resource use for this assignment's existing processes only."""
from settings import OUT, now, pin, save, stamp
import json
import psutil
import time

OWNED = ("acquire_bbo_panel.py", "export_native_bbo.py", "q18_later_source.py")


def main():
    pin()
    started=time.monotonic()
    peak=0
    samples=0
    log=OUT/"resource_samples.jsonl"
    with log.open("a",encoding="utf-8") as stream:
        while time.monotonic()-started < 3550:
            jobs=[]
            for proc in psutil.process_iter(["pid","name","cmdline","create_time","memory_info"]):
                try:
                    info=proc.info
                    cmd=" ".join(info["cmdline"] or [])
                    if info["name"] != "python.exe" or not any("source_recovery/"+name in cmd for name in OWNED):
                        continue
                    jobs.append(dict(pid=info["pid"],script=next(n for n in OWNED if n in cmd),
                        rss_bytes=info["memory_info"].rss, affinity=proc.cpu_affinity(),
                        age_seconds=time.time()-info["create_time"]))
                except (psutil.NoSuchProcess,psutil.AccessDenied):
                    continue
            total=sum(j["rss_bytes"] for j in jobs)
            peak=max(peak,total)
            samples+=1
            stream.write(json.dumps(dict(at=now(),jobs=jobs,total_rss_bytes=total))+"\n")
            stream.flush()
            if total>8*1024**3 or any(j["affinity"] != [0,1] for j in jobs):
                save(OUT/"resource_limit_violation.json",dict(at=now(),jobs=jobs,total_rss_bytes=total))
                raise RuntimeError("Owned process resource limit requires intervention")
            if not jobs:
                break
            time.sleep(5)
    save(OUT/"resource_monitor_summary.json",dict(at=now(),samples=samples,peak_combined_rss_bytes=peak,
        elapsed_seconds=time.monotonic()-started,coverage="Five-second samples from monitor start; not unobserved earlier runtime"))
    stamp(f"Resource monitor ended: peak sampled combined RSS={peak}, samples={samples}")


if __name__ == "__main__":
    main()
