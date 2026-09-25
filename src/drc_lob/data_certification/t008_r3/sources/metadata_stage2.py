from metadata_probe import fetch, head

PIN = "e28ac5f9139033a3e991b3db52702dad1350683e"
fetch("hf_gionuibk_data_tree.json", f"https://huggingface.co/api/datasets/gionuibk/hyperliquidL2Book-v2/tree/{PIN}/data?recursive=false&expand=false")
fetch("tardis_hyperliquid_exchange.json", "https://api.tardis.dev/v1/exchanges/hyperliquid", 400000)
for symbol in ("BTC", "ETH"):
    for month in ("04", "11"):
        head(f"tardis_{symbol}_2025{month}01", f"https://datasets.tardis.dev/v1/hyperliquid/book_snapshot_5/2025/{month}/01/{symbol}.csv.gz")
