"""Three untouched later L2 dates for the requested Q18 temporal comparison."""
from settings import OUT, SEED, bind, now, pin, save, stamp
import acquire_bbo_panel as acquisition
import export_receipt_quotes as exporter
from concurrent.futures import ThreadPoolExecutor
import time

DATES = ["2026-02-01", "2026-03-01", "2026-04-01"]
DEST = OUT / "q18_later"


def main():
    proc = pin()
    started = time.monotonic()
    DEST.mkdir(exist_ok=True)
    protocol = DEST / "protocol.json"
    if protocol.exists():
        raise RuntimeError("Existing frozen run must be resumed deliberately")
    save(protocol, dict(schema="t018-q18-later-source/1", frozen_at=now(), seed=SEED, dates=DATES,
        role="Three later temporal-transfer dates; no training or selection use", assets=["BTC","ETH"],
        source="Tardis raw Hyperliquid l2Book", fields="Five bid/ask prices and sizes, source clocks/changes/gaps; counts auxiliary only",
        reason="First three free monthly days after last old acquired Jan2026, before June2026 channel cadence change; previously unacquired source-only selection",
        observation="Both provider arrival and exchange clocks retained; consumer freezes exact representation/own-prefix timing and cached-view55s semantics",
        prefix_ns=30_000_000_000, max_gap_ns=2_000_000_000,
        response_allocation=256*1024**2, normalized_allocation=160*1024**2,
        empirical_acceptance=False))
    # These allocations fit alongside the full reserved BBO raw+normalized budget.
    reserved = acquisition.BASE_RETENTION + 400*1024**2 + 768*1024**2 + 1200*1024**2 + 416*1024**2
    if reserved > 12*1024**3:
        raise RuntimeError("Combined source allocations exceed retained-byte cap")
    acquisition.DEST = DEST
    acquisition.PANEL_CAP = 256*1024**2
    exporter.DEST = DEST / "normalized"
    exporter.DEST.mkdir(exist_ok=True)
    protocol_hash = bind(protocol)["sha256"]
    days = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for date in DATES:
            records = list(pool.map(lambda offset: acquisition.acquire(date,offset,protocol_hash,"l2Book"), range(0,1440,10)))
            index = dict(date=date, records=[dict(offset=r["offset"], compressed_path=r["raw"]["path"],
                compressed_sha256=r["raw"]["sha256"], decoded_sha256=r["decoded_sha256"], receipt=r) for r in records])
            save(DEST / "day_indexes" / f"{date}.json", index)
            result = exporter.export_day(date,index,proc)
            days.append(result)
            save(DEST / "progress.json", dict(at=now(),days=days,elapsed_seconds=time.monotonic()-started))
    save(DEST / "manifest.json", dict(at=now(),dates=DATES,days=days,protocol=bind(protocol),
        elapsed_seconds=time.monotonic()-started, source_status="pending_independent_review"))
    stamp("Q18 later-date source acquisition and exact normalization complete")


if __name__ == "__main__":
    main()
