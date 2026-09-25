"""Fetch only publicly advertised, bounded sample assets; never list identities."""
from acquire_sources import fetch
from settings import OUT, bind, pin, read, save, stamp
from html.parser import HTMLParser
import re
import urllib.parse
import pyarrow.parquet as pq


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href:
                self.links.append(href)


def main():
    pin()
    result = fetch("bitquery_documentation", "https://docs.bitquery.io/docs/cloud/hyperliquid/", 2*1024**2, metadata=True)
    parser = Links()
    parser.feed(open(result["body"]["path"], encoding="utf-8").read())
    urls = sorted(set(url for url in parser.links if "bitquery-blockchain-dataset.s3.us-east-1.amazonaws.com/hyperliquid/" in url and url.endswith(".parquet")))
    selected = [url for url in urls if any("/"+kind+"/" in url for kind in ("book_diffs", "order_statuses", "fills"))]
    audits = []
    for url in selected:
        kind = urllib.parse.urlsplit(url).path.split("/")[-2]
        record = fetch("bitquery_"+kind, url, 16*1024**2)
        if record["status"] != 200 or not record["complete"]:
            audits.append(dict(topic=kind, acquisition=record, readable=False))
            continue
        table = pq.read_table(record["body"]["path"])
        names = table.column_names
        coins = [n for n in names if n.endswith("_Coin")]
        counts = {}
        if coins:
            values = table[coins[0]].to_pylist()
            counts = {coin:values.count(coin) for coin in ("BTC", "ETH")}
        numbers = [int(x) for x in table["Block_Number"].to_pylist()]
        audit = dict(topic=kind, readable=True, acquisition=record, rows=table.num_rows,
                     columns=names, market_rows=counts, block_min=min(numbers), block_max=max(numbers),
                     distinct_blocks=len(set(numbers)), row_block_order_nondecreasing=all(a<=b for a,b in zip(numbers,numbers[1:])),
                     checkpoint_present=False, source_order_certificate=False,
                     supported="Actual public block-tagged sample parsing and field inventory",
                     not_supported="Initial queue completeness, omitted/empty-block continuity, action grouping, within-block priority or receipt clocks")
        audits.append(audit)
        stamp(f"Native alternative {kind}: rows={table.num_rows}, BTC/ETH counts={counts}; no checkpoint advertised")
    save(OUT / "native_alternatives.json", dict(candidate="Bitquery public HyperCore sample", advertised_urls=selected,
         audits=audits, q16_empirical_admission=False,
         next_asset="Height-bound relevant-price resting snapshot plus every native block/action through sample; export ordinal/order and empty-block certificates",
         identity_policy="Raw provider files private only; audit never emits account or order IDs"))


if __name__ == "__main__":
    main()
