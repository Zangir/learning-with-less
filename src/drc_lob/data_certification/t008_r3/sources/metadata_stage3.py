from metadata_probe import fetch

PIN = "e28ac5f9139033a3e991b3db52702dad1350683e"
for path in ("data/market_data", "data/l2book", "config"):
    fetch("hf_" + path.replace("/", "_") + ".json", f"https://huggingface.co/api/datasets/gionuibk/hyperliquidL2Book-v2/tree/{PIN}/{path}?recursive=false&expand=false")
fetch("tardis_hyperliquid_docs.md", "https://docs.tardis.dev/historical-data-details/hyperliquid.md", 16384)
fetch("tardis_http_api.md", "https://docs.tardis.dev/api/http-api-reference.md", 65536)
